import math
from statistics import median

from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import APP, ATO, PASS, WARN, SignalResult
from utils.money import format_brl

VALUE = "PERFIL.valor"


def percentile(amounts: list, percent: int) -> int:
    """Percentil pelo método do posto mais próximo: sempre um valor que existiu de verdade."""
    ordered = sorted(amounts)
    rank = math.ceil(percent / 100 * len(ordered))

    return ordered[max(rank, 1) - 1]


class PerfilRule(BaseRule):
    """Regra 4 — Está no padrão deste cliente?

    A Res. BCB 403 exige identificar transação "não compatível com o
    perfil do cliente", e o STJ (REsp 2.209.868, 2026) usa o mesmo
    critério para decidir se o banco responde pelo golpe.

    O mesmo valor fora do perfil muda de sentido com o contexto:
      • destino já pago antes → a conta do mês (aluguel): atenua, passa;
      • aparelho novo ou ainda não confiável → quem opera pode não ser o
        dono: pontua invasão;
      • aparelho conhecido, destino novo → a vítima autenticada mandando
        para o golpista: pontua golpe.
    """

    rule_code = "PERFIL"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {VALUE: (1, self._evaluate_value)}

    @staticmethod
    def profile_check(features: PixFeatures, parameters: dict) -> dict:
        """Se o valor está fora do perfil, com o que foi observado e contra qual limite.

        Estático porque a conta nova (Regra 6) faz a MESMA pergunta — "o
        valor está fora do perfil?" — e não pode ter uma resposta sua.
        """
        amounts = features.profile_amounts
        amount = features.amount

        if len(amounts) >= parameters["min_history"]:
            amounts_median = int(median(amounts))
            amounts_percentile = percentile(amounts, parameters["percentile"])
            median_limit = parameters["median_multiplier"] * amounts_median
            out_of_profile = amount > amounts_percentile and amount > median_limit

            # O segundo degrau: muito fora do perfil (10x a mediana) e acima
            # do piso (R$ 1.000), para que o cliente de mediana R$ 20 não
            # tome 2FA num Pix de R$ 200.
            high_median_limit = parameters["high_median_multiplier"] * amounts_median

            return {
                "out_of_profile": out_of_profile,
                "far_out_of_profile": (
                    out_of_profile and amount >= high_median_limit and amount > parameters["high_min_amount"]
                ),
                "observed": {
                    "amount": amount,
                    "median": amounts_median,
                    f"p{parameters['percentile']}": amounts_percentile,
                    "history_size": len(amounts),
                },
                "threshold": {
                    f"p{parameters['percentile']}": amounts_percentile,
                    "median_multiple": median_limit,
                    "high_median_multiple": high_median_limit,
                    "high_min_amount": parameters["high_min_amount"],
                    "window_days": parameters["window_days"],
                },
            }

        # Sem histórico suficiente, o limite de partida: entre o Pix médio
        # entre pessoas (R$ 273) e o ticket médio da fraude (R$ 1.735).
        return {
            "out_of_profile": amount > parameters["fallback_amount"],
            "far_out_of_profile": False,
            "observed": {"amount": amount, "history_size": len(amounts)},
            "threshold": {"fallback_amount": parameters["fallback_amount"], "min_history": parameters["min_history"]},
        }

    def _evaluate_value(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        if features.same_ownership:
            return self.not_needed(VALUE, 1, "Mesma titularidade: mover o próprio dinheiro não é golpe de terceiro.")

        check = self.profile_check(features, parameters)
        observed = check["observed"]
        threshold = check["threshold"]

        if not check["out_of_profile"]:
            return self.result(
                VALUE, 1, PASS, "Valor dentro do perfil do pagador.", observed=observed, threshold=threshold
            )

        if features.destination_recurring:
            return self.result(
                VALUE,
                1,
                PASS,
                f"Valor fora do perfil, mas para um destino já pago {features.pair_approved_count} vez(es) "
                "por este pagador: a conta do mês, não o golpe.",
                observed=observed,
                threshold=threshold,
            )

        if not features.device_trusted:
            return self.result(
                VALUE,
                1,
                WARN,
                f"{format_brl(features.amount)} fora do perfil, de um aparelho ainda não confiável: quem opera pode não ser o titular.",
                typology=ATO,
                points=parameters["ato_points"],
                observed=observed,
                threshold=threshold,
            )

        # Aparelho de sempre, destino novo: golpe. Entre 5 e 10x a mediana,
        # o primeiro degrau pontua a faixa de aviso; com 10x ou mais (acima
        # do piso), o segundo pontua o corte de golpe: 2FA com aviso.
        app_points = parameters["app_points"]
        degree = ""
        if check["far_out_of_profile"]:
            app_points = parameters["high_app_points"]
            degree = f" — {parameters['high_median_multiplier']}x a mediana ou mais"

        if features.pair_scam_step_up_count > 0:
            return self.result(
                VALUE,
                1,
                WARN,
                f"{format_brl(features.amount)} fora do perfil{degree}, para um destino que este pagador já "
                "confirmou sob aviso de golpe: o destino não conta como recorrente.",
                typology=APP,
                points=app_points,
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            VALUE,
            1,
            WARN,
            f"{format_brl(features.amount)} fora do perfil{degree}, para um destino novo, do aparelho de sempre: "
            "padrão de golpe com a vítima autenticada.",
            typology=APP,
            points=app_points,
            observed=observed,
            threshold=threshold,
        )
