import time
from dataclasses import dataclass
from typing import List, Optional

from controllers.decision import (
    STEP_UP_ACCOUNT_TAKEOVER,
    STEP_UP_LIMIT,
    STEP_UP_POSSIBLE_SCAM,
    Decision,
    DecisionMaker,
)
from controllers.features import PixFeatures
from controllers.rules import RULES
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import APP, ATO, MULE, NOT_EVALUATED, SignalResult

FAST = "fast"
DEEP = "deep"

ALWAYS_LAYERS = (0, 1)
DEEP_LAYER = 2

DECISION_PARAMETERS = "DECISAO.placares"


@dataclass(frozen=True)
class EngineResult:
    results: List[SignalResult]
    decision: Decision
    path: str
    layers: List[int]


class AnalysisEngine:
    """Avalia um Pix em camadas e só aprofunda quando a camada anterior levanta sinal.

      camada 0 — sempre: marcação, limites de norma, velocidade;
      camada 1 — sempre: leituras das tabelas agregadas (perfil, conta recebedora);
      gatilho  — sem sinal de risco, aprova pelo caminho rápido;
      camada 2 — só com sinal, com tempo limite: regras de rede e ML.

    O motor só conhece a interface das regras (`evaluate`). Regra nova é
    mais uma linha em `controllers/rules/__init__.py`.
    """

    def __init__(self) -> None:
        self.rules = RULES
        self.decision_maker = DecisionMaker()

    def run(self, features: PixFeatures, params: PolicyParameters) -> EngineResult:
        results = []
        for layer in ALWAYS_LAYERS:
            for rule in self.rules:
                results.extend(rule.evaluate(features, params, layer))

        cuts = params.of(DECISION_PARAMETERS)
        strong_step_up = self._needs_strong_step_up(features, cuts)

        deep_layer_reason = self._deep_layer_reason(features, results)

        if deep_layer_reason is None:
            for rule in self.rules:
                for signal_code in rule.layer_signals(DEEP_LAYER):
                    results.append(
                        rule.not_needed(signal_code, DEEP_LAYER, "Caminho rápido: nenhum sinal de risco nas camadas 0 e 1.")
                    )

            decision = self.decision_maker.decide(
                results, cuts, deep_layer_timed_out=False, deep_layer_reason=None, strong_step_up=strong_step_up
            )
            return EngineResult(results, decision, FAST, list(ALWAYS_LAYERS))

        deep_layer_timed_out = self._run_deep_layer(features, params, results, cuts["deep_layer_timeout_ms"])

        decision = self.decision_maker.decide(
            results, cuts, deep_layer_timed_out, deep_layer_reason, strong_step_up=strong_step_up
        )
        return EngineResult(results, decision, DEEP, list(ALWAYS_LAYERS) + [DEEP_LAYER])

    @staticmethod
    def _needs_strong_step_up(features: PixFeatures, cuts: dict) -> bool:
        """Se qualquer 2FA deste Pix tem de ser biometria facial, e não a confirmação no app.

        A confirmação no próprio celular não protege quando é o ladrão quem o
        segura: na bateria, o celular roubado e desbloqueado confirmou 3 Pix
        seguidos no app. Por isso `in_app_confirmation` só fica para o
        aparelho confiável, sem biometria reprovada nas últimas 24 h, perto
        de onde o pagador costuma estar. Longe de TODOS os últimos locais
        aprovados (mais de `street_mode_km`) vale a biometria: é o que o
        Modo Rua do Nubank faz.
        """
        far_from_usual_places = features.zone_nearest_km is not None and features.zone_nearest_km > cuts["street_mode_km"]

        return not features.device_trusted or features.payer_biometric_failed_recently or far_from_usual_places

    def _deep_layer_reason(self, features: PixFeatures, results: List[SignalResult]) -> Optional[str]:
        """O gatilho: POR QUE este Pix precisa da camada 2 — ou None, e ele sai pelo caminho rápido.

        Vale um sinal de risco das camadas 0 e 1 ou um contexto de risco do
        plano: aparelho não confiável, destino não recorrente, horário noturno. Valor
        fora do perfil e conta destino recente já aparecem como sinal.

        O motivo é o mesmo vocabulário do `step_up_reason`: se a camada 2
        estourar o tempo, o 2FA sai pelo motivo que levou até ela.
        """
        risk_typologies = {result.typology for result in results if result.is_risk()}
        has_risk_signal = any(result.is_risk() for result in results)

        if ATO in risk_typologies or not features.device_trusted:
            return STEP_UP_ACCOUNT_TAKEOVER

        if APP in risk_typologies or MULE in risk_typologies or not features.destination_recurring:
            return STEP_UP_POSSIBLE_SCAM

        if has_risk_signal or features.is_night:
            return STEP_UP_LIMIT

        return None

    def _run_deep_layer(self, features, params, results, timeout_ms: int) -> bool:
        """Roda a camada 2 dentro do orçamento de tempo. Devolve se estourou.

        O relógio é conferido antes de cada regra: a que já começou
        termina, e as seguintes ficam `not_evaluated`. Não dá para
        interromper uma consulta no meio sem perder a sessão de banco.
        """
        started_at = time.perf_counter()
        timed_out = False

        for rule in self.rules:
            elapsed_ms = (time.perf_counter() - started_at) * 1000

            if elapsed_ms > timeout_ms:
                timed_out = True
                for signal_code in rule.layer_signals(DEEP_LAYER):
                    results.append(
                        rule.result(signal_code, DEEP_LAYER, NOT_EVALUATED, f"Camada 2 passou de {timeout_ms} ms.")
                    )
                continue

            results.extend(rule.evaluate(features, params, DEEP_LAYER))

        return timed_out
