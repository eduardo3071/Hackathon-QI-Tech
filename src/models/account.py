from sqlalchemy import CHAR, Column, DateTime, Integer, String, func
from models.base import Base


class Account(Base):
    """Conta de origem ou de destino, nascida do próprio Pix.

    A unicidade (ispb, agência, número) mora no `database.sql`, com
    NULLS NOT DISTINCT — a origem chega sem ISPB, e é essa cláusula que
    faz a mesma origem ser sempre a mesma linha.
    """

    __tablename__ = "account"

    id = Column(Integer, primary_key=True)
    ispb = Column(CHAR(8), nullable=True)
    branch = Column(String(10), nullable=False)
    account_number = Column(String(20), nullable=False)
    opening_date = Column(DateTime(timezone=True), nullable=False)
    owner_document_number = Column(String(14), nullable=False)
    owner_type = Column(CHAR(2), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    PERSON = "PF"
    COMPANY = "PJ"
