from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from models.base import Base
from models import Device, PixTransaction


class DeviceOwner(Base):
    """Aparelho × documento: este aparelho já fez Pix aprovado para esta pessoa?"""

    __tablename__ = "device_owner"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey(Device.id), nullable=False)
    document_number = Column(String(14), nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    first_approved_pix_id = Column(Integer, ForeignKey(PixTransaction.id), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "document_number"),)
