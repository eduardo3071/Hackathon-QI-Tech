from dataclasses import asdict, dataclass
from typing import List, Optional


@dataclass(frozen=True)
class PixFeatures:
    """Tudo o que as regras sabem sobre um Pix, já calculado.

    As regras não consultam o banco: recebem estes números prontos e só
    decidem. É o que deixa cada regra testável pelo que ela FAZ, e é o
    que fica gravado em `analysis.features` — o mesmo vetor que o modelo
    de anomalia da Fase 4 vai usar.

    Toda contagem de histórico é do que veio ANTES deste Pix: o Pix
    avaliado entra na conta dentro da regra, à vista ("anteriores + 1").
    A exceção é `payee_distinct_payers`, explicada no FeatureBuilder.
    Um campo `None` quer dizer que o sinal que o usa está desligado na
    política, e por isso nem foi calculado.
    """

    amount: int
    transaction_date: str
    local_hour: int
    same_ownership: bool
    payer_type: str
    payee_type: str

    # Regra 1 — marcações vigentes no momento do Pix
    payer_markers: List[dict]
    payee_markers: List[dict]

    # Regra 2 — aparelho e horário noturno
    payer_known: bool
    payer_account_age_days: int
    device_trusted: bool
    untrusted_devices_day_amount: Optional[int]
    is_night: Optional[bool]
    night_person_to_person_amount: Optional[int]
    max_night_approved_amount: int

    # Regra 3 — velocidade (pares recebedor+valor distintos, sem o deste Pix)
    velocity_attempts: Optional[int]
    velocity_amount: Optional[int]

    # Regra 4 — perfil
    profile_amounts: Optional[List[int]]
    pair_approved_count: int

    # Regra 6 — conta recebedora
    payee_account_age_days: int
    payee_prior_approved_credits: int
    payee_distinct_payers: Optional[int]

    def to_dict(self) -> dict:
        return asdict(self)
