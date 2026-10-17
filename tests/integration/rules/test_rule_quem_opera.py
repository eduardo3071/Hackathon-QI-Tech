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


SAO_PAULO = {"latitude": -23.56, "longitude": -46.65}
FORTALEZA = {"latitude": -3.73, "longitude": -38.52}  # ~2.370 km de São Paulo
SAO_PAULO_NEARBY = {"latitude": -23.58, "longitude": -46.66}  # ~2,5 km


def not_evaluated_signals(response: dict) -> list:
    return [item["signal"] for item in response["metadata"]["not_evaluated"]]


def payer_last_seen_in_sao_paulo(hours_before: int) -> dict:
    """Pagador com aparelho confiável cujo último Pix aprovado saiu de São Paulo, `hours_before` horas antes de DAY."""
    context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": new_device()}
    Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, hours=-hours_before))

    return context


class TestRuleQuemOperaViagemImpossivel:
    """Regra 5 — QUEM_OPERA.viagem_impossivel: daria para estar lá?

    A distância até o último Pix aprovado com geolocalização, dividida
    pelo tempo desde ele, acima de 900 km/h (mais rápido que um avião
    comercial): quem opera não pode ser a mesma pessoa. Pontua `ato` no
    corte, e por isso pede biometria; nunca recusa.
    """

    def test_faster_than_a_plane_requires_face_liveness(self):
        context = payer_last_seen_in_sao_paulo(hours_before=2)

        response = Scenario.send(**context, geolocation=FORTALEZA, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "account_takeover"
        assert response["metadata"]["step_up_method"] == "face_liveness"
        reason = reason_for(response, "QUEM_OPERA.viagem_impossivel")
        assert reason["typology"] == "ato"
        assert reason["observed"]["speed_kmh"] > 900

    def test_plane_speed_passes(self):
        """A mesma viagem em 3 horas: ~790 km/h, o voo São Paulo–Fortaleza."""
        context = payer_last_seen_in_sao_paulo(hours_before=3)

        response = Scenario.send(**context, geolocation=FORTALEZA, transaction_date=DAY)

        assert response["status"] == "approved"
        assert reason_for(response, "QUEM_OPERA.viagem_impossivel") is None
        assert "QUEM_OPERA.viagem_impossivel" in response["metadata"]["passed"]

    def test_gps_noise_below_5_km_is_ignored(self):
        """2,5 km em 1 minuto daria 150 km/h — mas é a imprecisão do GPS, não uma viagem."""
        context = payer_last_seen_in_sao_paulo(hours_before=0)

        response = Scenario.send(**context, geolocation=SAO_PAULO_NEARBY, transaction_date=shift_date(DAY, seconds=10))

        assert reason_for(response, "QUEM_OPERA.viagem_impossivel") is None
        assert "QUEM_OPERA.viagem_impossivel" in response["metadata"]["passed"]

    def test_pix_without_geolocation_is_not_evaluated(self):
        context = payer_last_seen_in_sao_paulo(hours_before=2)

        response = Scenario.send(**context, with_geolocation=False, amount=10000, transaction_date=DAY)

        assert "QUEM_OPERA.viagem_impossivel" in not_evaluated_signals(response)

    def test_payer_without_geolocated_history_is_not_evaluated(self):
        response = Scenario.send(geolocation=FORTALEZA, transaction_date=DAY)

        assert "QUEM_OPERA.viagem_impossivel" in not_evaluated_signals(response)

    def test_pix_older_than_the_last_location_is_not_evaluated(self):
        """Pix que chega fora de ordem (Δt ≤ 0): não há velocidade para calcular."""
        context = payer_last_seen_in_sao_paulo(hours_before=0)

        response = Scenario.send(**context, geolocation=FORTALEZA, transaction_date=shift_date(DAY, minutes=-30))

        assert "QUEM_OPERA.viagem_impossivel" in not_evaluated_signals(response)
