from uuid import uuid4

from tests.utils import RandomGenerator, Scenario, shift_date

# Coação e celular roubado na rua (F6 e F8 da bateria de realidade). As duas
# falhas tinham a mesma causa: o Pix aprovado longe de casa virava "local
# habitual" na hora. Agora um local só conta como habitual 24 h depois.

HOME = {"latitude": -23.56, "longitude": -46.65}
NINE_KM_AWAY = {"latitude": -23.479, "longitude": -46.65}
FIFTEEN_KM_AWAY = {"latitude": -23.425, "longitude": -46.65}
TWO_KM_AWAY = {"latitude": -23.542, "longitude": -46.65}
NIGHT = "2026-10-17T23:00:00-03:00"


def client_at_home() -> dict:
    """Aparelho confiável e cinco Pix de R$ 700 aprovados de casa, um por dia, para o mesmo destino."""
    client = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
    Scenario.register_device(client["payer_document"], client["device_id"], "2026-09-19T14:00:00-03:00")
    usual = {
        "payee_document": RandomGenerator.generate_cpf(),
        "payee_account_number": RandomGenerator.generate_account_number(),
    }
    Scenario.build_history(**client, **usual, amounts=[70000] * 5, first_date="2026-09-20T14:00:00-03:00")

    return {**client, "usual_payee": usual}


class TestLocalHabitualSoDepoisDe24h:
    """3a — o local de um Pix aprovado só vira habitual 24 h depois, para o Modo Rua do método do 2FA."""

    def test_second_night_pix_away_from_home_requires_face_liveness(self):
        """Celular de sempre, 23h, a 9 km de casa: o 1º Pix sai; o 2º pede biometria, e não a confirmação no app.

        Antes, o local do 1º Pix (aprovado) virava "habitual" na hora, e o 2º
        caía na confirmação no app — que o ladrão com o celular desbloqueado
        confirma. Os dois vão para o destino de sempre, para o sinal de
        coação (que só vale para destino novo) não entrar na conta.
        """
        client = client_at_home()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}

        first = Scenario.send(**origin, **client["usual_payee"], amount=90000, geolocation=NINE_KM_AWAY, transaction_date=NIGHT)
        assert first["status"] == "approved", first

        second = Scenario.send(
            **origin, **client["usual_payee"], amount=95000, geolocation=NINE_KM_AWAY,
            transaction_date=shift_date(NIGHT, minutes=2),
        )

        assert second["status"] == "two_factor_required"
        assert second["metadata"]["step_up_method"] == "face_liveness"
