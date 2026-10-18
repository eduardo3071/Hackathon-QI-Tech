from uuid import uuid4

from tests.utils import RandomGenerator, Scenario, not_needed_signals, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"
SEVEN_DAYS_BEFORE = "2026-10-10T09:00:00-03:00"
THIRTY_ONE_DAYS_BEFORE = "2026-09-16T09:00:00-03:00"


def payer_with_known_device() -> dict:
    context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
    Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, days=-1))

    return context


class TestRuleContaRecebedoraContaNova:
    """Regra 6 — CONTA_RECEBEDORA.conta_nova: quem recebe é confiável?

    Conta destino com menos de 30 dias, recebendo o primeiro crédito, num
    valor fora do perfil do pagador: é a cara da conta laranja
    recém-aberta — mas também do vendedor de carro usado que acabou de
    abrir conta. Sozinha, pede 2FA com aviso de golpe; recusa só junto de
    outro sinal de conta laranja. Só a idade, sem o resto, pontua pouco.
    """

    def test_new_account_first_credit_out_of_profile_requires_two_factor_with_scam_warning(self):
        context = payer_with_known_device()

        response = Scenario.send(
            **context, amount=150000, payee_opening_date=SEVEN_DAYS_BEFORE, transaction_date=DAY
        )

        assert response["status"] == "two_factor_required"
        # O primeiro Pix alto para conta PF nova também é o falso parente
        # (CONTA_RECEBEDORA.primeiro_pix_alto): o placar de golpe chega ao
        # corte, e a tipologia é golpe; status, motivo e método não mudam.
        assert response["metadata"]["typology"] == "app_scam"
        assert response["metadata"]["step_up_reason"] == "possible_scam"
        assert response["metadata"]["step_up_method"] == "in_app_confirmation"
        assert response["metadata"]["scam_warning"] is True
        reason = reason_for(response, "CONTA_RECEBEDORA.conta_nova")
        assert reason["typology"] == "mule"
        assert reason["observed"]["account_age_days"] == 7

    def test_account_older_than_30_days_is_not_new(self):
        context = payer_with_known_device()

        response = Scenario.send(
            **context, amount=150000, payee_opening_date=THIRTY_ONE_DAYS_BEFORE, transaction_date=DAY
        )

        assert response["status"] == "approved"
        assert reason_for(response, "CONTA_RECEBEDORA.conta_nova") is None

    def test_new_account_within_profile_only_scores(self):
        """Primeiro Pix de R$ 100 para a conta de um amigo que acabou de abrir conta: passa."""
        context = payer_with_known_device()

        response = Scenario.send(**context, amount=10000, payee_opening_date=SEVEN_DAYS_BEFORE, transaction_date=DAY)

        assert response["status"] == "approved"
        reason = reason_for(response, "CONTA_RECEBEDORA.conta_nova")
        assert reason["points"] == 20
        assert response["metadata"]["scores"]["mule"] == 20

    def test_same_ownership_is_outside_the_mule_signals(self):
        """Salário que vai para a conta de investimento recém-aberta do próprio cliente."""
        context = payer_with_known_device()

        response = Scenario.send(
            **context,
            payee_document=context["payer_document"],
            amount=150000,
            payee_opening_date=SEVEN_DAYS_BEFORE,
            transaction_date=DAY,
        )

        assert response["status"] == "approved"
        assert "CONTA_RECEBEDORA.conta_nova" in not_needed_signals(response)
        assert "CONTA_RECEBEDORA.fan_in" in not_needed_signals(response)


class TestRuleContaRecebedoraFanIn:
    """Regra 6 — CONTA_RECEBEDORA.fan_in: muitos pagadores para uma pessoa física.

    Várias vítimas convergindo para a mesma conta PF numa hora é o padrão
    clássico de conta laranja. Só vale para PF: lojista recebe de muitos.
    """

    def _payers_to(self, payee: dict, count: int, amount: int = 20000) -> list:
        """`count` pagadores diferentes, um por minuto, R$ 200 cada (o fan-in só vale com R$ 1.000 na janela).

        R$ 200 é o limite por Pix do aparelho não cadastrado (Res. BCB 403):
        os pagadores chegam de aparelhos novos e passam sem 2FA de aparelho.
        """
        responses = []
        for minute in range(count):
            responses.append(Scenario.send(**payee, amount=amount, transaction_date=shift_date(DAY, minutes=minute)))

        return responses

    def _known_payers_to(self, payee: dict, count: int, amount: int) -> list:
        """`count` clientes diferentes, um por minuto, cada um do seu aparelho confiável (cadastro já feito)."""
        responses = []
        for minute in range(count):
            buyer = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
            Scenario.register_device(buyer["payer_document"], buyer["device_id"], shift_date(DAY, days=-5))
            responses.append(
                Scenario.send(**buyer, **payee, amount=amount, transaction_date=shift_date(DAY, minutes=minute))
            )

        return responses

    def _old_person_account(self) -> dict:
        return {
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }

    def test_fifth_distinct_payer_in_one_hour_scores_mule(self):
        responses = self._payers_to(self._old_person_account(), count=5)

        assert reason_for(responses[3], "CONTA_RECEBEDORA.fan_in") is None
        reason = reason_for(responses[4], "CONTA_RECEBEDORA.fan_in")
        assert reason["observed"]["distinct_payers"] == 5
        assert responses[4]["metadata"]["scores"]["mule"] == 40
        # Sozinho, o fan-in pontua e não recusa: pode ser uma vaquinha.
        assert responses[4]["status"] == "approved"

    def test_company_payee_is_outside_fan_in(self):
        """O lojista que recebe de 50 clientes por hora não é conta laranja."""
        store = {
            "payee_document": RandomGenerator.generate_cnpj(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }

        responses = self._payers_to(store, count=6)

        assert [response["status"] for response in responses] == ["approved"] * 6
        assert "CONTA_RECEBEDORA.fan_in" in not_needed_signals(responses[5])

    def test_fan_in_to_a_new_account_is_rejected(self):
        """Conta aberta há 7 dias recebendo de 3 pessoas (R$ 1.050) na mesma hora: laranja (20 + 40).

        Conta com menos de 30 dias converge com 3 pagadores, e não 5 (item 7
        da bateria de realidade): antes, só o 5º pagador travava.
        """
        new_account = self._old_person_account()
        new_account["payee_opening_date"] = SEVEN_DAYS_BEFORE

        responses = self._known_payers_to(new_account, count=4, amount=35000)

        assert [response["status"] for response in responses[:2]] == ["approved"] * 2
        assert responses[2]["status"] == "rejected"
        assert responses[2]["metadata"]["typology"] == "mule_account"
        assert responses[2]["metadata"]["scores"]["mule"] == 60


def payee_credited_at(transaction_date: str) -> dict:
    """Uma conta destino que o motor viu receber um Pix aprovado em `transaction_date`."""
    payee = {
        "payee_document": RandomGenerator.generate_cpf(),
        "payee_account_number": RandomGenerator.generate_account_number(),
    }
    response = Scenario.send(**payee, amount=10000, transaction_date=transaction_date)
    assert response["status"] == "approved", response

    return payee


class TestRuleContaRecebedoraDormente:
    """Regra 6 — CONTA_RECEBEDORA.dormente: destino que reaparece depois de 60 dias sem movimento na nossa base.

    A conta laranja alugada costuma ser uma conta antiga, parada, que
    volta a receber de repente. O motor só sabe que a conta ficou parada
    NA NOSSA BASE — ela pode ter movimentado em outro banco. Pontua
    `mule` abaixo do corte: reforça outro sinal de laranja.
    """

    def test_destination_back_after_60_days_scores_mule(self):
        payee = payee_credited_at(shift_date(DAY, days=-61))

        response = Scenario.send(**payee, amount=15000, transaction_date=DAY)

        reason = reason_for(response, "CONTA_RECEBEDORA.dormente")
        assert reason["typology"] == "mule"
        assert reason["points"] > 0
        assert reason["observed"]["days_without_movement"] == 61

    def test_destination_back_after_59_days_passes(self):
        payee = payee_credited_at(shift_date(DAY, days=-59))

        response = Scenario.send(**payee, amount=15000, transaction_date=DAY)

        assert reason_for(response, "CONTA_RECEBEDORA.dormente") is None
        assert "CONTA_RECEBEDORA.dormente" in response["metadata"]["passed"]

    def test_destination_never_seen_receiving_passes(self):
        response = Scenario.send(amount=15000, transaction_date=DAY)

        assert reason_for(response, "CONTA_RECEBEDORA.dormente") is None


FIVE_DAYS_BEFORE = "2026-10-12T09:00:00-03:00"


class TestRuleContaRecebedoraVariasInstituicoes:
    """Regra 6 — CONTA_RECEBEDORA.varias_instituicoes: o recebedor abriu contas em vários bancos de uma vez?

    O mesmo CPF recebedor com contas abertas há menos de 30 dias em 2 ou
    mais instituições (ISPBs) diferentes: a laranja que abre contas em
    série para receber de várias vítimas. O motor só conhece as contas que
    já apareceram como destino na nossa base. Pontua `mule` abaixo do
    corte: reforça.
    """

    def test_new_accounts_in_two_institutions_score_mule(self):
        payee_document = RandomGenerator.generate_cpf()
        Scenario.send(payee_document=payee_document, payee_participant="60701190", payee_opening_date=SEVEN_DAYS_BEFORE, transaction_date=DAY)

        response = Scenario.send(
            payee_document=payee_document,
            payee_participant="18236120",
            payee_opening_date=FIVE_DAYS_BEFORE,
            transaction_date=shift_date(DAY, minutes=10),
        )

        reason = reason_for(response, "CONTA_RECEBEDORA.varias_instituicoes")
        assert reason["typology"] == "mule"
        assert reason["observed"]["institutions"] == 2

    def test_second_institution_account_older_than_30_days_passes(self):
        payee_document = RandomGenerator.generate_cpf()
        Scenario.send(payee_document=payee_document, payee_participant="60701190", payee_opening_date=SEVEN_DAYS_BEFORE, transaction_date=DAY)

        response = Scenario.send(
            payee_document=payee_document,
            payee_participant="18236120",
            payee_opening_date=THIRTY_ONE_DAYS_BEFORE,
            transaction_date=shift_date(DAY, minutes=10),
        )

        assert reason_for(response, "CONTA_RECEBEDORA.varias_instituicoes") is None
        assert "CONTA_RECEBEDORA.varias_instituicoes" in response["metadata"]["passed"]

    def test_two_new_accounts_in_the_same_institution_pass(self):
        payee_document = RandomGenerator.generate_cpf()
        Scenario.send(payee_document=payee_document, payee_opening_date=SEVEN_DAYS_BEFORE, transaction_date=DAY)

        response = Scenario.send(
            payee_document=payee_document, payee_opening_date=FIVE_DAYS_BEFORE, transaction_date=shift_date(DAY, minutes=10)
        )

        assert reason_for(response, "CONTA_RECEBEDORA.varias_instituicoes") is None
