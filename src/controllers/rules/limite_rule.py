from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import APP, ATO, MULE, PASS, TWO_FACTOR, SignalResult
from models import Account

UNREGISTERED_DEVICE = "LIMITE.aparelho_nao_cadastrado"
NIGHT = "LIMITE.noturno"


def format_brl(amount_in_cents: int) -> str:
    """15000 → "R$ 150,00". Só para as mensagens: o número de verdade viaja em centavos."""
    reais, cents = divmod(amount_in_cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{cents:02d}"


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

        O 2FA pedido aqui é o cadastro do aparelho que a norma prevê:
        depois do primeiro Pix aprovado, o aparelho vira conhecido. Vale
        também na mesma titularidade — o celular roubado transfere para
        onde o ladrão quiser, inclusive para outra conta da vítima.
        """
        max_per_pix = parameters["max_amount_per_pix"]
        max_per_day = parameters["max_amount_per_day"]
        threshold = {"max_amount_per_pix": max_per_pix, "max_amount_per_day": max_per_day}

        if features.device_known:
            return self.result(
                UNREGISTERED_DEVICE, 0, PASS, "Aparelho já cadastrado para este pagador.", threshold=threshold
            )

        day_amount = features.unregistered_devices_day_amount + features.amount
        observed = {"amount": features.amount, "day_amount": day_amount}

        if features.amount > max_per_pix:
            return self.result(
                UNREGISTERED_DEVICE,
                0,
                TWO_FACTOR,
                f"Aparelho sem Pix aprovado deste pagador e valor de {format_brl(features.amount)}, "
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
                f"Aparelhos não cadastrados somam {format_brl(day_amount)} hoje, "
                f"acima dos {format_brl(max_per_day)} por dia permitidos sem cadastro.",
                typology=ATO,
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            UNREGISTERED_DEVICE,
            0,
            PASS,
            "Aparelho não cadastrado, mas dentro dos limites por Pix e por dia.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_night(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """R$ 1.000 entre 20h e 6h, PF para PF (Res. BCB 142/2021) — como SINAL, não teto.

        O motor não recebe o limite noturno que o cliente configurou no
        app. Quem já teve aprovado um Pix noturno maior que a soma desta
        noite mostrou que o limite dele é maior, e passa. Fora disso, 2FA;
        e se houver cara de golpe ou de conta laranja, a decisão recusa
        (`escalates_with`).
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
                escalates_with=(APP, MULE),
            )

        return self.result(
            NIGHT, 0, PASS, "Soma noturna dentro do limite deste pagador.", observed=observed, threshold=threshold
        )
