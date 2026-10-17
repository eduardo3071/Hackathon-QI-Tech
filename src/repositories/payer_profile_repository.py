from datetime import datetime
from typing import Optional

from database import Context
from models import PayerProfile

# Quantos Pix aprovados o perfil guarda. É tamanho de armazenamento, não
# política: a janela de 90 dias é aplicada na leitura, com o parâmetro
# da política.
PROFILE_HISTORY_SIZE = 50

# Quantos locais de Pix aprovados o perfil guarda para a zona habitual.
# Também é tamanho de armazenamento: o raio e o mínimo de locais são da
# política.
LOCATION_HISTORY_SIZE = 20


class PayerProfileRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get(self, payer_document: str) -> Optional[PayerProfile]:
        return self.session.query(PayerProfile).filter(PayerProfile.payer_document_number == payer_document).first()

    def get_or_create(self, payer_document: str) -> PayerProfile:
        profile = self.get(payer_document)

        if profile is None:
            profile = PayerProfile(
                payer_document_number=payer_document,
                recent_approved=[],
                approved_count=0,
                max_night_approved_amount=0,
                recent_locations=[],
            )
            self.session.add(profile)

        return profile

    def add_approved(self, profile: PayerProfile, amount: int, approved_at: datetime) -> None:
        """Acrescenta um Pix aprovado e descarta os mais antigos além dos 50.

        A lista é TROCADA, não alterada no lugar: o SQLAlchemy não
        percebe um `.append` dentro de uma coluna JSONB, e a mudança não
        seria gravada.
        """
        recent_approved = profile.recent_approved + [{"amount": amount, "at": approved_at.isoformat()}]
        recent_approved.sort(key=lambda approved: datetime.fromisoformat(approved["at"]))

        profile.recent_approved = recent_approved[-PROFILE_HISTORY_SIZE:]
        profile.approved_count = profile.approved_count + 1

    def update_max_night_approved_amount(self, profile: PayerProfile, amount: int) -> None:
        profile.max_night_approved_amount = max(profile.max_night_approved_amount, amount)

    def update_last_geolocation(self, profile: PayerProfile, latitude, longitude, seen_at: datetime) -> None:
        profile.last_latitude = latitude
        profile.last_longitude = longitude
        profile.last_geolocation_at = seen_at

    def add_location(self, profile: PayerProfile, latitude, longitude, seen_at: datetime) -> None:
        """Acrescenta o local de um Pix aprovado e descarta os mais antigos além dos 20 (lista TROCADA, como acima)."""
        recent_locations = profile.recent_locations + [
            {"latitude": float(latitude), "longitude": float(longitude), "at": seen_at.isoformat()}
        ]
        recent_locations.sort(key=lambda location: datetime.fromisoformat(location["at"]))

        profile.recent_locations = recent_locations[-LOCATION_HISTORY_SIZE:]
