CPF_LENGTH = 11
CNPJ_LENGTH = 14

CHECK_DIGIT_POSITIONS = [9, 10]

# Os pesos do CNPJ, um para cada dígito anterior ao verificador. Ao
# contrário do CPF, eles não decrescem em linha reta: descem de 5 a 2 e
# recomeçam em 9 — por isso estão escritos, e não calculados.
CNPJ_FIRST_CHECK_WEIGHTS = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
CNPJ_SECOND_CHECK_WEIGHTS = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def only_digits(document_number: str) -> str:
    """O documento sem máscara: "123.456.789-09" vira "12345678909".

    O motor guarda e compara documentos SÓ com dígitos. Com e sem máscara
    são o mesmo CPF; se o banco guardasse os dois jeitos, o mesmo
    pagador viraria duas pessoas no histórico, e toda regra de janela
    contaria errado.
    """
    digits = []
    for character in document_number:
        if character.isdigit():
            digits.append(character)

    return "".join(digits)


def is_valid_document(document_number: str) -> bool:
    """CPF (11 dígitos) ou CNPJ (14), conferindo os dígitos verificadores."""
    digits = only_digits(document_number)

    if len(digits) == CPF_LENGTH:
        return is_valid_cpf(digits)

    if len(digits) == CNPJ_LENGTH:
        return is_valid_cnpj(digits)

    return False


def is_valid_cpf(document_number: str) -> bool:
    """Diz se um CPF existe de verdade — não se ele tem a cara certa.

    O schema em src/schemas/post_pix_transaction.json já cobrou o formato:
    com ou sem máscara, onze dígitos. Isto aqui é outra pergunta, e a
    diferença entre as duas é a lição deste arquivo.

    Os dois últimos dígitos de um CPF não são escolhidos: eles são o
    RESULTADO de uma conta feita sobre os nove primeiros. Por isso um
    número pode ter o formato perfeito e não existir — "111.222.333-44"
    passa no schema e não passa aqui.

    É o mesmo motivo pelo qual a resposta dessa recusa é 422 e não 400:
    não é que a API não conseguiu ler o pedido; ela leu, entendeu, e o
    valor não pode existir.

    A conta, para cada um dos dois dígitos: multiplica cada dígito
    anterior por um peso que decresce, soma tudo, tira o resto da divisão
    por 11. Resto menor que 2 vira dígito 0; nos outros casos, o dígito é
    11 menos o resto.
    """
    digits = []
    for character in document_number:
        if character.isdigit():
            digits.append(int(character))

    if len(digits) != CPF_LENGTH:
        return False

    # Um CPF de dígitos todos iguais ("111.111.111-11") passa na conta
    # dos dígitos verificadores e mesmo assim não vale. São onze números
    # conhecidos, e a Receita não emite nenhum deles.
    all_digits_are_equal = True
    for digit in digits:
        if digit != digits[0]:
            all_digits_are_equal = False
            break

    if all_digits_are_equal:
        return False

    for position in CHECK_DIGIT_POSITIONS:
        total = 0
        first_weight = position + 1

        for index in range(position):
            total = total + digits[index] * (first_weight - index)

        remainder = total % 11

        if remainder < 2:
            expected_digit = 0
        else:
            expected_digit = 11 - remainder

        if digits[position] != expected_digit:
            return False

    return True


def is_valid_cnpj(document_number: str) -> bool:
    """O mesmo raciocínio do CPF, com outros pesos e outro tamanho.

    A regra de cada dígito verificador: multiplica cada dígito anterior
    pelo seu peso, soma, tira o resto da divisão por 11. Resto menor que
    2 vira 0; nos outros casos, o dígito é 11 menos o resto — a mesma
    conta do CPF, só que sobre os doze (e depois treze) primeiros.
    """
    digits = []
    for character in document_number:
        if character.isdigit():
            digits.append(int(character))

    if len(digits) != CNPJ_LENGTH:
        return False

    # Mesma armadilha do CPF: "00.000.000/0000-00" fecha a conta e não existe.
    if len(set(digits)) == 1:
        return False

    for weights in [CNPJ_FIRST_CHECK_WEIGHTS, CNPJ_SECOND_CHECK_WEIGHTS]:
        position = len(weights)
        total = 0

        for index, weight in enumerate(weights):
            total = total + digits[index] * weight

        remainder = total % 11

        if remainder < 2:
            expected_digit = 0
        else:
            expected_digit = 11 - remainder

        if digits[position] != expected_digit:
            return False

    return True
