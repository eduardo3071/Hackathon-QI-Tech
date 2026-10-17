from errors import QIException


class NotFoundPixTransaction(QIException):
    code = "QIT001001"

    def __init__(self, pix_id) -> None:
        title = "Pix transaction not Found"
        http_status = 404
        description = f"Pix transaction with id {pix_id} was not found."
        translation = f"O Pix com id {pix_id} não foi encontrado."
        super().__init__(title, self.code, http_status, description, translation)


class PixTransactionConflict(QIException):
    """O mesmo `id` chegou de novo, com outro conteúdo.

    409 Conflict: o `id` identifica UM Pix. Reenvio com o mesmo conteúdo
    é retentativa e devolve a análise gravada; com conteúdo diferente,
    alguém está reusando o identificador — e reavaliar seria deixar o
    segundo Pix sobrescrever a história do primeiro.
    """

    code = "QIT001002"

    def __init__(self, pix_id) -> None:
        title = "Pix transaction id already used"
        http_status = 409
        description = f"Pix transaction with id {pix_id} was already received with a different content."
        translation = f"O Pix com id {pix_id} já foi recebido com outro conteúdo."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidDocumentNumber(QIException):
    """O CPF ou CNPJ tem o formato certo e não existe.

    422, e não 400, de propósito: a API leu o pedido, e o valor é que não
    pode existir — os dígitos verificadores não batem com a conta. A
    diferença está explicada em src/utils/document_number.py.
    """

    code = "QIT001003"

    def __init__(self, document_number) -> None:
        title = "Invalid Document Number"
        http_status = 422
        description = f"The document number {document_number} is not a valid CPF or CNPJ."
        translation = "O CPF ou CNPJ informado não é válido."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidDate(QIException):
    """A data tem o formato certo e não existe no calendário.

    O `pattern` do schema conta dígitos, não dias: "2026-02-30" passa pelo
    regex e morre no `datetime.fromisoformat`. Sem esta classe, esse
    ValueError virava 500 — a API culpando a si mesma por um erro de quem
    chamou.
    """

    code = "QIT001004"

    def __init__(self, field_name, value) -> None:
        title = "Invalid Date"
        http_status = 422
        description = f"The field {field_name} has the date {value}, which does not exist."
        translation = f"A data informada em {field_name} não existe."
        super().__init__(title, self.code, http_status, description, translation)


class NoActivePolicy(QIException):
    """Não há política ativa no banco: o motor não tem com que decidir.

    É erro de configuração do serviço, não de quem chamou — por isso 500.
    O seed do database/database.sql cria a política ativa; se ela sumiu,
    o banco nasceu sem o seed.
    """

    code = "QIT001005"

    def __init__(self) -> None:
        title = "No active policy"
        http_status = 500
        description = "There is no active antifraud policy configured."
        translation = "Não existe política antifraude ativa configurada."
        super().__init__(title, self.code, http_status, description, translation)
