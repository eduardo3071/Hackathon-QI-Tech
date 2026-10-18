"""O mundo simulado: clientes com hábitos próprios e os cenários de fraude.

Tudo sai de UMA semente: a mesma semente gera os mesmos clientes, os
mesmos Pix, nas mesmas datas. O período (maio e junho de 2026) não cruza
com as datas fixas dos testes (agosto a outubro), para o simulador e a
suíte poderem dividir o mesmo banco sem um contaminar as janelas do outro.

Visibilidade: o motor só vê Pix de clientes da QI Tech. Cada crédito que
uma conta recebe "de fora" (salário, vítimas de outros bancos) só vira um
Pix enviado à API com 30% de chance; os outros 70% acontecem num mundo que
o motor não vê.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

BRT = ZoneInfo("America/Sao_Paulo")
START = datetime(2026, 5, 1, tzinfo=BRT)
DAYS = 45
FRAUD_START = datetime(2026, 6, 1, tzinfo=BRT)

VISIBLE_CREDIT_SHARE = 0.30
QI_ISPB = "32402502"
OTHER_ISPBS = ["60701190", "18236120", "00000000", "00360305", "60746948"]

CITIES = [
    ("São Paulo", -23.55, -46.63),
    ("Rio de Janeiro", -22.91, -43.17),
    ("Belo Horizonte", -19.92, -43.94),
    ("Curitiba", -25.43, -49.27),
    ("Porto Alegre", -30.03, -51.23),
    ("Salvador", -12.97, -38.50),
    ("Recife", -8.05, -34.88),
    ("Fortaleza", -3.73, -38.52),
    ("Brasília", -15.79, -47.88),
    ("Manaus", -3.12, -60.02),
]


def _check_digit(digits: List[int], weights: List[int]) -> int:
    remainder = sum(d * w for d, w in zip(digits, weights)) % 11
    return 0 if remainder < 2 else 11 - remainder


def make_cpf(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(9)]
    digits.append(_check_digit(digits, list(range(10, 1, -1))))
    digits.append(_check_digit(digits, list(range(11, 1, -1))))
    return "".join(map(str, digits))


def make_cnpj(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    digits.append(_check_digit(digits, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    digits.append(_check_digit(digits, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    return "".join(map(str, digits))


@dataclass
class Account:
    """Uma conta de destino: documento, banco, número e abertura."""

    document: str
    ispb: str
    number: str
    opening_date: datetime


@dataclass
class Client:
    """Um cliente da QI Tech com hábitos próprios."""

    index: int
    document: str
    opening_date: datetime
    device_id: str
    ip_pool: List[str]
    home: tuple
    typical_amount: int
    daily_rate: float
    channels: List[str]
    shares_location: bool
    night_owl: bool
    recurring: List[Account]
    account: Account
    landlord: Optional[Account] = None
    rent: int = 0
    salary_employer: Optional[str] = None
    salary: int = 0
    travel: Optional[tuple] = None  # (dia de partida, dias, cidade)
    new_phone_day: Optional[int] = None
    new_device_id: Optional[str] = None


@dataclass(order=True)
class Event:
    """Um Pix a mandar. `two_factor` diz como o 2FA termina, se a API pedir: passed, failed ou None."""

    at: datetime
    seq: int
    scenario: str = field(compare=False)
    sub: str = field(compare=False)
    payer: str = field(compare=False)
    payer_opening: datetime = field(compare=False)
    payee: Account = field(compare=False)
    amount: int = field(compare=False)
    device_id: str = field(compare=False)
    ip: str = field(compare=False)
    channel: str = field(compare=False)
    location: Optional[tuple] = field(compare=False)
    two_factor: Optional[str] = field(compare=False)


class World:
    def __init__(self, seed: int, clients: int) -> None:
        self.rng = random.Random(seed)
        self.seq = 0
        self.events: List[Event] = []
        self.mobile_ips = [f"100.{64 + self.rng.randint(0, 63)}.{self.rng.randint(0, 255)}.{self.rng.randint(1, 254)}" for _ in range(clients)]
        self.merchants = [self._account(cnpj=True, days_old=self.rng.randint(400, 4000)) for _ in range(60)]
        # Poucas empresas pagam o salário de muitos clientes, do mesmo aparelho.
        self.employers = [make_cnpj(self.rng) for _ in range(8)]
        self.clients = [self._client(index) for index in range(clients)]

    # ── peças ────────────────────────────────────────────────────────

    def _account(self, cnpj: bool = False, days_old: int = None, document: str = None, ispb: str = None) -> Account:
        rng = self.rng
        if document is None:
            document = make_cnpj(rng) if cnpj else make_cpf(rng)
        if days_old is None:
            days_old = rng.randint(200, 5000)
        return Account(
            document=document,
            ispb=ispb or rng.choice(OTHER_ISPBS),
            number=str(rng.randint(10000, 9999999)),
            opening_date=START - timedelta(days=days_old),
        )

    def _client(self, index: int) -> Client:
        rng = self.rng
        city = rng.choice(CITIES)
        home = (city[1] + rng.uniform(-0.03, 0.03), city[2] + rng.uniform(-0.03, 0.03))
        document = make_cpf(rng)
        typical = int(math.exp(rng.uniform(math.log(3000), math.log(40000))))
        client = Client(
            index=index,
            document=document,
            opening_date=START - timedelta(days=rng.randint(200, 3000)),
            device_id=f"sim-dvc-{index:04d}",
            ip_pool=[rng.choice(self.mobile_ips) for _ in range(2)],
            home=home,
            typical_amount=typical,
            daily_rate=rng.uniform(0.2, 1.1),
            channels=["app"] if rng.random() < 0.85 else ["app", "internet_banking"],
            shares_location=rng.random() < 0.9,
            night_owl=rng.random() < 0.2,
            recurring=[self._account(days_old=rng.randint(60, 4000)) for _ in range(rng.randint(3, 6))],
            account=Account(document=document, ispb=QI_ISPB, number=document[:9], opening_date=START - timedelta(days=900)),
        )
        if rng.random() < 0.4:
            client.landlord = self._account()
            client.rent = rng.randint(80000, 300000)
        if rng.random() < 0.6:
            client.salary_employer = rng.choice(self.employers)
            client.salary = rng.randint(200000, 900000)
        if rng.random() < 0.15:
            client.travel = (rng.randint(5, 28), rng.randint(3, 5), rng.choice([c for c in CITIES if c[0] != city[0]]))
        if rng.random() < 0.06:
            client.new_phone_day = rng.randint(10, 40)
            client.new_device_id = f"sim-dvc-{index:04d}-novo"
        return client

    def _jitter(self, point: tuple, km: float = 2.0) -> tuple:
        delta = km / 111.0
        return (round(point[0] + self.rng.uniform(-delta, delta), 6), round(point[1] + self.rng.uniform(-delta, delta), 6))

    def _add(self, scenario, sub, at, payer, payer_opening, payee, amount, device_id, ip, channel, location, two_factor):
        self.seq += 1
        self.events.append(
            Event(at, self.seq, scenario, sub, payer, payer_opening, payee, max(1, int(amount)), device_id, ip, channel, location, two_factor)
        )

    def _client_context(self, client: Client, day: int, at: datetime):
        device = client.device_id
        if client.new_phone_day is not None and day >= client.new_phone_day:
            device = client.new_device_id
        location = None
        if client.shares_location:
            location = self._jitter(client.home)
            if client.travel and client.travel[0] <= day < client.travel[0] + client.travel[1]:
                location = self._jitter((client.travel[2][1], client.travel[2][2]))
        return device, self.rng.choice(client.ip_pool), self.rng.choice(client.channels), location

    def _legit(self, client: Client, sub: str, at: datetime, payee: Account, amount: int):
        day = (at - START).days
        device, ip, channel, location = self._client_context(client, day, at)
        if client.travel and client.travel[0] <= day < client.travel[0] + client.travel[1]:
            sub = "viagem"
        if client.new_phone_day is not None and day == client.new_phone_day:
            sub = "celular_novo"
        self._add("legit", sub, at, client.document, client.opening_date, payee, amount, device, ip, channel, location, "passed")

    def _hour(self, client: Client) -> int:
        if client.night_owl and self.rng.random() < 0.3:
            return self.rng.randint(20, 23)
        return self.rng.randint(8, 19)

    def _at(self, day: int, hour: int) -> datetime:
        return START + timedelta(days=day, hours=hour, minutes=self.rng.randint(0, 59), seconds=self.rng.randint(0, 59))

    # ── clientes legítimos ───────────────────────────────────────────

    def build_legit(self) -> None:
        rng = self.rng
        for client in self.clients:
            for day in range(DAYS):
                date = START + timedelta(days=day)
                # Salário no dia 1, vindo de uma empresa: só 30% dos créditos
                # de fora são visíveis ao motor.
                if client.salary_employer and date.day == 1 and rng.random() < VISIBLE_CREDIT_SHARE:
                    self._add(
                        "legit", "salario", date + timedelta(hours=7, minutes=rng.randint(0, 59)), client.salary_employer,
                        START - timedelta(days=4000), client.account, client.salary,
                        f"sim-dvc-rh-{client.salary_employer[:6]}", "200.155.10.1", "internet_banking", None, "passed",
                    )
                if client.landlord and date.day == 5:
                    self._legit(client, "aluguel", date + timedelta(hours=10, minutes=rng.randint(0, 50)), client.landlord, client.rent)

                for _ in range(self._poisson(client.daily_rate)):
                    at = self._at(day, self._hour(client))
                    choice = rng.random()
                    if choice < 0.65:
                        payee, sub = rng.choice(client.recurring), "rotina"
                        amount = client.typical_amount * math.exp(rng.gauss(0, 0.5))
                    elif choice < 0.85:
                        payee, sub = rng.choice(self.merchants), "lojista"
                        amount = client.typical_amount * math.exp(rng.gauss(-0.3, 0.6))
                    else:
                        # Um destino novo: amigo, prestador. Às vezes com conta recente.
                        days_old = rng.randint(3, 25) if rng.random() < 0.1 else None
                        payee, sub = self._account(days_old=days_old), "destino_novo"
                        amount = client.typical_amount * math.exp(rng.gauss(0, 0.7))
                    self._legit(client, sub, at, payee, amount)

            # Racha da conta do bar: uma ou duas vezes, de 3 a 6 Pix pequenos em minutos.
            for _ in range(rng.randint(0, 2)):
                day = rng.randint(1, DAYS - 1)
                at = START + timedelta(days=day, hours=22, minutes=rng.randint(0, 40))
                for friend in range(rng.randint(3, 6)):
                    payee = rng.choice(client.recurring) if rng.random() < 0.5 else self._account()
                    self._legit(client, "racha", at + timedelta(seconds=40 * friend), payee, rng.randint(1500, 8000))

    def _poisson(self, rate: float) -> int:
        limit, count, product = math.exp(-rate), 0, self.rng.random()
        while product > limit:
            count += 1
            product *= self.rng.random()
        return count

    # ── fraudes ─────────────────────────────────────────────────────

    def _victims(self, count: int) -> List[Client]:
        return self.rng.sample(self.clients, count)

    def build_fraud(self) -> None:
        rng = self.rng
        fraud_days = (DAYS - (FRAUD_START - START).days)

        def fraud_time(hour_range=(9, 20)) -> datetime:
            return FRAUD_START + timedelta(days=rng.randint(0, fraud_days - 2), hours=rng.randint(*hour_range), minutes=rng.randint(0, 59))

        victims = self._victims(60)

        # Conta invadida — o invasor reprova na biometria.
        for i, victim in enumerate(victims[0:10]):
            # Celular roubado: aparelho novo, Pix de teste, depois o grande; tenta de novo menor.
            at, thief = fraud_time(), f"sim-dvc-ladrao-{i}"
            ip, loc = rng.choice(self.mobile_ips), self._jitter(victim.home, 5)
            mule = self._account(days_old=rng.randint(2, 200))
            self._add("ato", "celular_roubado", at, victim.document, victim.opening_date, mule, 1000, thief, ip, "app", loc, "failed")
            self._add("ato", "celular_roubado", at + timedelta(minutes=3), victim.document, victim.opening_date, mule, victim.typical_amount * rng.uniform(8, 20), thief, ip, "app", loc, "failed")
            self._add("ato", "celular_roubado", at + timedelta(minutes=6), victim.document, victim.opening_date, mule, 19900, thief, ip, "app", loc, "failed")
        for i, victim in enumerate(victims[10:18]):
            # Aparelho novo, de longe (SIM swap, acesso remoto).
            at, far = fraud_time(), rng.choice([c for c in CITIES])
            self._add("ato", "aparelho_novo", at, victim.document, victim.opening_date, self._account(), rng.randint(150000, 500000),
                      f"sim-dvc-swap-{i}", rng.choice(self.mobile_ips), "app", self._jitter((far[1], far[2])), "failed")
        for i, victim in enumerate(victims[18:26]):
            # Rajada a partir do celular confiável roubado e desbloqueado.
            at = fraud_time()
            for k in range(rng.randint(6, 9)):
                self._add("ato", "rajada", at + timedelta(seconds=50 * k), victim.document, victim.opening_date, self._account(),
                          rng.randint(30000, 90000), victim.device_id, rng.choice(victim.ip_pool), "app", self._jitter(victim.home), "failed")
        for i, victim in enumerate([v for v in victims[26:40] if v.shares_location][:8]):
            # Celular confiável usado em outra cidade, valor acima de R$ 500.
            at = fraud_time()
            far = rng.choice([c for c in CITIES if abs(c[1] - victim.home[0]) > 2])
            self._add("ato", "fora_da_zona", at, victim.document, victim.opening_date, self._account(), rng.randint(60000, 200000),
                      victim.device_id, rng.choice(self.mobile_ips), "app", self._jitter((far[1], far[2])), "failed")

        # Golpe — a vítima, no próprio celular, confirma o 2FA.
        for i, victim in enumerate(victims[40:52]):
            # Falsa central: valor muito fora do perfil, destino novo; no dia seguinte paga de novo.
            at = fraud_time()
            scammer = self._account(days_old=rng.randint(5, 400))
            device, ip, _channel, loc = self._client_context(victim, (at - START).days, at)
            amount = max(victim.typical_amount * rng.uniform(6, 25), 120000)
            self._add("app", "falsa_central", at, victim.document, victim.opening_date, scammer, amount, device, ip, "app", loc, "passed")
            self._add("app", "falsa_central_repetido", at + timedelta(days=1, minutes=rng.randint(-60, 60)), victim.document,
                      victim.opening_date, scammer, amount * rng.uniform(1.0, 1.5), device, ip, "app", loc, "passed")
        for i, victim in enumerate(victims[52:60]):
            # Falso investimento: começa pequeno e cresce, para o mesmo destino.
            at = fraud_time((10, 18)) - timedelta(days=2)
            scammer = self._account(days_old=rng.randint(30, 600))
            device, ip, _channel, loc = self._client_context(victim, (at - START).days, at)
            for k, factor in enumerate((2.5, 5, 9)):
                self._add("app", "falso_investimento", at + timedelta(days=k), victim.document, victim.opening_date, scammer,
                          victim.typical_amount * factor, device, ip, "app", loc, "passed")

        # Conta laranja: várias vítimas (30% visíveis) para uma conta nova, que repassa em minutos.
        for m in range(6):
            mule_document = make_cpf(rng)
            mule_opening = FRAUD_START - timedelta(days=rng.randint(3, 25))
            mule_account = Account(mule_document, QI_ISPB, mule_document[:9], mule_opening)
            at = fraud_time((10, 16))
            received = 0
            for k in range(rng.randint(10, 16)):
                amount = rng.randint(20000, 150000)
                received += amount
                if rng.random() < VISIBLE_CREDIT_SHARE:
                    victim_document = make_cpf(rng)
                    self._add("mule", "vitima_para_laranja", at + timedelta(minutes=4 * k), victim_document,
                              START - timedelta(days=rng.randint(400, 3000)), mule_account, amount, f"sim-dvc-vit-{m}-{k}",
                              rng.choice(self.mobile_ips), "app", self._jitter(rng.choice(CITIES)[1:]), "passed")
                if k % 4 == 3:
                    # O repasse: a maior parte do que entrou, para a próxima conta.
                    self._add("mule", "repasse", at + timedelta(minutes=4 * k + 2), mule_document, mule_opening,
                              self._account(days_old=rng.randint(2, 60)), received * rng.uniform(0.85, 0.95),
                              f"sim-dvc-laranja-{m}", rng.choice(self.mobile_ips), "app", None, "passed")
                    received = 0

        # Padrão novo: Pix de centavos, espaçados, para muitos destinos diferentes (validação de contas).
        for n in range(4):
            operator = rng.choice(self.clients)
            at = fraud_time((9, 12))
            for k in range(rng.randint(20, 30)):
                device, ip, _channel, loc = self._client_context(operator, (at - START).days, at)
                self._add("novel", "centavos", at + timedelta(minutes=rng.randint(15, 40) * k), operator.document,
                          operator.opening_date, self._account(), rng.randint(1, 99), device, ip, "app", loc, "passed")


def build_world(seed: int, clients: int) -> List[Event]:
    world = World(seed, clients)
    world.build_legit()
    world.build_fraud()
    return sorted(world.events)
