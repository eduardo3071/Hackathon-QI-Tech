from tests.utils import Scenario, reason_for

# Os documentos marcados nascem no seed do database/database.sql. São
# fictícios, com dígitos verificadores válidos.
OWN_MARKER = "111.444.777-35"
RECENT_THIRD_PARTY_MARKER = "222.555.888-46"
OLD_THIRD_PARTY_MARKER = "333.666.999-57"
EXPIRED_OWN_MARKER = "444.777.000-83"


class TestRuleMarcacao:
    """Regra 1 — MARCACAO.lista: alguém já marcou esta pessoa?

    A Res. BCB 587/2026 manda rejeitar todas as transações do usuário
    marcado, como pagador ou recebedor. É regra dura: recusa sozinha,
    sem passar pelos placares.
    """

    def test_payer_with_own_marker_is_rejected(self):
        response = Scenario.send(payer_document=OWN_MARKER)

        assert response["status"] == "rejected"
        assert response["metadata"]["typology"] == "fraud_marker"
        assert response["metadata"]["recommended_action"] == "block"
        assert reason_for(response, "MARCACAO.lista")["outcome"] == "reject"

    def test_payee_with_recent_third_party_marker_is_rejected(self):
        response = Scenario.send(payee_document=RECENT_THIRD_PARTY_MARKER)

        assert response["status"] == "rejected"
        assert reason_for(response, "MARCACAO.lista")["outcome"] == "reject"

    def test_third_party_marker_older_than_90_days_does_not_reject(self):
        """Fora da janela d90 do DICT, a marcação de outro PSP não decide sozinha."""
        response = Scenario.send(payee_document=OLD_THIRD_PARTY_MARKER)

        assert response["status"] == "approved"
        assert reason_for(response, "MARCACAO.lista") is None

    def test_expired_own_marker_does_not_reject(self):
        # Como RECEBEDOR, de propósito: o documento é fixo, e como pagador
        # ele acumularia tentativas a cada vez que a suíte roda, até cair
        # na regra de velocidade.
        response = Scenario.send(payee_document=EXPIRED_OWN_MARKER)

        assert response["status"] == "approved"
        assert reason_for(response, "MARCACAO.lista") is None

    def test_same_ownership_does_not_exempt_a_marked_person(self):
        """Mesma titularidade isenta golpe e laranja — nunca a marcação."""
        response = Scenario.send(payer_document=OWN_MARKER, payee_document=OWN_MARKER)

        assert response["status"] == "rejected"
        assert reason_for(response, "MARCACAO.lista")["outcome"] == "reject"
