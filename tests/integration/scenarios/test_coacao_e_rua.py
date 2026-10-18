from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator, Scenario, reason_for, shift_date

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


DAY = "2026-10-17T11:00:00-03:00"
FIFTEEN_DAYS_OLD = "2026-10-02T10:00:00-03:00"
FORTY_FIVE_DAYS_OLD = "2026-09-02T10:00:00-03:00"


def client_who_pays_high_to_new_destinations() -> dict:
    """Aparelho confiável e cinco Pix de R$ 2.000 aprovados, cada um para um destino novo de conta antiga."""
    client = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
    Scenario.register_device(client["payer_document"], client["device_id"], "2026-09-19T14:00:00-03:00")
    for day in range(5):
        response = Scenario.send(**client, amount=200000, transaction_date=shift_date("2026-09-20T14:00:00-03:00", days=day))
        assert response["status"] != "rejected", response

    return client


def new_person_account(opening_date: str) -> dict:
    return {
        "payee_document": RandomGenerator.generate_cpf(),
        "payee_account_number": RandomGenerator.generate_account_number(),
        "payee_opening_date": opening_date,
    }


class TestFalsoParente:
    """Item 2 — CONTA_RECEBEDORA.primeiro_pix_alto: primeiro Pix alto para conta PF recém-aberta (F2)."""

    def test_first_high_pix_to_a_fifteen_day_account_requires_scam_two_factor(self):
        client = client_who_pays_high_to_new_destinations()

        response = Scenario.send(**client, **new_person_account(FIFTEEN_DAYS_OLD), amount=189000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "possible_scam"
        assert response["metadata"]["scam_warning"] is True
        assert reason_for(response, "CONTA_RECEBEDORA.primeiro_pix_alto")["typology"] == "app"

    def test_second_pix_the_same_day_still_requires_two_factor(self):
        """A vítima confirma o 1º; o 2º ao mesmo golpista, horas depois, ainda pede 2FA com aviso."""
        client = client_who_pays_high_to_new_destinations()
        relative = new_person_account(FIFTEEN_DAYS_OLD)

        first_id = f"pix-{uuid4()}"
        first = Scenario.send(pix_id=first_id, **client, **relative, amount=189000, transaction_date=DAY)
        assert first["status"] == "two_factor_required"
        status, _patched = RequestGenerator.PATCH_pix_transaction(
            first_id, {"two_factor_result": "passed", "completed_at": shift_date(DAY, minutes=1)}
        )
        assert status == 200

        second = Scenario.send(**client, **relative, amount=230000, transaction_date=shift_date(DAY, hours=4))

        assert second["status"] == "two_factor_required"
        assert second["metadata"]["scam_warning"] is True

    def test_below_the_floor_does_not_fire(self):
        client = client_who_pays_high_to_new_destinations()

        response = Scenario.send(**client, **new_person_account(FIFTEEN_DAYS_OLD), amount=95000, transaction_date=DAY)

        assert reason_for(response, "CONTA_RECEBEDORA.primeiro_pix_alto") is None

    def test_account_older_than_30_days_does_not_fire(self):
        client = client_who_pays_high_to_new_destinations()

        response = Scenario.send(**client, **new_person_account(FORTY_FIVE_DAYS_OLD), amount=189000, transaction_date=DAY)

        assert reason_for(response, "CONTA_RECEBEDORA.primeiro_pix_alto") is None
