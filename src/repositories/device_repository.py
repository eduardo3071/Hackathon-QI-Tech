from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import Device


class DeviceRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_or_create(self, device_id: str, seen_at: datetime) -> Device:
        """Mesmo desenho do AccountRepository.get_or_create, pelo mesmo motivo."""
        statement = insert(Device).values(device_id=device_id, first_seen_at=seen_at).on_conflict_do_nothing()
        self.session.execute(statement)

        return self.session.query(Device).filter(Device.device_id == device_id).one()
