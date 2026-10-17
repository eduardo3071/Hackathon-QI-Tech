from tests.utils import RandomGenerator, Scenario, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"
SEVEN_DAYS_BEFORE = "2026-10-10T09:00:00-03:00"


def credit(payee_document: str, amount: int, transaction_date: str, payer_document: str = None) -> dict:
    """Um Pix aprovado PARA `payee_document` — o dinheiro que entra na conta que vai repassar."""
    response = Scenario.send(
        payer_document=payer_document,
        payee_document=payee_document,
        payee_account_number=RandomGenerator.account_number_for(payee_document),
        amount=amount,
        transaction_date=transaction_date,
    )
    assert response["status"] == "approved", response

    return response


class TestRuleRastroRepasseRapido:
    """Regra 7 — RASTRO.repasse_rapido: o dinheiro está só de passagem?

    O CPF pagador recebeu de terceiros na última hora e agora repassa 80%
    ou mais disso. É a conta laranja servindo de conta de passagem: pontua
    `mule`. Sozinho pede 2FA com aviso de golpe; com outro sinal de conta
    laranja, recusa pela regra dos dois sinais.
    """

    def test_forwarding_most_of_a_recent_credit_requires_two_factor(self):
        mule = RandomGenerator.generate_cpf()
        credit(mule, 100000, shift_date(DAY, minutes=-30))

        response = Scenario.send(payer_document=mule, amount=80000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "possible_scam"
        assert response["metadata"]["scam_warning"] is True
        reason = reason_for(response, "RASTRO.repasse_rapido")
        assert reason["typology"] == "mule"
        assert reason["observed"]["received_amount"] == 100000

    def test_forwarding_just_below_the_share_passes(self):
        mule = RandomGenerator.generate_cpf()
        credit(mule, 100000, shift_date(DAY, minutes=-30))

        response = Scenario.send(payer_document=mule, amount=79000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert reason_for(response, "RASTRO.repasse_rapido") is None

    def test_credit_older_than_the_window_does_not_count(self):
        mule = RandomGenerator.generate_cpf()
        credit(mule, 100000, shift_date(DAY, minutes=-61))

        response = Scenario.send(payer_document=mule, amount=80000, transaction_date=DAY)

        assert reason_for(response, "RASTRO.repasse_rapido") is None

    def test_credit_from_the_same_owner_does_not_count(self):
        """Salário que cai na conta e vai para a outra conta do mesmo titular não é passagem."""
        owner = RandomGenerator.generate_cpf()
        credit(owner, 100000, shift_date(DAY, minutes=-30), payer_document=owner)

        response = Scenario.send(payer_document=owner, amount=80000, transaction_date=DAY)

        assert reason_for(response, "RASTRO.repasse_rapido") is None

    def test_forwarding_to_a_new_account_is_two_mule_signals_and_rejects(self):
        mule = RandomGenerator.generate_cpf()
        credit(mule, 100000, shift_date(DAY, minutes=-30))

        response = Scenario.send(
            payer_document=mule, amount=80000, payee_opening_date=SEVEN_DAYS_BEFORE, transaction_date=DAY
        )

        assert response["status"] == "rejected"
        assert response["metadata"]["typology"] == "mule_account"
