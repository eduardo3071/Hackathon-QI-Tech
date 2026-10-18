import math

from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import ATO, NOT_EVALUATED, PASS, WARN, SignalResult
from ml import AnomalyModel

ML = "ANOMALIA.ml"
ACTIVE = "active"


class AnomaliaRule(BaseRule):
    """Regra 8 — É diferente de tudo que é normal?

    Um Isolation Forest treinado só com Pix legítimos (scripts/ml/train.py)
    mede o quanto este Pix foge do comportamento normal. As regras cobrem
    o que conhecemos; o modelo sinaliza o que nenhuma regra descreve.

    O modo vem da política (`ml_mode`):
      • sombra — o escore vai para o metadata e não muda a decisão;
      • ativo — acima do corte, pontua invasão, crescendo com o escore até
        um teto. O placar de invasão só leva a 2FA (biometria): o modelo
        nunca recusa, nem somado a outros sinais.

    Sem o artefato do modelo, ou com erro nele, `not_evaluated`: o motor
    decide só com as regras.
    """

    rule_code = "ANOMALIA"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {ML: (2, self._evaluate_ml)}

    def _evaluate_ml(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        result = AnomalyModel.shared().evaluate(features.to_dict())
        mode = params.ml_mode

        threshold = {
            "mode": mode,
            "score_threshold": parameters["score_threshold"],
            "score_span": parameters["score_span"],
            "max_points": parameters["max_points"],
        }

        if not result.evaluated:
            return self.result(ML, 2, NOT_EVALUATED, f"Modelo de anomalia não avaliado: {result.reason}.", threshold=threshold)

        observed = {
            "anomaly_score": result.score,
            "model_version": result.model_version,
            "top_features": result.top_features,
        }
        above = result.score >= parameters["score_threshold"]
        why = ", ".join(result.top_features)

        if mode != ACTIVE:
            message = f"Modo sombra: escore de anomalia {result.score:.3f} ({why}); não muda a decisão."
            return self.result(ML, 2, PASS, message, observed=observed, threshold=threshold)

        if not above:
            return self.result(
                ML, 2, PASS, f"Escore de anomalia {result.score:.3f}, abaixo do corte.", observed=observed, threshold=threshold
            )

        share = (result.score - parameters["score_threshold"]) / parameters["score_span"]
        points = min(parameters["max_points"], max(1, math.ceil(share * parameters["max_points"])))

        return self.result(
            ML,
            2,
            WARN,
            f"Pix fora do comportamento normal (escore {result.score:.3f}): {why}.",
            typology=ATO,
            points=points,
            observed=observed,
            threshold=threshold,
        )
