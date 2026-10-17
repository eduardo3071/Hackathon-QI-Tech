from datetime import datetime
from typing import List, Tuple

from sqlalchemy import func

from database import Context
from models import Account, Analysis, AnalysisStatus, PixTransaction


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

    def payer_has_pix(self, payer_document: str) -> bool:
        """Se o motor já gravou algum Pix deste pagador, com qualquer status."""
        return self.session.query(
            self.session.query(PixTransaction.id).filter(PixTransaction.payer_document_number == payer_document).exists()
        ).scalar()

    def attempt_groups(self, payer_document: str, start: datetime, end: datetime) -> List[Tuple[str, int]]:
        """As tentativas do pagador na janela, com qualquer status, agrupadas por (recebedor, valor).

        Cada par distinto volta uma vez só. Quem decide que o mesmo Pix
        refeito com `id` novo é UMA tentativa é o controller; aqui só se
        agrupa.
        """
        rows = (
            self.session.query(PixTransaction.payee_document_number, PixTransaction.amount)
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
            )
            .distinct()
            .all()
        )
        return [(row.payee_document_number, row.amount) for row in rows]

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

    def sum_by_device_trust(
        self, payer_document: str, start: datetime, end: datetime, device_trusted: bool, status_enumerator: str
    ) -> int:
        """Soma dos Pix do pagador, com o status pedido, que saíram de aparelho confiável (ou não).

        A confiança é a do momento de cada Pix, gravada em `analysis.device_trusted`.
        """
        amount = (
            self.session.query(func.coalesce(func.sum(PixTransaction.amount), 0))
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
                Analysis.device_trusted.is_(device_trusted),
                AnalysisStatus.enumerator == status_enumerator,
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

    def count_step_ups(
        self, payer_document: str, destination_account_id: int, start: datetime, end: datetime, step_up_reason: str
    ) -> int:
        """Quantos Pix deste pagador para esta conta pediram 2FA pelo motivo pedido, na janela.

        Conta o 2FA PEDIDO, qualquer que tenha sido o retorno (passou,
        falhou ou nem voltou): é a suspeita que o motor levantou na hora.
        """
        return (
            self.session.query(func.count(PixTransaction.id))
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.destination_account_id == destination_account_id,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
                Analysis.step_up_reason == step_up_reason,
            )
            .scalar()
        )

    def sum_third_party_credits(self, document: str, start: datetime, end: datetime, status_enumerator: str) -> int:
        """Quanto este documento recebeu de OUTROS documentos na janela, com o status pedido.

        O cruzamento é pelo documento, e não pela conta: a conta de origem
        chega sem ISPB, então "a conta que recebeu" e "a conta que agora
        paga" só se encontram pela pessoa.
        """
        amount = (
            self.session.query(func.coalesce(func.sum(PixTransaction.amount), 0))
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .filter(
                PixTransaction.payee_document_number == document,
                PixTransaction.payer_document_number != document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
                AnalysisStatus.enumerator == status_enumerator,
            )
            .scalar()
        )
        return int(amount)

    def distinct_payers_on_device(self, device_id: int, start: datetime, end: datetime) -> List[str]:
        """Os documentos distintos que pagaram deste aparelho na janela, com qualquer status."""
        rows = (
            self.session.query(PixTransaction.payer_document_number)
            .filter(
                PixTransaction.device_id == device_id,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
            )
            .distinct()
            .all()
        )
        return [row.payer_document_number for row in rows]
