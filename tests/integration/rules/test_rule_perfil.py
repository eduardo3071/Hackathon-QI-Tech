from uuid import uuid4

from tests.utils import RandomGenerator, Scenario, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"
HISTORY_START = "2026-09-20T14:00:00-03:00"


class TestRulePerfilValor:
    """Regra 4 — PERFIL.valor: está no padrão deste cliente?

    Valor acima do P95 E de 5x a mediana dos Pix aprovados nos últimos 90
    dias, com pelo menos 5 Pix. O mesmo valor muda de sentido com o
    contexto: para um destino recorrente é a conta do mês; para um
    destino novo é risco de golpe; de um aparelho novo, de invasão.
    """

    def _payer_with_history(self) -> dict:
        """Cinco Pix de R$ 100 para o mesmo destino: mediana R$ 100, P95 R$ 100."""
        context = {
            "payer_document": RandomGenerator.generate_cpf(),
            "device_id": f"dvc-{uuid4().hex[:12]}",
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }
        Scenario.build_history(
            payer_document=context["payer_document"],
            device_id=context["device_id"],
            payee_document=context["payee_document"],
            payee_account_number=context["payee_account_number"],
            amounts=[10000] * 5,
            first_date=HISTORY_START,
        )
        return context

    def test_out_of_profile_to_a_new_payee_warns(self):
        """Aparelho conhecido, destino novo, 6x a mediana: cara de golpe, sinal fraco → aviso."""
        context = self._payer_with_history()

        response = Scenario.send(
            payer_document=context["payer_document"],
            device_id=context["device_id"],
            amount=60000,
            transaction_date=DAY,
        )

        assert response["status"] == "approved"
        assert response["metadata"]["recommended_action"] == "warn"
        assert response["metadata"]["typology"] == "app_scam"
        reason = reason_for(response, "PERFIL.valor")
        assert reason["typology"] == "app"
        assert reason["observed"]["median"] == 10000

    def test_exactly_five_times_the_median_is_in_profile(self):
        context = self._payer_with_history()

        response = Scenario.send(
            payer_document=context["payer_document"],
            device_id=context["device_id"],
            amount=50000,
            transaction_date=DAY,
        )

        assert response["status"] == "approved"
        assert response["metadata"]["recommended_action"] == "none"
        assert reason_for(response, "PERFIL.valor") is None

    def _payer_with_rent_history(self) -> dict:
        """Oito Pix de R$ 20 (mediana R$ 20) e três de R$ 1.000 ao mesmo destino, em dias diferentes (P95 R$ 1.000)."""
        context = {
            "payer_document": RandomGenerator.generate_cpf(),
            "device_id": f"dvc-{uuid4().hex[:12]}",
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }
        Scenario.build_history(
            payer_document=context["payer_document"],
            device_id=context["device_id"],
            amounts=[2000] * 8,
            first_date=HISTORY_START,
        )
        Scenario.build_history(
            payer_document=context["payer_document"],
            device_id=context["device_id"],
            payee_document=context["payee_document"],
            payee_account_number=context["payee_account_number"],
            amounts=[100000] * 3,
            first_date=shift_date(HISTORY_START, days=10),
        )
        return context

    def test_recurrent_payee_attenuates_the_signal(self):
        """O aluguel: 3 Pix de R$ 1.000 ao mesmo destino; R$ 1.200 (até 1,5x o maior) passa sem aviso."""
        context = self._payer_with_rent_history()

        response = Scenario.send(**context, amount=120000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert response["metadata"]["recommended_action"] == "none"
        assert reason_for(response, "PERFIL.valor") is None
        assert "PERFIL.valor" in response["metadata"]["passed"]

    def test_recurrent_payee_does_not_excuse_a_jump_above_one_and_a_half_times_the_largest(self):
        """Mesmo destino de sempre, mas R$ 2.500 (2,5x o maior já pago a ele): o atenuante não vale."""
        context = self._payer_with_rent_history()

        response = Scenario.send(**context, amount=250000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["scam_warning"] is True
        assert reason_for(response, "PERFIL.valor")["typology"] == "app"

    def test_out_of_profile_from_a_new_device_points_to_takeover(self):
        context = self._payer_with_history()

        response = Scenario.send(payer_document=context["payer_document"], amount=60000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["typology"] == "account_takeover"
        assert reason_for(response, "PERFIL.valor")["typology"] == "ato"

    def test_without_history_uses_the_starting_limit(self):
        """Cliente sem histórico: R$ 1.000 de partida, entre o Pix médio (R$ 273) e a fraude média (R$ 1.735)."""
        payer = RandomGenerator.generate_cpf()
        device = f"dvc-{uuid4().hex[:12]}"
        Scenario.register_device(payer, device, shift_date(DAY, days=-1))

        within = Scenario.send(payer_document=payer, device_id=device, amount=100000, transaction_date=DAY)
        above = Scenario.send(
            payer_document=payer, device_id=device, amount=100001, transaction_date=shift_date(DAY, hours=1)
        )

        assert reason_for(within, "PERFIL.valor") is None
        reason = reason_for(above, "PERFIL.valor")
        assert reason["threshold"]["fallback_amount"] == 100000

    def test_rejected_attempts_do_not_teach_the_profile(self):
        """O fraudador que sobe valores aos poucos: tentativa recusada não vira perfil.

        Um Pix de R$ 600 recusado (destino marcado) não entra na mediana:
        o próximo R$ 600 para um destino novo continua fora do perfil.
        """
        context = self._payer_with_history()

        rejected = Scenario.send(
            payer_document=context["payer_document"],
            device_id=context["device_id"],
            payee_document="111.444.777-35",
            amount=60000,
            transaction_date=shift_date(DAY, hours=-2),
        )
        assert rejected["status"] == "rejected"

        response = Scenario.send(
            payer_document=context["payer_document"],
            device_id=context["device_id"],
            amount=60000,
            transaction_date=DAY,
        )

        assert reason_for(response, "PERFIL.valor")["observed"]["history_size"] == 5


class TestRulePerfilValorSegundoDegrau:
    """Regra 4 — PERFIL.valor graduado: muito fora do perfil é mais que um aviso.

    Com 10 vezes a mediana ou mais, acima de R$ 1.000, para um destino
    novo e do aparelho confiável de sempre, o sinal pontua golpe no valor
    do corte de golpe: 2FA com aviso de golpe, e não só o aviso. Entre 5 e
    10 vezes, o primeiro degrau continua: aprova com aviso.
    """

    def _payer_with_median_200(self) -> dict:
        """Cinco Pix de R$ 200, um por dia, do mesmo aparelho: mediana R$ 200, aparelho confiável."""
        context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
        Scenario.build_history(**context, amounts=[20000] * 5, first_date=HISTORY_START)

        return context

    def test_fifteen_times_the_median_to_a_new_destination_requires_two_factor_with_scam_warning(self):
        context = self._payer_with_median_200()

        response = Scenario.send(**context, amount=300000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "possible_scam"
        assert response["metadata"]["scam_warning"] is True
        reason = reason_for(response, "PERFIL.valor")
        assert reason["typology"] == "app"
        assert reason["threshold"]["high_median_multiple"] == 200000

    def test_seven_and_a_half_times_the_median_stays_approved_with_warning(self):
        context = self._payer_with_median_200()

        response = Scenario.send(**context, amount=150000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert response["metadata"]["recommended_action"] == "warn"
        assert reason_for(response, "PERFIL.valor")["typology"] == "app"


class TestRulePerfilValorTetoSemHistorico:
    """Regra 4 — PERFIL.valor sem histórico suficiente: um teto para o valor muito alto.

    Com menos de 5 Pix não há mediana, e o segundo degrau nunca valia: um
    aparelho que ficou confiável com dois Pix de R$ 100 mandava, no dia
    seguinte, R$ 200.000 a um destino novo só com aviso. Com o valor no
    teto (`high_fallback_amount`, R$ 10.000) ou acima, vale o mesmo
    caminho do segundo degrau: 2FA com aviso de golpe.
    """

    def _payer_with_two_pix(self) -> dict:
        """Aparelho confiável com dois Pix de R$ 100: histórico curto, abaixo de `min_history`."""
        context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
        Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, days=-1))

        return context

    def test_very_high_amount_with_short_history_requires_two_factor_with_scam_warning(self):
        context = self._payer_with_two_pix()

        response = Scenario.send(**context, amount=20000000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "possible_scam"
        assert response["metadata"]["scam_warning"] is True
        reason = reason_for(response, "PERFIL.valor")
        assert reason["typology"] == "app"
        assert reason["threshold"]["high_fallback_amount"] == 1000000

    def test_just_below_the_ceiling_stays_approved_with_warning(self):
        context = self._payer_with_two_pix()

        response = Scenario.send(**context, amount=900000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert response["metadata"]["recommended_action"] == "warn"
        assert reason_for(response, "PERFIL.valor")["typology"] == "app"

    def test_same_ownership_above_the_ceiling_stays_approved(self):
        context = self._payer_with_two_pix()

        response = Scenario.send(
            **context,
            payee_document=context["payer_document"],
            amount=2000000,
            transaction_date=DAY,
        )

        assert response["status"] == "approved"
