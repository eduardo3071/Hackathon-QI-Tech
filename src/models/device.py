from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func
from models.base import Base


class Device(Base):
    __tablename__ = "device"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(128), nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id"),)
