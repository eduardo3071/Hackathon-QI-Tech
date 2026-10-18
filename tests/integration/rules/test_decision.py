from uuid import uuid4

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator, Scenario, decision_of, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"


class TestDecisionSlideExample:
    def test_slide_payload_requires_two_factor_with_scam_warning(self):
        """O Pix do slide, com documentos novos a cada execução.

        R$ 1.500 às 22h15, primeiro Pix de um cliente que o motor ainda não
        conhece, para uma conta PF aberta há 7 dias. Cada pedaço conta uma
        história, e o metadata precisa trazer todas:
          • cliente sem histórico, acima do limite de partida → 2FA;
          • acima de R$ 1.000 à noite, PF para PF → 2FA;
          • sem histórico, acima do valor de partida → fora do perfil;
          • conta de 7 dias recebendo o primeiro crédito, fora do perfil
            → um sinal forte de conta laranja.
        Um sinal de conta laranja SOZINHO não é "risco claro": não recusa.
        Há motivo de invasão (aparelho) e de golpe (conta laranja), então o
        2FA é biometria facial com aviso de golpe na tela.
        """
        response = Scenario.send(
            amount=150000,
            transaction_date="2026-10-17T22:15:00-03:00",
            payee_opening_date="2026-10-10T09:00:00-03:00",
        )

        assert response["status"] == "two_factor_required"
        metadata = response["metadata"]
        assert metadata["recommended_action"] == "step_up"
        assert metadata["step_up_reason"] == "account_takeover"
        assert metadata["step_up_method"] == "face_liveness"
        assert metadata["scam_warning"] is True
        assert metadata["path"] == "deep"

        fired = {reason["signal"] for reason in metadata["reasons"]}
        assert fired == {
            "LIMITE.aparelho_nao_cadastrado",
            "LIMITE.noturno",
            "PERFIL.valor",
            "CONTA_RECEBEDORA.conta_nova",
            "CONTA_RECEBEDORA.primeiro_pix_alto",
        }
        for reason in metadata["reasons"]:
            assert reason["message"], f"{reason['signal']} sem mensagem"
            assert "observed" in reason and "threshold" in reason


class TestDecisionStepUp:
    """O 2FA diz POR QUE e COMO.

    Conta invadida → biometria facial com prova de vida: no SIM swap o
    fraudador recebe o SMS. Suspeita de golpe → confirmação no app com
    aviso de golpe: a vítima passa em qualquer segundo fator, e a fricção
    útil é o aviso. Limite → confirmação no app.
    """

    def _trusted_client(self) -> dict:
        context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": f"dvc-{uuid4().hex[:12]}"}
        Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, days=-1))
        return context

    def test_untrusted_device_asks_for_face_liveness(self):
        client = self._trusted_client()

        response = Scenario.send(payer_document=client["payer_document"], amount=30000, transaction_date=DAY)

        metadata = response["metadata"]
        assert response["status"] == "two_factor_required"
        assert metadata["step_up_reason"] == "account_takeover"
        assert metadata["step_up_method"] == "face_liveness"
        assert metadata["scam_warning"] is False

    def test_night_limit_alone_asks_for_in_app_confirmation(self):
        client = self._trusted_client()
        payee = {
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }
        Scenario.send(**client, **payee, amount=10000, transaction_date=shift_date(DAY, hours=-2))

        response = Scenario.send(**client, **payee, amount=100001, transaction_date="2026-10-17T22:15:00-03:00")

        metadata = response["metadata"]
        assert response["status"] == "two_factor_required"
        assert metadata["step_up_reason"] == "limit"
        assert metadata["step_up_method"] == "in_app_confirmation"
        assert metadata["scam_warning"] is False

    def test_approved_pix_has_no_step_up(self):
        response = Scenario.send(amount=10000, transaction_date=DAY)

        metadata = response["metadata"]
        assert response["status"] == "approved"
        assert metadata["step_up_reason"] is None
        assert metadata["step_up_method"] is None
        assert metadata["scam_warning"] is False


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
        # O destino só é "já pago" com Pix aprovados em 2 dias diferentes.
        Scenario.send(**context, amount=10000, transaction_date=shift_date(DAY, days=-2, hours=1))
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
            "RITMO.destinos_novos",
            "PERFIL.valor",
            "CONTA_RECEBEDORA.conta_nova",
            "CONTA_RECEBEDORA.fan_in",
            "CONTA_RECEBEDORA.suspeita_anterior",
            "RASTRO.repasse_rapido",
            "QUEM_OPERA.aparelho_compartilhado",
            "QUEM_OPERA.viagem_impossivel",
            "LIMITE.sem_geolocalizacao",
            "QUEM_OPERA.canal_incomum",
            "QUEM_OPERA.ip_compartilhado",
            "RASTRO.conta_pagadora_recente",
            "RITMO.fracionamento",
            "CONTA_RECEBEDORA.dormente",
            "RASTRO.proximidade_marcada",
            "CONTA_RECEBEDORA.varias_instituicoes",
            "QUEM_OPERA.fora_da_zona",
            "ANOMALIA.ml",
            "CONTA_RECEBEDORA.primeiro_pix_alto",
            "PERFIL.escalada",
            "LIMITE.noturno_fora_de_casa",
        }

    def test_rejected_pix_is_recorded_and_consultable(self):
        """Recusa antifraude não é erro HTTP: 201, gravado, e o GET devolve a mesma decisão."""
        payload = PayloadGenerator.create_pix_payload(payer_document="111.444.777-35")

        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert created["status"] == "rejected"

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])
        assert status == 200
        assert decision_of(fetched) == created
        assert reason_for(fetched, "MARCACAO.lista")["outcome"] == "reject"
