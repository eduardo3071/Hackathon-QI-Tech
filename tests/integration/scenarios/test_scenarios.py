import re
from uuid import uuid4

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator, Scenario, shift_date

# Os cenários de ponta a ponta do CLAUDE.md, cada um com o status que a
# API tem de devolver. Foram o critério de pronto das revisões de 17/10.

DAY = "2026-10-17T14:00:00-03:00"
HISTORY_START = "2026-09-20T14:00:00-03:00"


def client_with_history() -> dict:
    """Cliente com 5 Pix de R$ 100 aprovados, um por dia, do mesmo aparelho."""
    context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
    Scenario.build_history(
        payer_document=context["payer_document"],
        device_id=context["device_id"],
        amounts=[10000] * 5,
        first_date=HISTORY_START,
    )
    return context


class TestEndToEndScenarios:
    def test_slide_example(self):
        """R$ 1.500 às 22h15, destino aberto há 7 dias, pagador sem histórico no motor.

        Um sinal de conta laranja sozinho não é "risco claro": 2FA com aviso
        de golpe, não recusa.
        """
        response = Scenario.send(
            amount=150000,
            transaction_date="2026-10-17T22:15:00-03:00",
            payer_opening_date="2025-03-02T10:00:00-03:00",
            payee_opening_date="2026-10-10T09:00:00-03:00",
        )

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["scam_warning"] is True

    def test_unknown_client_small_pix(self):
        """Primeiro Pix de um cliente de conta antiga: R$ 300 de dia, para conta antiga."""
        response = Scenario.send(amount=30000, transaction_date=DAY)

        assert response["status"] == "approved"

    def test_unknown_client_above_starting_limit(self):
        response = Scenario.send(amount=150000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"

    def test_stolen_phone(self):
        """Aparelho novo faz um Pix de R$ 10 (aprovado) e, 3 minutos depois, R$ 5.000."""
        client = client_with_history()
        thief_device = f"dvc-{uuid4().hex[:12]}"

        warm_up = Scenario.send(
            payer_document=client["payer_document"], device_id=thief_device, amount=1000, transaction_date=DAY
        )
        assert warm_up["status"] == "approved"

        response = Scenario.send(
            payer_document=client["payer_document"],
            device_id=thief_device,
            amount=500000,
            transaction_date=shift_date(DAY, minutes=3),
        )

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_method"] == "face_liveness"

    def test_used_car(self):
        """R$ 35.000 de dia para um vendedor com conta de 20 dias (primeiro crédito): 2FA com aviso."""
        client = client_with_history()

        response = Scenario.send(
            **client, amount=3500000, payee_opening_date="2026-09-27T10:00:00-03:00", transaction_date=DAY
        )

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["scam_warning"] is True

    def test_mule_account(self):
        """Conta PF de 10 dias recebe R$ 300 de 5 pagadores em 1 h: o 5º é recusado."""
        payee = {
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
            "payee_opening_date": "2026-10-07T10:00:00-03:00",
        }

        responses = [
            Scenario.send(**payee, amount=30000, transaction_date=shift_date(DAY, minutes=10 * index))
            for index in range(5)
        ]

        assert responses[4]["status"] == "rejected"

    def test_replay_with_masked_cpf(self):
        payer_digits = re.sub(r"\D", "", RandomGenerator.generate_cpf())
        masked = f"{payer_digits[0:3]}.{payer_digits[3:6]}.{payer_digits[6:9]}-{payer_digits[9:11]}"

        payload = PayloadGenerator.create_pix_payload(payer_document=payer_digits)
        status, first = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        payload["source_account"]["owner"]["document_number"] = masked
        status, second = RequestGenerator.POST_pix_transaction(payload)

        assert status == 200
        assert second == first

    def test_resend_with_new_id_counts_once(self):
        """O mesmo Pix refeito 3 vezes com `id` novo em 5 min é UMA tentativa.

        Antes dele, 2 Pix para outros destinos. Se cada reenvio contasse, o
        último seria a 5ª tentativa da janela, somando R$ 1.500, e pediria
        2FA. Contando uma vez, são 3 tentativas.
        """
        client = client_with_history()

        for minute in range(2):
            Scenario.send(**client, amount=30000, transaction_date=shift_date(DAY, minutes=minute))

        payee = {
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }
        responses = [
            Scenario.send(**client, **payee, amount=30000, transaction_date=shift_date(DAY, minutes=2 + 2 * index))
            for index in range(3)
        ]

        assert [response["status"] for response in responses] == ["approved"] * 3
