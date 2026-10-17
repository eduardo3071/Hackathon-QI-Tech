from uuid import uuid4

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator, Scenario, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"


class TestRuleRitmoVelocidade:
    """Regra 3 — RITMO.velocidade: rápido demais?

    Tentativas do pagador numa janela deslizante de 10 minutos, contando
    as recusadas: insistência também é sinal. A contagem só pesa se a
    janela somar R$ 1.000 — rajada de valor baixo (racha da conta do
    bar) pesa menos.
    """

    def _payer_with_known_device(self) -> dict:
        context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
        Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, hours=-1))

        return context

    def _burst(self, context: dict, count: int, amount: int) -> list:
        """`count` Pix, um por minuto, cada um para um destino diferente."""
        responses = []
        for minute in range(count):
            responses.append(Scenario.send(**context, amount=amount, transaction_date=shift_date(DAY, minutes=minute)))

        return responses

    def test_fifth_attempt_in_ten_minutes_requires_two_factor(self):
        context = self._payer_with_known_device()

        responses = self._burst(context, count=5, amount=30000)

        assert [response["status"] for response in responses[:4]] == ["approved"] * 4
        assert responses[4]["status"] == "two_factor_required"
        reason = reason_for(responses[4], "RITMO.velocidade")
        assert reason["outcome"] == "two_factor"
        assert reason["observed"]["attempts"] == 5

    def test_tenth_attempt_is_rejected(self):
        """Do 5º ao 9º pede 2FA; o 10º recusa. Os pedidos de 2FA também contam."""
        context = self._payer_with_known_device()

        responses = self._burst(context, count=10, amount=30000)

        assert [response["status"] for response in responses[4:9]] == ["two_factor_required"] * 5
        assert responses[9]["status"] == "rejected"
        assert reason_for(responses[9], "RITMO.velocidade")["outcome"] == "reject"

    def test_low_value_burst_is_not_a_takeover(self):
        """Seis Pix de R$ 20 em seis minutos: é racha de conta, não conta invadida."""
        context = self._payer_with_known_device()

        responses = self._burst(context, count=6, amount=2000)

        assert [response["status"] for response in responses] == ["approved"] * 6

    def test_attempts_outside_the_window_do_not_count(self):
        context = self._payer_with_known_device()

        for index in range(4):
            Scenario.send(**context, amount=30000, transaction_date=shift_date(DAY, minutes=index))

        response = Scenario.send(**context, amount=30000, transaction_date=shift_date(DAY, minutes=14))

        assert response["status"] == "approved"

    def test_replay_of_the_same_pix_is_not_another_attempt(self):
        """Reenvio do mesmo `id` (retry de rede) não conta de novo na velocidade."""
        context = self._payer_with_known_device()

        for minute in range(2):
            Scenario.send(**context, amount=30000, transaction_date=shift_date(DAY, minutes=minute))

        # Três envios do mesmo Pix: se cada um contasse, o próximo seria a
        # 6ª tentativa da janela e pediria 2FA. Contando uma vez só, é a 4ª.
        replayed = PayloadGenerator.create_pix_payload(**context, amount=30000, transaction_date=shift_date(DAY, minutes=2))
        for _attempt in range(3):
            _status, response = RequestGenerator.POST_pix_transaction(replayed)
            assert response["status"] == "approved"

        response = Scenario.send(**context, amount=30000, transaction_date=shift_date(DAY, minutes=3))

        assert response["status"] == "approved"
        assert reason_for(response, "RITMO.velocidade") is None

    def test_same_pix_redone_with_new_id_counts_once(self):
        """Mesmo pagador, mesmo recebedor, mesmo valor, `id` novo: é o cliente refazendo o Pix.

        Quem tomou um 2FA e refez o Pix não pode ser empurrado para a recusa
        por isso. Cinco envios iguais em cinco minutos são UMA tentativa.
        """
        context = self._payer_with_known_device()
        payee = {
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }

        responses = [
            Scenario.send(**context, **payee, amount=30000, transaction_date=shift_date(DAY, minutes=minute))
            for minute in range(5)
        ]

        assert [response["status"] for response in responses] == ["approved"] * 5

    def test_same_payee_with_another_amount_is_another_attempt(self):
        """O limite logo ao lado: outro valor para o mesmo recebedor é outra tentativa."""
        context = self._payer_with_known_device()
        payee = {
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }

        responses = [
            Scenario.send(**context, **payee, amount=30000 + minute, transaction_date=shift_date(DAY, minutes=minute))
            for minute in range(5)
        ]

        assert responses[4]["status"] == "two_factor_required"
        assert reason_for(responses[4], "RITMO.velocidade")["observed"]["attempts"] == 5


def payer_with_trusted_device() -> dict:
    context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
    Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, hours=-3))

    return context


class TestRuleRitmoFracionamento:
    """Regra 3 — RITMO.fracionamento: o valor foi picado para caber no limite?

    Três ou mais Pix em 1 h, cada um entre 90% e 100% de um limite (os
    R$ 200 do aparelho não cadastrado ou os R$ 1.000 do noturno): é quem
    divide um valor grande para passar por baixo do teto. Pede 2FA de
    limite — confirmação no app, sem tipologia de fraude.
    """

    def test_three_pix_just_below_the_unregistered_device_limit_require_limit_two_factor(self):
        context = payer_with_trusted_device()
        for minutes, amount in ((-50, 19000), (-25, 19500)):
            Scenario.send(**context, amount=amount, transaction_date=shift_date(DAY, minutes=minutes))

        response = Scenario.send(**context, amount=19900, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "limit"
        reason = reason_for(response, "RITMO.fracionamento")
        assert reason["outcome"] == "two_factor"
        assert reason["observed"]["pix_in_band"] == 3

    def test_third_pix_below_the_band_passes(self):
        """R$ 179 fica abaixo de 90% de R$ 200: não é o valor picado para caber no teto."""
        context = payer_with_trusted_device()
        for minutes, amount in ((-50, 19000), (-25, 19500)):
            Scenario.send(**context, amount=amount, transaction_date=shift_date(DAY, minutes=minutes))

        response = Scenario.send(**context, amount=17900, transaction_date=DAY)

        assert reason_for(response, "RITMO.fracionamento") is None

    def test_pix_outside_the_hour_do_not_count(self):
        context = payer_with_trusted_device()
        for minutes, amount in ((-61, 19000), (-25, 19500)):
            Scenario.send(**context, amount=amount, transaction_date=shift_date(DAY, minutes=minutes))

        response = Scenario.send(**context, amount=19900, transaction_date=DAY)

        assert reason_for(response, "RITMO.fracionamento") is None

    def test_three_pix_just_below_the_night_limit_require_limit_two_factor(self):
        context = payer_with_trusted_device()
        for minutes in (-50, -25):
            Scenario.send(**context, amount=95000, transaction_date=shift_date(DAY, minutes=minutes))

        response = Scenario.send(**context, amount=99000, transaction_date=DAY)

        assert reason_for(response, "RITMO.fracionamento")["outcome"] == "two_factor"
