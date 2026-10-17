import re

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator


UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DECISIONS = ("approved", "two_factor_required", "rejected")


class TestPixTransactionCreate:
    def test_creates_analysis_with_only_the_three_contract_fields(self):
        """O slide define a saída em três campos, e o DTO é o único que a monta.

        Um campo a mais aqui (o `id` interno, por exemplo) é vazamento:
        o que o DTO monta é exatamente o que sai.
        """
        payload = PayloadGenerator.create_pix_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert set(response.keys()) == {"key", "status", "metadata"}
        assert UUID_PATTERN.match(response["key"])
        assert response["status"] in DECISIONS
        assert isinstance(response["metadata"], dict)

    def test_routine_pix_is_approved(self):
        """R$ 150, à tarde, para uma conta antiga: o Pix do dia a dia passa."""
        payload = PayloadGenerator.create_pix_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert response["status"] == "approved"
        assert response["metadata"]["policy_version"] == "2026.10.1"

    def test_geolocation_is_optional(self):
        payload = PayloadGenerator.create_pix_payload(with_geolocation=False)

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201

    def test_accepts_documents_with_and_without_mask(self):
        """O slide manda CPF com máscara; quem integra pode mandar só os dígitos.

        Os dois formatos são o mesmo documento: o motor normaliza para
        dígitos antes de qualquer regra, senão o mesmo pagador viraria
        duas pessoas no histórico.
        """
        payer_digits = re.sub(r"\D", "", RandomGenerator.generate_cpf())
        payee_digits = re.sub(r"\D", "", RandomGenerator.generate_cnpj())

        payload = PayloadGenerator.create_pix_payload(payer_document=payer_digits, payee_document=payee_digits)

        status, _response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201

    def test_accepts_company_payee(self):
        payload = PayloadGenerator.create_pix_payload(payee_document=RandomGenerator.generate_cnpj())

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert response["status"] == "approved"


class TestPixTransactionCreateSchema:
    """Formato errado é 400 na porta, antes de qualquer regra."""

    def test_refuses_empty_body(self):
        status, response = RequestGenerator.POST_pix_transaction({})

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_refuses_unknown_field_at_any_depth(self):
        """Campo a mais é erro, não campo ignorado — no topo e nos objetos de dentro.

        O `additionalProperties: false` precisa estar em CADA objeto do
        schema: no topo ele não enxerga o que está dentro de `source`.
        """
        locations = [
            (),
            ("source_account",),
            ("source_account", "owner"),
            ("destination_account",),
            ("source",),
            ("source", "geolocation"),
        ]

        for location in locations:
            payload = PayloadGenerator.create_pix_payload()

            target = payload
            for key in location:
                target = target[key]
            target["campo_que_nao_existe"] = 1

            status, response = RequestGenerator.POST_pix_transaction(payload)

            assert status == 400, f"campo a mais aceito em {'.'.join(location) or 'raiz'}"
            assert response["code"] == "QIT000001"

    def test_refuses_missing_required_fields(self):
        required_paths = [
            ("id",),
            ("amount",),
            ("transaction_date",),
            ("source_account", "opening_date"),
            ("source_account", "owner"),
            ("destination_account", "participant"),
            ("destination_account", "owner", "document_number"),
            ("source", "device_id"),
            ("source", "channel"),
            ("source", "ip"),
        ]

        for path in required_paths:
            payload = PayloadGenerator.create_pix_payload()

            target = payload
            for key in path[:-1]:
                target = target[key]
            del target[path[-1]]

            status, response = RequestGenerator.POST_pix_transaction(payload)

            assert status == 400, f"aceitou o Pix sem {'.'.join(path)}"
            assert response["code"] == "QIT000001"

    def test_refuses_malformed_values(self):
        """Cada linha derruba UM campo e mantém os outros certos.

        Assim, quando o teste fica vermelho, a mensagem diz qual formato
        deixou de ser cobrado.
        """
        malformed_values = [
            (("amount",), 0),
            (("amount",), -100),
            (("amount",), "150.00"),
            (("amount",), 150.5),
            (("transaction_date",), "2026-10-17T22:15:00"),
            (("transaction_date",), "17/10/2026 22:15"),
            (("source_account", "owner", "document_number"), "123456789"),
            (("destination_account", "owner", "document_number"), "abc.def.ghi-jk"),
            (("destination_account", "participant"), "6070119"),
            (("source", "ip"), "não é ip"),
            (("source", "geolocation"), {"latitude": -95, "longitude": -46.65}),
            (("source", "geolocation"), {"latitude": -23.56}),
            (("id",), ""),
        ]

        for path, value in malformed_values:
            payload = PayloadGenerator.create_pix_payload()

            target = payload
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value

            status, response = RequestGenerator.POST_pix_transaction(payload)

            assert status == 400, f"o campo '{'.'.join(path)}' aceitou {value!r}"
            assert response["code"] == "QIT000001"


class TestPixTransactionCreateUnprocessable:
    """Formato certo, valor impossível: 422, nunca 400 nem 500."""

    def test_refuses_invalid_cpf_check_digits(self):
        for side in ("source_account", "destination_account"):
            payload = PayloadGenerator.create_pix_payload()
            payload[side]["owner"]["document_number"] = "111.222.333-44"

            status, response = RequestGenerator.POST_pix_transaction(payload)

            assert status == 422, f"aceitou CPF inválido em {side}"
            assert response["code"] == "QIT001003"

    def test_refuses_invalid_cnpj_check_digits(self):
        payload = PayloadGenerator.create_pix_payload(payee_document="11.222.333/0001-99")

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT001003"

    def test_refuses_impossible_dates(self):
        """O `pattern` conta dígitos; ele não sabe que fevereiro não tem dia 30."""
        for field_path in [("transaction_date",), ("destination_account", "opening_date")]:
            payload = PayloadGenerator.create_pix_payload()

            target = payload
            for key in field_path[:-1]:
                target = target[key]
            target[field_path[-1]] = "2026-02-30T10:00:00-03:00"

            status, response = RequestGenerator.POST_pix_transaction(payload)

            assert status == 422, f"aceitou data impossível em {'.'.join(field_path)}"
            assert response["code"] == "QIT001004"


class TestPixTransactionCreateToken:
    def test_refuses_without_internal_token(self):
        payload = PayloadGenerator.create_pix_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload, headers={})

        assert status == 403
        assert response["code"] == "QIT000002"

    def test_refuses_with_wrong_internal_token(self):
        payload = PayloadGenerator.create_pix_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload, headers={"INTERNAL-TOKEN": "errado"})

        assert status == 403
        assert response["code"] == "QIT000002"
