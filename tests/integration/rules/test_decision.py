from uuid import uuid4

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator, Scenario, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"


class TestDecisionSlideExample:
    def test_slide_payload_is_rejected_with_coherent_reasons(self):
        """O portão da Fase 2: o Pix do slide, com documentos novos a cada execução.

        R$ 1.500 às 22h15, de um aparelho que nunca fez Pix, para uma conta
        PF aberta há 7 dias. Cada pedaço conta uma história, e o metadata
        precisa trazer todas:
          • aparelho não cadastrado acima de R$ 200 → 2FA;
          • acima de R$ 1.000 à noite, PF para PF → 2FA;
          • sem histórico, acima do valor de partida → fora do perfil;
          • conta de 7 dias recebendo o primeiro crédito, fora do perfil
            → conta laranja, que recusa — e recusa vence 2FA.
        """
        response = Scenario.send(
            amount=150000,
            transaction_date="2026-10-17T22:15:00-03:00",
            payee_opening_date="2026-10-10T09:00:00-03:00",
        )

        assert response["status"] == "rejected"
        metadata = response["metadata"]
        assert metadata["typology"] == "mule_account"
        assert metadata["recommended_action"] == "block"
        assert metadata["path"] == "deep"

        fired = {reason["signal"] for reason in metadata["reasons"]}
        assert fired == {
            "LIMITE.aparelho_nao_cadastrado",
            "LIMITE.noturno",
            "PERFIL.valor",
            "CONTA_RECEBEDORA.conta_nova",
        }
        for reason in metadata["reasons"]:
            assert reason["message"], f"{reason['signal']} sem mensagem"
            assert "observed" in reason and "threshold" in reason


class TestDecisionLayers:
    """Esforço proporcional ao risco: o Pix rotineiro não paga o custo do suspeito."""

    def test_routine_pix_takes_the_fast_path(self):
        """Aparelho confiável, destino já pago, de dia, dentro do perfil: caminho rápido."""
        context = {
            "payer_document": RandomGenerator.generate_cpf(),
            "device_id": f"dvc-{uuid4().hex[:12]}",
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }
        Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, days=-2))
        Scenario.send(**context, amount=10000, transaction_date=shift_date(DAY, days=-1))

        response = Scenario.send(**context, amount=10000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert response["metadata"]["path"] == "fast"
        assert response["metadata"]["layers"] == [0, 1]

    def test_new_payee_takes_the_deep_path(self):
        response = Scenario.send(amount=10000, transaction_date=DAY)

        assert response["metadata"]["path"] == "deep"
        assert response["metadata"]["layers"] == [0, 1, 2]

    def test_every_signal_is_accounted_for(self):
        """Nenhum sinal some do metadata: ou disparou, ou passou, ou foi dispensado, ou faltou dado."""
        response = Scenario.send(amount=10000, transaction_date=DAY)

        metadata = response["metadata"]
        accounted = (
            {reason["signal"] for reason in metadata["reasons"]}
            | set(metadata["passed"])
            | {item["signal"] for item in metadata["not_needed"]}
            | {item["signal"] for item in metadata["not_evaluated"]}
        )
        assert accounted == {
            "MARCACAO.lista",
            "LIMITE.aparelho_nao_cadastrado",
            "LIMITE.noturno",
            "RITMO.velocidade",
            "PERFIL.valor",
            "CONTA_RECEBEDORA.conta_nova",
            "CONTA_RECEBEDORA.fan_in",
        }

    def test_rejected_pix_is_recorded_and_consultable(self):
        """Recusa antifraude não é erro HTTP: 201, gravado, e o GET devolve igual."""
        payload = PayloadGenerator.create_pix_payload(payer_document="111.444.777-35")

        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert created["status"] == "rejected"

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])
        assert status == 200
        assert fetched == created
        assert reason_for(fetched, "MARCACAO.lista")["outcome"] == "reject"
