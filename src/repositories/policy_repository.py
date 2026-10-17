from typing import Optional

from database import Context
from models import PolicyVersion


class PolicyRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_active(self) -> Optional[PolicyVersion]:
        """A política em vigor. O índice único parcial garante que há no máximo uma."""
        return self.session.query(PolicyVersion).filter(PolicyVersion.is_active.is_(True)).first()
