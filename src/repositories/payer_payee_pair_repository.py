from datetime import date, datetime
from typing import Optional

from database import Context
from models import PayerPayeePair


class PayerPayeePairRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get(self, payer_document: str, destination_account_id: int) -> Optional[PayerPayeePair]:
        return (
            self.session.query(PayerPayeePair)
            .filter(
                PayerPayeePair.payer_document_number == payer_document,
                PayerPayeePair.destination_account_id == destination_account_id,
            )
            .first()
        )

    def register_attempt(self, payer_document: str, destination_account_id: int, seen_at: datetime) -> PayerPayeePair:
        """Cria o par na primeira vez e alarga a janela de primeira/última vez vista."""
        pair = self.get(payer_document, destination_account_id)

        if pair is None:
            pair = PayerPayeePair(
                payer_document_number=payer_document,
                destination_account_id=destination_account_id,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                approved_count=0,
                approved_amount=0,
                approved_days=0,
                max_approved_amount=0,
                scam_step_up_count=0,
            )
            self.session.add(pair)

        pair.first_seen_at = min(pair.first_seen_at, seen_at)
        pair.last_seen_at = max(pair.last_seen_at, seen_at)

        return pair

    def add_approved(self, pair: PayerPayeePair, amount: int, approved_day: date) -> None:
        """Soma um Pix aprovado ao par; `approved_day` é o dia de Brasília, para contar dias diferentes."""
        pair.approved_count = pair.approved_count + 1
        pair.approved_amount = pair.approved_amount + amount
        pair.max_approved_amount = max(pair.max_approved_amount, amount)

        if pair.last_approved_day != approved_day:
            pair.approved_days = pair.approved_days + 1
            pair.last_approved_day = approved_day

    def add_scam_step_up(self, pair: PayerPayeePair) -> None:
        pair.scam_step_up_count = pair.scam_step_up_count + 1
