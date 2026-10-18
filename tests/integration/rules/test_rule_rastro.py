from uuid import uuid4

from tests.utils import RandomGenerator, Scenario, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"
SEVEN_DAYS_BEFORE = "2026-10-10T09:00:00-03:00"


def trusted_device(payer_document: str) -> str:
    """Um aparelho confiável para este pagador (R$ 200 por Pix é o limite de um aparelho novo, Res. BCB 403)."""
    device_id = f"dvc-{uuid4().hex[:12]}"
    Scenario.register_device(payer_document, device_id, shift_date(DAY, days=-2))

    return device_id


def credit(payee_document: str, amount: int, transaction_date: str, payer_document: str = None) -> dict:
    """Um Pix aprovado PARA `payee_document` — o dinheiro que entra na conta que vai repassar."""
    if payer_document is None:
        payer_document = RandomGenerator.generate_cpf()

    response = Scenario.send(
        payer_document=payer_document,
        device_id=trusted_device(payer_document),
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

        response = Scenario.send(payer_document=mule, device_id=trusted_device(mule), amount=80000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "possible_scam"
        assert response["metadata"]["scam_warning"] is True
        reason = reason_for(response, "RASTRO.repasse_rapido")
        assert reason["typology"] == "mule"
        assert reason["observed"]["received_amount"] == 100000

    def test_forwarding_just_below_the_share_passes(self):
        mule = RandomGenerator.generate_cpf()
        credit(mule, 100000, shift_date(DAY, minutes=-30))

        response = Scenario.send(payer_document=mule, device_id=trusted_device(mule), amount=79000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert reason_for(response, "RASTRO.repasse_rapido") is None

    def test_credit_older_than_the_window_does_not_count(self):
        mule = RandomGenerator.generate_cpf()
        credit(mule, 100000, shift_date(DAY, minutes=-61))

        response = Scenario.send(payer_document=mule, device_id=trusted_device(mule), amount=80000, transaction_date=DAY)

        assert reason_for(response, "RASTRO.repasse_rapido") is None

    def test_credit_from_the_same_owner_does_not_count(self):
        """Salário que cai na conta e vai para a outra conta do mesmo titular não é passagem."""
        owner = RandomGenerator.generate_cpf()
        credit(owner, 100000, shift_date(DAY, minutes=-30), payer_document=owner)

        response = Scenario.send(payer_document=owner, device_id=trusted_device(owner), amount=80000, transaction_date=DAY)

        assert reason_for(response, "RASTRO.repasse_rapido") is None

    def test_forwarding_to_a_new_account_is_two_mule_signals_and_rejects(self):
        mule = RandomGenerator.generate_cpf()
        credit(mule, 100000, shift_date(DAY, minutes=-30))

        response = Scenario.send(
            payer_document=mule,
            device_id=trusted_device(mule),
            amount=80000,
            payee_opening_date=SEVEN_DAYS_BEFORE,
            transaction_date=DAY,
        )

        assert response["status"] == "rejected"
        assert response["metadata"]["typology"] == "mule_account"


TEN_DAYS_BEFORE = "2026-10-07T10:00:00-03:00"
THIRTY_ONE_DAYS_BEFORE = "2026-09-16T10:00:00-03:00"


class TestRuleRastroContaPagadoraRecente:
    """Regra 7 — RASTRO.conta_pagadora_recente: quem paga acabou de abrir a conta?

    Conta pagadora com menos de 30 dias mandando mais que o limite de
    partida (R$ 1.000) para um destino novo: a laranja de segundo salto,
    que recebe a vítima e repassa, ou a conta aberta com documento de
    outra pessoa. Pontua `mule` abaixo do corte (30): reforça.
    """

    def test_new_payer_account_sending_above_the_starting_limit_scores_mule(self):
        response = Scenario.send(payer_opening_date=TEN_DAYS_BEFORE, amount=150000, transaction_date=DAY)

        reason = reason_for(response, "RASTRO.conta_pagadora_recente")
        assert reason["typology"] == "mule"
        assert reason["points"] > 0
        assert reason["observed"]["payer_account_age_days"] == 10

    def test_new_payer_account_at_the_starting_limit_passes(self):
        response = Scenario.send(payer_opening_date=TEN_DAYS_BEFORE, amount=100000, transaction_date=DAY)

        assert reason_for(response, "RASTRO.conta_pagadora_recente") is None
        assert "RASTRO.conta_pagadora_recente" in response["metadata"]["passed"]

    def test_payer_account_older_than_30_days_passes(self):
        response = Scenario.send(payer_opening_date=THIRTY_ONE_DAYS_BEFORE, amount=150000, transaction_date=DAY)

        assert reason_for(response, "RASTRO.conta_pagadora_recente") is None


# Marcações do seed (database/database.sql): a própria vale desde
# 2026-09-01 10h; a de outro PSP, desde 2026-09-20 10h. Um Pix do
# documento marcado ANTES disso ainda é aprovado — é o dinheiro que já
# tinha saído quando a fraude foi descoberta.
OWN_MARKED = "111.444.777-35"
THIRD_PARTY_MARKED = "222.555.888-46"


def approved_pix(payer_document: str, payee: dict, transaction_date: str, amount: int = 15000) -> None:
    response = Scenario.send(payer_document=payer_document, **payee, amount=amount, transaction_date=transaction_date)
    assert response["status"] == "approved", response


def new_person() -> dict:
    document = RandomGenerator.generate_cpf()
    return {"payee_document": document, "payee_account_number": RandomGenerator.account_number_for(document)}


class TestRuleRastroProximidadeMarcada:
    """Regra 7 — RASTRO.proximidade_marcada: o recebedor recebeu de quem tem marcação de fraude?

    Nas últimas 24 h, um Pix aprovado de um documento com marcação
    vigente para o recebedor (1 salto) é evidência dura: recusa. Dois
    saltos (o recebedor recebeu de quem recebeu do marcado) pontuam
    `mule`. Só vale para recebedor PF: um lojista que recebeu de um
    marcado não pode bloquear todos os clientes dele por um dia.
    """

    def test_receiver_credited_by_a_marked_document_rejects(self):
        receiver = new_person()
        approved_pix(OWN_MARKED, receiver, "2026-09-01T08:00:00-03:00")

        response = Scenario.send(**receiver, amount=15000, transaction_date="2026-09-01T12:00:00-03:00")

        assert response["status"] == "rejected"
        assert response["metadata"]["typology"] == "mule_account"
        reason = reason_for(response, "RASTRO.proximidade_marcada")
        assert reason["outcome"] == "reject"
        assert reason["observed"]["hops"] == 1

    def test_credit_from_the_marked_document_older_than_24_hours_does_not_count(self):
        receiver = new_person()
        approved_pix(OWN_MARKED, receiver, "2026-09-01T08:00:00-03:00")

        response = Scenario.send(**receiver, amount=15000, transaction_date="2026-09-02T08:01:00-03:00")

        assert reason_for(response, "RASTRO.proximidade_marcada") is None

    def test_two_hops_from_a_marked_document_scores_mule(self):
        intermediary = new_person()
        receiver = new_person()
        approved_pix(THIRD_PARTY_MARKED, intermediary, "2026-09-20T08:00:00-03:00")
        approved_pix(intermediary["payee_document"], receiver, "2026-09-20T09:00:00-03:00", amount=10000)

        response = Scenario.send(**receiver, amount=15000, transaction_date="2026-09-20T12:00:00-03:00")

        reason = reason_for(response, "RASTRO.proximidade_marcada")
        assert reason["outcome"] == "warn"
        assert reason["typology"] == "mule"
        assert reason["observed"]["hops"] == 2
        assert response["status"] != "rejected"

    def test_receiver_without_marked_senders_passes(self):
        receiver = new_person()
        approved_pix(RandomGenerator.generate_cpf(), receiver, "2026-09-01T08:00:00-03:00")

        response = Scenario.send(**receiver, amount=15000, transaction_date="2026-09-01T12:00:00-03:00")

        assert reason_for(response, "RASTRO.proximidade_marcada") is None
        assert "RASTRO.proximidade_marcada" in response["metadata"]["passed"]
