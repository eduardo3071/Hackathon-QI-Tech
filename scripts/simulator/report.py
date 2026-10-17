"""Relatório do simulador: uma tabela por cenário, a fricção e a latência.

    python scripts/simulator/report.py RESULTADO.jsonl [--ml RESULTADO_COM_ML.jsonl] [--output docs/resultados-simulador.md]

"Pego" é todo Pix de fraude que não saiu aprovado direto: 2FA ou recusa.
A taxa por valor pesa cada Pix pelo valor — o Pix de teste de R$ 10 do
ladrão pesa menos que o de R$ 5.000. Com `--ml`, compara as regras
sozinhas com as regras mais o ML em modo ativo.
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

SCENARIOS = {
    "legit": "Clientes legítimos",
    "ato": "Conta invadida",
    "app": "Golpe",
    "mule": "Conta laranja",
    "novel": "Padrão novo (nenhuma regra cobre)",
}

DISCLAIMER = (
    "> **Leia antes dos números.** O simulador é do próprio grupo: os cenários de fraude foram desenhados por nós, "
    "conhecendo as regras. Por isso estes números são **teste de regressão da política e medida de fricção**, "
    "e **não eficácia**: não dizem quanto o motor pegaria de fraude real. O motor só vê Pix de clientes da QI Tech, "
    "e o simulador reproduz isso: 70% dos créditos que as contas recebem vêm de pagadores que o motor nunca vê "
    "(salário, vítimas de outros bancos). O cenário \"padrão novo\" também foi desenhado por nós: ele mostra o "
    "mecanismo do ML, não a eficácia dele."
)


def load(path: str):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
    meta_path = Path(path).with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return rows, meta


def pct(part: float, whole: float) -> str:
    return "—" if whole == 0 else f"{100 * part / whole:.1f}%"


def percentile(values, percent):
    if not values:
        return "—"
    ordered = sorted(values)
    return ordered[max(math.ceil(percent / 100 * len(ordered)), 1) - 1]


def caught(row) -> bool:
    return row["status"] != "approved"


def scenario_table(rows) -> list:
    groups = defaultdict(list)
    for row in rows:
        groups[(row["scenario"], row["sub"])].append(row)

    lines = [
        "| Cenário | Situação | Pix | Aprovado | (dos quais com aviso) | 2FA | Recusado | Pego (Pix) | Pego (valor) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in SCENARIOS:
        for (group_scenario, sub), items in sorted(groups.items()):
            if group_scenario != scenario:
                continue
            n = len(items)
            approved = sum(1 for r in items if r["status"] == "approved")
            warned = sum(1 for r in items if r["status"] == "approved" and r["recommended_action"] == "warn")
            two_factor = sum(1 for r in items if r["status"] == "two_factor_required")
            rejected = sum(1 for r in items if r["status"] == "rejected")
            total_value = sum(r["amount"] for r in items)
            caught_value = sum(r["amount"] for r in items if caught(r))
            is_fraud = scenario != "legit"
            lines.append(
                f"| {SCENARIOS[scenario]} | `{sub}` | {n} | {pct(approved, n)} | {pct(warned, n)} | {pct(two_factor, n)} "
                f"| {pct(rejected, n)} | {pct(n - approved, n) if is_fraud else '—'} "
                f"| {pct(caught_value, total_value) if is_fraud else '—'} |"
            )
    return lines


def summary(rows) -> dict:
    result = {}
    for scenario in SCENARIOS:
        items = [r for r in rows if r["scenario"] == scenario]
        n = len(items)
        result[scenario] = {
            "n": n,
            "caught": sum(1 for r in items if caught(r)),
            "two_factor": sum(1 for r in items if r["status"] == "two_factor_required"),
            "rejected": sum(1 for r in items if r["status"] == "rejected"),
            "value": sum(r["amount"] for r in items),
            "caught_value": sum(r["amount"] for r in items if caught(r)),
        }
    return result


def summary_table(rows) -> list:
    data = summary(rows)
    lines = ["| Tipologia | Pix | Pego (Pix) | Pego (valor) |", "|---|---:|---:|---:|"]
    for scenario in ("ato", "app", "mule", "novel"):
        item = data[scenario]
        lines.append(
            f"| {SCENARIOS[scenario]} | {item['n']} | {pct(item['caught'], item['n'])} | {pct(item['caught_value'], item['value'])} |"
        )
    legit = data["legit"]
    lines += [
        "",
        "| Fricção nos clientes legítimos | Pix | 2FA | Recusa |",
        "|---|---:|---:|---:|",
        f"| Todos | {legit['n']} | {pct(legit['two_factor'], legit['n'])} | {pct(legit['rejected'], legit['n'])} |",
    ]
    return lines


def friction_causes(rows) -> list:
    counts = defaultdict(int)
    for row in rows:
        if row["scenario"] == "legit" and row["status"] != "approved":
            for signal in row["signals"]:
                counts[signal] += 1
    lines = ["| Sinal presente | Pix legítimos com 2FA ou recusa |", "|---|---:|"]
    for signal, count in sorted(counts.items(), key=lambda item: -item[1]):
        lines.append(f"| `{signal}` | {count} |")
    return lines


def latency_table(rows) -> list:
    lines = ["| Caminho | Pix | % dos Pix | p50 | p95 | p99 |", "|---|---:|---:|---:|---:|---:|"]
    for path in ("fast", "deep"):
        values = [r["latency_ms"] for r in rows if r["path"] == path and r["latency_ms"] is not None]
        lines.append(
            f"| {'rápido' if path == 'fast' else 'profundo'} | {len(values)} | {pct(len(values), len(rows))} "
            f"| {percentile(values, 50)} ms | {percentile(values, 95)} ms | {percentile(values, 99)} ms |"
        )
    return lines


def comparison_table(rules, with_ml) -> list:
    base, ml = summary(rules), summary(with_ml)
    lines = [
        "| | Regras sozinhas | Regras + ML (ativo) | Diferença |",
        "|---|---:|---:|---:|",
    ]
    for scenario in ("ato", "app", "mule", "novel"):
        b, m = base[scenario], ml[scenario]
        b_rate = b["caught"] / b["n"] if b["n"] else 0
        m_rate = m["caught"] / m["n"] if m["n"] else 0
        lines.append(
            f"| {SCENARIOS[scenario]} — pego (Pix) | {pct(b['caught'], b['n'])} | {pct(m['caught'], m['n'])} "
            f"| {100 * (m_rate - b_rate):+.1f} p.p. |"
        )
    b, m = base["legit"], ml["legit"]
    for key, label in (("two_factor", "2FA"), ("rejected", "recusa")):
        lines.append(
            f"| Legítimos — {label} | {pct(b[key], b['n'])} | {pct(m[key], m['n'])} "
            f"| {100 * (m[key] / m['n'] - b[key] / b['n']):+.1f} p.p. |"
        )
    return lines


def ml_scores(rows) -> list:
    groups = defaultdict(list)
    for row in rows:
        ml = row.get("ml") or {}
        if ml.get("anomaly_score") is not None:
            groups[row["scenario"]].append(ml["anomaly_score"])
    if not groups:
        return []
    lines = ["| Tipologia | Pix com escore | Escore p50 | Escore p95 |", "|---|---:|---:|---:|"]
    for scenario in SCENARIOS:
        values = groups.get(scenario, [])
        if values:
            lines.append(
                f"| {SCENARIOS[scenario]} | {len(values)} | {percentile(values, 50):.3f} | {percentile(values, 95):.3f} |"
            )
    return lines


FINDINGS = [
    "**Salário que a empresa paga pelo internet banking pede 2FA** (`LIMITE.sem_geolocalizacao`): o computador da "
    "empresa não manda geolocalização, e todo Pix acima de R$ 500 sem ela pede confirmação de limite.",
    "**Aluguel no mês em que o motor ainda não conhece o destino.** O primeiro aluguel, 10x a mediana para um destino "
    "novo, cai no segundo degrau do `PERFIL.valor` e pede 2FA com aviso de golpe. O cliente confirma, mas a "
    "confirmação com aviso de golpe não torna o destino recorrente, e a `CONTA_RECEBEDORA.suspeita_anterior` pede "
    "2FA de novo no mês seguinte: o aluguel da matriz de erros reais volta a ter fricção nesse caso.",
    "**Falso investimento passa.** O primeiro Pix, pequeno e dentro do perfil, é aprovado e torna o destino "
    "recorrente; os seguintes, maiores, ficam atenuados pelo \"destino já pago antes\".",
    "**Celular roubado: o Pix grande é sempre pego, os pequenos passam.** O Pix de teste de R$ 10 e a nova tentativa "
    "de R$ 199 cabem nos R$ 200 por Pix que o BCB permite em aparelho não cadastrado; a perda fica no teto diário.",
    "**Rajada:** a velocidade só pede 2FA a partir do 5º Pix em 10 minutos; os 4 primeiros saem.",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rules")
    parser.add_argument("--ml", help="resultado da mesma semente com o ML em modo ativo")
    parser.add_argument("--output", default="docs/resultados-simulador.md")
    args = parser.parse_args()

    rows, meta = load(args.rules)
    out = [
        "# Resultados do simulador",
        "",
        DISCLAIMER,
        "",
        f"Semente {meta.get('seed', '?')}, {meta.get('clients', '?')} clientes, {len(rows)} Pix, "
        f"{meta.get('seconds', '?')} s de simulação (de maio a meados de junho de 2026). Gerado por "
        "`scripts/simulator/report.py`; como reproduzir está no fim.",
        "",
        "## Resumo",
        "",
        *summary_table(rows),
        "",
        "## Achados para o grupo",
        "",
        *[f"- {finding}" for finding in FINDINGS],
        "",
        "## Por cenário",
        "",
        "\"Pego\" é o Pix de fraude que não saiu aprovado direto (2FA ou recusa). Por valor, cada Pix pesa o que vale: "
        "o Pix de teste de R$ 10 do ladrão pesa menos que o de R$ 5.000.",
        "",
        *scenario_table(rows),
        "",
        "## O que causa a fricção nos clientes legítimos",
        "",
        *friction_causes(rows),
        "",
        "## Caminho e latência",
        "",
        "Latência gravada pelo motor (`latency_ms`), da chegada do Pix à decisão.",
        "",
        *latency_table(rows),
    ]

    scores = ml_scores(rows)
    if scores:
        out += ["", "## Escore de anomalia (modo sombra)", "", *scores]

    if args.ml:
        ml_rows, ml_meta = load(args.ml)
        out += [
            "",
            "## Regras sozinhas × regras + ML",
            "",
            f"A mesma semente ({ml_meta.get('seed', '?')}) com o ML em modo ativo (`ml_mode = active`): o escore soma "
            "pontos de invasão, com teto, e nunca recusa sozinho.",
            "",
            *comparison_table(rows, ml_rows),
            "",
            "### Por cenário, com o ML ativo",
            "",
            *scenario_table(ml_rows),
        ]

    out += [
        "",
        "## Como reproduzir",
        "",
        "```bash",
        "docker compose up -d",
        "python scripts/simulator/prepare_db.py --ml-mode shadow   # APAGA o banco",
        "python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/regras.jsonl",
        "python scripts/simulator/prepare_db.py --ml-mode active",
        "python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/ml.jsonl",
        "python scripts/simulator/report.py scripts/simulator/output/regras.jsonl --ml scripts/simulator/output/ml.jsonl",
        "```",
        "",
    ]

    Path(args.output).write_text("\n".join(out), encoding="utf-8")
    print(f"Relatório em {args.output}")


if __name__ == "__main__":
    main()
