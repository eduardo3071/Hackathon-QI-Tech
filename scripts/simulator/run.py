"""Simulador: manda os Pix do mundo simulado para a API, por HTTP, como qualquer cliente.

    python scripts/simulator/prepare_db.py --ml-mode shadow     # banco do zero (APAGA tudo)
    python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/regras.jsonl
    python scripts/simulator/report.py scripts/simulator/output/regras.jsonl

O cenário vai no prefixo do `id` (sim-legit-, sim-ato-, sim-app-, sim-mule-,
sim-novel-), sem mudar o contrato. Os Pix saem em ordem de data, e quando a
API pede 2FA o simulador responde pelo PATCH, como o app faria: o cliente
legítimo passa, o invasor reprova, a vítima de golpe confirma.

A mesma semente gera os mesmos Pix. Rodar de novo no mesmo banco é
idempotente (o mesmo `id` com o mesmo conteúdo devolve a análise gravada);
para uma medição nova, recrie o banco com o prepare_db.py.
"""

import argparse
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from population import build_world  # noqa: E402

API = os.environ.get("SIMULATOR_API", "http://localhost:3000")
TOKEN = os.environ.get("INTERNAL_TOKEN", "default_token")


def payload_for(event, pix_id: str) -> dict:
    source = {"device_id": event.device_id, "channel": event.channel, "ip": event.ip}
    if event.location is not None:
        source["geolocation"] = {"latitude": event.location[0], "longitude": event.location[1]}

    return {
        "id": pix_id,
        "amount": event.amount,
        "transaction_date": event.at.isoformat(),
        "source_account": {
            "branch": "0001",
            "account_number": event.payer[:9],
            "opening_date": event.payer_opening.isoformat(),
            "owner": {"document_number": event.payer},
        },
        "destination_account": {
            "participant": event.payee.ispb,
            "branch": "0001",
            "account_number": event.payee.number,
            "opening_date": event.payee.opening_date.isoformat(),
            "owner": {"document_number": event.payee.document},
        },
        "source": source,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--clients", type=int, default=200)
    parser.add_argument("--output", default="scripts/simulator/output/simulacao.jsonl")
    args = parser.parse_args()

    events = build_world(args.seed, args.clients)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"INTERNAL-TOKEN": TOKEN})
    started_at = time.perf_counter()

    with open(args.output, "w", encoding="utf-8") as output:
        for index, event in enumerate(events):
            pix_id = f"sim-{event.scenario}-{event.sub}-s{args.seed}-{index:06d}"
            response = session.post(f"{API}/pix/transaction", json=payload_for(event, pix_id))
            if response.status_code not in (200, 201):
                raise SystemExit(f"{pix_id}: HTTP {response.status_code} {response.text}")
            analysis = response.json()
            metadata = analysis["metadata"]

            final_status = analysis["status"]
            if analysis["status"] == "two_factor_required" and event.two_factor is not None:
                completed_at = (event.at + timedelta(minutes=1)).isoformat()
                patched = session.patch(
                    f"{API}/pix/transaction/{pix_id}",
                    json={"two_factor_result": event.two_factor, "completed_at": completed_at},
                )
                if patched.status_code != 200:
                    raise SystemExit(f"{pix_id}: PATCH HTTP {patched.status_code} {patched.text}")
                final_status = patched.json()["status"]

            record = {
                "id": pix_id,
                "scenario": event.scenario,
                "sub": event.sub,
                "amount": event.amount,
                "status": analysis["status"],
                "final_status": final_status,
                "path": metadata["path"],
                "latency_ms": metadata.get("latency_ms"),
                "typology": metadata["typology"],
                "step_up_reason": metadata["step_up_reason"],
                "scam_warning": metadata["scam_warning"],
                "recommended_action": metadata["recommended_action"],
                "scores": metadata["scores"],
                "signals": [reason["signal"] for reason in metadata["reasons"]],
                "ml": metadata.get("ml"),
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")

            if (index + 1) % 1000 == 0:
                print(f"{index + 1}/{len(events)} Pix ({time.perf_counter() - started_at:.0f} s)", flush=True)

    seconds = round(time.perf_counter() - started_at)
    meta = {"seed": args.seed, "clients": args.clients, "pix": len(events), "seconds": seconds}
    Path(args.output).with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"{len(events)} Pix em {seconds} s → {args.output}")


if __name__ == "__main__":
    main()
