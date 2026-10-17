# Resultados do simulador

> **Leia antes dos números.** O simulador é do próprio grupo: os cenários de fraude foram desenhados por nós, conhecendo as regras. Por isso estes números são **teste de regressão da política e medida de fricção**, e **não eficácia**: não dizem quanto o motor pegaria de fraude real. O motor só vê Pix de clientes da QI Tech, e o simulador reproduz isso: 70% dos créditos que as contas recebem vêm de pagadores que o motor nunca vê (salário, vítimas de outros bancos). O cenário "padrão novo" também foi desenhado por nós: ele mostra o mecanismo do ML, não a eficácia dele.

Semente 2, 200 clientes, 6915 Pix, 494 s de simulação (de maio a meados de junho de 2026). Gerado por `scripts/simulator/report.py`; como reproduzir está no fim.

## Resumo

| Tipologia | Pix | Pego (Pix) | Pego (valor) |
|---|---:|---:|---:|
| Conta invadida | 103 | 51.5% | 77.5% |
| Golpe | 48 | 37.5% | 65.0% |
| Conta laranja | 44 | 70.5% | 91.0% |
| Padrão novo (nenhuma regra cobre) | 106 | 0.0% | 0.0% |

| Fricção nos clientes legítimos | Pix | 2FA | Recusa |
|---|---:|---:|---:|
| Todos | 6614 | 2.1% | 0.0% |

## Achados para o grupo

- **Salário que a empresa paga pelo internet banking pede 2FA** (`LIMITE.sem_geolocalizacao`): o computador da empresa não manda geolocalização, e todo Pix acima de R$ 500 sem ela pede confirmação de limite.
- **Aluguel no mês em que o motor ainda não conhece o destino.** O primeiro aluguel, 10x a mediana para um destino novo, cai no segundo degrau do `PERFIL.valor` e pede 2FA com aviso de golpe. O cliente confirma, mas a confirmação com aviso de golpe não torna o destino recorrente, e a `CONTA_RECEBEDORA.suspeita_anterior` pede 2FA de novo no mês seguinte: o aluguel da matriz de erros reais volta a ter fricção nesse caso.
- **Falso investimento passa.** O primeiro Pix, pequeno e dentro do perfil, é aprovado e torna o destino recorrente; os seguintes, maiores, ficam atenuados pelo "destino já pago antes".
- **Celular roubado: o Pix grande é sempre pego, os pequenos passam.** O Pix de teste de R$ 10 e a nova tentativa de R$ 199 cabem nos R$ 200 por Pix que o BCB permite em aparelho não cadastrado; a perda fica no teto diário.
- **Rajada:** a velocidade só pede 2FA a partir do 5º Pix em 10 minutos; os 4 primeiros saem.

## Por cenário

"Pego" é o Pix de fraude que não saiu aprovado direto (2FA ou recusa). Por valor, cada Pix pesa o que vale: o Pix de teste de R$ 10 do ladrão pesa menos que o de R$ 5.000.

| Cenário | Situação | Pix | Aprovado | (dos quais com aviso) | 2FA | Recusado | Pego (Pix) | Pego (valor) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Clientes legítimos | `aluguel` | 154 | 66.2% | 20.1% | 33.8% | 0.0% | — | — |
| Clientes legítimos | `celular_novo` | 10 | 100.0% | 0.0% | 0.0% | 0.0% | — | — |
| Clientes legítimos | `destino_novo` | 734 | 98.9% | 1.2% | 1.1% | 0.0% | — | — |
| Clientes legítimos | `lojista` | 1097 | 99.8% | 0.1% | 0.2% | 0.0% | — | — |
| Clientes legítimos | `racha` | 929 | 100.0% | 0.0% | 0.0% | 0.0% | — | — |
| Clientes legítimos | `rotina` | 3582 | 99.6% | 0.0% | 0.4% | 0.0% | — | — |
| Clientes legítimos | `salario` | 62 | 0.0% | 0.0% | 100.0% | 0.0% | — | — |
| Clientes legítimos | `viagem` | 46 | 100.0% | 0.0% | 0.0% | 0.0% | — | — |
| Conta invadida | `aparelho_novo` | 8 | 0.0% | 0.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| Conta invadida | `celular_roubado` | 30 | 66.7% | 0.0% | 33.3% | 0.0% | 33.3% | 89.3% |
| Conta invadida | `fora_da_zona` | 8 | 0.0% | 0.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| Conta invadida | `rajada` | 57 | 52.6% | 5.3% | 47.4% | 0.0% | 47.4% | 47.7% |
| Golpe | `falsa_central` | 12 | 25.0% | 8.3% | 75.0% | 0.0% | 75.0% | 85.5% |
| Golpe | `falsa_central_repetido` | 12 | 25.0% | 0.0% | 75.0% | 0.0% | 75.0% | 84.5% |
| Golpe | `falso_investimento` | 24 | 100.0% | 4.2% | 0.0% | 0.0% | 0.0% | 0.0% |
| Conta laranja | `repasse` | 18 | 0.0% | 0.0% | 38.9% | 61.1% | 100.0% | 100.0% |
| Conta laranja | `vitima_para_laranja` | 26 | 50.0% | 0.0% | 34.6% | 15.4% | 50.0% | 66.7% |
| Padrão novo (nenhuma regra cobre) | `centavos` | 106 | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

## O que causa a fricção nos clientes legítimos

| Sinal presente | Pix legítimos com 2FA ou recusa |
|---|---:|
| `PERFIL.valor` | 89 |
| `LIMITE.sem_geolocalizacao` | 83 |
| `LIMITE.aparelho_nao_cadastrado` | 46 |
| `CONTA_RECEBEDORA.suspeita_anterior` | 9 |
| `QUEM_OPERA.ip_compartilhado` | 7 |
| `RITMO.velocidade` | 2 |
| `QUEM_OPERA.canal_incomum` | 1 |
| `LIMITE.noturno` | 1 |
| `CONTA_RECEBEDORA.conta_nova` | 1 |

## Caminho e latência

Latência gravada pelo motor (`latency_ms`), da chegada do Pix à decisão.

| Caminho | Pix | % dos Pix | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|
| rápido | 2831 | 40.9% | 37 ms | 50 ms | 57 ms |
| profundo | 4084 | 59.1% | 37 ms | 50 ms | 56 ms |

## Como reproduzir

```bash
docker compose up -d
python scripts/simulator/prepare_db.py --ml-mode shadow   # APAGA o banco
python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/regras.jsonl
python scripts/simulator/prepare_db.py --ml-mode active
python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/ml.jsonl
python scripts/simulator/report.py scripts/simulator/output/regras.jsonl --ml scripts/simulator/output/ml.jsonl
```
