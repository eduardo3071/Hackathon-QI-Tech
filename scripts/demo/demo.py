"""Demo ao vivo da apresentação: quatro histórias, só por HTTP.

    python scripts/demo/demo.py

1. Cliente normal — o Pix de sempre sai pelo caminho rápido.
2. Celular roubado — Pix de teste pequeno, depois o grande: biometria; o ladrão reprova.
3. Falsa central — a vítima, no próprio celular, manda muito acima do perfil: 2FA com aviso de golpe.
4. Conta laranja — conta aberta há 10 dias recebe de vários pagadores em minutos.

Cada rodada usa documentos novos e datas de abril de 2026, longe das dos
testes, do simulador e da bateria: roda quantas vezes quiser, sem recriar o
banco. O script não confere nada — mostra o que o motor decidiu, para a
banca ver o `metadata` de cada Pix.
"""

import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import requests

API = os.environ.get("DEMO_API", "http://127.0.0.1:3000")
HEADERS = {"INTERNAL-TOKEN": os.environ.get("INTERNAL_TOKEN", "default_token")}
BRT = timezone(timedelta(hours=-3))
DAY = datetime(2026, 4, 15, 14, 0, tzinfo=BRT)
HOME = {"latitude": -23.561, "longitude": -46.656}
rng = random.Random()


def cpf() -> str:
    digits = [rng.randint(0, 9) for _ in range(9)]
    for _ in range(2):
        total = sum(d * w for d, w in zip(digits, range(len(digits) + 1, 1, -1)))
        digits.append(0 if 11 - total % 11 >= 10 else 11 - total % 11)
    return "".join(map(str, digits))


def account(document=None, opened_days_ago=2000) -> dict:
    return {"document": document or cpf(), "number": str(rng.randint(10**6, 10**8)), "opened": DAY - timedelta(days=opened_days_ago)}


def send(payer, payee, amount, when, device, geolocation=HOME) -> dict:
    source = {"device_id": device, "channel": "app", "ip": f"189.1.{rng.randint(0, 255)}.{rng.randint(1, 254)}"}
    if geolocation:
        source["geolocation"] = geolocation
    pix_id = f"demo-{uuid.uuid4().hex[:12]}"
    body = {
        "id": pix_id,
        "amount": amount,
        "transaction_date": when.isoformat(),
        "source_account": {"branch": "0001", "account_number": payer["number"], "opening_date": payer["opened"].isoformat(),
                           "owner": {"document_number": payer["document"]}},
        "destination_account": {"participant": "60701190", "branch": "0001", "account_number": payee["number"],
                                "opening_date": payee["opened"].isoformat(), "owner": {"document_number": payee["document"]}},
        "source": source,
    }
    response = requests.post(f"{API}/pix/transaction", json=body, headers=HEADERS)
    response.raise_for_status()
    return {"id": pix_id, **response.json()}


def two_factor(pix, result, when) -> dict:
    response = requests.patch(f"{API}/pix/transaction/{pix['id']}", headers=HEADERS,
                              json={"two_factor_result": result, "completed_at": when.isoformat()})
    response.raise_for_status()
    return response.json()


def show(step: str, pix: dict) -> None:
    metadata = pix["metadata"]
    decision = pix["status"]
    if decision == "two_factor_required":
        decision += f" ({metadata['step_up_reason']} → {metadata['step_up_method']}{', aviso de golpe' if metadata['scam_warning'] else ''})"
    elif metadata.get("recommended_action") == "warn":
        decision += " (com aviso)"
    print(f"  {step:<52} {decision}")
    print(f"  {'':<52} caminho {metadata['path']}, placares {metadata['scores']}, {metadata.get('latency_ms')} ms")
    for reason in metadata["reasons"]:
        print(f"  {'':<52} • {reason['signal']}: {reason['message']}")


def client_with_history() -> dict:
    """Cinco Pix de R$ 150, um por dia, do mesmo celular, para o mesmo destino: o motor conhece o cliente."""
    client = {"account": account(), "device": f"demo-dvc-{uuid.uuid4().hex[:8]}", "usual": account()}
    for day in range(6, 1, -1):
        send(client["account"], client["usual"], 15000, DAY - timedelta(days=day), client["device"])
    return client


def main() -> None:
    print(f"API: {API}\n")

    print("1. Cliente normal")
    client = client_with_history()
    show("Pix de R$ 180 para o destino de sempre", send(client["account"], client["usual"], 18000, DAY, client["device"]))

    print("\n2. Celular roubado")
    thief = f"demo-ladrao-{uuid.uuid4().hex[:6]}"
    show("Ladrão, celular novo: Pix de teste de R$ 10", send(client["account"], account(), 1000, DAY + timedelta(minutes=5), thief))
    stolen = send(client["account"], account(), 300000, DAY + timedelta(minutes=8), thief)
    show("3 min depois: R$ 3.000 para um destino novo", stolen)
    if stolen["status"] == "two_factor_required":
        after = two_factor(stolen, "failed", DAY + timedelta(minutes=9))
        print(f"  {'→ o ladrão reprova na biometria (PATCH failed)':<52} {after['status']}")

    print("\n3. Falsa central")
    victim = client_with_history()
    scammer = account(opened_days_ago=400)
    scam = send(victim["account"], scammer, 400000, DAY + timedelta(hours=1), victim["device"])
    show("Vítima, no próprio celular: R$ 4.000 a um destino novo", scam)
    if scam["status"] == "two_factor_required":
        after = two_factor(scam, "passed", DAY + timedelta(hours=1, minutes=1))
        print(f"  {'→ a vítima, manipulada, confirma (PATCH passed)':<52} {after['status']}")
    show("No dia seguinte, R$ 5.000 ao mesmo golpista",
         send(victim["account"], scammer, 500000, DAY + timedelta(days=1, hours=1), victim["device"]))

    print("\n4. Conta laranja")
    mule = account(opened_days_ago=10)
    for index in range(5):
        payer = client_with_history()
        show(f"Pagador {index + 1} manda R$ 300 à conta de 10 dias",
             send(payer["account"], mule, 30000, DAY + timedelta(hours=3, minutes=8 * index), payer["device"]))


if __name__ == "__main__":
    main()
