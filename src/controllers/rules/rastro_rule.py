from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.perfil_rule import VALUE as PROFILE_VALUE
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import MULE, NOT_EVALUATED, PASS, REJECT, WARN, SignalResult
from models import Account
from utils.money import format_brl

FAST_FORWARD = "RASTRO.repasse_rapido"
NEW_PAYER_ACCOUNT = "RASTRO.conta_pagadora_recente"
MARKED_PROXIMITY = "RASTRO.proximidade_marcada"


class RastroRule(BaseRule):
    """Regra 7 — O dinheiro está só de passagem?

    A conta laranja não guarda o dinheiro: recebe e repassa em minutos,
    antes que a vítima perceba e o MED bloqueie. O motor só vê o rastro
    dentro da própria base — os créditos que vieram de clientes da QI Tech.
    """

    rule_code = "RASTRO"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {
            NEW_PAYER_ACCOUNT: (1, self._evaluate_new_payer_account),
            FAST_FORWARD: (2, self._evaluate_fast_forward),
            MARKED_PROXIMITY: (2, self._evaluate_marked_proximity),
        }

    def _evaluate_fast_forward(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Recebeu de terceiros na última hora e repassa a maior parte: conta de passagem.

        Pontua `mule` e não recusa sozinho: o cliente que recebe o
        pagamento de um serviço e paga o fornecedor faz o mesmo movimento.
        Junto com outro sinal de conta laranja, recusa pela regra dos dois
        sinais. Créditos da mesma titularidade não entram na soma.
        """
        if features.same_ownership:
            return self.not_needed(FAST_FORWARD, 2, "Mesma titularidade: mover o próprio dinheiro não é repasse.")

        received = features.payer_recent_third_party_credits
        min_share = parameters["min_forward_share_percent"]

        observed = {"received_amount": received, "amount": features.amount}
        threshold = {"window_minutes": parameters["window_minutes"], "min_forward_share_percent": min_share}

        if received > 0 and features.amount * 100 >= received * min_share:
            return self.result(
                FAST_FORWARD,
                2,
                WARN,
                f"O pagador recebeu {format_brl(received)} de terceiros nos últimos {parameters['window_minutes']} "
                f"minutos e repassa {format_brl(features.amount)}: o dinheiro está só de passagem.",
                typology=MULE,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            FAST_FORWARD,
            2,
            PASS,
            "Sem repasse da maior parte de um crédito recente de terceiros.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_new_payer_account(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """Conta pagadora recente mandando acima do limite de partida para um destino novo.

        É a laranja de segundo salto (recebe a vítima e repassa) ou a conta
        aberta com documento de outra pessoa. Pontua `mule` abaixo do
        corte: muita conta nova é gente de bem fazendo o primeiro Pix
        grande. O limite de partida vem do PERFIL.valor.
        """
        if features.same_ownership:
            return self.not_needed(NEW_PAYER_ACCOUNT, 1, "Mesma titularidade: o dinheiro não sai do titular.")

        if not params.is_enabled(PROFILE_VALUE):
            return self.result(NEW_PAYER_ACCOUNT, 1, NOT_EVALUATED, "PERFIL.valor desligado: sem limite de partida.")

        max_age_days = parameters["max_account_age_days"]
        fallback_amount = params.of(PROFILE_VALUE)["fallback_amount"]

        observed = {
            "payer_account_age_days": features.payer_account_age_days,
            "amount": features.amount,
            "destination_recurring": features.destination_recurring,
        }
        threshold = {"max_account_age_days": max_age_days, "fallback_amount": fallback_amount}

        if (
            features.payer_account_age_days < max_age_days
            and features.amount > fallback_amount
            and not features.destination_recurring
        ):
            return self.result(
                NEW_PAYER_ACCOUNT,
                1,
                WARN,
                f"Conta pagadora aberta há {features.payer_account_age_days} dias mandando {format_brl(features.amount)} "
                "para um destino novo: padrão de conta laranja de segundo salto.",
                typology=MULE,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            NEW_PAYER_ACCOUNT,
            1,
            PASS,
            "Conta pagadora antiga, valor dentro do limite de partida, ou destino recorrente.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_marked_proximity(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """O recebedor recebeu, nas últimas 24 h, de quem tem marcação de fraude?

        A 1 salto (o marcado pagou o recebedor) é evidência dura: o
        recebedor está na ponta do dinheiro da fraude, e recusa. A 2
        saltos (pagou quem pagou o recebedor) pontua `mule`: pode ser só
        um elo comum. Só vale para recebedor PF — um lojista que recebeu
        de um marcado bloquearia todos os clientes dele por um dia.
        """
        if features.same_ownership:
            return self.not_needed(MARKED_PROXIMITY, 2, "Mesma titularidade: o dinheiro não sai do titular.")

        if features.payee_type != Account.PERSON:
            return self.not_needed(MARKED_PROXIMITY, 2, "Recebedor PJ: lojista recebe de qualquer um.")

        hop = features.payee_marked_sender_hop
        observed = {"hops": hop}
        threshold = {
            "window_hours": parameters["window_hours"],
            "reject_hops": parameters["reject_hops"],
            "max_hops": parameters["max_hops"],
        }

        if hop is not None and hop <= parameters["reject_hops"]:
            return self.result(
                MARKED_PROXIMITY,
                2,
                REJECT,
                f"O recebedor recebeu Pix de um documento com marcação de fraude vigente nas últimas "
                f"{parameters['window_hours']} horas.",
                typology=MULE,
                observed=observed,
                threshold=threshold,
            )

        if hop is not None:
            return self.result(
                MARKED_PROXIMITY,
                2,
                WARN,
                f"O recebedor está a {hop} saltos de um documento com marcação de fraude vigente "
                f"(últimas {parameters['window_hours']} horas).",
                typology=MULE,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            MARKED_PROXIMITY,
            2,
            PASS,
            f"Nenhum documento marcado a até {parameters['max_hops']} saltos do recebedor na janela.",
            observed=observed,
            threshold=threshold,
        )
