from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import ATO, PASS, REJECT, TWO_FACTOR, SignalResult
from utils.money import format_brl

VELOCITY = "RITMO.velocidade"
FRACTIONING = "RITMO.fracionamento"
NEW_PAYEES = "RITMO.destinos_novos"


class RitmoRule(BaseRule):
    """Regra 3 — Rápido demais ou somou demais?

    Quem invade uma conta tenta esvaziá-la rápido. A janela é deslizante
    e conta as tentativas recusadas também: insistência é sinal.
    """

    rule_code = "RITMO"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {
            VELOCITY: (0, self._evaluate_velocity),
            NEW_PAYEES: (0, self._evaluate_new_payees),
            FRACTIONING: (2, self._evaluate_fractioning),
        }

    def _evaluate_new_payees(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Rajada para destinos novos: a mão fantasma do acesso remoto.

        Quem opera a conta por acesso remoto, do aparelho de sempre, manda
        vários Pix para contas que o titular nunca pagou. A velocidade só
        trava a partir do 5º Pix; aqui, 3 destinos novos distintos em 10
        minutos, somando R$ 2.000 ou mais, já pedem biometria (a
        confirmação no app não prova nada com o celular nas mãos de outro).
        """
        min_count = parameters["min_count"]
        min_amount = parameters["min_amount"]
        new_payees = features.new_payee_burst_count
        window_amount = features.new_payee_burst_amount

        observed = {"new_payees": new_payees, "window_amount": window_amount}
        threshold = {
            "window_minutes": parameters["window_minutes"],
            "min_count": min_count,
            "min_amount": min_amount,
        }

        if new_payees >= min_count and window_amount >= min_amount:
            return self.result(
                NEW_PAYEES,
                0,
                TWO_FACTOR,
                f"{new_payees} destinos novos em {parameters['window_minutes']} minutos, somando "
                f"{format_brl(window_amount)}: padrão de conta sendo operada à distância.",
                typology=ATO,
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            NEW_PAYEES, 0, PASS, "Sem rajada de Pix para destinos novos.", observed=observed, threshold=threshold
        )

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

    def _evaluate_fractioning(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Vários Pix logo abaixo de um limite, na mesma hora: o valor picado para caber no teto.

        Os limites são os da própria política: os R$ 200 por Pix do
        aparelho não cadastrado e os R$ 1.000 do noturno. Um Pix "logo
        abaixo" fica entre 90% e 100% de um deles. Pede 2FA de limite —
        confirmação no app, sem tipologia de fraude: picar o valor é jeito
        de passar pelo limite, não prova de quem opera.
        """
        limits = []
        for signal_code, limit_field in (
            ("LIMITE.aparelho_nao_cadastrado", "max_amount_per_pix"),
            ("LIMITE.noturno", "max_night_amount"),
        ):
            if params.of(signal_code) is not None:
                limits.append(params.of(signal_code)[limit_field])

        floor_percent = parameters["band_floor_percent"]

        def in_band(amount: int) -> bool:
            return any(limit * floor_percent <= amount * 100 <= limit * 100 for limit in limits)

        pix_in_band = 0
        if in_band(features.amount):
            pix_in_band = 1 + sum(1 for amount in features.fractioning_window_amounts if in_band(amount))

        min_count = parameters["min_count"]
        observed = {"pix_in_band": pix_in_band}
        threshold = {
            "min_count": min_count,
            "window_minutes": parameters["window_minutes"],
            "band_floor_percent": floor_percent,
            "limits": limits,
        }

        if pix_in_band >= min_count:
            return self.result(
                FRACTIONING,
                2,
                TWO_FACTOR,
                f"{pix_in_band} Pix em {parameters['window_minutes']} minutos, cada um logo abaixo de um limite "
                f"({', '.join(format_brl(limit) for limit in limits)}): valor picado para caber no teto.",
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            FRACTIONING, 2, PASS, "Sem sequência de Pix logo abaixo de um limite.", observed=observed, threshold=threshold
        )
