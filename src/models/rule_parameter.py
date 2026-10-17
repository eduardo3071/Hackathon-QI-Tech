from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from models.base import Base
from models import PolicyVersion


class RuleParameter(Base):
    __tablename__ = "rule_parameter"

    id = Column(Integer, primary_key=True)
    policy_version_id = Column(Integer, ForeignKey(PolicyVersion.id), nullable=False)
    signal_code = Column(String(60), nullable=False)
    enabled = Column(Boolean, nullable=False)
    parameters = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("policy_version_id", "signal_code"),)

    policy_version = relationship("PolicyVersion", foreign_keys=[policy_version_id], back_populates="rule_parameters")
