from sqlalchemy import Column, DateTime, Integer, String, func
from models.base import Base


class FraudMarker(Base):
    """Marcação de fraude que simula o DICT (Res. BCB 587/2026). Só leitura: nasce por seed."""

    __tablename__ = "fraud_marker"

    id = Column(Integer, primary_key=True)
    document_number = Column(String(14), nullable=False)
    marker_type = Column(String(30), nullable=False)
    origin = Column(String(20), nullable=False)
    marked_at = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    OWN = "own"
    THIRD_PARTY = "third_party"
