from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator, Scenario, reason_for, shift_date

# Os cenários que a bateria de realidade (scripts/realidade/) mostrou que o
# motor errava: golpes encenados passo a passo e o cliente legítimo que o
# motor travava sem motivo. Cada teste é um desses casos.

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


def client_with_history(amounts=None) -> dict:
    """Cliente com Pix aprovados, um por dia, do mesmo aparelho, para o mesmo destino (R$ 100 por padrão)."""
    if amounts is None:
        amounts = [10000] * 5

    client = {"payer_document": RandomGenerator.generate_cpf(), "device_id": new_device()}
    usual_payee = new_payee()
    Scenario.build_history(**client, **usual_payee, amounts=amounts, first_date=HISTORY_START)

    return {**client, "usual_payee": usual_payee}


def send(pix_id: str = None, **payload_overrides) -> dict:
    """Manda o Pix e devolve a resposta junto com o `id`, para o PATCH saber a quem responder."""
    if pix_id is None:
        pix_id = f"pix-{uuid4()}"

    return {"id": pix_id, **Scenario.send(pix_id=pix_id, **payload_overrides)}


def confirm(pix: dict, minutes: int = 2) -> dict:
    """O cliente passa no 2FA: o PATCH de retorno, `minutes` depois do Pix."""
    status, response = RequestGenerator.PATCH_pix_transaction(
        pix["id"],
        {
            "two_factor_result": "passed",
            "completed_at": shift_date(pix["transaction_date"], minutes=minutes),
        },
    )
    assert status == 200, response

    return response


def send_and_confirm_if_asked(**payload) -> dict:
    """O Pix e, se pediu 2FA, a confirmação do cliente."""
    pix = send(**payload)
    pix["transaction_date"] = payload["transaction_date"]
    if pix["status"] == "two_factor_required":
        confirm(pix)

    return pix


class TestRecurringDestinationNeedsRealHistory:
    def test_fake_investment_growing_amounts_asks_two_factor(self):
        """Item 2 — falso investimento: R$ 500, R$ 1.000, R$ 3.000 e R$ 8.000 ao mesmo destino em 8 dias.

        Antes, um único Pix aprovado já tornava o destino "recorrente" e
        desligava o PERFIL.valor: tudo saía `approved` sem aviso. Agora o
        destino só é recorrente com 2 ou mais Pix aprovados em dias
        diferentes e valor atual de no máximo 1,5x o maior já pago a ele.
        """
        client = client_with_history()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}
        investment = new_payee()

        responses = []
        for day, amount in [(0, 50000), (2, 100000), (5, 300000), (8, 800000)]:
            date = shift_date(DAY, days=day)
            pix = send(**origin, **investment, amount=amount, transaction_date=date)
            pix["transaction_date"] = date
            responses.append(pix)
            if pix["status"] == "two_factor_required":
                confirm(pix)

        for pix in responses[2:]:
            assert pix["status"] == "two_factor_required", pix["metadata"]
            assert pix["metadata"]["scam_warning"] is True

    def test_stable_monthly_bill_stays_approved(self):
        """Caso logo abaixo: o aluguel, mesmo valor todo mês para o mesmo destino, continua sem fricção."""
        client = client_with_history()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}
        landlord = new_payee()

        for month in range(4):
            pix = send(**origin, **landlord, amount=80000, transaction_date=shift_date(DAY, days=30 * month))
            assert pix["status"] == "approved", (month, pix["metadata"])


class TestOldCompanyIsNotAScam:
    TWELVE_YEARS_BEFORE = "2014-10-17T10:00:00-03:00"

    def _store(self, document: str) -> dict:
        return {
            "payee_document": document,
            "payee_account_number": RandomGenerator.generate_account_number(),
            "payee_opening_date": self.TWELVE_YEARS_BEFORE,
        }

    def test_black_friday_tv_at_an_old_store_is_approved_with_a_warning(self):
        """Item 8 — uma TV de R$ 3.500 na Black Friday, numa loja com CNPJ de 12 anos: aviso, nunca 2FA.

        Antes, o valor fora do perfil (35x a mediana) para um destino novo
        pedia 2FA com aviso de golpe, mesmo num lojista consolidado. Para
        recebedor PJ com conta de 1 ano ou mais, o PERFIL.valor no máximo
        aprova com aviso.
        """
        client = client_with_history()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}

        response = send(
            **origin, **self._store(RandomGenerator.generate_cnpj()), amount=350000, transaction_date=DAY
        )

        assert response["status"] == "approved", response["metadata"]
        assert response["metadata"]["recommended_action"] == "warn"
        assert reason_for(response, "PERFIL.valor")["typology"] == "app"

    def test_same_amount_to_a_person_account_still_asks_two_factor(self):
        """Caso logo abaixo: o mesmo valor para uma pessoa física (mesma idade de conta) segue pedindo 2FA com aviso."""
        client = client_with_history()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}

        response = send(
            **origin, **self._store(RandomGenerator.generate_cpf()), amount=350000, transaction_date=DAY
        )

        assert response["status"] == "two_factor_required", response["metadata"]
        assert response["metadata"]["scam_warning"] is True


class TestFanInNeedsMoneyAndFewerPayersForNewAccounts:
    TWELVE_DAYS_BEFORE = "2026-10-05T09:00:00-03:00"

    def _buyers(self, payee: dict, count: int, amount: int) -> list:
        """`count` pagadores diferentes, um por minuto, cada um de um aparelho novo."""
        return [
            send(**payee, amount=amount, transaction_date=shift_date(DAY, minutes=minute)) for minute in range(count)
        ]

    def test_graduation_raffle_is_not_a_mule_account(self):
        """Item 7 — a rifa da formatura: 8 amigos mandam R$ 20 a uma conta de 12 dias. Falso positivo antes (RECUSADA)."""
        organizer = {**new_payee(opening_date=self.TWELVE_DAYS_BEFORE)}

        responses = self._buyers(organizer, count=8, amount=2000)

        assert [response["status"] for response in responses] == ["approved"] * 8
        assert all(reason_for(response, "CONTA_RECEBEDORA.fan_in") is None for response in responses)

    def test_fake_sale_is_rejected_at_the_third_buyer(self):
        """A falsa venda: R$ 450 de cada comprador para uma conta de 12 dias. Antes, só travava na 5ª vítima."""
        seller = {**new_payee(opening_date=self.TWELVE_DAYS_BEFORE)}

        responses = self._buyers(seller, count=4, amount=45000)

        assert [response["status"] for response in responses[:2]] == ["approved", "approved"]
        assert responses[2]["status"] == "rejected", responses[2]["metadata"]
        assert responses[2]["metadata"]["typology"] == "mule_account"
        reason = reason_for(responses[2], "CONTA_RECEBEDORA.fan_in")
        assert reason["observed"]["distinct_payers"] == 3

    def test_old_account_still_needs_five_payers(self):
        """Caso logo abaixo: conta antiga recebendo de 3 pagadores, mesmo somando R$ 1.350, não pontua fan-in."""
        organizer = new_payee()

        responses = self._buyers(organizer, count=3, amount=45000)

        assert all(reason_for(response, "CONTA_RECEBEDORA.fan_in") is None for response in responses)


class TestBurstToNewDestinations:
    def _client(self) -> dict:
        """Cliente de R$ 500 por dia: R$ 800 não está fora do perfil (até 5x a mediana)."""
        client = client_with_history(amounts=[50000] * 5)

        return {"payer_document": client["payer_document"], "device_id": client["device_id"]}

    def test_ghost_hand_locks_at_the_third_pix(self):
        """Item 6 — a mão fantasma: acesso remoto, do aparelho de sempre, Pix de R$ 800 a destinos novos, um por minuto.

        Antes, 4 Pix e R$ 5.200 saíam antes de o motor pedir 2FA. Agora, 3 ou
        mais Pix para destinos novos distintos em 10 minutos, somando
        R$ 2.000 ou mais, pedem biometria (motivo: invasão de conta).
        """
        origin = self._client()

        responses = [
            send(**origin, amount=80000, transaction_date=shift_date(DAY, minutes=minute)) for minute in range(4)
        ]

        assert [response["status"] for response in responses[:2]] == ["approved", "approved"]
        third = responses[2]
        assert third["status"] == "two_factor_required", third["metadata"]
        assert third["metadata"]["step_up_reason"] == "account_takeover"
        assert third["metadata"]["step_up_method"] == "face_liveness"
        reason = reason_for(third, "RITMO.destinos_novos")
        assert reason["outcome"] == "two_factor"
        assert reason["observed"]["new_payees"] == 3

    def test_three_new_destinations_below_the_amount_do_not_lock(self):
        """Caso logo abaixo: 3 destinos novos somando R$ 1.500 (abaixo de R$ 2.000) passam."""
        origin = self._client()

        responses = [
            send(**origin, amount=50000, transaction_date=shift_date(DAY, minutes=minute)) for minute in range(3)
        ]

        assert [response["status"] for response in responses] == ["approved"] * 3

    def test_repeated_pix_to_the_same_new_destination_counts_once(self):
        """Três Pix a UM destino novo são um destino só: não é a rajada de destinos novos."""
        origin = self._client()
        payee = new_payee()

        responses = [
            send(**origin, **payee, amount=80000 + minute, transaction_date=shift_date(DAY, minutes=minute))
            for minute in range(3)
        ]

        for response in responses:
            assert reason_for(response, "RITMO.destinos_novos") is None


class TestStepUpMethodDependsOnContext:
    NIGHT = "2026-10-17T22:00:00-03:00"
    NINE_KM_FROM_HOME = {"latitude": -23.479, "longitude": -46.65}

    def _night_client(self) -> dict:
        """Cliente de R$ 600 por dia, que já fez um Pix noturno de R$ 600 de casa (R$ 600 de soma na noite)."""
        client = client_with_history(amounts=[60000] * 5)
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}

        first = send(**origin, **client["usual_payee"], amount=60000, transaction_date=self.NIGHT)
        assert first["status"] == "approved", first["metadata"]

        return {"origin": origin, "usual_payee": client["usual_payee"]}

    def test_stolen_unlocked_phone_far_from_home_asks_face_liveness(self):
        """Item 5 — o celular de sempre, desbloqueado, a 9 km de casa às 23h: a confirmação no app não prova nada.

        A confirmação no próprio celular não protege quando é o ladrão quem
        o segura (como na bateria: 3 Pix seguidos confirmados no app). Com o
        Pix a mais de 5 km de todos os locais aprovados, o 2FA é biometria.
        """
        client = self._night_client()

        second = send(
            **client["origin"],
            **client["usual_payee"],
            amount=60000,
            transaction_date=shift_date(self.NIGHT, hours=1),
            geolocation=self.NINE_KM_FROM_HOME,
        )

        assert second["status"] == "two_factor_required", second["metadata"]
        assert second["metadata"]["step_up_reason"] == "limit"
        assert second["metadata"]["step_up_method"] == "face_liveness"

    def test_same_night_pix_near_home_keeps_the_in_app_confirmation(self):
        """Caso logo abaixo: o mesmo Pix, de casa, do aparelho de sempre, pede só a confirmação no app."""
        client = self._night_client()

        second = send(
            **client["origin"], **client["usual_payee"], amount=60000, transaction_date=shift_date(self.NIGHT, hours=1)
        )

        assert second["status"] == "two_factor_required", second["metadata"]
        assert second["metadata"]["step_up_reason"] == "limit"
        assert second["metadata"]["step_up_method"] == "in_app_confirmation"

    def test_recent_failed_biometrics_asks_face_liveness_on_any_two_factor(self):
        """Biometria reprovada há menos de 24 h: o próximo 2FA, ainda que de limite, volta a ser biometria."""
        client = self._night_client()
        origin = client["origin"]

        takeover = send(payer_document=origin["payer_document"], amount=60000, transaction_date=shift_date(self.NIGHT, minutes=10))
        assert takeover["metadata"]["step_up_method"] == "face_liveness"
        takeover["transaction_date"] = shift_date(self.NIGHT, minutes=10)
        status, _ = RequestGenerator.PATCH_pix_transaction(
            takeover["id"],
            {"two_factor_result": "failed", "completed_at": shift_date(self.NIGHT, minutes=11)},
        )
        assert status == 200

        second = send(**origin, **client["usual_payee"], amount=60000, transaction_date=shift_date(self.NIGHT, hours=1))

        assert second["status"] == "two_factor_required", second["metadata"]
        assert second["metadata"]["step_up_method"] == "face_liveness"


class TestProfileForNewDestinations:
    def _client_with_rent_and_small_pix_to_new_payees(self) -> dict:
        """O aluguel de R$ 2.000 entra no perfil geral (P95 R$ 2.000), e o resto são Pix de R$ 100 para destinos novos."""
        origin = {"payer_document": RandomGenerator.generate_cpf(), "device_id": new_device()}
        Scenario.register_device(origin["payer_document"], origin["device_id"], HISTORY_START)

        landlord = new_payee()
        for month in range(4):
            rent = send(**origin, **landlord, amount=200000, transaction_date=shift_date(HISTORY_START, days=1 + month))
            assert rent["status"] == "approved", rent["metadata"]

        for index in range(19):
            small = send(**origin, amount=10000, transaction_date=shift_date(HISTORY_START, days=6, hours=index))
            assert small["status"] == "approved", small["metadata"]

        return {"origin": origin, "landlord": landlord}

    def test_fake_relative_to_a_new_account_is_not_excused_by_the_rent(self):
        """Item 4 — o falso parente: R$ 1.890 para um destino novo, e o aluguel de R$ 2.000 do perfil geral não o desculpa.

        Antes, o P95 do perfil misturava o aluguel (recorrente e alto) com o
        resto, e o motor aceitava R$ 2.000 para qualquer um. Para destino
        novo, o PERFIL.valor compara com o que o pagador já mandou para
        destinos novos.
        """
        client = self._client_with_rent_and_small_pix_to_new_payees()

        response = send(**client["origin"], **new_payee(), amount=189000, transaction_date=DAY)

        assert response["status"] == "two_factor_required", response["metadata"]
        assert response["metadata"]["scam_warning"] is True
        assert reason_for(response, "PERFIL.valor")["observed"]["basis"] == "new_payees"

    def test_the_rent_itself_is_still_within_the_general_profile(self):
        """Caso logo abaixo: o aluguel do mês seguinte, para o destino de sempre, continua aprovado."""
        client = self._client_with_rent_and_small_pix_to_new_payees()

        response = send(**client["origin"], **client["landlord"], amount=200000, transaction_date=DAY)

        assert response["status"] == "approved", response["metadata"]


class TestPriorSuspicionDoesNotPunishTheMonthlyBill:
    def _rent_first_month(self) -> dict:
        """Cliente com histórico paga R$ 2.000 de aluguel pela primeira vez: 2FA de golpe, e ele confirma."""
        client = client_with_history()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}
        landlord = new_payee()

        first = send(**origin, **landlord, amount=200000, transaction_date=DAY)
        assert first["status"] == "two_factor_required", first["metadata"]
        assert first["metadata"]["step_up_reason"] == "possible_scam"
        first["transaction_date"] = DAY
        confirm(first)

        return {"origin": origin, "landlord": landlord}

    def test_same_rent_a_month_later_is_approved(self):
        """Item 3 — o aluguel do mês 2, mesmo valor 30 dias depois, sai sem 2FA (antes, 46 dos 2FA dos clientes bons)."""
        rent = self._rent_first_month()

        second = send(**rent["origin"], **rent["landlord"], amount=200000, transaction_date=shift_date(DAY, days=30))

        assert second["status"] == "approved", second["metadata"]
        assert reason_for(second, "CONTA_RECEBEDORA.suspeita_anterior") is None
        assert reason_for(second, "PERFIL.valor") is None

    def test_rent_that_grew_still_asks_two_factor(self):
        """O mesmo destino 30 dias depois, mas com valor 50% maior: não é conta do mês, é valor crescente."""
        rent = self._rent_first_month()

        second = send(**rent["origin"], **rent["landlord"], amount=300000, transaction_date=shift_date(DAY, days=30))

        assert second["status"] == "two_factor_required", second["metadata"]
        assert second["metadata"]["scam_warning"] is True

    def test_same_amount_after_a_short_interval_still_asks_two_factor(self):
        """O mesmo valor para o mesmo destino 10 dias depois: intervalo curto, a suspeita continua valendo."""
        rent = self._rent_first_month()

        second = send(**rent["origin"], **rent["landlord"], amount=200000, transaction_date=shift_date(DAY, days=10))

        assert second["status"] == "two_factor_required", second["metadata"]
        assert second["metadata"]["scam_warning"] is True


class TestConfirmedScamDoesNotTeachTheProfile:
    def test_third_fake_call_center_pix_still_asks_two_factor(self):
        """Item 1 — a vítima da falsa central confirma R$ 4.800 e R$ 4.500; o 3º Pix, de R$ 3.900, não pode passar.

        Antes, os dois Pix confirmados entravam no perfil e levavam o P95 e a
        mediana para cima: o terceiro saía `approved` sem sinal nenhum. O golpe
        "educava" o perfil. Agora o Pix confirmado sob aviso de golpe conta só
        para a soma noturna e os tetos diários.
        """
        client = client_with_history()
        origin = {"payer_document": client["payer_document"], "device_id": client["device_id"]}
        fraudster = new_payee(opening_date="2026-10-02T10:00:00-03:00")

        for day, amount in enumerate([480000, 450000]):
            pix = send(**origin, **fraudster, amount=amount, transaction_date=shift_date(DAY, days=day))
            assert pix["status"] == "two_factor_required", pix["metadata"]
            assert pix["metadata"]["scam_warning"] is True
            pix["transaction_date"] = shift_date(DAY, days=day)
            confirm(pix)

        third = send(**origin, **fraudster, amount=390000, transaction_date=shift_date(DAY, days=2))

        assert third["status"] == "two_factor_required", third["metadata"]
        assert third["metadata"]["scam_warning"] is True
        assert reason_for(third, "PERFIL.valor") is not None
