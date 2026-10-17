from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from models.base import Base
from models import Account, Device


class PixTransaction(Base):
    __tablename__ = "pix_transaction"

    id = Column(Integer, primary_key=True)
    external_id = Column(String(64), nullable=False)
    payload_hash = Column(CHAR(64), nullable=False)
    amount = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    source_account_id = Column(Integer, ForeignKey(Account.id), nullable=False)
    destination_account_id = Column(Integer, ForeignKey(Account.id), nullable=False)
    device_id = Column(Integer, ForeignKey(Device.id), nullable=False)
    payer_document_number = Column(String(14), nullable=False)
    payee_document_number = Column(String(14), nullable=False)
    channel = Column(String(30), nullable=False)
    ip = Column(String(45), nullable=False)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)
    raw_payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("external_id"),)

    source_account = relationship("Account", foreign_keys=[source_account_id], lazy="selectin")
    destination_account = relationship("Account", foreign_keys=[destination_account_id], lazy="selectin")
    device = relationship("Device", foreign_keys=[device_id], lazy="selectin")
    analysis = relationship("Analysis", back_populates="pix_transaction", uselist=False, lazy="selectin")
