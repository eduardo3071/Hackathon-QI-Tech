from sqlalchemy import Column, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from models.base import Base
from models import Analysis


class AnalysisRuleResult(Base):
    """Um sinal avaliado numa análise: o que se viu, contra qual limite, e o que deu."""

    __tablename__ = "analysis_rule_result"

    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey(Analysis.id), nullable=False)
    rule_code = Column(String(40), nullable=False)
    signal_code = Column(String(60), nullable=False)
    layer = Column(SmallInteger, nullable=False)
    outcome = Column(String(20), nullable=False)
    typology = Column(String(10), nullable=True)
    points = Column(Integer, nullable=False)
    observed = Column(JSONB, nullable=False)
    threshold = Column(JSONB, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis = relationship("Analysis", foreign_keys=[analysis_id], back_populates="rule_results")
