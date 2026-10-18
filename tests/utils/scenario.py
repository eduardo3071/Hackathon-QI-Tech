from typing import List, Optional

from tests.utils.payload_generator import PayloadGenerator, shift_date
from tests.utils.request_generator import RequestGenerator
from tests.utils.random_generator import RandomGenerator


class Scenario:
    """Monta histórico pela API, como um cliente qualquer faria.

    Os testes não escrevem no banco: se uma regra precisa de "pagador com
    aparelho conhecido" ou "cinco Pix aprovados", esse passado nasce aqui,
    com POSTs, e passa pelas mesmas regras que o Pix do teste.
    """

    @staticmethod
    def send(expected_status: int = 201, **payload_overrides) -> dict:
        payload = PayloadGenerator.create_pix_payload(**payload_overrides)

        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == expected_status, f"esperava {expected_status}, veio {status}: {response}"

        return response

    @staticmethod
    def register_device(payer_document: str, device_id: str, transaction_date: str) -> None:
        """Dois Pix pequenos e aprovados, 24 h antes e em `transaction_date`.

        Daqui em diante o aparelho é CONFIÁVEL para este pagador: 2 Pix
        aprovados, o primeiro há pelo menos 24 h.
        """
        for date in (shift_date(transaction_date, days=-1), transaction_date):
            response = Scenario.send(
                payer_document=payer_document,
                device_id=device_id,
                transaction_date=date,
                amount=10000,
            )
            assert response["status"] == "approved", response

    @staticmethod
    def build_history(
        payer_document: str,
        device_id: str,
        amounts: List[int],
        first_date: str,
        payee_document: Optional[str] = None,
        payee_account_number: Optional[str] = None,
    ) -> None:
        """Um Pix aprovado por dia, para o mesmo destino: a rotina do pagador."""
        if payee_document is None:
            payee_document = RandomGenerator.generate_cpf()

        if payee_account_number is None:
            payee_account_number = RandomGenerator.generate_account_number()

        for day, amount in enumerate(amounts):
            response = Scenario.send(
                payer_document=payer_document,
                device_id=device_id,
                payee_document=payee_document,
                payee_account_number=payee_account_number,
                transaction_date=shift_date(first_date, days=day),
                amount=amount,
            )
            assert response["status"] == "approved", response


def reason_for(response: dict, signal: str) -> Optional[dict]:
    """O motivo de um sinal no `metadata`, ou None se ele não disparou."""
    for reason in response["metadata"]["reasons"]:
        if reason["signal"] == signal:
            return reason

    return None


def not_needed_signals(response: dict) -> List[str]:
    return [item["signal"] for item in response["metadata"]["not_needed"]]


# O que o GET (o dossiê) acrescenta ao que o POST respondeu: a história
# da decisão, não a decisão.
DOSSIER_ONLY_FIELDS = ("initial_status", "two_factor", "status_history")


def decision_of(response: dict) -> dict:
    """A resposta sem o que só o dossiê traz: o que o POST respondeu."""
    metadata = {field: value for field, value in response["metadata"].items() if field not in DOSSIER_ONLY_FIELDS}

    return {"key": response["key"], "status": response["status"], "metadata": metadata}
