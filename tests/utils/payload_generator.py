from datetime import datetime, timedelta
from uuid import uuid4

from tests.utils.random_generator import RandomGenerator


# Datas fixas, nunca o relógio da máquina: a regra de horário e as
# janelas de tempo dependem do `transaction_date`, e um teste que usa
# "agora" muda de resultado conforme a hora em que roda.
DEFAULT_TRANSACTION_DATE = "2026-10-17T14:00:00-03:00"
OLD_ACCOUNT_OPENING_DATE = "2020-01-15T10:00:00-03:00"


def shift_date(iso_date: str, **delta) -> str:
    """A mesma data ISO com fuso, deslocada (`minutes=5`, `days=-1`...)."""
    return (datetime.fromisoformat(iso_date) + timedelta(**delta)).isoformat()


class PayloadGenerator:
    @staticmethod
    def create_pix_payload(
        pix_id: str = None,
        amount: int = 15000,
        transaction_date: str = DEFAULT_TRANSACTION_DATE,
        payer_document: str = None,
        payee_document: str = None,
        payee_account_number: str = None,
        payee_opening_date: str = OLD_ACCOUNT_OPENING_DATE,
        payee_participant: str = "60701190",
        device_id: str = None,
        geolocation: dict = None,
        with_geolocation: bool = True,
    ) -> dict:
        """Um Pix válido no formato do slide, com qualquer campo trocado a pedido.

        Sem argumento nenhum, tudo que identifica alguém sai aleatório
        (id, CPFs, conta destino, aparelho): dois testes nunca dividem
        histórico por acaso. Quem testa histórico passa o mesmo
        documento ou aparelho de propósito.

        O padrão é um Pix "limpo": R$ 150, às 14h de Brasília, para uma
        conta PF antiga, de um aparelho que ainda não fez Pix — abaixo
        dos R$ 200 que o BCB permite para aparelho não cadastrado.
        """
        if pix_id is None:
            pix_id = f"pix-{uuid4()}"

        if payer_document is None:
            payer_document = RandomGenerator.generate_cpf()

        if payee_document is None:
            payee_document = RandomGenerator.generate_cpf()

        if payee_account_number is None:
            payee_account_number = RandomGenerator.generate_account_number()

        if device_id is None:
            device_id = f"dvc-{uuid4().hex[:12]}"

        if geolocation is None:
            geolocation = {"latitude": -23.56, "longitude": -46.65}

        source = {
            "device_id": device_id,
            "channel": "app",
            "ip": "198.51.100.23",
        }
        if with_geolocation:
            source["geolocation"] = geolocation

        payload = {
            "id": pix_id,
            "amount": amount,
            "transaction_date": transaction_date,
            "source_account": {
                "branch": "0001",
                "account_number": RandomGenerator.account_number_for(payer_document),
                "opening_date": "2025-03-02T10:00:00-03:00",
                "owner": {"document_number": payer_document},
            },
            "destination_account": {
                "participant": payee_participant,
                "branch": "3675",
                "account_number": payee_account_number,
                "opening_date": payee_opening_date,
                "owner": {"document_number": payee_document},
            },
            "source": source,
        }
        return payload
