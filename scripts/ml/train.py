"""Treina o Isolation Forest da Regra 8 só com os Pix legítimos do simulador.

    python scripts/simulator/prepare_db.py --ml-mode shadow
    python scripts/simulator/run.py --seed 1 --output scripts/simulator/output/treino.jsonl
    python scripts/ml/train.py

No container, com as versões da imagem:

    docker compose run --rm -v "$PWD/scripts:/scripts" -e PYTHONPATH=/app api python /scripts/ml/train.py

Lê as features que cada análise já grava (`analysis.features`) dos Pix com
`id` `sim-legit-`, treina só com eles (o modelo aprende o normal, e não as
nossas fraudes) e exporta o modelo para JSON em src/ml/artifacts/. O JSON
traz a versão, a lista de features, as estatísticas do treino (para
explicar o escore) e as árvores. Antes de gravar, confere que a inferência
em Python puro do src/ml/ dá o mesmo escore que o scikit-learn.

Treine com uma semente e avalie com outra: o modelo não pode ter visto os
Pix da avaliação.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy
import sklearn
from sklearn.ensemble import IsolationForest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from ml.anomaly_model import AnomalyModel  # noqa: E402
from ml.features import FEATURES, feature_vector  # noqa: E402

DEFAULT_DATABASE_URL = "postgresql+psycopg2://bootcamp:bootcamp@localhost:5432/bootcamp"
VERSION = "iforest-v1"


def load_legit_features(database_url: str) -> list:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT analysis.features FROM analysis "
                "JOIN pix_transaction ON pix_transaction.id = analysis.pix_transaction_id "
                "WHERE pix_transaction.external_id LIKE 'sim-legit-%' ORDER BY pix_transaction.id"
            )
        ).all()
    engine.dispose()
    return [row.features for row in rows]


def export_tree(estimator, feature_indices) -> dict:
    """A árvore do scikit-learn em listas, com o índice da feature já no vetor completo."""
    tree = estimator.tree_
    return {
        "left": tree.children_left.tolist(),
        "right": tree.children_right.tolist(),
        "feature": [int(feature_indices[f]) if f >= 0 else -1 for f in tree.feature],
        "threshold": [float(t) for t in tree.threshold],
        "samples": [int(n) for n in tree.n_node_samples],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default=str(ROOT / "src" / "ml" / "artifacts" / f"{VERSION}.json"))
    parser.add_argument("--trees", type=int, default=100)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    raw = load_legit_features(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    if len(raw) < 500:
        raise SystemExit(f"Só {len(raw)} Pix legítimos no banco: rode o simulador antes de treinar.")

    matrix = numpy.array([feature_vector(features) for features in raw])
    model = IsolationForest(n_estimators=args.trees, max_samples=256, random_state=args.random_state)
    model.fit(matrix)

    quartiles = numpy.percentile(matrix, [25, 50, 75], axis=0)
    artifact = {
        "version": VERSION,
        "trained_with": {"sklearn": sklearn.__version__, "legit_pix": len(raw), "random_state": args.random_state},
        "max_samples": int(model.max_samples_),
        "features": [{"name": feature.name, "label": feature.label} for feature in FEATURES],
        "stats": [
            {
                "median": float(quartiles[1][i]),
                "iqr": float(quartiles[2][i] - quartiles[0][i]),
                "std": float(matrix[:, i].std()),
            }
            for i in range(matrix.shape[1])
        ],
        "trees": [
            export_tree(estimator, features)
            for estimator, features in zip(model.estimators_, model.estimators_features_)
        ],
    }

    Path(args.output).write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")

    # A inferência do src/ml/ tem de dar o mesmo escore que o scikit-learn.
    exported = AnomalyModel(Path(args.output))
    sample = raw[:: max(len(raw) // 300, 1)]
    ours = numpy.array([exported.evaluate(features).score for features in sample])
    theirs = -model.score_samples(numpy.array([feature_vector(features) for features in sample]))
    worst = float(numpy.max(numpy.abs(ours - theirs)))
    if worst > 1e-3:
        Path(args.output).unlink()
        raise SystemExit(f"A inferência exportada difere do scikit-learn em {worst:.5f}: artefato descartado.")

    legit_scores = -model.score_samples(matrix)
    print(f"{VERSION}: {len(raw)} Pix legítimos, {args.trees} árvores → {args.output}")
    print(f"Inferência exportada = scikit-learn (maior diferença {worst:.6f}).")
    for percent in (50, 95, 99, 99.5, 99.9):
        print(f"  escore dos legítimos p{percent}: {numpy.percentile(legit_scores, percent):.4f}")


if __name__ == "__main__":
    main()
