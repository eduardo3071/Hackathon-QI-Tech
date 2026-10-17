import time
from dataclasses import dataclass
from typing import List

from controllers.decision import Decision, DecisionMaker
from controllers.features import PixFeatures
from controllers.rules import RULES
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import NOT_EVALUATED, SignalResult

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

        if not self._needs_deep_layer(features, results):
            for rule in self.rules:
                for signal_code in rule.layer_signals(DEEP_LAYER):
                    results.append(
                        rule.not_needed(signal_code, DEEP_LAYER, "Caminho rápido: nenhum sinal de risco nas camadas 0 e 1.")
                    )

            decision = self.decision_maker.decide(results, cuts, deep_layer_timed_out=False)
            return EngineResult(results, decision, FAST, list(ALWAYS_LAYERS))

        deep_layer_timed_out = self._run_deep_layer(features, params, results, cuts["deep_layer_timeout_ms"])

        decision = self.decision_maker.decide(results, cuts, deep_layer_timed_out)
        return EngineResult(results, decision, DEEP, list(ALWAYS_LAYERS) + [DEEP_LAYER])

    def _needs_deep_layer(self, features: PixFeatures, results: List[SignalResult]) -> bool:
        """O gatilho: algum sinal de risco, ou um contexto que o justifique.

        Contexto de risco é o que o plano lista: destino novo, aparelho
        novo e horário noturno. Valor fora do perfil e conta destino
        recente já aparecem como sinal nas camadas 0 e 1.
        """
        if any(result.is_risk() for result in results):
            return True

        return not features.device_known or features.pair_approved_count == 0 or bool(features.is_night)

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
