from datetime import datetime
from typing import List

from database import Context
from models import FraudMarker


class FraudMarkerRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_valid(self, document_number: str, at: datetime) -> List[FraudMarker]:
        """As marcações deste documento que já existiam e ainda valiam no instante `at`."""
        return (
            self.session.query(FraudMarker)
            .filter(
                FraudMarker.document_number == document_number,
                FraudMarker.marked_at <= at,
                FraudMarker.valid_until > at,
            )
            .order_by(FraudMarker.marked_at.desc(), FraudMarker.id.desc())
            .all()
        )
