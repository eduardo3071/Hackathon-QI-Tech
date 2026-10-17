from datetime import datetime
from typing import List, Tuple

from sqlalchemy import func

from database import Context
from models import Account, Analysis, AnalysisStatus, DeviceOwner, PixTransaction


class PixFeatureRepository:
    """As consultas em janela de tempo que alimentam as regras.

    Cada método conta ou soma sobre um dos índices de `pix_transaction`
    (pagador + data, recebedor + data, conta destino + data) e devolve um
    número. Nenhum decide nada: o tamanho da janela, o status que conta
    e o tipo de recebedor chegam por parâmetro, escolhidos pelo
    controller. As janelas são fechadas nas duas pontas, `[início, fim]`.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def count_attempts(self, payer_document: str, start: datetime, end: datetime) -> Tuple[int, int]:
        """Quantas tentativas o pagador fez na janela, e quanto elas somam — com qualquer status."""
        attempts, amount = (
            self.session.query(func.count(PixTransaction.id), func.coalesce(func.sum(PixTransaction.amount), 0))
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
            )
            .one()
        )
        return attempts, int(amount)

    def sum_approved_between_people(
        self,
        payer_document: str,
        start: datetime,
        end: datetime,
        payee_owner_type: str,
        status_enumerator: str,
    ) -> int:
        """Soma dos Pix do pagador, com o status pedido, para terceiros do tipo pedido."""
        amount = (
            self.session.query(func.coalesce(func.sum(PixTransaction.amount), 0))
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .join(Account, Account.id == PixTransaction.destination_account_id)
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.payee_document_number != payer_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
                Account.owner_type == payee_owner_type,
                AnalysisStatus.enumerator == status_enumerator,
            )
            .scalar()
        )
        return int(amount)

    def sum_first_approved_per_device(self, payer_document: str, start: datetime, end: datetime) -> int:
        """Soma do PRIMEIRO Pix aprovado de cada aparelho do pagador, na janela.

        O primeiro Pix aprovado de um aparelho é o que saiu enquanto ele
        ainda não era cadastrado (veja o comentário de `device_owner` no
        database.sql).
        """
        amount = (
            self.session.query(func.coalesce(func.sum(PixTransaction.amount), 0))
            .join(DeviceOwner, DeviceOwner.first_approved_pix_id == PixTransaction.id)
            .filter(
                DeviceOwner.document_number == payer_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
            )
            .scalar()
        )
        return int(amount)

    def distinct_payers(self, payee_document: str, start: datetime, end: datetime) -> List[str]:
        """Os documentos distintos que mandaram Pix para este recebedor, sem contar ele mesmo."""
        rows = (
            self.session.query(PixTransaction.payer_document_number)
            .filter(
                PixTransaction.payee_document_number == payee_document,
                PixTransaction.payer_document_number != payee_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
            )
            .distinct()
            .all()
        )
        return [row.payer_document_number for row in rows]

    def count_credits(self, destination_account_id: int, status_enumerator: str) -> int:
        """Quantos Pix, com o status pedido, esta conta já recebeu."""
        return (
            self.session.query(func.count(PixTransaction.id))
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .filter(
                PixTransaction.destination_account_id == destination_account_id,
                AnalysisStatus.enumerator == status_enumerator,
            )
            .scalar()
        )
