from uuid import uuid4

from tests.utils import RandomGenerator, Scenario, not_needed_signals, reason_for, shift_date

DAY = "2026-10-17T14:00:00-03:00"
NIGHT = "2026-10-17T22:15:00-03:00"


def new_device() -> str:
    return f"dvc-{uuid4().hex[:12]}"


class TestRuleLimiteAparelhoNaoCadastrado:
    """Regra 2 — LIMITE.aparelho_nao_cadastrado.

    Desde nov/2024 o BCB limita aparelho que nunca fez Pix para o usuário
    a R$ 200 por Pix e R$ 1.000 por dia, e o cadastro exige 2FA. Aqui o
    2FA É o cadastro: depois do primeiro Pix aprovado, o aparelho vira
    conhecido.
    """

    # Conta pagadora recente: com conta antiga, o primeiro Pix de um cliente
    # que o motor não conhece vai para o limite de partida (classe abaixo).
    RECENT_ACCOUNT = "2026-08-01T10:00:00-03:00"

    def test_new_device_above_200_requires_two_factor(self):
        response = Scenario.send(payer_opening_date=self.RECENT_ACCOUNT, amount=20001, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["recommended_action"] == "step_up"
        assert reason_for(response, "LIMITE.aparelho_nao_cadastrado")["outcome"] == "two_factor"

    def test_new_device_at_exactly_200_is_approved(self):
        response = Scenario.send(payer_opening_date=self.RECENT_ACCOUNT, amount=20000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert reason_for(response, "LIMITE.aparelho_nao_cadastrado") is None

    def test_known_device_has_no_200_limit(self):
        payer = RandomGenerator.generate_cpf()
        device = new_device()
        Scenario.register_device(payer, device, shift_date(DAY, days=-1))

        response = Scenario.send(payer_document=payer, device_id=device, amount=50000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert reason_for(response, "LIMITE.aparelho_nao_cadastrado") is None

    def test_daily_limit_adds_up_across_unregistered_devices(self):
        """Cinco aparelhos novos de R$ 200 somam R$ 1.000 no dia: o próximo centavo pede 2FA.

        Cada aparelho, sozinho, respeita os R$ 200. O teto diário existe
        justamente para quem troca de aparelho para fracionar. Os Pix ficam
        a 61 minutos um do outro: em menos de uma hora, o terceiro de
        R$ 200 já pediria 2FA pelo RITMO.fracionamento, e o teste deixaria
        de olhar o teto diário.
        """
        payer = RandomGenerator.generate_cpf()

        for index in range(5):
            response = Scenario.send(
                payer_document=payer,
                amount=20000,
                transaction_date=shift_date(DAY, minutes=61 * index),
            )
            assert response["status"] == "approved", f"o aparelho {index + 1} já pediu 2FA"

        response = Scenario.send(payer_document=payer, amount=1, transaction_date=shift_date(DAY, minutes=61 * 5))

        assert response["status"] == "two_factor_required"
        reason = reason_for(response, "LIMITE.aparelho_nao_cadastrado")
        assert reason["observed"]["day_amount"] == 100001


class TestRuleLimiteConfiancaDoAparelho:
    """Aparelho confiável: 2 ou mais Pix aprovados do pagador, o primeiro há pelo menos 24 h.

    Fecha a brecha do Pix pequeno: sem isso, um Pix de R$ 10 aprovado
    tornava o aparelho do ladrão "conhecido", e o Pix seguinte, de
    R$ 5.000, não pedia 2FA nenhum.

    Os pagadores daqui têm conta de menos de 180 dias: com conta antiga e
    sem aparelho confiável, estariam no período de aprendizado (limite de
    partida de R$ 1.000), e o teste deixaria de olhar os R$ 200.
    """

    RECENT_ACCOUNT = "2026-06-01T10:00:00-03:00"

    def _two_pix(self, payer: str, device: str, first_date: str, second_date: str) -> None:
        for transaction_date in (first_date, second_date):
            response = Scenario.send(
                payer_document=payer,
                device_id=device,
                payer_opening_date=self.RECENT_ACCOUNT,
                amount=1000,
                transaction_date=transaction_date,
            )
            assert response["status"] == "approved", response

    def test_one_small_pix_does_not_make_the_device_trusted(self):
        payer = RandomGenerator.generate_cpf()
        device = new_device()
        Scenario.send(
            payer_document=payer, device_id=device, payer_opening_date=self.RECENT_ACCOUNT, amount=1000, transaction_date=DAY
        )

        response = Scenario.send(
            payer_document=payer,
            device_id=device,
            payer_opening_date=self.RECENT_ACCOUNT,
            amount=30000,
            transaction_date=shift_date(DAY, minutes=3),
        )

        assert response["status"] == "two_factor_required"
        assert reason_for(response, "LIMITE.aparelho_nao_cadastrado")["outcome"] == "two_factor"

    def test_first_approved_pix_less_than_24h_ago_is_not_enough(self):
        payer = RandomGenerator.generate_cpf()
        device = new_device()
        self._two_pix(payer, device, shift_date(DAY, hours=-23, minutes=-59), shift_date(DAY, hours=-1))

        response = Scenario.send(
            payer_document=payer, device_id=device, payer_opening_date=self.RECENT_ACCOUNT, amount=30000, transaction_date=DAY
        )

        assert response["status"] == "two_factor_required"

    def test_two_approved_pix_with_the_first_24h_ago_make_it_trusted(self):
        payer = RandomGenerator.generate_cpf()
        device = new_device()
        self._two_pix(payer, device, shift_date(DAY, hours=-24), shift_date(DAY, hours=-1))

        response = Scenario.send(payer_document=payer, device_id=device, amount=30000, transaction_date=DAY)

        assert response["status"] == "approved"
        assert reason_for(response, "LIMITE.aparelho_nao_cadastrado") is None

    def test_daily_limit_adds_every_pix_from_an_untrusted_device(self):
        """Cinco Pix de R$ 180 do mesmo aparelho novo somam R$ 900; o sexto passa de R$ 1.000.

        Cada um respeita os R$ 200 por Pix, e o aparelho não vira confiável
        no meio do dia: todos contam no teto diário. A 61 minutos um do
        outro, para o RITMO.fracionamento não pedir 2FA antes (R$ 180 é 90%
        de R$ 200).
        """
        payer = RandomGenerator.generate_cpf()
        device = new_device()

        for index in range(5):
            response = Scenario.send(
                payer_document=payer, device_id=device, amount=18000, transaction_date=shift_date(DAY, minutes=61 * index)
            )
            assert response["status"] == "approved", f"o Pix {index + 1} já pediu 2FA"

        response = Scenario.send(
            payer_document=payer, device_id=device, amount=18000, transaction_date=shift_date(DAY, minutes=61 * 5)
        )

        assert response["status"] == "two_factor_required"
        assert reason_for(response, "LIMITE.aparelho_nao_cadastrado")["observed"]["day_amount"] == 108000


class TestRuleLimiteClienteDesconhecido:
    """Cliente que o motor ainda não conhece: o período de aprendizado.

    Na avaliação o banco nasce vazio, e todo cliente chega num aparelho
    "novo". Enquanto o pagador não tem nenhum aparelho confiável, e se a
    conta pagadora tem 180 dias ou mais, o limite por Pix do aparelho é o
    limite de partida do perfil (R$ 1.000), e não os R$ 200 — sempre
    dentro do teto do BCB de R$ 1.000 por dia em aparelhos não
    confiáveis. Em produção o motor nasceria com a carga do histórico.
    Conta pagadora recente segue a regra normal de aparelho não confiável.
    """

    OLD_ACCOUNT = "2025-03-02T10:00:00-03:00"
    EXACTLY_180_DAYS = "2026-04-20T14:00:00-03:00"
    ONLY_179_DAYS = "2026-04-21T14:00:00-03:00"

    def test_up_to_the_starting_limit_the_device_is_not_evaluated(self):
        response = Scenario.send(payer_opening_date=self.OLD_ACCOUNT, amount=100000, transaction_date=DAY)

        assert response["status"] == "approved"
        not_evaluated = {item["signal"]: item["reason"] for item in response["metadata"]["not_evaluated"]}
        assert "ainda não tem histórico deste pagador" in not_evaluated["LIMITE.aparelho_nao_cadastrado"]

    def test_above_the_starting_limit_requires_two_factor(self):
        response = Scenario.send(payer_opening_date=self.OLD_ACCOUNT, amount=100001, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        reason = reason_for(response, "LIMITE.aparelho_nao_cadastrado")
        assert reason["outcome"] == "two_factor"
        assert reason["threshold"]["fallback_amount"] == 100000

    def test_payer_account_with_exactly_180_days_counts_as_old(self):
        response = Scenario.send(payer_opening_date=self.EXACTLY_180_DAYS, amount=30000, transaction_date=DAY)

        assert response["status"] == "approved"

    def test_payer_account_with_179_days_follows_the_normal_device_rule(self):
        response = Scenario.send(payer_opening_date=self.ONLY_179_DAYS, amount=30000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert reason_for(response, "LIMITE.aparelho_nao_cadastrado")["outcome"] == "two_factor"

    def test_learning_period_lasts_while_no_device_is_trusted(self):
        """R$ 300 aprovado; R$ 800 dez minutos depois passa do teto diário (2FA); R$ 300 no dia seguinte, aprovado.

        O alívio não acaba no primeiro Pix: dura enquanto o aparelho do
        pagador não é confiável. O que o limita é o teto do BCB de R$ 1.000
        por dia em aparelhos não confiáveis.
        """
        context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": new_device()}

        first = Scenario.send(**context, amount=30000, transaction_date=DAY)
        second = Scenario.send(**context, amount=80000, transaction_date=shift_date(DAY, minutes=10))
        third = Scenario.send(**context, amount=30000, transaction_date=shift_date(DAY, days=1))

        assert first["status"] == "approved"
        assert second["status"] == "two_factor_required"
        second_reason = reason_for(second, "LIMITE.aparelho_nao_cadastrado")
        assert second_reason["outcome"] == "two_factor"
        assert second_reason["observed"]["day_amount"] == 110000
        assert third["status"] == "approved"

    def test_learning_period_ends_once_the_payer_has_a_trusted_device(self):
        """Cliente com aparelho confiável: um aparelho novo volta aos R$ 200 — é o celular roubado."""
        payer = RandomGenerator.generate_cpf()
        Scenario.register_device(payer, new_device(), shift_date(DAY, hours=-1))

        response = Scenario.send(payer_document=payer, device_id=new_device(), amount=30000, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        reason = reason_for(response, "LIMITE.aparelho_nao_cadastrado")
        assert reason["threshold"]["max_amount_per_pix"] == 20000


class TestRuleLimiteNoturno:
    """Regra 2 — LIMITE.noturno.

    A Res. BCB 142 fixa R$ 1.000 entre 20h e 6h, PF para PF. O motor não
    recebe o limite que o cliente configurou, então isto é SINAL, não
    teto: passa se o valor cabe no maior Pix noturno que esse pagador já
    teve aprovado; fora disso, 2FA.
    """

    def _payer_with_known_device_and_recurrent_payee(self) -> dict:
        """Pagador com aparelho confiável que já pagou este destino de dia.

        O destino recorrente isola o sinal noturno: sem ele, um valor
        acima de R$ 1.000 também dispararia o sinal de perfil.
        """
        context = {
            "payer_document": RandomGenerator.generate_cpf(),
            "device_id": new_device(),
            "payee_document": RandomGenerator.generate_cpf(),
            "payee_account_number": RandomGenerator.generate_account_number(),
        }
        Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, days=-2))
        Scenario.send(**context, amount=10000, transaction_date=shift_date(DAY, days=-1))

        return context

    def test_night_pix_above_1000_requires_two_factor(self):
        context = self._payer_with_known_device_and_recurrent_payee()

        response = Scenario.send(**context, amount=100001, transaction_date=NIGHT)

        assert response["status"] == "two_factor_required"
        reason = reason_for(response, "LIMITE.noturno")
        assert reason["outcome"] == "two_factor"
        assert reason["observed"]["night_amount"] == 100001

    def test_night_pix_at_exactly_1000_is_approved(self):
        context = self._payer_with_known_device_and_recurrent_payee()

        response = Scenario.send(**context, amount=100000, transaction_date=NIGHT)

        assert response["status"] == "approved"
        assert reason_for(response, "LIMITE.noturno") is None

    def test_night_amount_adds_up_within_the_same_night(self):
        """R$ 600 às 22h15 e R$ 600 às 23h15: a segunda passa do teto somado."""
        context = self._payer_with_known_device_and_recurrent_payee()

        first = Scenario.send(**context, amount=60000, transaction_date=NIGHT)
        assert first["status"] == "approved"

        second = Scenario.send(**context, amount=60000, transaction_date=shift_date(NIGHT, hours=1))

        assert second["status"] == "two_factor_required"
        assert reason_for(second, "LIMITE.noturno")["observed"]["night_amount"] == 120000

    def test_within_the_largest_night_pix_already_approved(self):
        """Quem já teve aprovado um Pix noturno de R$ 3.000 aumentou o próprio limite.

        O Pix de R$ 3.000 vai para um lojista (PJ), onde o teto PF→PF não
        vale. Depois dele, um Pix PF→PF de R$ 2.000 cabe no histórico
        noturno do pagador e passa.
        """
        context = self._payer_with_known_device_and_recurrent_payee()

        store = Scenario.send(
            payer_document=context["payer_document"],
            device_id=context["device_id"],
            payee_document=RandomGenerator.generate_cnpj(),
            amount=300000,
            transaction_date=shift_date(NIGHT, days=-1),
        )
        assert store["status"] == "approved"

        response = Scenario.send(**context, amount=200000, transaction_date=NIGHT)

        assert response["status"] == "approved"
        assert reason_for(response, "LIMITE.noturno") is None

    def test_daytime_pix_is_not_a_night_pix(self):
        context = self._payer_with_known_device_and_recurrent_payee()

        response = Scenario.send(**context, amount=150000, transaction_date=DAY)

        assert reason_for(response, "LIMITE.noturno") is None

    def test_company_payee_is_outside_the_night_rule(self):
        context = self._payer_with_known_device_and_recurrent_payee()
        context["payee_document"] = RandomGenerator.generate_cnpj()

        response = Scenario.send(**context, amount=100001, transaction_date=NIGHT)

        assert reason_for(response, "LIMITE.noturno") is None
        assert "LIMITE.noturno" in not_needed_signals(response)

    def test_same_ownership_is_outside_the_night_rule(self):
        """Mover o próprio dinheiro de madrugada não é Pix entre pessoas distintas."""
        context = self._payer_with_known_device_and_recurrent_payee()
        context["payee_document"] = context["payer_document"]
        context["payee_account_number"] = RandomGenerator.generate_account_number()

        response = Scenario.send(**context, amount=500000, transaction_date=NIGHT)

        assert response["status"] == "approved"
        assert "LIMITE.noturno" in not_needed_signals(response)


def known_device() -> dict:
    """Pagador com aparelho confiável (2 Pix aprovados, o primeiro há 24 h)."""
    context = {"payer_document": RandomGenerator.generate_cpf(), "device_id": new_device()}
    Scenario.register_device(context["payer_document"], context["device_id"], shift_date(DAY, hours=-1))

    return context


class TestRuleLimiteSemGeolocalizacao:
    """Regra 2 — LIMITE.sem_geolocalizacao: limite menor com a geolocalização desligada.

    A IN BCB 669 permite um limite reduzido quando o app não manda a
    geolocalização. Acima de R$ 500 (estimativa) sem ela, 2FA de limite:
    confirmação no app, sem tipologia de fraude.
    """

    def test_above_the_reduced_limit_without_geolocation_requires_limit_two_factor(self):
        context = known_device()

        response = Scenario.send(**context, amount=50001, with_geolocation=False, transaction_date=DAY)

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["step_up_reason"] == "limit"
        assert response["metadata"]["step_up_method"] == "in_app_confirmation"
        assert reason_for(response, "LIMITE.sem_geolocalizacao")["outcome"] == "two_factor"

    def test_at_the_reduced_limit_without_geolocation_passes(self):
        context = known_device()

        response = Scenario.send(**context, amount=50000, with_geolocation=False, transaction_date=DAY)

        assert reason_for(response, "LIMITE.sem_geolocalizacao") is None
        assert "LIMITE.sem_geolocalizacao" in response["metadata"]["passed"]

    def test_with_geolocation_the_reduced_limit_does_not_apply(self):
        context = known_device()

        response = Scenario.send(**context, amount=50001, transaction_date=DAY)

        assert reason_for(response, "LIMITE.sem_geolocalizacao") is None
