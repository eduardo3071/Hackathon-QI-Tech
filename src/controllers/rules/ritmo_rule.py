from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.limite_rule import format_brl
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import ATO, PASS, REJECT, TWO_FACTOR, SignalResult

VELOCITY = "RITMO.velocidade"


class RitmoRule(BaseRule):
    """Regra 3 — Rápido demais ou somou demais?

    Quem invade uma conta tenta esvaziá-la rápido. A janela é deslizante
    e conta as tentativas recusadas também: insistência é sinal.
    """

    rule_code = "RITMO"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {VELOCITY: (0, self._evaluate_velocity)}

    def _evaluate_velocity(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Contagem E soma na mesma janela.

        Com a mediana do Pix entre pessoas em R$ 50, rajada de valor baixo
        é comum (o racha da conta do bar). Por isso a contagem só pede 2FA
        a partir de 5 tentativas quando a janela soma o mínimo; abaixo
        dele, só 10 tentativas pedem 2FA, e nunca recusam.
        """
        attempts = features.velocity_attempts + 1
        window_amount = features.velocity_amount + features.amount

        two_factor_count = parameters["two_factor_count"]
        reject_count = parameters["reject_count"]
        min_window_amount = parameters["min_window_amount"]

        observed = {"attempts": attempts, "window_amount": window_amount}
        threshold = {
            "window_minutes": parameters["window_minutes"],
            "two_factor_count": two_factor_count,
            "reject_count": reject_count,
            "min_window_amount": min_window_amount,
        }
        window = f"{attempts} tentativas em {parameters['window_minutes']} minutos"

        if window_amount >= min_window_amount:
            if attempts >= reject_count:
                return self.result(
                    VELOCITY,
                    0,
                    REJECT,
                    f"{window} somando {format_brl(window_amount)}: padrão de conta sendo esvaziada.",
                    typology=ATO,
                    observed=observed,
                    threshold=threshold,
                )

            if attempts >= two_factor_count:
                return self.result(
                    VELOCITY,
                    0,
                    TWO_FACTOR,
                    f"{window} somando {format_brl(window_amount)}.",
                    typology=ATO,
                    observed=observed,
                    threshold=threshold,
                )

        elif attempts >= reject_count:
            return self.result(
                VELOCITY,
                0,
                TWO_FACTOR,
                f"{window}, todas de valor baixo ({format_brl(window_amount)} no total).",
                typology=ATO,
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            VELOCITY, 0, PASS, "Ritmo de tentativas dentro do esperado.", observed=observed, threshold=threshold
        )
