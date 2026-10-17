from datetime import datetime
from typing import Optional

from database import Context
from models import DeviceOwner, PixTransaction


class DeviceOwnerRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get(self, device_id: int, document_number: str) -> Optional[DeviceOwner]:
        return (
            self.session.query(DeviceOwner)
            .filter(DeviceOwner.device_id == device_id, DeviceOwner.document_number == document_number)
            .first()
        )

    def register_attempt(self, device_id: int, document_number: str, seen_at: datetime) -> DeviceOwner:
        device_owner = self.get(device_id, document_number)

        if device_owner is None:
            device_owner = DeviceOwner(device_id=device_id, document_number=document_number, first_seen_at=seen_at)
            self.session.add(device_owner)

        return device_owner

    def set_first_approved(self, device_owner: DeviceOwner, pix_transaction: PixTransaction) -> None:
        device_owner.first_approved_pix_id = pix_transaction.id
