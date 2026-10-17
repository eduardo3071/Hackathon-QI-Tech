"""Confere o módulo de inferência sem a API: artefato bom, ausente e corrompido.

    python scripts/ml/check_model.py

Os testes do projeto são caixa-preta (só HTTP), e a falha do artefato não
dá para provocar por HTTP sem mexer nos arquivos da API. Esta checagem
cobre o que eles não alcançam: arquivo faltando ou com defeito vira "não
avaliado", nunca exceção.
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from ml.anomaly_model import DEFAULT_ARTIFACT, AnomalyModel  # noqa: E402

TYPICAL = {
    "amount": 15000, "local_hour": 14, "payer_account_age_days": 900, "payee_account_age_days": 2000,
    "profile_amounts": [12000, 15000, 18000, 14000, 16000], "pair_approved_count": 3, "pair_scam_step_up_count": 0,
    "device_trusted": True, "velocity_attempts": 0, "payee_distinct_payers": 1, "zone_nearest_km": 1.2,
    "payer_recent_third_party_credits": 0, "device_distinct_payers": 1, "payer_distinct_payees_24h": 2,
}
CENTS = {**TYPICAL, "amount": 7, "pair_approved_count": 0, "payer_distinct_payees_24h": 18}


def main() -> None:
    model = AnomalyModel(DEFAULT_ARTIFACT)
    typical, cents = model.evaluate(TYPICAL), model.evaluate(CENTS)
    assert typical.evaluated and cents.evaluated, "o artefato do repositório não carregou"
    assert len(cents.top_features) == 3
    print(f"típico: {typical.score}  centavos: {cents.score}  motivos: {cents.top_features}")

    missing = AnomalyModel(Path("/nao/existe.json")).evaluate(TYPICAL)
    assert not missing.evaluated and missing.reason, missing

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as broken:
        broken.write("{ isto não é json")
    corrupt = AnomalyModel(Path(broken.name)).evaluate(TYPICAL)
    Path(broken.name).unlink()
    assert not corrupt.evaluated and corrupt.reason, corrupt

    print(f"ausente: não avaliado ({missing.reason}); corrompido: não avaliado ({corrupt.reason})")


if __name__ == "__main__":
    main()
