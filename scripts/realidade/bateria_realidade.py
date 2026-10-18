"""Bateria de realidade do motor antifraude Pix — só por HTTP, como qualquer cliente.

Três partes:
  1. Dia a dia: uma população de clientes legítimos vivendo ~60 dias de Pix, com a
     distribuição real do Pix entre pessoas no Brasil (mediana R$ 50, média R$ 273,
     ~21% acima de R$ 200 — BCB, dez/2025). Mede a fricção e a latência.
  2. Golpes reais, encenados passo a passo (tipologias Febraban/BCB), com o que
     acontece DEPOIS do 2FA (vítima manipulada confirma; invasor reprova).
  3. Conformidade com normas do BCB e casos de fronteira do cotidiano.

Uso: python scripts/realidade/bateria_realidade.py [semente] [saída]   (API em http://127.0.0.1:3000)
     A saída padrão é docs/bateria-realidade.md. Rode contra um banco recriado do zero.
"""
import math
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import requests

BASE = os.environ.get("BATERIA_API", "http://127.0.0.1:3000")
OUTPUT = sys.argv[2] if len(sys.argv) > 2 else "docs/bateria-realidade.md"
# Onde a bateria rodou, para o rótulo da latência (ex.: "Docker Desktop, Windows 11").
AMBIENTE = os.environ.get("BATERIA_AMBIENTE", "não informado (defina BATERIA_AMBIENTE)")
H = {"INTERNAL-TOKEN": "default_token"}
BRT = timezone(timedelta(hours=-3))
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
rng = random.Random(SEED)
S = requests.Session()

ISPBS = ["18236120", "60701190", "60746948", "00416968", "00360305", "00000000", "10573521", "22896431"]
HOME = (-23.5610, -46.6560)      # São Paulo
RIO = (-22.9068, -43.1729)
RECIFE = (-8.0476, -34.8770)
CGNAT = ["177.32.10.1", "177.32.10.2", "177.32.10.3"]   # IP de operadora móvel, compartilhado por muita gente

LAT = []            # latências (ms) de todos os POST
COUNTER = [0]


# ───────────────────────── documentos e contas ─────────────────────────
def cpf():
    n = [rng.randint(0, 9) for _ in range(9)]
    for _ in range(2):
        s = sum(v * w for v, w in zip(n, range(len(n) + 1, 1, -1)))
        d = 11 - s % 11
        n.append(0 if d >= 10 else d)
    return "".join(map(str, n))


def cnpj():
    n = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    for weights in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        s = sum(v * w for v, w in zip(n, weights))
        d = 11 - s % 11
        n.append(0 if d >= 10 else d)
    return "".join(map(str, n))


def acc_number():
    return str(rng.randint(10**6, 10**8))


def account(doc, opened, ispb=None):
    return {"doc": doc, "branch": str(rng.randint(1, 9999)).zfill(4), "number": acc_number(),
            "opening": opened, "ispb": ispb or rng.choice(ISPBS)}


def years_ago(y, ref=datetime(2026, 10, 17, tzinfo=BRT)):
    return ref - timedelta(days=int(365 * y))


def jitter(geo, km=3.0):
    d = km / 111.0
    return (geo[0] + rng.uniform(-d, d), geo[1] + rng.uniform(-d, d))


# ───────────────────────── chamadas à API ─────────────────────────
def post(payer, dest, amount, when, device, channel="app", ip=None, geo=None, prefix="t"):
    COUNTER[0] += 1
    body = {
        "id": f"{prefix}-{SEED}-{COUNTER[0]}",
        "amount": int(amount),
        "transaction_date": when.isoformat(),
        "source_account": {"branch": payer["acc"]["branch"], "account_number": payer["acc"]["number"],
                           "opening_date": payer["acc"]["opening"].isoformat(),
                           "owner": {"document_number": payer["doc"]}},
        "destination_account": {"participant": dest["ispb"], "branch": dest["branch"],
                                "account_number": dest["number"], "opening_date": dest["opening"].isoformat(),
                                "owner": {"document_number": dest["doc"]}},
        "source": {"device_id": device, "channel": channel, "ip": ip or payer["home_ip"]},
    }
    if geo is not None:
        body["source"]["geolocation"] = {"latitude": round(geo[0], 6), "longitude": round(geo[1], 6)}
    t0 = time.perf_counter()
    r = S.post(f"{BASE}/pix/transaction", json=body, headers=H)
    LAT.append(((time.perf_counter() - t0) * 1000, None))
    out = r.json()
    md = out.get("metadata", {})
    LAT[-1] = (LAT[-1][0], md.get("path"))
    return {"id": body["id"], "http": r.status_code, "status": out.get("status"), "md": md, "amount": amount}


def patch(res, result, when):
    r = S.patch(f"{BASE}/pix/transaction/{res['id']}",
                json={"two_factor_result": result, "completed_at": when.isoformat()}, headers=H)
    return r.status_code


def label(res):
    md = res["md"]
    if res["status"] == "two_factor_required":
        w = " +aviso" if md.get("scam_warning") else ""
        return f"2FA {md.get('step_up_reason')}/{md.get('step_up_method')}{w}"
    if res["status"] == "approved" and md.get("recommended_action") == "warn":
        return "aprovado c/ aviso"
    return {"approved": "aprovado", "rejected": "RECUSADO"}.get(res["status"], f"?{res['http']}")


def signals(res):
    return ", ".join(sorted({r["signal"] for r in res["md"].get("reasons", [])})) or "—"


# ───────────────────────── população legítima ─────────────────────────
def make_client(i, merchants):
    doc = cpf()
    c = {
        "doc": doc,
        "acc": {"branch": "0001", "number": acc_number(), "opening": years_ago(rng.uniform(1.5, 9)), "ispb": None},
        "device": f"dvc-{doc[:6]}-1",
        "home": jitter(HOME, 8),
        "home_ip": f"189.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
        "contacts": [account(cpf(), years_ago(rng.uniform(1, 10))) for _ in range(6)],
        "merchants": rng.sample(merchants, 4),
        "landlord": account(cpf(), years_ago(rng.uniform(2, 10))),
        "rent": rng.randint(120000, 250000),
        "own_other": None,
        "changes_phone": rng.random() < 0.10,
        "travels": rng.random() < 0.10,
        "moves_own_money": rng.random() < 0.15,
    }
    c["own_other"] = account(doc, years_ago(rng.uniform(1, 5)))
    return c


def lognormal_amount():
    # mediana R$ 50, média ≈ R$ 273 (σ = 1,84) — calibrado no Pix P2P do BCB
    v = math.exp(math.log(5000) + 1.84 * rng.gauss(0, 1))
    return max(100, min(int(v), 400000))


def history_events(c, start, days):
    ev = []
    change_day = rng.randint(20, days - 10) if c["changes_phone"] else None
    travel_day = rng.randint(10, days - 8) if c["travels"] else None
    for d in range(days):
        day = start + timedelta(days=d)
        n = rng.choices([0, 1, 2, 3], weights=[45, 35, 15, 5])[0]
        for _ in range(n):
            night = rng.random() < 0.15
            hour = rng.randint(20, 22) if night else rng.randint(8, 19)
            when = day.replace(hour=hour, minute=rng.randint(0, 59))
            r = rng.random()
            if r < 0.50:
                dest = rng.choice(c["contacts"])
            elif r < 0.85:
                dest = rng.choice(c["merchants"])
            else:
                dest = account(cpf(), years_ago(rng.uniform(1, 8)))
            ev.append(("pix", when, dest, lognormal_amount()))
        if day.day == 5:
            ev.append(("pix", day.replace(hour=10, minute=5), c["landlord"], c["rent"]))
        if c["moves_own_money"] and day.day == 6:
            ev.append(("pix", day.replace(hour=9, minute=30), c["own_other"], rng.randint(100000, 500000)))
    return ev, change_day, travel_day


def run_population(n_clients, start, days):
    merchants = [account(cnpj(), years_ago(rng.uniform(3, 15))) for _ in range(25)]
    clients = [make_client(i, merchants) for i in range(n_clients)]
    events = []
    for c in clients:
        ev, change_day, travel_day = history_events(c, start, days)
        for kind, when, dest, amount in ev:
            d = (when - start).days
            device = c["device"] if change_day is None or d < change_day else c["device"].replace("-1", "-2")
            in_trip = travel_day is not None and travel_day <= d < travel_day + 3
            geo = jitter(RIO, 4) if in_trip else jitter(c["home"], 1.5)
            if rng.random() < 0.08:
                geo = None                                  # geolocalização desligada às vezes
            ip = rng.choice(CGNAT) if rng.random() < 0.4 else c["home_ip"]
            channel = "internet_banking" if rng.random() < 0.03 else "app"
            events.append((when, c, dest, amount, device, channel, ip, geo))
    events.sort(key=lambda e: e[0])

    stats = []
    for when, c, dest, amount, device, channel, ip, geo in events:
        res = post(c, dest, amount, when, device, channel, ip, geo, prefix="legit")
        if res["status"] == "two_factor_required":
            patch(res, "passed", when + timedelta(seconds=40))    # o cliente legítimo passa no 2FA
        stats.append((when, res, amount, dest["doc"] == c["doc"]))
    return clients, merchants, stats


def trusted_clients(clients, stats, min_ok=15):
    ok = Counter()
    for when, res, amount, own in stats:
        pass
    by_doc = defaultdict(int)
    for c in clients:
        by_doc[c["doc"]] = 0
    return clients


# ───────────────────────── golpes encenados ─────────────────────────
REPORT_FRAUD = []


def fraud_step(case, step, res, expect, after=None):
    REPORT_FRAUD.append((case, step, label(res), signals(res), expect, after or ""))


def scenarios(clients, merchants):
    pool = [c for c in clients if not c["changes_phone"] and not c["travels"]]
    rng.shuffle(pool)
    v = iter(pool)
    D = datetime(2026, 10, 17, tzinfo=BRT)

    # F1 — Falsa central de atendimento (Febraban 1º sem/2025: +196%)
    c = next(v); dev = c["device"]
    m1, m2 = account(cpf(), years_ago(2)), account(cpf(), years_ago(1.2))
    for step, (dest, amt, mins) in enumerate([(m1, 480000, 0), (m2, 450000, 8), (m1, 390000, 15)], 1):
        r = post(c, dest, amt, D.replace(hour=14) + timedelta(minutes=mins), dev, geo=jitter(c["home"], 1), prefix="f1")
        after = ""
        if r["status"] == "two_factor_required":
            patch(r, "passed", D.replace(hour=14) + timedelta(minutes=mins, seconds=50)); after = "vítima confirma"
        fraud_step("F1 Falsa central (aparelho e casa de sempre, 3 Pix altos p/ contas antigas)", f"R$ {amt/100:,.0f}", r,
                   "2FA c/ aviso em todos", after)

    # F2 — Falso parente no WhatsApp ("mãe, troquei de número")
    c = next(v); dev = c["device"]
    m = account(cpf(), D - timedelta(days=15))
    for amt, h in [(189000, 11), (230000, 15)]:
        r = post(c, m, amt, D.replace(hour=h), dev, geo=jitter(c["home"], 1), prefix="f2")
        after = ""
        if r["status"] == "two_factor_required":
            patch(r, "passed", D.replace(hour=h, minute=1)); after = "vítima confirma"
        fraud_step("F2 Falso parente (conta de 15 dias, 2 Pix no mesmo dia)", f"R$ {amt/100:,.0f} às {h}h", r,
                   "2FA c/ aviso; 2º também", after)

    # F3 — Falso investimento: valores crescentes ao mesmo destino ao longo de dias
    c = next(v); dev = c["device"]
    m = account(cpf(), years_ago(2))
    for amt, d in [(50000, 0), (100000, 2), (300000, 5), (800000, 8)]:
        when = D.replace(hour=19) + timedelta(days=d)
        r = post(c, m, amt, when, dev, geo=jitter(c["home"], 1), prefix="f3")
        after = ""
        if r["status"] == "two_factor_required":
            patch(r, "passed", when + timedelta(minutes=1)); after = "vítima confirma"
        fraud_step("F3 Falso investimento (mesmo destino, valor crescente)", f"dia {d}: R$ {amt/100:,.0f}", r,
                   "aviso a partir do salto; repete", after)

    # F4 — Falsa venda em marketplace (Febraban: tipologia que mais cresceu, +314%)
    seller = account(cpf(), D - timedelta(days=10))
    for k in range(6):
        c = next(v)
        r = post(c, seller, 45000 + rng.randint(-2000, 2000), D.replace(hour=16) + timedelta(minutes=8 * k),
                 c["device"], geo=jitter(c["home"], 1), prefix="f4")
        fraud_step("F4 Falsa venda (6 compradores → vendedor com conta de 10 dias, 50 min)", f"comprador {k+1}", r,
                   "barrar a partir do 5º")

    # F5 — Mão fantasma (acesso remoto no celular da vítima, drenagem rápida)
    c = next(v); dev = c["device"]
    for k in range(7):
        amt = rng.randint(90000, 190000)
        r = post(c, account(cpf(), years_ago(rng.uniform(1, 4))), amt, D.replace(hour=15) + timedelta(seconds=50 * k),
                 dev, geo=jitter(c["home"], 0.2), prefix="f5")
        after = ""
        if r["status"] == "two_factor_required":
            after = "golpista não passa na biometria" if r["md"].get("step_up_method") == "face_liveness" else "confirmação no app: golpista no controle CONFIRMA"
            patch(r, "failed" if r["md"].get("step_up_method") == "face_liveness" else "passed", D.replace(hour=15) + timedelta(seconds=50 * k + 20))
        fraud_step("F5 Mão fantasma (7 Pix em 6 min, aparelho de sempre)", f"Pix {k+1}: R$ {amt/100:,.0f}", r,
                   "travar a partir do 5º", after)

    # F6 — Celular roubado desbloqueado na rua, à noite (o aparelho É o de sempre)
    c = next(v); dev = c["device"]
    street = jitter(c["home"], 9)
    for k, amt in enumerate([90000, 95000, 98000, 300000]):
        r = post(c, account(cpf(), years_ago(rng.uniform(1, 3))), amt, D.replace(hour=23, minute=10) + timedelta(minutes=2 * k),
                 dev, ip=rng.choice(CGNAT), geo=street, prefix="f6")
        after = ""
        if r["status"] == "two_factor_required":
            if r["md"].get("step_up_method") == "face_liveness":
                patch(r, "failed", D.replace(hour=23, minute=11) + timedelta(minutes=2 * k)); after = "ladrão não passa na biometria"
            else:
                patch(r, "passed", D.replace(hour=23, minute=11) + timedelta(minutes=2 * k)); after = "confirmação no app: LADRÃO CONFIRMA"
        fraud_step("F6 Celular roubado na rua, 23h (aparelho de sempre, 9 km de casa)", f"Pix {k+1}: R$ {amt/100:,.0f}", r,
                   "biometria (Modo Rua)", after)

    # F7 — SIM swap / conta invadida em aparelho novo, outro estado, madrugada; depois fraciona abaixo de R$ 200
    c = next(v)
    r = post(c, account(cpf(), years_ago(1)), 700000, D.replace(hour=2), "dvc-invasor", ip="200.150.1.9",
             geo=jitter(RECIFE, 2), prefix="f7")
    if r["status"] == "two_factor_required":
        patch(r, "failed", D.replace(hour=2, minute=1))
    fraud_step("F7 SIM swap: aparelho novo, Recife, 2h", "R$ 7.000", r, "2FA biometria", "invasor reprova")
    for k in range(7):
        r = post(c, account(cpf(), years_ago(1)), 19000, D.replace(hour=2, minute=10 + 3 * k), "dvc-invasor",
                 ip="200.150.1.9", geo=jitter(RECIFE, 2), prefix="f7")
        fraud_step("F7 SIM swap: aparelho novo, Recife, 2h", f"fraciona {k+1}: R$ 190", r, "parar perto de R$ 1.000/dia")

    # F8 — Sequestro relâmpago (vítima coagida, aparelho de sempre, 22h30, 15 km de casa)
    c = next(v); dev = c["device"]; place = jitter(c["home"], 15)
    for k in range(3):
        r = post(c, account(cpf(), years_ago(2)), 100000, D.replace(hour=22, minute=30) + timedelta(minutes=3 * k),
                 dev, geo=place, prefix="f8")
        after = ""
        if r["status"] == "two_factor_required":
            patch(r, "passed", D.replace(hour=22, minute=31) + timedelta(minutes=3 * k)); after = "vítima coagida passa no 2FA"
        fraud_step("F8 Sequestro relâmpago (coação, 22h30, 3 Pix de R$ 1.000)", f"Pix {k+1}", r, "limite noturno segura", after)

    # F9 — Conta laranja de passagem (é NOSSA cliente): recebe de 5 vítimas e repassa em minutos
    mule_doc = cpf()
    mule = {"doc": mule_doc, "acc": {"branch": "0001", "number": acc_number(), "opening": D - timedelta(days=20), "ispb": None},
            "home_ip": "191.1.2.3", "device": "dvc-laranja"}
    mule_as_dest = {"doc": mule_doc, "branch": "0001", "number": mule["acc"]["number"], "opening": mule["acc"]["opening"],
                    "ispb": "18236120"}
    for k in range(5):
        cv = next(v)
        r = post(cv, mule_as_dest, 70000, D.replace(hour=13) + timedelta(minutes=6 * k), cv["device"],
                 geo=jitter(cv["home"], 1), prefix="f9")
        fraud_step("F9 Conta laranja de passagem (conta de 20 dias)", f"vítima {k+1} paga R$ 700", r, "barrar a partir do 5º")
    r = post(mule, account(cpf(), D - timedelta(days=5)), 330000, D.replace(hour=13, minute=34), "dvc-laranja",
             geo=jitter(HOME, 5), prefix="f9")
    fraud_step("F9 Conta laranja de passagem (conta de 20 dias)", "laranja repassa R$ 3.300 (4 min depois)", r, "RECUSAR")

    # F10 — Fazenda de contas: 4 CPFs diferentes operados do MESMO aparelho
    farm_dev = "dvc-fazenda"
    for k in range(4):
        fd = cpf()
        f = {"doc": fd, "acc": {"branch": "0001", "number": acc_number(), "opening": D - timedelta(days=rng.randint(60, 240)),
                               "ispb": None}, "home_ip": "45.4.4.4", "device": farm_dev}
        r = post(f, account(cpf(), years_ago(1)), 15000, D.replace(hour=10) + timedelta(hours=6 * k), farm_dev,
                 geo=jitter(HOME, 2), prefix="f10")
        fraud_step("F10 Fazenda de contas (4 CPFs, 1 aparelho)", f"CPF {k+1}", r, "sinalizar a partir do 3º")

    # F11 — Teste de contas com Pix de centavos (ninguém cobre isso com regra)
    c = next(v); dev = c["device"]; got = Counter()
    for k in range(25):
        r = post(c, account(cpf(), years_ago(rng.uniform(1, 5))), 1, D.replace(hour=8) + timedelta(minutes=20 * k), dev,
                 geo=jitter(c["home"], 1), prefix="f11")
        got[label(r)] += 1
    REPORT_FRAUD.append(("F11 Teste de contas (25 Pix de R$ 0,01 a cada 20 min)", "25 Pix", dict(got).__str__(),
                         "—", "só o ML pegaria", ""))

    # F12 — Marcação no DICT (seed do banco)
    c = next(v)
    own = {"doc": "11144477735", "branch": "1", "number": "1114447", "opening": years_ago(2), "ispb": "18236120"}
    old3 = {"doc": "33366699957", "branch": "1", "number": "3336669", "opening": years_ago(2), "ispb": "18236120"}
    fraud_step("F12 Marcação (Res. BCB 587)", "recebedor com marcação própria",
               post(c, own, 5000, D.replace(hour=12), c["device"], geo=jitter(c["home"], 1), prefix="f12"), "RECUSAR")
    fraud_step("F12 Marcação (Res. BCB 587)", "marcação de outro PSP há mais de 90 dias",
               post(c, old3, 5000, D.replace(hour=12, minute=5), c["device"], geo=jitter(c["home"], 1), prefix="f12"), "não recusar")
    return v


# ───────────────────────── cotidiano e normas ─────────────────────────
REPORT_LIFE = []


def life(case, res, expect):
    REPORT_LIFE.append((case, label(res), signals(res), expect))


def daily_life(clients, merchants, v):
    D = datetime(2026, 10, 17, tzinfo=BRT)
    c = next(v); dev = c["device"]
    # racha da conta do bar: 6 Pix pequenos para amigos de sempre em 4 min, sexta 23h
    for k, f in enumerate(c["contacts"][:6]):
        r = post(c, f, rng.randint(2500, 6000), D.replace(hour=23, minute=0) + timedelta(seconds=40 * k), dev,
                 geo=jitter(c["home"], 3), prefix="l")
    life("Racha da conta do bar: 6 Pix pequenos p/ amigos em 4 min, 23h (último)", r, "aprovar")
    life("Mecânico novo: R$ 1.200 p/ PF desconhecida, 14h",
         post(c, account(cpf(), years_ago(6)), 120000, D.replace(hour=14), dev, geo=jitter(c["home"], 2), prefix="l"),
         "aprovar ou aviso leve")
    life("TV na Black Friday: R$ 3.500 p/ loja PJ nova (CNPJ antigo), 10h",
         post(c, account(cnpj(), years_ago(12)), 350000, D.replace(hour=10), dev, geo=jitter(c["home"], 1), prefix="l"),
         "aprovar ou aviso")
    life("Farmácia de plantão: R$ 1.300 PF→PJ às 23h30",
         post(c, rng.choice(merchants), 130000, D.replace(hour=23, minute=30), dev, geo=jitter(c["home"], 1), prefix="l"),
         "limite noturno NÃO se aplica a PJ")
    life("Mover o próprio dinheiro: R$ 20.000 p/ conta própria em outro banco, 22h",
         post(c, c["own_other"], 2000000, D.replace(hour=22), dev, geo=jitter(c["home"], 1), prefix="l"),
         "aprovar (mesma titularidade)")
    life("Horário em UTC: Pix de R$ 1.500 enviado como 01:15Z (= 22h15 em Brasília) p/ amigo",
         post(c, c["contacts"][0], 150000, datetime(2026, 10, 19, 1, 15, tzinfo=timezone.utc), dev,
              geo=jitter(c["home"], 1), prefix="l"),
         "tratar como noturno")
    life("Viagem: jantar no Rio R$ 180 p/ restaurante PJ, 21h",
         post(c, account(cnpj(), years_ago(5)), 18000, D.replace(hour=21) + timedelta(days=3), dev, geo=jitter(RIO, 2),
              prefix="l"),
         "aprovar (viagem é rotina)")
    # vaquinha: 20 clientes mandam R$ 20 p/ uma PF com conta antiga em 1 h
    vaq = account(cpf(), years_ago(4))
    for k in range(20):
        cv = next(v)
        r = post(cv, vaq, 2000, D.replace(hour=18) + timedelta(minutes=3 * k), cv["device"], geo=jitter(cv["home"], 1),
                 prefix="l")
    life("Vaquinha: 20 amigos mandam R$ 20 p/ PF com conta de 4 anos em 1h (20º)", r, "aprovar")
    vaq2 = account(cpf(), D - timedelta(days=12))
    for k in range(8):
        cv = next(v)
        r = post(cv, vaq2, 2000, D.replace(hour=19) + timedelta(minutes=5 * k), cv["device"], geo=jitter(cv["home"], 1),
                 prefix="l")
    life("Rifa da formatura: 8 amigos mandam R$ 20 p/ conta aberta há 12 dias (8º)", r, "zona cinzenta: aviso ou 2FA")
    # cliente novo no banco
    newbie = {"doc": cpf(), "acc": {"branch": "0001", "number": acc_number(), "opening": D - timedelta(days=1), "ispb": None},
              "home_ip": "189.9.9.9"}
    life("Conta aberta ontem: 1º Pix R$ 150",
         post(newbie, account(cpf(), years_ago(3)), 15000, D.replace(hour=11), "dvc-novo1", geo=jitter(HOME, 2), prefix="l"),
         "aprovar (≤ R$ 200)")
    life("Conta aberta ontem: 2º Pix R$ 600",
         post(newbie, account(cpf(), years_ago(3)), 60000, D.replace(hour=11, minute=30), "dvc-novo1", geo=jitter(HOME, 2),
              prefix="l"),
         "2FA (aparelho não cadastrado, Res. BCB 403)")
    stranger = {"doc": cpf(), "acc": {"branch": "0001", "number": acc_number(), "opening": years_ago(5), "ispb": None},
                "home_ip": "189.8.8.8"}
    life("Cliente antigo do banco, desconhecido do motor, aparelho nunca visto: R$ 700",
         post(stranger, account(cpf(), years_ago(3)), 70000, D.replace(hour=11), "dvc-nunca-visto", geo=jitter(HOME, 2),
              prefix="l"),
         "Res. BCB 403 diz R$ 200 por Pix em aparelho não cadastrado")


# ───────────────────────── relatório ─────────────────────────
def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "—"


def main():
    t0 = time.time()
    start = datetime(2026, 8, 18, tzinfo=BRT)
    clients, merchants, stats = run_population(90, start, 60)
    pop_time = time.time() - t0

    amounts_p2p = [a for w, r, a, own in stats if not own]
    total = len(stats)
    by = Counter(label(r) for w, r, a, own in stats)
    steady = [(w, r) for w, r, a, own in stats if w >= start + timedelta(days=45)]
    by_steady = Counter(label(r) for w, r in steady)
    rejected_legit = [(w, r, a) for w, r, a, own in stats if r["status"] == "rejected"]

    v = scenarios(clients, merchants)
    daily_life(clients, merchants, v)

    fast = [ms for ms, path in LAT if path == "fast"]
    deep = [ms for ms, path in LAT if path == "deep"]

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else float("nan")

    out = []
    out.append(f"# Bateria de realidade — semente {SEED}\n")
    out.append("## 1. Dia a dia: 90 clientes legítimos, 60 dias de Pix\n")
    out.append(f"- Pix simulados: **{total}** em {pop_time:.0f} s. Ticket P2P simulado: mediana R$ {statistics.median(amounts_p2p)/100:.0f}, "
               f"média R$ {statistics.mean(amounts_p2p)/100:.0f}, {pct(sum(a > 20000 for a in amounts_p2p), len(amounts_p2p))} acima de R$ 200 "
               f"(referência BCB dez/2025: R$ 50, R$ 273, 21%).")
    out.append(f"- Inclui: aluguel todo dia 5, compras em lojistas, Pix para amigos, 15% à noite, 10% trocam de celular, "
               f"10% viajam ao Rio, 15% movem dinheiro entre contas próprias, 40% usam IP de operadora compartilhado, "
               f"8% com geolocalização desligada, 3% usam internet banking.\n")
    out.append("| Decisão (todo o período) | Pix | % |\n|---|---|---|")
    for k, n in by.most_common():
        out.append(f"| {k} | {n} | {pct(n, total)} |")
    out.append(f"\n**Últimos 15 dias (motor já conhece os clientes):** " +
               "; ".join(f"{k}: {pct(n, len(steady))}" for k, n in by_steady.most_common()))
    if rejected_legit:
        out.append(f"\n**Clientes legítimos RECUSADOS: {len(rejected_legit)}**")
        for w, r, a in rejected_legit[:8]:
            out.append(f"- {w:%d/%m %Hh%M} R$ {a/100:,.2f}: {signals(r)}")
    out.append(f"\n**Latência (HTTP de ponta a ponta; ambiente: {AMBIENTE}):** caminho rápido p50 {q(fast,50):.0f} ms / p95 {q(fast,95):.0f} ms "
               f"/ p99 {q(fast,99):.0f} ms ({len(fast)} Pix); caminho profundo p50 {q(deep,50):.0f} ms / p95 {q(deep,95):.0f} ms "
               f"/ p99 {q(deep,99):.0f} ms ({len(deep)} Pix). Caminho rápido: {pct(len(fast), len(fast)+len(deep))} dos Pix.\n")

    out.append("## 2. Golpes reais encenados\n")
    out.append("| Golpe | Passo | Decisão do motor | Sinais | Esperado | Depois do 2FA |\n|---|---|---|---|---|---|")
    for row in REPORT_FRAUD:
        out.append("| " + " | ".join(row) + " |")

    out.append("\n## 3. Cotidiano e normas\n")
    out.append("| Caso | Decisão | Sinais | Esperado |\n|---|---|---|---|")
    for row in REPORT_LIFE:
        out.append("| " + " | ".join(row) + " |")

    text = "\n".join(out)
    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as output:
        output.write(text)
    print(text)


if __name__ == "__main__":
    main()
