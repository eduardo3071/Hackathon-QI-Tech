import random


class RandomGenerator:
    @staticmethod
    def generate_cpf():
        cpf = [random.randrange(10) for _ in range(9)]
        for _ in range(2):
            value = sum([(len(cpf) + 1 - i) * v for i, v in enumerate(cpf)]) % 11
            cpf.append(11 - value if value > 1 else 0)
        cpf_number = "".join(str(x) for x in cpf)
        cpf_number = f"{cpf_number[0:3]}.{cpf_number[3:6]}.{cpf_number[6:9]}-{cpf_number[9:11]}"
        return cpf_number

    @staticmethod
    def generate_cnpj():
        cnpj = [random.randrange(10) for _ in range(8)] + [0, 0, 0, 1]

        for _ in range(2):
            value = sum(v * (i % 8 + 2) for i, v in enumerate(reversed(cnpj)))
            digit = 11 - value % 11
            cnpj.append(digit if digit < 10 else 0)

        cnpj_number = "".join(str(x) for x in cnpj)

        cnpj_number = (
            f"{cnpj_number[0:2]}.{cnpj_number[2:5]}.{cnpj_number[5:8]}/{cnpj_number[8:12]}-{cnpj_number[12:14]}"
        )

        return cnpj_number

    @staticmethod
    def generate_account_number():
        return str(random.randrange(10_000_000, 99_999_999))

    @staticmethod
    def account_number_for(document_number: str) -> str:
        """A conta de origem de um pagador, sempre a mesma para o mesmo documento.

        O contrato não traz ISPB na origem, então quem identifica a conta
        é agência + número. Derivar o número do documento faz o mesmo
        pagador sair sempre da mesma conta, como na vida real.
        """
        return "".join(character for character in document_number if character.isdigit())
