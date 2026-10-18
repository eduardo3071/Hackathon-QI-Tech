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
    for scenario in SCENARIOS:
        scored = sum(1 for r in with_ml if r["scenario"] == scenario and "ANOMALIA.ml" in r["signals"])
        total = sum(1 for r in with_ml if r["scenario"] == scenario)
        lines.append(f"| {SCENARIOS[scenario]} — o ML pontuou (escore acima do corte) | — | {pct(scored, total)} | — |")
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
    "**Cadastro do aparelho de todo cliente (de propósito, item 9 da bateria de realidade).** 64 dos 188 Pix "
    "legítimos com 2FA são `device_registration`: o primeiro Pix acima de R$ 200 de cada cliente, de um aparelho "
    "novo, pede biometria (a Res. BCB 403/2024 vale para todos). Em produção o motor nasce com a carga do histórico "
    "e isso some.",
    "**Salário pelo internet banking: de 62 para 16 Pix com 2FA** (25,8%) depois da exceção de 18/10: o "
    "`LIMITE.sem_geolocalizacao` não se aplica à empresa no aparelho confiável e no canal de sempre. O que sobra é a "
    "primeira folha: o aparelho da empresa ainda não confiável (8 Pix, com o cadastro do aparelho) e a "
    "`RITMO.destinos_novos` (7 Pix: vários funcionários que o motor nunca viu em 10 minutos), de propósito.",
    "**Aluguel ainda tem fricção.** 41 dos 154 Pix de aluguel (26,6%) pedem 2FA, e 35 deles têm `PERFIL.valor`: o "
    "primeiro aluguel, 10x a mediana para um destino novo, cai no segundo degrau. A confirmação com aviso de golpe "
    "não ensina o perfil nem torna o destino recorrente (item 1), mas a `CONTA_RECEBEDORA.suspeita_anterior` deixou "
    "de punir o mês seguinte com valor parecido (item 3).",
    "**Falso investimento: 9 dos 24 Pix pedem 2FA com aviso** (37,5% dos Pix, 61,1% do valor), contra 2 antes da "
    "`PERFIL.escalada` de 18/10: a escalada pega o 3º Pix de cada vítima (9x o valor típico, 3x o primeiro). Os 2 "
    "primeiros de cada sequência (2,5x e 5x o típico) ainda saem, a maioria com aviso: sozinhos, parecem normais.",
    "**Celular roubado: o Pix grande é sempre pego, os pequenos passam.** O Pix de teste de R$ 10 e a nova tentativa "
    "de R$ 199 cabem nos R$ 200 por Pix que o BCB permite em aparelho não cadastrado; a perda fica no teto diário.",
    "**Rajada:** a `RITMO.destinos_novos` (item 6) pede biometria a partir do 3º destino novo somando R$ 2.000, e a "
    "velocidade a partir do 5º Pix em 10 minutos; os Pix de rajada pegos subiram de 47,4% para 63,2%.",
    "**Latência depende da máquina.** Nesta rodada (Windows com Docker Desktop, código montado por volume) o p95 é de "
    "algumas centenas de milissegundos, bem acima da rodada anterior, feita em outro ambiente. Não prometer "
    "\"p95 abaixo de 100 ms\" sem medir na máquina da demonstração.",
]

ML_CONCLUSION = [
    "**Conclusão sobre o ML.** O ganho é pequeno. O escore separa: no modo sombra, o padrão novo tem escore mediano "
    "acima do corte (p99 dos legítimos do treino), e o ML pontua a maior parte desses Pix. Mas os pontos crescem com o "
    "escore e só chegam aos 60 (o corte de invasão, que pede biometria) com o escore 0,04 acima do corte; a maioria "
    "dos Pix de centavos ganha poucos pontos e segue aprovada. Nas fraudes que as regras já pegam, o ML não muda nada, "
    "e nos legítimos não acrescenta fricção. Recomendação: manter em sombra na entrega e, se o grupo quiser o modo "
    "ativo, discutir a escala de pontos (`score_span`) com estes números — sabendo que o cenário \"padrão novo\" foi "
    "desenhado por nós e que uma feature (destinos distintos em 24 h) entrou depois de o ML errar esse cenário no treino.",
    "",
    "Treino: semente 1, só os Pix `sim-legit-`; avaliação: semente 2, que o modelo não viu.",
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
            *ML_CONCLUSION,
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
