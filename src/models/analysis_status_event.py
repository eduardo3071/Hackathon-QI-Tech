from sqlalchemy import Column, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import relationship
from models.base import Base
from models import Analysis, AnalysisStatus

# O resultado do 2FA é o status para onde a análise vai.
TWO_FACTOR_PASSED = "passed"
TWO_FACTOR_FAILED = "failed"
TWO_FACTOR_RESULT_STATUS = {
    TWO_FACTOR_PASSED: AnalysisStatus.APPROVED,
    TWO_FACTOR_FAILED: AnalysisStatus.REJECTED,
}


class AnalysisStatusEvent(Base):
    """Um passo da trilha de status da análise: de onde veio, para onde foi e quando.

    O primeiro evento de toda análise tem `from_status` nulo: é o
    nascimento. O segundo, se existir, é o retorno do 2FA.
    """

    __tablename__ = "analysis_status_event"

    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey(Analysis.id), nullable=False)
    from_status_id = Column(Integer, ForeignKey(AnalysisStatus.id), nullable=True)
    to_status_id = Column(Integer, ForeignKey(AnalysisStatus.id), nullable=False)
    event_datetime = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis = relationship("Analysis", foreign_keys=[analysis_id], back_populates="status_events")
    from_status = relationship("AnalysisStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("AnalysisStatus", foreign_keys=[to_status_id], lazy="selectin")

    @property
    def is_birth(self) -> bool:
        return self.from_status_id is None and self.from_status is None
