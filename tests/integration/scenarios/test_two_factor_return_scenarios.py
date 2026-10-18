from datetime import datetime
from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator, Scenario, reason_for, shift_date

# Os cenários do retorno do 2FA (CLAUDE.md, "Retorno do 2FA"): o que o
# motor aprende com cada resultado. Moram num arquivo só deles, como a
# rota: se o PATCH sair do escopo, este arquivo sai junto.

DAY = "2026-10-17T14:00:00-03:00"
HISTORY_START = "2026-09-20T14:00:00-03:00"


def new_device() -> str:
    return f"dvc-{uuid4().hex[:12]}"


def new_payee(opening_date: str = None) -> dict:
    payee = {
        "payee_document": RandomGenerator.generate_cpf(),
        "payee_account_number": RandomGenerator.generate_account_number(),
    }
    if opening_date is not None:
        payee["payee_opening_date"] = opening_date

    return payee


def client_with_history() -> dict:
    """Cliente com 5 Pix de R$ 100 aprovados, um por dia, do mesmo aparelho, para o mesmo destino."""
    client = {"payer_document": RandomGenerator.generate_cpf(), "device_id": new_device()}
    usual_payee = new_payee()
    Scenario.build_history(**client, **usual_payee, amounts=[10000] * 5, first_date=HISTORY_START)

    return {**client, "usual_payee": usual_payee}


def send_two_factor_return(pix: dict, result: str, completed_at: str) -> dict:
    status, response = RequestGenerator.PATCH_pix_transaction(
        pix["id"], {"two_factor_result": result, "completed_at": completed_at}
    )
    assert status == 200, response

    return response


def send(pix_id: str = None, **payload_overrides) -> dict:
    """Manda o Pix e devolve a resposta junto com o `id`, para o PATCH saber a quem responder."""
    if pix_id is None:
        pix_id = f"pix-{uuid4()}"

    return {"id": pix_id, **Scenario.send(pix_id=pix_id, **payload_overrides)}


class TestTwoFactorReturnScenarios:
    def test_face_liveness_passed_registers_the_device(self):
        """Celular novo pede biometria, ela passa, e 10 min depois R$ 800 do mesmo celular não pedem 2FA de aparelho.

        A biometria facial aprovada é o cadastro do aparelho que o BCB
        prevê: o aparelho fica confiável na hora, sem esperar 2 Pix com
        24 h de intervalo.
        """
        client = client_with_history()
        device = new_device()
        payee = new_payee()

        first = send(payer_document=client["payer_document"], device_id=device, **payee, amount=50000, transaction_date=DAY)
        assert first["status"] == "two_factor_required"
        assert first["metadata"]["step_up_method"] == "face_liveness"

        send_two_factor_return(first, "passed", shift_date(DAY, minutes=1))

        second = send(
            payer_document=client["payer_document"],
            device_id=device,
            **payee,
            amount=80000,
            transaction_date=shift_date(DAY, minutes=10),
        )

        assert "LIMITE.aparelho_nao_cadastrado" in second["metadata"]["passed"]
        assert second["status"] == "approved"

    def test_limit_two_factor_from_a_new_phone_is_a_biometric_registration(self):
        """2FA por limite noturno vindo de um celular novo: biometria, e ela passando cadastra o aparelho.

        Três Pix de R$ 300 de noite, do celular de sempre, somam R$ 900. Um
        quarto, de R$ 150, de um celular novo, passa o padrão noturno de
        R$ 1.000 e pede 2FA de limite. Como o aparelho não é confiável, o
        método é `face_liveness` (item 5 da bateria de realidade: a
        confirmação no app não prova nada num celular que pode ser do
        ladrão) e, com a biometria aprovada, o celular novo fica cadastrado:
        no dia seguinte R$ 300 saem sem 2FA de aparelho. (Antes, o 2FA de
        limite era só confirmação no app e não cadastrava o aparelho.)
        """
        client = client_with_history()
        night = "2026-10-17T21:00:00-03:00"

        for index in range(3):
            response = send(
                payer_document=client["payer_document"],
                device_id=client["device_id"],
                **client["usual_payee"],
                amount=30000,
                transaction_date=shift_date(night, minutes=15 * index),
            )
            assert response["status"] == "approved", response

        device = new_device()
        limit_pix = send(
            payer_document=client["payer_document"],
            device_id=device,
            **client["usual_payee"],
            amount=15000,
            transaction_date=shift_date(night, minutes=45),
        )
        assert limit_pix["status"] == "two_factor_required"
        assert limit_pix["metadata"]["step_up_reason"] == "limit"
        assert limit_pix["metadata"]["step_up_method"] == "face_liveness"

        send_two_factor_return(limit_pix, "passed", shift_date(night, minutes=46))

        next_day = send(
            payer_document=client["payer_document"],
            device_id=device,
            **client["usual_payee"],
            amount=30000,
            transaction_date="2026-10-18T14:00:00-03:00",
        )

        assert next_day["status"] == "approved", next_day["metadata"]
        assert "LIMITE.aparelho_nao_cadastrado" in next_day["metadata"]["passed"]

    def test_possible_scam_passed_does_not_make_the_destination_recurring(self):
        """A vítima confirma o Pix com aviso de golpe; no dia seguinte paga o mesmo destino de novo.

        O destino NÃO vira recorrente: o atenuante "destino já pago antes"
        do PERFIL.valor não vale para ele. É o padrão do falso
        investimento — a vítima confirma e volta a pagar o mesmo golpista.
        """
        client = client_with_history()
        scammer = new_payee(opening_date="2026-09-27T10:00:00-03:00")
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}

        first = send(**origin, **scammer, amount=200000, transaction_date=DAY)
        assert first["status"] == "two_factor_required"
        assert first["metadata"]["step_up_reason"] == "possible_scam"

        send_two_factor_return(first, "passed", shift_date(DAY, minutes=2))

        second = send(**origin, **scammer, amount=300000, transaction_date=shift_date(DAY, days=1))

        profile_reason = reason_for(second, "PERFIL.valor")
        assert profile_reason is not None, second["metadata"]
        assert profile_reason["typology"] == "app"
        assert profile_reason["points"] > 0

    def test_repeated_scam_out_of_profile_asks_two_factor_again(self):
        """A vítima confirmou o golpe ontem e hoje manda mais, fora do perfil, para o mesmo destino.

        Sem o sinal CONTA_RECEBEDORA.suspeita_anterior, este Pix saía
        `approved` com `warn`: o crédito confirmado ontem tirou a conta do
        "primeiro crédito", e o placar de golpe ficava na faixa de aviso.
        Com ele, a suspeita de ontem pontua o corte de golpe: 2FA com aviso.
        """
        client = client_with_history()
        scammer = new_payee(opening_date="2026-09-27T10:00:00-03:00")
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}

        first = send(**origin, **scammer, amount=200000, transaction_date=DAY)
        assert first["metadata"]["step_up_reason"] == "possible_scam"
        send_two_factor_return(first, "passed", shift_date(DAY, minutes=2))

        second = send(**origin, **scammer, amount=300000, transaction_date=shift_date(DAY, days=1))

        assert second["status"] == "two_factor_required"
        assert second["metadata"]["step_up_reason"] == "possible_scam"
        assert second["metadata"]["scam_warning"] is True
        signal = reason_for(second, "CONTA_RECEBEDORA.suspeita_anterior")
        assert signal is not None, second["metadata"]
        assert signal["typology"] == "app"
        assert signal["observed"]["prior_scam_step_ups"] == 1

    def test_repeated_scam_destination_within_profile_stays_approved(self):
        """O mesmo destino de novo, mas com valor dentro do perfil: o sinal não pontua, e o Pix sai."""
        client = client_with_history()
        scammer = new_payee(opening_date="2026-09-27T10:00:00-03:00")
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}

        first = send(**origin, **scammer, amount=200000, transaction_date=DAY)
        assert first["metadata"]["step_up_reason"] == "possible_scam"
        send_two_factor_return(first, "passed", shift_date(DAY, minutes=2))

        # O Pix confirmado sob aviso de golpe não entra no perfil (item 1 da
        # bateria de realidade): o perfil segue com os 5 Pix de R$ 100, e
        # só um Pix desse tamanho está dentro dele.
        second = send(**origin, **scammer, amount=10000, transaction_date=shift_date(DAY, days=1))

        assert second["status"] == "approved"
        assert reason_for(second, "CONTA_RECEBEDORA.suspeita_anterior") is None
        assert "CONTA_RECEBEDORA.suspeita_anterior" in second["metadata"]["passed"]

    def test_face_liveness_failed_blocks_the_device_trust_for_a_day(self):
        """Biometria reprovada: por 24 h, nenhum Pix aprovado deste celular o torna confiável.

        O celular já tinha um Pix aprovado havia dois dias. Sem o bloqueio,
        os dois Pix pequenos do dia seguinte completariam "2 aprovados, o
        primeiro há mais de 24 h", e o de R$ 300 sairia sem 2FA. E eles não
        contam nem depois que as 24 h passam: o de R$ 300 da tarde também
        pede biometria.
        """
        client = client_with_history()
        device = new_device()
        origin = {"payer_document": client["payer_document"], "device_id": device}

        warm_up = send(**origin, amount=10000, transaction_date=shift_date(DAY, days=-2))
        assert warm_up["status"] == "approved"

        stepped_up = send(**origin, amount=50000, transaction_date=DAY)
        assert stepped_up["metadata"]["step_up_method"] == "face_liveness"

        failed = send_two_factor_return(stepped_up, "failed", shift_date(DAY, minutes=1))
        assert failed["status"] == "rejected"

        next_morning = "2026-10-18T10:00:00-03:00"
        for minutes in (0, 5):
            small = send(**origin, amount=10000, transaction_date=shift_date(next_morning, minutes=minutes))
            assert small["status"] == "approved", small

        for transaction_date in (shift_date(next_morning, minutes=10), "2026-10-18T15:00:00-03:00"):
            response = send(**origin, amount=30000, transaction_date=transaction_date)

            assert response["status"] == "two_factor_required", transaction_date
            assert response["metadata"]["step_up_method"] == "face_liveness"
            assert reason_for(response, "LIMITE.aparelho_nao_cadastrado")["outcome"] == "two_factor"

    def test_get_after_passed_tells_the_whole_story(self):
        """GET depois de um `passed`: o status é o final, e o dossiê conta de onde ele veio."""
        pix = send(amount=150000, transaction_date=DAY)
        assert pix["status"] == "two_factor_required"

        completed_at = shift_date(DAY, minutes=1)
        send_two_factor_return(pix, "passed", completed_at)

        status, fetched = RequestGenerator.GET_pix_transaction(pix["id"])
        assert status == 200

        metadata = fetched["metadata"]
        assert fetched["status"] == "approved"
        assert metadata["initial_status"] == "two_factor_required"
        assert metadata["two_factor"]["result"] == "passed"
        assert datetime.fromisoformat(metadata["two_factor"]["completed_at"]) == datetime.fromisoformat(completed_at)
        assert [(event["from_status"], event["to_status"]) for event in metadata["status_history"]] == [
            (None, "two_factor_required"),
            ("two_factor_required", "approved"),
        ]
