from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.perfil_rule import VALUE as PROFILE_VALUE
from controllers.rules.signal_result import ATO, NOT_EVALUATED, PASS, TWO_FACTOR, SignalResult
from models import Account
from utils.money import format_brl

UNREGISTERED_DEVICE = "LIMITE.aparelho_nao_cadastrado"
NIGHT = "LIMITE.noturno"


class LimiteRule(BaseRule):
    """Regra 2 — O valor cabe no limite deste contexto?

    Os dois sinais daqui têm número de norma, e por isso decidem 2FA
    sozinhos, sem passar pelos placares.
    """

    rule_code = "LIMITE"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {
            UNREGISTERED_DEVICE: (0, self._evaluate_unregistered_device),
            NIGHT: (0, self._evaluate_night),
        }

    def _evaluate_unregistered_device(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """R$ 200 por Pix e R$ 1.000 por dia em aparelho não cadastrado (BCB, nov/2024).

        "Cadastrado", aqui, é o aparelho CONFIÁVEL: 2 Pix aprovados, o
        primeiro há 24 h ou mais (veja o FeatureBuilder). O teto diário
        soma todos os Pix aprovados hoje de aparelhos não confiáveis. Vale
        também na mesma titularidade — o celular roubado transfere para
        onde o ladrão quiser, inclusive para outra conta da vítima.
        """
        max_per_pix = parameters["max_amount_per_pix"]
        max_per_day = parameters["max_amount_per_day"]
        threshold = {
            "max_amount_per_pix": max_per_pix,
            "max_amount_per_day": max_per_day,
            "trusted_min_approved_pix": parameters["trusted_min_approved_pix"],
            "trusted_min_hours": parameters["trusted_min_hours"],
        }

        if features.device_trusted:
            return self.result(
                UNREGISTERED_DEVICE, 0, PASS, "Aparelho confiável para este pagador.", threshold=threshold
            )

        if self._is_new_client_with_old_account(features, parameters, params):
            return self._evaluate_new_client(features, parameters, params)

        day_amount = features.untrusted_devices_day_amount + features.amount
        observed = {"amount": features.amount, "day_amount": day_amount}

        if features.amount > max_per_pix:
            return self.result(
                UNREGISTERED_DEVICE,
                0,
                TWO_FACTOR,
                f"Aparelho ainda não confiável para este pagador e valor de {format_brl(features.amount)}, "
                f"acima dos {format_brl(max_per_pix)} por Pix permitidos sem cadastro.",
                typology=ATO,
                observed=observed,
                threshold=threshold,
            )

        if day_amount > max_per_day:
            return self.result(
                UNREGISTERED_DEVICE,
                0,
                TWO_FACTOR,
                f"Aparelhos não confiáveis somam {format_brl(day_amount)} hoje, "
                f"acima dos {format_brl(max_per_day)} por dia permitidos sem cadastro.",
                typology=ATO,
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            UNREGISTERED_DEVICE,
            0,
            PASS,
            "Aparelho ainda não confiável, mas dentro dos limites por Pix e por dia.",
            observed=observed,
            threshold=threshold,
        )

    def _is_new_client_with_old_account(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> bool:
        """Cliente que o motor ainda não conhece, com conta pagadora antiga.

        O limite de partida vem do PERFIL.valor: se ele estiver desligado,
        não há limite com que trocar o do aparelho, e vale a regra normal.
        """
        return (
            not features.payer_known
            and features.payer_account_age_days >= parameters["new_client_min_account_age_days"]
            and params.is_enabled(PROFILE_VALUE)
        )

    def _evaluate_new_client(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Primeiro Pix de um cliente de conta antiga: até o limite de partida, o aparelho não decide.

        Na avaliação o banco nasce vazio e todo cliente chega num aparelho
        "novo". Em produção o motor nasceria com a carga do histórico; isto
        evita tratar todo cliente como fraude no primeiro dia sem abrir mão
        do limite: acima do limite de partida, 2FA.
        """
        fallback_amount = params.of(PROFILE_VALUE)["fallback_amount"]
        observed = {"amount": features.amount, "payer_account_age_days": features.payer_account_age_days}
        threshold = {
            "fallback_amount": fallback_amount,
            "new_client_min_account_age_days": parameters["new_client_min_account_age_days"],
        }

        if features.amount > fallback_amount:
            return self.result(
                UNREGISTERED_DEVICE,
                0,
                TWO_FACTOR,
                f"Primeiro Pix deste pagador no motor, de {format_brl(features.amount)}, acima do limite de "
                f"partida de {format_brl(fallback_amount)}.",
                typology=ATO,
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            UNREGISTERED_DEVICE,
            0,
            NOT_EVALUATED,
            "O motor ainda não tem histórico deste pagador: conta pagadora com "
            f"{features.payer_account_age_days} dias e valor dentro do limite de partida.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_night(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """R$ 1.000 entre 20h e 6h, PF para PF (Res. BCB 142/2021) — como SINAL, não teto.

        O motor não recebe o limite noturno que o cliente configurou no
        app. Quem já teve aprovado um Pix noturno maior que a soma desta
        noite mostrou que o limite dele é maior, e passa. Fora disso, 2FA
        de limite: confirmação no app, sem typology de fraude.
        """
        max_night_amount = parameters["max_night_amount"]
        threshold = {
            "max_night_amount": max_night_amount,
            "max_night_approved_amount": features.max_night_approved_amount,
            "night_hours": f"{parameters['night_start_hour']}h-{parameters['night_end_hour']}h",
        }

        if not features.is_night:
            return self.result(NIGHT, 0, PASS, "Fora do período noturno (horário de Brasília).", threshold=threshold)

        if features.same_ownership:
            return self.not_needed(NIGHT, 0, "Mesma titularidade: o limite noturno vale entre pessoas distintas.")

        if features.payer_type != Account.PERSON or features.payee_type != Account.PERSON:
            return self.not_needed(NIGHT, 0, "O limite noturno da Res. BCB 142 vale só de pessoa física para pessoa física.")

        night_amount = features.night_person_to_person_amount + features.amount
        observed = {"night_amount": night_amount, "local_hour": features.local_hour}

        if night_amount > max_night_amount and night_amount > features.max_night_approved_amount:
            return self.result(
                NIGHT,
                0,
                TWO_FACTOR,
                f"Pix noturno PF→PF somando {format_brl(night_amount)} nesta noite, acima de "
                f"{format_brl(max_night_amount)} e do maior Pix noturno já aprovado deste pagador.",
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            NIGHT, 0, PASS, "Soma noturna dentro do limite deste pagador.", observed=observed, threshold=threshold
        )
