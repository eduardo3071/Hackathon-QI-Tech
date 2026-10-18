"""Inferência do Isolation Forest, em Python puro, a partir do artefato JSON.

O modelo é treinado com o scikit-learn (scripts/ml/train.py) e exportado
como JSON: as árvores (feature, corte e filhos de cada nó) e as
estatísticas do treino. Avaliar aqui, sem o scikit-learn e sem pickle,
evita que a versão de quem treinou precise bater com a da API.

O escore é o do artigo do Isolation Forest (Liu et al., 2008): de 0 a 1,
perto de 1 é anomalia, perto de 0,5 é comum. É o mesmo número que o
`score_samples` do scikit-learn devolve com o sinal trocado.

Se o artefato faltar ou der erro, o resultado é "não avaliado" — nunca
uma exceção: o motor decide só com as regras.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ml.features import FEATURES, feature_vector
from utils.logger import get_logger

DEFAULT_ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "iforest-v1.json"
EULER_GAMMA = 0.5772156649


def average_path_length(n: float) -> float:
    """c(n): o tamanho médio de uma busca sem sucesso numa árvore binária com n pontos."""
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (math.log(n - 1) + EULER_GAMMA) - 2.0 * (n - 1) / n


@dataclass(frozen=True)
class AnomalyResult:
    evaluated: bool
    reason: str = ""
    score: Optional[float] = None
    model_version: Optional[str] = None
    top_features: List[str] = field(default_factory=list)


class AnomalyModel:
    """Carrega o artefato uma vez e avalia Pix. Um só por processo (`AnomalyModel.shared()`)."""

    _shared = None

    def __init__(self, artifact_path: Path = DEFAULT_ARTIFACT) -> None:
        self.logger = get_logger(__name__)
        self.artifact = None
        self.load_error = None
        try:
            artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
            if [feature["name"] for feature in artifact["features"]] != [feature.name for feature in FEATURES]:
                raise ValueError("as features do artefato não são as do código")
            self.artifact = artifact
        except Exception as error:  # noqa: BLE001 — qualquer falha vira "não avaliado"
            self.load_error = f"modelo indisponível ({type(error).__name__})"
            self.logger.warning(f"Modelo de anomalia não carregado: {error}")

    @classmethod
    def shared(cls) -> "AnomalyModel":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def evaluate(self, features: dict) -> AnomalyResult:
        if self.artifact is None:
            return AnomalyResult(evaluated=False, reason=self.load_error or "modelo indisponível")

        try:
            vector = feature_vector(features)
            depths = [self._path_length(tree, vector) for tree in self.artifact["trees"]]
            normalizer = average_path_length(self.artifact["max_samples"])
            score = 2 ** (-(sum(depths) / len(depths)) / normalizer)

            return AnomalyResult(
                evaluated=True,
                score=round(score, 4),
                model_version=self.artifact["version"],
                top_features=self._top_features(vector),
            )
        except Exception as error:  # noqa: BLE001
            self.logger.warning(f"Falha ao avaliar o modelo de anomalia: {type(error).__name__}")
            return AnomalyResult(evaluated=False, reason=f"falha ao avaliar ({type(error).__name__})")

    @staticmethod
    def _path_length(tree: dict, vector: List[float]) -> float:
        node, depth = 0, 0
        while tree["left"][node] != -1:
            if vector[tree["feature"][node]] <= tree["threshold"][node]:
                node = tree["left"][node]
            else:
                node = tree["right"][node]
            depth += 1

        return depth + average_path_length(tree["samples"][node])

    def _top_features(self, vector: List[float]) -> List[str]:
        """As 3 features mais longe do normal do treino, em desvios robustos (mediana e intervalo interquartil)."""
        deviations = []
        for index, (feature, value) in enumerate(zip(self.artifact["features"], vector)):
            stats = self.artifact["stats"][index]
            spread = stats["iqr"] or stats["std"] or 1.0
            deviations.append((abs(value - stats["median"]) / spread, index, value))

        top = []
        for _deviation, index, value in sorted(deviations, reverse=True)[:3]:
            feature = self.artifact["features"][index]
            direction = "acima" if value > self.artifact["stats"][index]["median"] else "abaixo"
            top.append(f"{feature['label']} {direction} do normal")

        return top
