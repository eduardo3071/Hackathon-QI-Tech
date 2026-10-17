from abc import ABCMeta
from typing import Callable, Dict, List, Tuple

from controllers.features import PixFeatures
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import NOT_EVALUATED, NOT_NEEDED, SignalResult

# Um avaliador recebe as features e os parâmetros DO SEU sinal, e devolve
# o veredito. Os parâmetros da política inteira vêm junto para o raro
# sinal que depende de outro (a conta nova usa o "fora do perfil").
SignalEvaluator = Callable[[PixFeatures, dict, PolicyParameters], SignalResult]


class BaseRule(metaclass=ABCMeta):
    """A interface comum das 8 regras: `evaluate(features, params, camada)`.

    O motor só conhece este método. Regra nova é uma classe nova e uma
    linha de parâmetro, sem mexer no motor (padrão Strategy).

    Cada regra responde UMA pergunta e é composta de sinais. Cada sinal
    tem a sua camada, e `evaluate` só roda os sinais da camada pedida:
    é assim que um sinal caro fica na camada 2 e só roda quando houve
    motivo, sem que a regra precise saber disso.

    Quem herda declara `rule_code` e preenche `self.signals` no construtor
    com {código do sinal: (camada, método que avalia)}.
    """

    rule_code: str = ""

    def __init__(self) -> None:
        self.signals: Dict[str, Tuple[int, SignalEvaluator]] = {}

    def evaluate(self, features: PixFeatures, params: PolicyParameters, layer: int) -> List[SignalResult]:
        results = []

        for signal_code, (signal_layer, evaluator) in self.signals.items():
            if signal_layer != layer:
                continue

            if not params.is_enabled(signal_code):
                results.append(
                    self.result(signal_code, layer, NOT_EVALUATED, "Sinal desligado na política ativa.")
                )
                continue

            results.append(evaluator(features, params.of(signal_code), params))

        return results

    def layer_signals(self, layer: int) -> List[str]:
        return [signal_code for signal_code, (signal_layer, _evaluator) in self.signals.items() if signal_layer == layer]

    def result(self, signal_code: str, layer: int, outcome: str, message: str, **details) -> SignalResult:
        return SignalResult(
            rule_code=self.rule_code,
            signal_code=signal_code,
            layer=layer,
            outcome=outcome,
            message=message,
            **details,
        )

    def not_needed(self, signal_code: str, layer: int, message: str) -> SignalResult:
        return self.result(signal_code, layer, NOT_NEEDED, message)
