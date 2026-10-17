from uuid import uuid4

from tests.utils import RandomGenerator, Scenario, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"
SEVEN_DAYS_BEFORE = "2026-10-10T09:00:00-03:00"


def new_device() -> str:
    return f"dvc-{uuid4().hex[:12]}"


def payers_on_device(device_id: str, dates: list) -> None:
    """Um Pix pequeno de um CPF diferente, do mesmo aparelho, em cada data."""
    for date in dates:
        response = Scenario.send(
            payer_document=RandomGenerator.generate_cpf(), device_id=device_id, amount=5000, transaction_date=date
        )
        assert response["status"] != "rejected", response


class TestRuleQuemOperaAparelhoCompartilhado:
    """Regra 5 — QUEM_OPERA.aparelho_compartilhado: quantas pessoas operam deste aparelho?

    Três ou mais CPFs pagadores no mesmo aparelho em 30 dias é a fazenda de
    contas: um operador movimentando várias contas laranja do mesmo
    celular. Pontua `mule`; sozinho pede 2FA, com outro sinal de laranja
    recusa.
    """

    def test_third_payer_on_the_same_device_requires_two_factor(self):
        device = new_device()
        payers_on_device(device, [shift_date(DAY, days=-20), shift_date(DAY, days=-1)])

        response = Scenario.send(device_id=device, amount=15000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "possible_scam"
        reason = reason_for(response, "QUEM_OPERA.aparelho_compartilhado")
        assert reason["typology"] == "mule"
        assert reason["observed"]["distinct_payers"] == 3

    def test_second_payer_on_the_same_device_passes(self):
        """Dois CPFs no mesmo celular: o casal que divide o aparelho."""
        device = new_device()
        payers_on_device(device, [shift_date(DAY, days=-1)])

        response = Scenario.send(device_id=device, amount=15000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert reason_for(response, "QUEM_OPERA.aparelho_compartilhado") is None

    def test_payer_older_than_30_days_does_not_count(self):
        device = new_device()
        payers_on_device(device, [shift_date(DAY, days=-31), shift_date(DAY, days=-1)])

        response = Scenario.send(device_id=device, amount=15000, transaction_date=DAY)

        assert reason_for(response, "QUEM_OPERA.aparelho_compartilhado") is None

    def test_shared_device_paying_a_new_account_rejects(self):
        """Fazenda de contas pagando uma conta aberta há 7 dias: dois sinais de laranja."""
        device = new_device()
        payers_on_device(device, [shift_date(DAY, days=-20), shift_date(DAY, days=-1)])

        response = Scenario.send(
            device_id=device, amount=15000, payee_opening_date=SEVEN_DAYS_BEFORE, transaction_date=DAY
        )

        assert response["status"] == "rejected"
        assert response["metadata"]["typology"] == "mule_account"
