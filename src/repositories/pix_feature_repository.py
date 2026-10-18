from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, literal, or_, select

from database import Context
from models import Account, Analysis, AnalysisStatus, FraudMarker, PayerPayeePair, PixTransaction


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

    def attempts(self, payer_document: str, start: datetime, end: datetime) -> List[Tuple[str, int, str]]:
        """As tentativas do pagador na janela, com qualquer status: (recebedor, valor, status atual), uma por Pix.

        Quem decide que o reenvio de uma tentativa não aprovada é a mesma
        tentativa é o controller; aqui só se lista.
        """
        rows = (
            self.session.query(PixTransaction.payee_document_number, PixTransaction.amount, AnalysisStatus.enumerator)
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
            )
            .all()
        )
        return [(row.payee_document_number, row.amount, row.enumerator) for row in rows]

    def new_payee_attempt_groups(self, payer_document: str, start: datetime, end: datetime) -> List[Tuple[int, int]]:
        """As tentativas do pagador na janela para destinos que ele viu pela PRIMEIRA vez dentro dela.

        Cada (conta destino, valor) distinto volta uma vez só. O par
        pagador-recebedor guarda quando o destino apareceu pela primeira
        vez: um destino "novo na janela" é o que tem `first_seen_at` dentro
        dela, mesmo que o Pix já tenha sido aprovado (e o par já exista).
        """
        rows = (
            self.session.query(PixTransaction.destination_account_id, PixTransaction.amount)
            .join(
                PayerPayeePair,
                and_(
                    PayerPayeePair.payer_document_number == PixTransaction.payer_document_number,
                    PayerPayeePair.destination_account_id == PixTransaction.destination_account_id,
                ),
            )
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
                PayerPayeePair.first_seen_at >= start,
            )
            .distinct()
            .all()
        )
        return [(row.destination_account_id, row.amount) for row in rows]

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

    def sum_received(self, payee_document: str, start: datetime, end: datetime) -> int:
        """Quanto este recebedor recebeu de OUTROS documentos na janela, com qualquer status (tentativas incluídas)."""
        amount = (
            self.session.query(func.coalesce(func.sum(PixTransaction.amount), 0))
            .filter(
                PixTransaction.payee_document_number == payee_document,
                PixTransaction.payer_document_number != payee_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
            )
            .scalar()
        )
        return int(amount)

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

    def confirmed_payments(
        self, payer_document: str, destination_account_id: int, end: datetime, status_enumerator: str
    ) -> List[Tuple[int, datetime]]:
        """Os Pix deste pagador para esta conta, com o status pedido, até `end`: (valor, data).

        "Confirmado" é o status final: o Pix aprovado direto ou o que
        pediu 2FA e passou. Quem decide se o padrão é o da conta do mês é
        o FeatureBuilder; aqui só se lista.
        """
        rows = (
            self.session.query(PixTransaction.amount, PixTransaction.transaction_date)
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.destination_account_id == destination_account_id,
                PixTransaction.transaction_date <= end,
                AnalysisStatus.enumerator == status_enumerator,
            )
            .all()
        )
        return [(row.amount, row.transaction_date) for row in rows]

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

    def payer_used_channel(self, payer_document: str, channel: str, status_enumerator: str) -> bool:
        """Se o pagador já tem Pix com o status pedido saído deste canal."""
        return self.session.query(
            self.session.query(PixTransaction.id)
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.channel == channel,
                AnalysisStatus.enumerator == status_enumerator,
            )
            .exists()
        ).scalar()

    def distinct_payers_on_ip(self, ip: str, start: datetime, end: datetime) -> List[str]:
        """Os documentos distintos que pagaram deste IP na janela, com qualquer status."""
        rows = (
            self.session.query(PixTransaction.payer_document_number)
            .filter(
                PixTransaction.ip == ip,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
            )
            .distinct()
            .all()
        )
        return [row.payer_document_number for row in rows]

    def last_credit_before(self, destination_account_id: int, before: datetime, status_enumerator: str) -> Optional[datetime]:
        """A data do último Pix, com o status pedido, que esta conta recebeu ANTES de `before`."""
        return (
            self.session.query(func.max(PixTransaction.transaction_date))
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .filter(
                PixTransaction.destination_account_id == destination_account_id,
                PixTransaction.transaction_date < before,
                AnalysisStatus.enumerator == status_enumerator,
            )
            .scalar()
        )

    def nearest_marked_sender_hop(
        self,
        payee_document: str,
        start: datetime,
        end: datetime,
        status_enumerator: str,
        max_hops: int,
        third_party_marked_since: datetime,
    ) -> Optional[int]:
        """A quantos saltos deste recebedor está o documento marcado mais próximo, ou None.

        Consulta recursiva sobre os Pix com o status pedido na janela:
        salto 1 são os documentos que pagaram o recebedor; salto 2, os que
        pagaram esses — e assim até `max_hops`. Um documento conta como
        marcado se tem marcação vigente em `end`: a própria sempre, a de
        outro PSP só se feita depois de `third_party_marked_since` (a
        janela do DICT, que o controller calcula).
        """
        edges = (
            select(
                PixTransaction.payer_document_number.label("payer"),
                PixTransaction.payee_document_number.label("payee"),
            )
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .where(
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date <= end,
                PixTransaction.payer_document_number != PixTransaction.payee_document_number,
                AnalysisStatus.enumerator == status_enumerator,
            )
            .cte("edges")
        )

        senders = (
            select(edges.c.payer.label("document"), literal(1).label("hop"))
            .where(edges.c.payee == payee_document)
            .cte("senders", recursive=True)
        )
        senders = senders.union(
            select(edges.c.payer, senders.c.hop + 1)
            .join(senders, edges.c.payee == senders.c.document)
            .where(senders.c.hop < max_hops)
        )

        return self.session.execute(
            select(func.min(senders.c.hop))
            .join(FraudMarker, FraudMarker.document_number == senders.c.document)
            .where(
                FraudMarker.marked_at <= end,
                FraudMarker.valid_until > end,
                or_(FraudMarker.origin == FraudMarker.OWN, FraudMarker.marked_at >= third_party_marked_since),
            )
        ).scalar()

    def count_institutions_with_accounts_opened(self, owner_document: str, start: datetime, end: datetime) -> int:
        """Em quantas instituições (ISPBs distintos) este documento tem conta aberta na janela.

        Só as contas que o motor já viu como destino: a origem chega sem
        ISPB, e a conta que nunca recebeu Pix na nossa base não existe aqui.
        """
        return (
            self.session.query(func.count(func.distinct(Account.ispb)))
            .filter(
                Account.owner_document_number == owner_document,
                Account.ispb.isnot(None),
                Account.opening_date >= start,
                Account.opening_date <= end,
            )
            .scalar()
        )

    def count_distinct_payees(self, payer_document: str, start: datetime, end: datetime) -> int:
        """Para quantos recebedores distintos o pagador mandou Pix na janela `[início, fim)`, com qualquer status."""
        return (
            self.session.query(func.count(func.distinct(PixTransaction.payee_document_number)))
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date < end,
            )
            .scalar()
        )

    def approved_amounts_to_destination(
        self, payer_document: str, destination_account_id: int, start: datetime, end: datetime, status_enumerator: str
    ) -> List[int]:
        """Os valores dos Pix do pagador para esta conta na janela `[início, fim)`, com o status pedido, em ordem de data."""
        rows = (
            self.session.query(PixTransaction.amount)
            .join(Analysis, Analysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == Analysis.status_id)
            .filter(
                PixTransaction.payer_document_number == payer_document,
                PixTransaction.destination_account_id == destination_account_id,
                PixTransaction.transaction_date >= start,
                PixTransaction.transaction_date < end,
                AnalysisStatus.enumerator == status_enumerator,
            )
            .order_by(PixTransaction.transaction_date, PixTransaction.id)
            .all()
        )
        return [row.amount for row in rows]
