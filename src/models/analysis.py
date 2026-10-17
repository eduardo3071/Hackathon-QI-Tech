from sqlalchemy import Boolean, CHAR, Column, DateTime, ForeignKey, Integer, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship
from models.base import Base
from models import AnalysisStatus, PixTransaction, PolicyVersion


class Analysis(Base):
    """A decisão sobre um Pix.

    O que foi decidido nunca muda. O status muda uma única vez, pelo
    retorno do 2FA, e cada status deixa uma linha em
    `analysis_status_event` — a mesma trilha do sample_entity do Base
    Service. O status inicial mora no primeiro evento.
    """

    __tablename__ = "analysis"

    id = Column(Integer, primary_key=True)
    analysis_key = Column(CHAR(36), nullable=False)
    pix_transaction_id = Column(Integer, ForeignKey(PixTransaction.id), nullable=False)
    status_id = Column(Integer, ForeignKey(AnalysisStatus.id), nullable=False)
    policy_version_id = Column(Integer, ForeignKey(PolicyVersion.id), nullable=False)
    typology = Column(String(30), nullable=True)
    recommended_action = Column(String(20), nullable=False)
    step_up_reason = Column(String(20), nullable=True)
    step_up_method = Column(String(30), nullable=True)
    scam_warning = Column(Boolean, nullable=False)
    score_ato = Column(Integer, nullable=False)
    score_app = Column(Integer, nullable=False)
    score_mule = Column(Integer, nullable=False)
    path = Column(String(10), nullable=False)
    device_trusted = Column(Boolean, nullable=False)
    layers = Column(ARRAY(SmallInteger), nullable=False)
    features = Column(JSONB, nullable=False)
    latency_ms = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("analysis_key"),
        UniqueConstraint("pix_transaction_id"),
    )

    pix_transaction = relationship("PixTransaction", foreign_keys=[pix_transaction_id], back_populates="analysis")
    status = relationship("AnalysisStatus", foreign_keys=[status_id], lazy="selectin")
    policy_version = relationship("PolicyVersion", foreign_keys=[policy_version_id], lazy="selectin")
    rule_results = relationship(
        "AnalysisRuleResult",
        back_populates="analysis",
        order_by="asc(AnalysisRuleResult.id)",
        lazy="selectin",
    )
    status_events = relationship(
        "AnalysisStatusEvent",
        back_populates="analysis",
        order_by="asc(AnalysisStatusEvent.id)",
        lazy="selectin",
    )

    @property
    def birth_event(self):
        """O primeiro evento da trilha: o status com que a análise nasceu."""
        return self.status_events[0]

    @property
    def two_factor_event(self):
        """O evento do retorno do 2FA, ou None se o 2FA ainda não voltou (ou nem foi pedido)."""
        for status_event in self.status_events:
            if not status_event.is_birth:
                return status_event

        return None
