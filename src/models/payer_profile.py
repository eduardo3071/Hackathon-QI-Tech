from sqlalchemy import BigInteger, Column, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from models.base import Base


class PayerProfile(Base):
    """O perfil do pagador, feito só de Pix aprovados. Tabela agregada do caminho rápido."""

    __tablename__ = "payer_profile"

    id = Column(Integer, primary_key=True)
    payer_document_number = Column(String(14), nullable=False)
    recent_approved = Column(JSONB, nullable=False)
    approved_count = Column(Integer, nullable=False)
    max_night_approved_amount = Column(BigInteger, nullable=False)
    recent_locations = Column(JSONB, nullable=False)
    last_latitude = Column(Numeric(9, 6), nullable=True)
    last_longitude = Column(Numeric(9, 6), nullable=True)
    last_geolocation_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("payer_document_number"),)
