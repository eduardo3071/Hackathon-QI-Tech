from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator, Scenario, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"


def send_in_parallel(payloads: list) -> list:
    """Dispara todos os POSTs ao mesmo tempo e devolve as respostas."""
    with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
        results = list(executor.map(RequestGenerator.POST_pix_transaction, payloads))

    for status, response in results:
        assert status == 201, response

    return [response for _status, response in results]


class TestConcurrency:
    """Pix simultâneos que disputam a mesma contagem decidem como se viessem em fila.

    Sem a trava, dez Pix chegando juntos leriam todos "zero tentativas
    antes de mim" — e quem dispara dez Pix ao mesmo tempo é justamente o
    caso suspeito. Os Pix têm o MESMO `transaction_date`: assim a ordem
    em que o servidor os atende não muda o resultado, e o teste compara o
    conjunto de decisões, que tem de ser o mesmo da avaliação em fila.
    """

    def test_ten_parallel_pix_from_the_same_payer(self):
        """Em fila, R$ 150 x 10: seis aprovados, três 2FA (a partir de R$ 1.050 somados) e uma recusa."""
        payer = RandomGenerator.generate_cpf()
        device = f"dvc-{uuid4().hex[:12]}"
        # Aparelho já conhecido, de propósito: aparelho NOVO serializa os
        # Pix por outro caminho (o INSERT do aparelho espera o primeiro
        # commit), e o teste passaria mesmo sem a trava.
        Scenario.register_device(payer, device, shift_date(DAY, hours=-1))

        payloads = [
            PayloadGenerator.create_pix_payload(
                payer_document=payer, device_id=device, amount=15000, transaction_date=DAY
            )
            for _index in range(10)
        ]

        responses = send_in_parallel(payloads)

        decisions = Counter(response["status"] for response in responses)
        assert decisions == Counter({"approved": 6, "two_factor_required": 3, "rejected": 1})

        attempts_seen = sorted(
            reason_for(response, "RITMO.velocidade")["observed"]["attempts"]
            for response in responses
            if reason_for(response, "RITMO.velocidade") is not None
        )
        assert attempts_seen == [7, 8, 9, 10]

    def test_six_parallel_payers_to_the_same_person_account(self):
        """Em fila, o 5º e o 6º pagadores disparam o fan-in. Em paralelo, também — nem mais, nem menos."""
        payee = {
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }
        payloads = [
            # R$ 250 cada: o fan-in só vale a partir de R$ 1.000 na janela.
            PayloadGenerator.create_pix_payload(**payee, amount=25000, transaction_date=DAY) for _index in range(6)
        ]

        responses = send_in_parallel(payloads)

        fan_in_counts = sorted(
            reason_for(response, "CONTA_RECEBEDORA.fan_in")["observed"]["distinct_payers"]
            for response in responses
            if reason_for(response, "CONTA_RECEBEDORA.fan_in") is not None
        )
        assert fan_in_counts == [5, 6]
