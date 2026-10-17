from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship
from models.base import Base


class PolicyVersion(Base):
    __tablename__ = "policy_version"

    id = Column(Integer, primary_key=True)
    version = Column(String(20), nullable=False)
    ml_mode = Column(String(10), nullable=False)
    is_active = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("version"),)

    rule_parameters = relationship("RuleParameter", back_populates="policy_version", lazy="selectin")
