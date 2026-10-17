from concurrent.futures import ThreadPoolExecutor

from tests.utils import PayloadGenerator, RequestGenerator, shift_date

# O retorno do 2FA (`PATCH /pix/transaction/{id}`) mora sozinho neste
# arquivo, como mora sozinho no controller: se a QI Tech disser que a rota
# está fora do escopo, ela sai sem quebrar nenhum outro teste.

TRANSACTION_DATE = "2026-10-17T14:00:00-03:00"
COMPLETED_AT = "2026-10-17T14:01:10-03:00"


def two_factor_pix() -> dict:
    """Um Pix que pede 2FA: primeiro Pix de um cliente desconhecido, acima do limite de partida."""
    payload = PayloadGenerator.create_pix_payload(amount=150000, transaction_date=TRANSACTION_DATE)

    status, response = RequestGenerator.POST_pix_transaction(payload)
    assert status == 201
    assert response["status"] == "two_factor_required", response

    return payload


def two_factor_return(result: str, completed_at: str = COMPLETED_AT) -> dict:
    return {"two_factor_result": result, "completed_at": completed_at}


class TestTwoFactorReturn:
    def test_passed_approves_the_pix(self):
        """O cliente passou no 2FA: o Pix saiu, e a análise passa a dizer isso."""
        payload = two_factor_pix()

        status, response = RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("passed"))

        assert status == 200
        assert response["status"] == "approved"

    def test_failed_rejects_the_pix(self):
        payload = two_factor_pix()

        status, response = RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("failed"))

        assert status == 200
        assert response["status"] == "rejected"

    def test_answers_with_the_same_dossier_as_the_get(self):
        payload = two_factor_pix()

        status, patched = RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("passed"))
        assert status == 200

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        assert patched == fetched

    def test_records_the_change_in_the_status_history(self):
        payload = two_factor_pix()

        RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("passed"))
        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        birth, change = fetched["metadata"]["status_history"]
        assert (birth["from_status"], birth["to_status"]) == (None, "two_factor_required")
        assert (change["from_status"], change["to_status"]) == ("two_factor_required", "approved")

    def test_same_result_again_records_nothing(self):
        """Retorno repetido (retry da rede) devolve o mesmo dossiê e não grava outro evento."""
        payload = two_factor_pix()

        status, first = RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("passed"))
        assert status == 200

        status, second = RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("passed"))

        assert status == 200
        assert second == first
        assert len(second["metadata"]["status_history"]) == 2

    def test_different_result_is_a_conflict(self):
        """O 2FA terminou uma vez só: um segundo resultado, diferente, não reescreve o primeiro."""
        payload = two_factor_pix()

        status, _response = RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("passed"))
        assert status == 200

        status, response = RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("failed"))

        assert status == 409
        assert response["code"] == "QIT001008"

    def test_analysis_that_did_not_ask_for_two_factor_is_a_conflict(self):
        payload = PayloadGenerator.create_pix_payload()
        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert created["status"] == "approved"

        status, response = RequestGenerator.PATCH_pix_transaction(payload["id"], two_factor_return("passed"))

        assert status == 409
        assert response["code"] == "QIT001009"

    def test_completed_before_the_pix_is_unprocessable(self):
        payload = two_factor_pix()

        status, response = RequestGenerator.PATCH_pix_transaction(
            payload["id"], two_factor_return("passed", completed_at=shift_date(TRANSACTION_DATE, seconds=-1))
        )

        assert status == 422
        assert response["code"] == "QIT001007"

    def test_completed_at_the_same_instant_as_the_pix_is_accepted(self):
        payload = two_factor_pix()

        status, _response = RequestGenerator.PATCH_pix_transaction(
            payload["id"], two_factor_return("passed", completed_at="2026-10-17T17:00:00+00:00")
        )

        assert status == 200

    def test_date_that_does_not_exist_is_unprocessable(self):
        payload = two_factor_pix()

        status, response = RequestGenerator.PATCH_pix_transaction(
            payload["id"], two_factor_return("passed", completed_at="2026-02-30T14:00:00-03:00")
        )

        assert status == 422
        assert response["code"] == "QIT001004"

    def test_unknown_id_is_not_found(self):
        status, response = RequestGenerator.PATCH_pix_transaction("pix-que-nunca-existiu", two_factor_return("passed"))

        assert status == 404
        assert response["code"] == "QIT001001"

    def test_out_of_schema_is_a_bad_request(self):
        payload = two_factor_pix()

        invalid_bodies = [
            {**two_factor_return("passed"), "reason": "a mais"},
            {"two_factor_result": "passed"},
            {"completed_at": COMPLETED_AT},
            two_factor_return("maybe"),
            two_factor_return("passed", completed_at="17/10/2026 14:01"),
            two_factor_return("passed", completed_at="2026-10-17T14:01:10"),
        ]

        for body in invalid_bodies:
            status, response = RequestGenerator.PATCH_pix_transaction(payload["id"], body)
            assert status == 400, body
            assert response["code"] == "QIT000001"

    def test_refuses_without_internal_token(self):
        status, response = RequestGenerator.PATCH_pix_transaction(
            "pix-qualquer", two_factor_return("passed"), headers={}
        )

        assert status == 403
        assert response["code"] == "QIT000002"


class TestTwoFactorReturnConcurrency:
    def test_two_simultaneous_returns_with_different_results(self):
        """Um passa, o outro encontra o resultado já gravado: 200 e 409, e um evento só.

        Sem a trava, os dois leriam "ainda em two_factor_required" e os dois
        gravariam — e a análise teria dois desfechos.
        """
        payload = two_factor_pix()
        bodies = [two_factor_return("passed"), two_factor_return("failed")]

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda body: RequestGenerator.PATCH_pix_transaction(payload["id"], body), bodies)
            )

        assert sorted(status for status, _response in results) == [200, 409]

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])
        assert status == 200
        assert len(fetched["metadata"]["status_history"]) == 2

        [winner] = [response for status, response in results if status == 200]
        assert fetched["status"] == winner["status"]
