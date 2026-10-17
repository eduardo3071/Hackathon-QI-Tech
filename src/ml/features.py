"""As features do modelo de anomalia, tiradas do que cada análise já grava.

O treino (scripts/ml/train.py) lê `analysis.features` do banco; a API usa
as features do Pix que está avaliando (`PixFeatures.to_dict()`). Os dois
passam por `feature_vector`, e por isso o modelo vê, na hora de decidir,
exatamente o que viu no treino.

Escalas: valores e idades em log, porque a diferença entre R$ 10 e R$ 100
importa tanto quanto entre R$ 1.000 e R$ 10.000.
"""

import math
from statistics import median
from typing import Callable, List, NamedTuple, Optional


class Feature(NamedTuple):
    name: str
    label: str  # como aparece no motivo, em português
    extract: Callable[[dict], float]


def _log10_reais(cents: Optional[float]) -> float:
    return math.log10(max(cents or 0, 0) / 100 + 1)


def _amount_to_median(features: dict) -> float:
    """Quantas vezes a mediana dos Pix aprovados do pagador; sem histórico, quantas vezes R$ 1.000."""
    amounts = features.get("profile_amounts") or []
    reference = median(amounts) if amounts else 100000
    return math.log10(features["amount"] / max(reference, 1))


# Só features contínuas. As binárias (destino novo, aparelho confiável)
# faziam o Isolation Forest isolar rápido qualquer legítimo do lado raro
# delas, e o escore dos legítimos se espalhava. As regras já cuidam delas.
FEATURES: List[Feature] = [
    Feature("amount", "valor do Pix", lambda f: _log10_reais(f["amount"])),
    Feature("amount_to_median", "valor em relação à mediana do pagador", _amount_to_median),
    Feature("local_hour", "hora do Pix", lambda f: float(f["local_hour"])),
    Feature("payee_account_age", "idade da conta recebedora", lambda f: math.log1p(f.get("payee_account_age_days") or 0)),
    Feature("zone_distance", "distância da zona habitual", lambda f: math.log1p(f.get("zone_nearest_km") or 0)),
    Feature("third_party_credits", "créditos de terceiros na última hora", lambda f: _log10_reais(f.get("payer_recent_third_party_credits"))),
    Feature("velocity_attempts", "tentativas nos últimos 10 minutos", lambda f: float(f.get("velocity_attempts") or 0)),
    Feature("distinct_payees_24h", "destinos distintos nas últimas 24 h", lambda f: math.log1p(f.get("payer_distinct_payees_24h") or 0)),
]


def feature_vector(features: dict) -> List[float]:
    return [feature.extract(features) for feature in FEATURES]
