from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import MULE, PASS, WARN, SignalResult
from utils.money import format_brl

FAST_FORWARD = "RASTRO.repasse_rapido"


class RastroRule(BaseRule):
    """Regra 7 — O dinheiro está só de passagem?

    A conta laranja não guarda o dinheiro: recebe e repassa em minutos,
    antes que a vítima perceba e o MED bloqueie. O motor só vê o rastro
    dentro da própria base — os créditos que vieram de clientes da QI Tech.
    """

    rule_code = "RASTRO"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {FAST_FORWARD: (2, self._evaluate_fast_forward)}

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
