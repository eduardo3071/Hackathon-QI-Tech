from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator, Scenario, reason_for, shift_date

# Os cenários que a bateria de realidade (scripts/realidade/) mostrou que o
# motor errava: golpes encenados passo a passo e o cliente legítimo que o
# motor travava sem motivo. Cada teste é um desses casos.

DAY = "2026-10-17T14:00:00-03:00"
HISTORY_START = "2026-09-20T14:00:00-03:00"


def new_device() -> str:
    return f"dvc-{uuid4().hex[:12]}"


def new_payee(opening_date: str = None) -> dict:
    payee = {
        "payee_document": RandomGenerator.generate_cpf(),
        "payee_account_number": RandomGenerator.generate_account_number(),
    }
    if opening_date is not None:
        payee["payee_opening_date"] = opening_date

    return payee


def client_with_history(amounts=None) -> dict:
    """Cliente com Pix aprovados, um por dia, do mesmo aparelho, para o mesmo destino (R$ 100 por padrão)."""
    if amounts is None:
        amounts = [10000] * 5

    client = {"payer_document": RandomGenerator.generate_cpf(), "device_id": new_device()}
    usual_payee = new_payee()
    Scenario.build_history(**client, **usual_payee, amounts=amounts, first_date=HISTORY_START)

    return {**client, "usual_payee": usual_payee}


def send(pix_id: str = None, **payload_overrides) -> dict:
    """Manda o Pix e devolve a resposta junto com o `id`, para o PATCH saber a quem responder."""
    if pix_id is None:
        pix_id = f"pix-{uuid4()}"

    return {"id": pix_id, **Scenario.send(pix_id=pix_id, **payload_overrides)}


def confirm(pix: dict, minutes: int = 2) -> dict:
    """O cliente passa no 2FA: o PATCH de retorno, `minutes` depois do Pix."""
    status, response = RequestGenerator.PATCH_pix_transaction(
        pix["id"],
        {
            "two_factor_result": "passed",
            "completed_at": shift_date(pix["transaction_date"], minutes=minutes),
        },
    )
    assert status == 200, response

    return response


def send_and_confirm_if_asked(**payload) -> dict:
    """O Pix e, se pediu 2FA, a confirmação do cliente."""
    pix = send(**payload)
    pix["transaction_date"] = payload["transaction_date"]
    if pix["status"] == "two_factor_required":
        confirm(pix)

    return pix


class TestConfirmedScamDoesNotTeachTheProfile:
    def test_third_fake_call_center_pix_still_asks_two_factor(self):
        """Item 1 — a vítima da falsa central confirma R$ 4.800 e R$ 4.500; o 3º Pix, de R$ 3.900, não pode passar.

        Antes, os dois Pix confirmados entravam no perfil e levavam o P95 e a
        mediana para cima: o terceiro saía `approved` sem sinal nenhum. O golpe
        "educava" o perfil. Agora o Pix confirmado sob aviso de golpe conta só
        para a soma noturna e os tetos diários.
        """
        client = client_with_history()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}
        fraudster = new_payee(opening_date="2026-10-02T10:00:00-03:00")

        for day, amount in enumerate([480000, 450000]):
            pix = send(**origin, **fraudster, amount=amount, transaction_date=shift_date(DAY, days=day))
            assert pix["status"] == "two_factor_required", pix["metadata"]
            assert pix["metadata"]["scam_warning"] is True
            pix["transaction_date"] = shift_date(DAY, days=day)
            confirm(pix)

        third = send(**origin, **fraudster, amount=390000, transaction_date=shift_date(DAY, days=2))

        assert third["status"] == "two_factor_required", third["metadata"]
        assert third["metadata"]["scam_warning"] is True
        assert reason_for(third, "PERFIL.valor") is not None
