from uuid import uuid4

from tests.utils import RandomGenerator, Scenario, not_needed_signals, reason_for, shift_date

DAY = "2026-10-17T09:00:00-03:00"
HISTORY_START = "2026-09-20T14:00:00-03:00"


def payer_with_history() -> dict:
    """Cinco Pix de R$ 150 aprovados para o mesmo destino, um por dia, do mesmo aparelho."""
    context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
    payee = {
        "payee_document": RandomGenerator.generate_cpf(),
        "payee_account_number": RandomGenerator.generate_account_number(),
    }
    Scenario.build_history(**context, **payee, amounts=[15000] * 5, first_date=HISTORY_START)

    return {**context, "usual_payee": payee}


class TestRuleAnomaliaModoSombra:
    """Regra 8 — ANOMALIA.ml: é diferente de tudo que é normal?

    O Isolation Forest, treinado só com Pix legítimos do simulador, mede o
    quanto o Pix foge do normal. A política nasce em modo sombra: o escore
    vai para o `metadata` e não muda a decisão.
    """

    def test_shadow_mode_records_the_score_without_changing_the_decision(self):
        client = payer_with_history()

        response = Scenario.send(
            payer_document=client["payer_document"], device_id=client["device_id"], amount=7, transaction_date=DAY
        )

        ml = response["metadata"]["ml"]
        assert ml["mode"] == "shadow"
        assert ml["status"] == "evaluated"
        assert ml["model_version"] == "iforest-v1"
        assert 0 < ml["anomaly_score"] < 1
        assert len(ml["top_features"]) == 3
        assert reason_for(response, "ANOMALIA.ml") is None
        assert "ANOMALIA.ml" in response["metadata"]["passed"]

    def test_cents_to_many_destinations_score_above_a_usual_pix(self):
        """O padrão novo: centavos, espaçados, cada um para um destino diferente."""
        client = payer_with_history()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}

        usual = Scenario.send(**origin, amount=15000, transaction_date=shift_date(DAY, minutes=-30))
        for index in range(12):
            cents = Scenario.send(**origin, amount=5 + index, transaction_date=shift_date(DAY, minutes=20 * index))

        assert cents["metadata"]["ml"]["anomaly_score"] > usual["metadata"]["ml"]["anomaly_score"]
        assert "destinos distintos nas últimas 24 h acima do normal" in cents["metadata"]["ml"]["top_features"]

    def test_fast_path_does_not_run_the_model(self):
        client = payer_with_history()

        response = Scenario.send(
            payer_document=client["payer_document"],
            device_id=client["device_id"],
            **client["usual_payee"],
            amount=15000,
            transaction_date=DAY,
        )

        assert response["metadata"]["path"] == "fast"
        assert response["metadata"]["ml"]["status"] == "not_needed"
        assert response["metadata"]["ml"]["anomaly_score"] is None
        assert "ANOMALIA.ml" in not_needed_signals(response)
