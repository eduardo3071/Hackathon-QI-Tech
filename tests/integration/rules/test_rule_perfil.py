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

    def test_recurrent_payee_attenuates_the_signal(self):
        """O aluguel: valor alto, mesmo destino de sempre, aparelho de sempre → aprova sem aviso."""
        context = self._payer_with_history()

        response = Scenario.send(**context, amount=250000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert response["metadata"]["recommended_action"] == "none"
        assert reason_for(response, "PERFIL.valor") is None
        assert "PERFIL.valor" in response["metadata"]["passed"]

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
