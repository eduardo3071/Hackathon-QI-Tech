from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from models.base import Base
from models import Account


class PayerPayeePair(Base):
    """Pagador × conta recebedora: o destino já foi pago antes? Tabela agregada do caminho rápido."""

    __tablename__ = "payer_payee_pair"

    id = Column(Integer, primary_key=True)
    payer_document_number = Column(String(14), nullable=False)
    destination_account_id = Column(Integer, ForeignKey(Account.id), nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    approved_count = Column(Integer, nullable=False)
    approved_amount = Column(BigInteger, nullable=False)
    scam_step_up_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("payer_document_number", "destination_account_id"),)
