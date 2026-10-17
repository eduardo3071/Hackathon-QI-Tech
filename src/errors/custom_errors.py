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


class InvalidIpAddress(QIException):
    """O IP tem cara de IP e não é um IPv4 nem um IPv6 de verdade.

    422 pelo mesmo motivo do CPF: a API leu o pedido, e o valor é que não
    pode existir — "999.1.1.1" tem quatro números separados por ponto, e
    nenhum IPv4 passa de 255. Quem confere é o módulo `ipaddress` do
    Python, no controller; um `pattern` de JSON Schema para IPv6 é
    ilegível e erra nos casos de borda.
    """

    code = "QIT001006"

    def __init__(self, ip) -> None:
        title = "Invalid IP Address"
        http_status = 422
        description = f"The IP {ip} is not a valid IPv4 or IPv6 address."
        translation = "O IP informado não é um IPv4 nem um IPv6 válido."
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


class TwoFactorCompletedBeforePix(QIException):
    """O 2FA diz que terminou antes de o Pix existir.

    422 pelo mesmo motivo da data inexistente: o corpo tem o formato certo,
    e o valor é que não pode ser verdade. Aceitar seria gravar na trilha um
    evento anterior ao nascimento da análise.
    """

    code = "QIT001007"

    def __init__(self, pix_id) -> None:
        title = "Two factor completed before the Pix"
        http_status = 422
        description = f"The two factor of the Pix transaction with id {pix_id} cannot be completed before its transaction_date."
        translation = f"O 2FA do Pix com id {pix_id} não pode terminar antes da data do Pix."
        super().__init__(title, self.code, http_status, description, translation)


class TwoFactorResultConflict(QIException):
    """O retorno do 2FA já foi gravado, com o resultado oposto.

    409: o 2FA termina uma vez só. O mesmo resultado de novo é retentativa
    e devolve o dossiê; o resultado contrário reescreveria o desfecho de um
    Pix que já saiu (ou que já foi barrado).
    """

    code = "QIT001008"

    def __init__(self, pix_id, recorded_result) -> None:
        title = "Two factor result already recorded"
        http_status = 409
        description = f"The two factor of the Pix transaction with id {pix_id} was already recorded as {recorded_result}."
        translation = f"O retorno do 2FA do Pix com id {pix_id} já foi gravado como {recorded_result}."
        super().__init__(title, self.code, http_status, description, translation)


class PixNotAwaitingTwoFactor(QIException):
    """A análise não pediu 2FA: não há retorno de 2FA para aplicar.

    409: o Pix existe, e o estado dele é que não admite a troca. Um Pix
    aprovado ou recusado direto pelo motor não vira outra coisa por fora.
    """

    code = "QIT001009"

    def __init__(self, pix_id, status) -> None:
        title = "Pix transaction is not awaiting two factor"
        http_status = 409
        description = f"The analysis of the Pix transaction with id {pix_id} is {status}, not two_factor_required."
        translation = f"A análise do Pix com id {pix_id} está como {status}, e não como two_factor_required."
        super().__init__(title, self.code, http_status, description, translation)
