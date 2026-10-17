from datetime import datetime

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator, decision_of


class TestPixTransactionGet:
    def test_returns_the_recorded_decision_of_the_post(self):
        """O GET devolve a análise GRAVADA, não uma reavaliação.

        Se o GET reavaliasse, o mesmo Pix poderia mudar de decisão
        conforme o histórico cresce — e a resposta deixaria de ser prova
        do que foi decidido naquele momento. Tudo o que o POST respondeu
        volta igual; o dossiê só acrescenta a trilha de status.
        """
        payload = PayloadGenerator.create_pix_payload()

        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        assert decision_of(fetched) == created

    def test_status_history_starts_with_the_birth_of_the_analysis(self):
        """Toda análise nasce com um evento: de nenhum status para o status decidido, na data do Pix."""
        payload = PayloadGenerator.create_pix_payload()

        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        [birth] = fetched["metadata"]["status_history"]
        assert birth["from_status"] is None
        assert birth["to_status"] == created["status"]
        assert datetime.fromisoformat(birth["event_datetime"]) == datetime.fromisoformat(payload["transaction_date"])

    def test_post_does_not_carry_the_status_history(self):
        """O POST continua com a resposta do slide: a história mora no dossiê (GET)."""
        payload = PayloadGenerator.create_pix_payload()

        status, created = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert "status_history" not in created["metadata"]

    def test_unknown_id_is_not_found(self):
        status, response = RequestGenerator.GET_pix_transaction("pix-que-nunca-existiu")

        assert status == 404
        assert response["code"] == "QIT001001"

    def test_refuses_without_internal_token(self):
        status, response = RequestGenerator.GET_pix_transaction("pix-qualquer", headers={})

        assert status == 403
        assert response["code"] == "QIT000002"


class TestPixTransactionIdempotency:
    def test_same_id_and_same_content_returns_the_recorded_analysis(self):
        """Reenvio do mesmo Pix (timeout do cliente, retry da rede) não é Pix novo.

        Responde 200, não 201: nada foi criado agora. E devolve a MESMA
        análise, sem reavaliar.
        """
        payload = PayloadGenerator.create_pix_payload()

        status, first = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, second = RequestGenerator.POST_pix_transaction(payload)

        assert status == 200
        assert second == first

    def test_key_order_does_not_change_the_content(self):
        """Mesmo conteúdo com as chaves em outra ordem continua sendo o mesmo Pix."""
        payload = PayloadGenerator.create_pix_payload()

        status, first = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        reordered = dict(reversed(list(payload.items())))
        status, second = RequestGenerator.POST_pix_transaction(reordered)

        assert status == 200
        assert second == first

    def test_same_id_with_different_content_is_a_conflict(self):
        payload = PayloadGenerator.create_pix_payload()

        status, _response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        payload["amount"] = payload["amount"] + 1
        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 409
        assert response["code"] == "QIT001002"

    def test_mask_does_not_change_the_content(self):
        """O mesmo CNPJ com e sem máscara é o mesmo documento, e o mesmo Pix.

        O hash de idempotência é calculado sobre o payload normalizado: o
        cliente que reenvia formatando o documento de outro jeito recebe a
        análise gravada, não um 409.
        """
        payee_digits = "".join(character for character in RandomGenerator.generate_cnpj() if character.isdigit())
        payload = PayloadGenerator.create_pix_payload(payee_document=payee_digits)

        status, first = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        payload["destination_account"]["owner"]["document_number"] = (
            f"{payee_digits[0:2]}.{payee_digits[2:5]}.{payee_digits[5:8]}/{payee_digits[8:12]}-{payee_digits[12:14]}"
        )
        status, second = RequestGenerator.POST_pix_transaction(payload)

        assert status == 200
        assert second == first
