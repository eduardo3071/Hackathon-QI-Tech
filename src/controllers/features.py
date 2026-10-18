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
    payer_has_trusted_device: bool
    untrusted_devices_day_amount: Optional[int]
    is_night: Optional[bool]
    night_person_to_person_amount: Optional[int]
    max_night_approved_amount: int

    # Regra 3 — velocidade (pares recebedor+valor distintos, sem o deste Pix)
    velocity_attempts: Optional[int]
    velocity_amount: Optional[int]
    # Valores das tentativas anteriores na janela do fracionamento, um por
    # par (recebedor, valor), sem o deste Pix.
    fractioning_window_amounts: Optional[List[int]]

    # Regra 4 — perfil
    profile_amounts: Optional[List[int]]
    pair_approved_count: int
    pair_approved_days: int
    pair_max_approved_amount: int
    pair_scam_step_up_count: int
    # Se o destino vale como "a conta do mês": calculado pelo FeatureBuilder
    # (precisa do valor deste Pix e dos parâmetros da política).
    destination_recurring: bool
    # O padrão da conta mensal: valor parecido com um pagamento já confirmado
    # a este destino, feito há pelo menos N dias.
    destination_monthly_bill: bool

    # Regra 5 — quem está operando
    device_distinct_payers: Optional[int]
    ip_distinct_payers: Optional[int]
    has_geolocation: bool
    channel: str
    channel_used_before: Optional[bool]
    # Até o último Pix APROVADO com geolocalização; None sem esse histórico.
    # As horas podem ser zero ou negativas (Pix que chegou fora de ordem).
    last_location_distance_km: Optional[float]
    last_location_hours: Optional[float]
    # Zona habitual: quantos locais de Pix aprovados o perfil conhece, e a
    # distância deste Pix até o mais próximo deles (None sem geolocalização).
    zone_known_locations: int
    zone_nearest_km: Optional[float]

    # Regra 6 — conta recebedora
    payee_account_age_days: int
    payee_prior_approved_credits: int
    payee_distinct_payers: Optional[int]
    payee_prior_scam_step_ups: Optional[int]
    # Dias desde o último crédito aprovado que a conta destino recebeu NA
    # NOSSA BASE; None se o motor nunca a viu receber.
    payee_days_without_movement: Optional[int]
    payee_new_account_institutions: Optional[int]

    # Regra 8 — anomalia: para quantos destinos distintos o pagador mandou
    # nas 24 h anteriores (o "muitos destinos" que nenhuma regra conta).
    payer_distinct_payees_24h: int

    # Regra 7 — rastro do dinheiro
    payer_recent_third_party_credits: Optional[int]
    # Saltos até o documento com marcação mais próximo que mandou dinheiro
    # (direta ou indiretamente) ao recebedor na janela; None se nenhum.
    payee_marked_sender_hop: Optional[int]

    def to_dict(self) -> dict:
        return asdict(self)
