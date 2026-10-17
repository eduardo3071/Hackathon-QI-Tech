from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import Account


class AccountRepository:
    """A conta nasce do próprio Pix: primeira vez que aparece, é criada."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_or_create(self, account_data: dict) -> Account:
        """Cria a conta se ela ainda não existe, e devolve a linha do banco.

        Por que `INSERT ... ON CONFLICT DO NOTHING` e não "busca; se não
        achou, cria": a conta recebedora PJ não entra na trava (um lojista
        grande ficaria em fila), então dois Pix para a mesma conta nova
        podem chegar juntos. Com busca-e-cria, os dois não acham, os dois
        criam, e o segundo morre na UNIQUE com 500. O ON CONFLICT espera o
        outro terminar e simplesmente não insere.

        Se a conta já existe, os dados dela NÃO são sobrescritos: a data
        de abertura e o titular são os da primeira vez que o motor a viu.
        """
        statement = insert(Account).values(**account_data).on_conflict_do_nothing()
        self.session.execute(statement)

        return (
            self.session.query(Account)
            .filter(
                Account.ispb.is_not_distinct_from(account_data["ispb"]),
                Account.branch == account_data["branch"],
                Account.account_number == account_data["account_number"],
            )
            .one()
        )
