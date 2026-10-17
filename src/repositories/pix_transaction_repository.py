from typing import List, Optional

from sqlalchemy import func, select

from database import Context
from models import PixTransaction


class PixTransactionRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, pix_data: dict) -> PixTransaction:
        pix_transaction = PixTransaction(**pix_data)

        self.session.add(pix_transaction)
        self.session.flush()

        return pix_transaction

    def get_by_external_id(self, external_id: str) -> Optional[PixTransaction]:
        return self.session.query(PixTransaction).filter(PixTransaction.external_id == external_id).first()

    def lock(self, lock_keys: List[str]) -> None:
        """Toma uma trava de transação para cada chave, NA ORDEM recebida.

        `pg_advisory_xact_lock` segura até o commit ou o rollback — não
        existe "soltar" na mão, e por isso não existe esquecer de soltar.
        Duas requisições que pedem a mesma chave ficam em fila; as que
        pedem chaves diferentes seguem em paralelo.

        Quem decide QUAIS chaves e em QUE ordem é o controller: a ordem é
        o que evita o impasse, e isso é regra, não consulta. Aqui só se
        executa. O `hashtextextended` vira o texto da chave no número de
        64 bits que a trava exige, do lado do banco.
        """
        for lock_key in lock_keys:
            self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))
