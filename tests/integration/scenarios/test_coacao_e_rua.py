from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator, Scenario, not_needed_signals, reason_for, shift_date

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


def client_with_small_history() -> dict:
    """Aparelho confiável e cinco Pix de R$ 100 aprovados para o mesmo destino."""
    client = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
    Scenario.register_device(client["payer_document"], client["device_id"], "2026-09-19T14:00:00-03:00")
    Scenario.build_history(**client, amounts=[10000] * 5, first_date="2026-09-20T14:00:00-03:00")

    return client


def sequence(client: dict, payee: dict, amounts: list, first_date: str, every_days: int = 1) -> list:
    """Um Pix por intervalo para o mesmo destino; quando pede 2FA, a vítima confirma."""
    responses = []
    for index, amount in enumerate(amounts):
        when = shift_date(first_date, days=every_days * index)
        pix_id = f"pix-{uuid4()}"
        response = Scenario.send(pix_id=pix_id, **client, **payee, amount=amount, transaction_date=when)
        if response["status"] == "two_factor_required":
            RequestGenerator.PATCH_pix_transaction(
                pix_id, {"two_factor_result": "passed", "completed_at": shift_date(when, minutes=1)}
            )
        responses.append(response)
    return responses


class TestFalsoInvestimentoEscalada:
    """Item 3 — PERFIL.escalada: valores crescentes para o mesmo destino em poucos dias."""

    def test_growing_payments_to_the_same_destination_require_scam_two_factor(self):
        client = client_with_small_history()
        broker = new_person_account("2024-01-10T10:00:00-03:00")

        responses = sequence(client, broker, [15000, 30000, 50000], "2026-10-10T19:00:00-03:00")

        third = responses[2]
        assert third["status"] == "two_factor_required"
        assert third["metadata"]["scam_warning"] is True
        assert reason_for(third, "PERFIL.escalada")["typology"] == "app"

    def test_monthly_rent_of_the_same_amount_does_not_fire(self):
        client = client_with_small_history()
        landlord = new_person_account("2020-01-10T10:00:00-03:00")

        responses = sequence(client, landlord, [200000, 200000, 200000], "2026-08-05T10:00:00-03:00", every_days=30)

        assert all(reason_for(response, "PERFIL.escalada") is None for response in responses)

    def test_growing_less_than_three_times_does_not_fire(self):
        client = client_with_small_history()
        broker = new_person_account("2024-01-10T10:00:00-03:00")

        responses = sequence(client, broker, [15000, 30000, 40000], "2026-10-10T19:00:00-03:00")

        assert reason_for(responses[2], "PERFIL.escalada") is None

    def test_old_company_destination_is_not_needed(self):
        client = client_with_small_history()
        broker = {
            "payee_document": RandomGenerator.generate_cnpj(),
            "payee_account_number": RandomGenerator.generate_account_number(),
            "payee_opening_date": "2021-10-10T10:00:00-03:00",
        }

        responses = sequence(client, broker, [15000, 30000, 50000], "2026-10-10T19:00:00-03:00")

        assert "PERFIL.escalada" in not_needed_signals(responses[2])


COERCION_NIGHT = "2026-10-17T22:30:00-03:00"
SIGNAL = "LIMITE.noturno_fora_de_casa"


def not_evaluated_signals(response: dict) -> list:
    return [item["signal"] for item in response["metadata"]["not_evaluated"]]


def night_pix(client: dict, payee: dict, minutes: int, geolocation=FIFTEEN_KM_AWAY, with_geolocation=True) -> dict:
    return Scenario.send(
        payer_document=client["payer_document"], device_id=client["device_id"], **payee, amount=100000,
        geolocation=geolocation, with_geolocation=with_geolocation, transaction_date=shift_date(COERCION_NIGHT, minutes=minutes),
    )


class TestNoturnoForaDeCasa:
    """Item 5b — LIMITE.noturno_fora_de_casa: o teto noturno da Res. BCB 142 sem exceção, no contexto de coação (F8)."""

    def test_kidnapping_second_pix_is_rejected(self):
        """Aparelho de sempre, 22h30, a 15 km de casa, 3 Pix de R$ 1.000 para destinos novos."""
        client = client_at_home()

        first = night_pix(client, new_person_account("2020-01-10T10:00:00-03:00"), 0)
        second = night_pix(client, new_person_account("2020-01-10T10:00:00-03:00"), 3)

        assert first["status"] == "approved", first
        assert second["status"] == "rejected"
        assert second["metadata"]["recommended_action"] == "block"
        reason = reason_for(second, SIGNAL)
        assert reason["outcome"] == "reject"
        assert "Res. BCB 142 vale sem exceção" in reason["message"]

    def test_near_home_keeps_the_limit_two_factor(self):
        client = client_at_home()

        night_pix(client, new_person_account("2020-01-10T10:00:00-03:00"), 0, geolocation=TWO_KM_AWAY)
        second = night_pix(client, new_person_account("2020-01-10T10:00:00-03:00"), 3, geolocation=TWO_KM_AWAY)

        assert second["status"] == "two_factor_required"
        assert second["metadata"]["step_up_reason"] == "limit"
        assert reason_for(second, SIGNAL) is None

    def test_recurring_destination_is_not_rejected(self):
        client = client_at_home()

        night_pix(client, new_person_account("2020-01-10T10:00:00-03:00"), 0)
        second = night_pix(client, client["usual_payee"], 3)

        assert second["status"] != "rejected"
        assert reason_for(second, SIGNAL) is None

    def test_person_to_company_is_not_needed(self):
        client = client_at_home()
        shop = {
            "payee_document": RandomGenerator.generate_cnpj(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }

        night_pix(client, new_person_account("2020-01-10T10:00:00-03:00"), 0)
        second = night_pix(client, shop, 3)

        assert SIGNAL in not_needed_signals(second)

    def test_payer_without_a_24h_old_location_is_not_evaluated(self):
        client = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
        Scenario.send(**client, amount=15000, geolocation=HOME, transaction_date=shift_date(COERCION_NIGHT, hours=-3))

        response = night_pix(client, new_person_account("2020-01-10T10:00:00-03:00"), 0)

        assert SIGNAL in not_evaluated_signals(response)

    def test_without_geolocation_is_not_evaluated(self):
        client = client_at_home()

        response = night_pix(client, new_person_account("2020-01-10T10:00:00-03:00"), 0, with_geolocation=False)

        assert SIGNAL in not_evaluated_signals(response)
