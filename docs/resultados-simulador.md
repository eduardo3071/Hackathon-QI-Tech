# Resultados do simulador

> **Rodada de 18/10, 9h16.** Estes números já refletem os ajustes finais: `CONTA_RECEBEDORA.primeiro_pix_alto`, `PERFIL.escalada`, a exceção da empresa no `LIMITE.sem_geolocalizacao`, o local habitual só depois de 24 h e o `LIMITE.noturno_fora_de_casa`. **A comparação com o ML ativo, no fim, não foi refeita**: é da rodada anterior (item 10 da bateria de realidade), antes desses ajustes. O modelo não foi retreinado; os sinais novos não são features dele.

> **Leia antes dos números.** O simulador é do próprio grupo: os cenários de fraude foram desenhados por nós, conhecendo as regras. Por isso estes números são **teste de regressão da política e medida de fricção**, e **não eficácia**: não dizem quanto o motor pegaria de fraude real. O motor só vê Pix de clientes da QI Tech, e o simulador reproduz isso: 70% dos créditos que as contas recebem vêm de pagadores que o motor nunca vê (salário, vítimas de outros bancos). O cenário "padrão novo" também foi desenhado por nós: ele mostra o mecanismo do ML, não a eficácia dele.

Semente 2, 200 clientes, 6915 Pix, 586 s de simulação (de maio a meados de junho de 2026). Gerado por `scripts/simulator/report.py`; como reproduzir está no fim.

## Resumo

| Tipologia | Pix | Pego (Pix) | Pego (valor) |
|---|---:|---:|---:|
| Conta invadida | 103 | 63.1% | 84.0% |
| Golpe | 48 | 58.3% | 81.5% |
| Conta laranja | 44 | 100.0% | 100.0% |
| Padrão novo (nenhuma regra cobre) | 106 | 0.0% | 0.0% |

| Fricção nos clientes legítimos | Pix | 2FA | Recusa |
|---|---:|---:|---:|
| Todos | 6614 | 2.3% | 0.0% |

## Achados para o grupo

- **Cadastro do aparelho de todo cliente (de propósito, item 9 da bateria de realidade).** 64 dos 188 Pix legítimos com 2FA são `device_registration`: o primeiro Pix acima de R$ 200 de cada cliente, de um aparelho novo, pede biometria (a Res. BCB 403/2024 vale para todos). Em produção o motor nasce com a carga do histórico e isso some.
- **Salário pelo internet banking: de 62 para 16 Pix com 2FA** (25,8%) depois da exceção de 18/10: o `LIMITE.sem_geolocalizacao` não se aplica à empresa no aparelho confiável e no canal de sempre. O que sobra é a primeira folha: o aparelho da empresa ainda não confiável (8 Pix, com o cadastro do aparelho) e a `RITMO.destinos_novos` (7 Pix: vários funcionários que o motor nunca viu em 10 minutos), de propósito.
- **Aluguel ainda tem fricção.** 41 dos 154 Pix de aluguel (26,6%) pedem 2FA, e 35 deles têm `PERFIL.valor`: o primeiro aluguel, 10x a mediana para um destino novo, cai no segundo degrau. A confirmação com aviso de golpe não ensina o perfil nem torna o destino recorrente (item 1), mas a `CONTA_RECEBEDORA.suspeita_anterior` deixou de punir o mês seguinte com valor parecido (item 3).
- **Falso investimento: 9 dos 24 Pix pedem 2FA com aviso** (37,5% dos Pix, 61,1% do valor), contra 2 antes da `PERFIL.escalada` de 18/10: a escalada pega o 3º Pix de cada vítima (9x o valor típico, 3x o primeiro). Os 2 primeiros de cada sequência (2,5x e 5x o típico) ainda saem, a maioria com aviso: sozinhos, parecem normais.
- **Celular roubado: o Pix grande é sempre pego, os pequenos passam.** O Pix de teste de R$ 10 e a nova tentativa de R$ 199 cabem nos R$ 200 por Pix que o BCB permite em aparelho não cadastrado; a perda fica no teto diário.
- **Rajada:** a `RITMO.destinos_novos` (item 6) pede biometria a partir do 3º destino novo somando R$ 2.000, e a velocidade a partir do 5º Pix em 10 minutos; os Pix de rajada pegos subiram de 47,4% para 63,2%.
- **Latência depende da máquina.** Nesta rodada (Windows com Docker Desktop, código montado por volume) o p95 é de algumas centenas de milissegundos, bem acima da rodada anterior, feita em outro ambiente. Não prometer "p95 abaixo de 100 ms" sem medir na máquina da demonstração.

## Por cenário

"Pego" é o Pix de fraude que não saiu aprovado direto (2FA ou recusa). Por valor, cada Pix pesa o que vale: o Pix de teste de R$ 10 do ladrão pesa menos que o de R$ 5.000.

| Cenário | Situação | Pix | Aprovado | (dos quais com aviso) | 2FA | Recusado | Pego (Pix) | Pego (valor) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Clientes legítimos | `aluguel` | 154 | 73.4% | 22.1% | 26.6% | 0.0% | — | — |
| Clientes legítimos | `celular_novo` | 10 | 100.0% | 0.0% | 0.0% | 0.0% | — | — |
| Clientes legítimos | `destino_novo` | 734 | 97.5% | 1.5% | 2.5% | 0.0% | — | — |
| Clientes legítimos | `lojista` | 1097 | 98.5% | 0.3% | 1.5% | 0.0% | — | — |
| Clientes legítimos | `racha` | 929 | 100.0% | 0.1% | 0.0% | 0.0% | — | — |
| Clientes legítimos | `rotina` | 3582 | 98.4% | 1.0% | 1.6% | 0.0% | — | — |
| Clientes legítimos | `salario` | 62 | 74.2% | 40.3% | 25.8% | 0.0% | — | — |
| Clientes legítimos | `viagem` | 46 | 100.0% | 0.0% | 0.0% | 0.0% | — | — |
| Conta invadida | `aparelho_novo` | 8 | 0.0% | 0.0% | 87.5% | 12.5% | 100.0% | 100.0% |
| Conta invadida | `celular_roubado` | 30 | 56.7% | 0.0% | 43.3% | 0.0% | 43.3% | 92.4% |
| Conta invadida | `fora_da_zona` | 8 | 0.0% | 0.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| Conta invadida | `rajada` | 57 | 36.8% | 1.8% | 63.2% | 0.0% | 63.2% | 62.8% |
| Golpe | `falsa_central` | 12 | 25.0% | 8.3% | 75.0% | 0.0% | 75.0% | 85.5% |
| Golpe | `falsa_central_repetido` | 12 | 16.7% | 0.0% | 83.3% | 0.0% | 83.3% | 89.6% |
| Golpe | `falso_investimento` | 24 | 62.5% | 33.3% | 37.5% | 0.0% | 37.5% | 61.1% |
| Conta laranja | `repasse` | 18 | 0.0% | 0.0% | 27.8% | 72.2% | 100.0% | 100.0% |
| Conta laranja | `vitima_para_laranja` | 26 | 0.0% | 0.0% | 61.5% | 38.5% | 100.0% | 100.0% |
| Padrão novo (nenhuma regra cobre) | `centavos` | 106 | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

## O que causa a fricção nos clientes legítimos

| Sinal presente | Pix legítimos com 2FA ou recusa |
|---|---:|
| `LIMITE.aparelho_nao_cadastrado` | 102 |
| `PERFIL.valor` | 51 |
| `LIMITE.sem_geolocalizacao` | 29 |
| `RITMO.destinos_novos` | 8 |
| `PERFIL.escalada` | 8 |
| `QUEM_OPERA.ip_compartilhado` | 7 |
| `RITMO.velocidade` | 2 |
| `QUEM_OPERA.canal_incomum` | 1 |
| `LIMITE.noturno` | 1 |
| `CONTA_RECEBEDORA.conta_nova` | 1 |
| `CONTA_RECEBEDORA.primeiro_pix_alto` | 1 |

## Caminho e latência

Latência gravada pelo motor (`latency_ms`), da chegada do Pix à decisão.

| Caminho | Pix | % dos Pix | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|
| rápido | 1953 | 28.2% | 48 ms | 61 ms | 96 ms |
| profundo | 4962 | 71.8% | 48 ms | 62 ms | 82 ms |

## Escore de anomalia (modo sombra)

| Tipologia | Pix com escore | Escore p50 | Escore p95 |
|---|---:|---:|---:|
| Clientes legítimos | 4661 | 0.443 | 0.562 |
| Conta invadida | 103 | 0.612 | 0.680 |
| Golpe | 48 | 0.574 | 0.629 |
| Conta laranja | 44 | 0.572 | 0.611 |
| Padrão novo (nenhuma regra cobre) | 106 | 0.617 | 0.644 |

## Regras sozinhas × regras + ML (rodada anterior, item 10 da bateria)

A mesma semente (2) com o ML em modo ativo (`ml_mode = active`): o escore soma pontos de invasão, com teto, e nunca recusa sozinho.

| | Regras sozinhas | Regras + ML (ativo) | Diferença |
|---|---:|---:|---:|
| Conta invadida — pego (Pix) | 63.1% | 63.1% | +0.0 p.p. |
| Golpe — pego (Pix) | 43.8% | 43.8% | +0.0 p.p. |
| Conta laranja — pego (Pix) | 100.0% | 100.0% | +0.0 p.p. |
| Padrão novo (nenhuma regra cobre) — pego (Pix) | 0.0% | 2.8% | +2.8 p.p. |
| Clientes legítimos — o ML pontuou (escore acima do corte) | — | 0.9% | — |
| Conta invadida — o ML pontuou (escore acima do corte) | — | 51.5% | — |
| Golpe — o ML pontuou (escore acima do corte) | — | 14.6% | — |
| Conta laranja — o ML pontuou (escore acima do corte) | — | 6.8% | — |
| Padrão novo (nenhuma regra cobre) — o ML pontuou (escore acima do corte) | — | 64.2% | — |
| Legítimos — 2FA | 2.8% | 2.8% | +0.0 p.p. |
| Legítimos — recusa | 0.0% | 0.0% | +0.0 p.p. |

**Conclusão sobre o ML.** O ganho é pequeno. O escore separa: no modo sombra, o padrão novo tem escore mediano acima do corte (p99 dos legítimos do treino), e o ML pontua a maior parte desses Pix. Mas os pontos crescem com o escore e só chegam aos 60 (o corte de invasão, que pede biometria) com o escore 0,04 acima do corte; a maioria dos Pix de centavos ganha poucos pontos e segue aprovada. Nas fraudes que as regras já pegam, o ML não muda nada, e nos legítimos não acrescenta fricção. Recomendação: manter em sombra na entrega e, se o grupo quiser o modo ativo, discutir a escala de pontos (`score_span`) com estes números — sabendo que o cenário "padrão novo" foi desenhado por nós e que uma feature (destinos distintos em 24 h) entrou depois de o ML errar esse cenário no treino.

Treino: semente 1, só os Pix `sim-legit-`; avaliação: semente 2, que o modelo não viu.

### Por cenário, com o ML ativo

| Cenário | Situação | Pix | Aprovado | (dos quais com aviso) | 2FA | Recusado | Pego (Pix) | Pego (valor) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Clientes legítimos | `aluguel` | 154 | 73.4% | 22.1% | 26.6% | 0.0% | — | — |
| Clientes legítimos | `celular_novo` | 10 | 100.0% | 0.0% | 0.0% | 0.0% | — | — |
| Clientes legítimos | `destino_novo` | 734 | 97.5% | 1.5% | 2.5% | 0.0% | — | — |
| Clientes legítimos | `lojista` | 1097 | 98.5% | 0.3% | 1.5% | 0.0% | — | — |
| Clientes legítimos | `racha` | 929 | 100.0% | 0.0% | 0.0% | 0.0% | — | — |
| Clientes legítimos | `rotina` | 3582 | 98.6% | 0.4% | 1.4% | 0.0% | — | — |
| Clientes legítimos | `salario` | 62 | 0.0% | 0.0% | 100.0% | 0.0% | — | — |
| Clientes legítimos | `viagem` | 46 | 100.0% | 0.0% | 0.0% | 0.0% | — | — |
| Conta invadida | `aparelho_novo` | 8 | 0.0% | 0.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| Conta invadida | `celular_roubado` | 30 | 56.7% | 0.0% | 43.3% | 0.0% | 43.3% | 92.4% |
| Conta invadida | `fora_da_zona` | 8 | 0.0% | 0.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| Conta invadida | `rajada` | 57 | 36.8% | 1.8% | 63.2% | 0.0% | 63.2% | 62.8% |
| Golpe | `falsa_central` | 12 | 25.0% | 8.3% | 75.0% | 0.0% | 75.0% | 85.5% |
| Golpe | `falsa_central_repetido` | 12 | 16.7% | 0.0% | 83.3% | 0.0% | 83.3% | 89.6% |
| Golpe | `falso_investimento` | 24 | 91.7% | 58.3% | 8.3% | 0.0% | 8.3% | 18.3% |
| Conta laranja | `repasse` | 18 | 0.0% | 0.0% | 27.8% | 72.2% | 100.0% | 100.0% |
| Conta laranja | `vitima_para_laranja` | 26 | 0.0% | 0.0% | 61.5% | 38.5% | 100.0% | 100.0% |
| Padrão novo (nenhuma regra cobre) | `centavos` | 106 | 97.2% | 0.0% | 2.8% | 0.0% | 2.8% | 3.5% |

## Como reproduzir

```bash
docker compose up -d
python scripts/simulator/prepare_db.py --ml-mode shadow   # APAGA o banco
python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/regras.jsonl
python scripts/simulator/prepare_db.py --ml-mode active
python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/ml.jsonl
python scripts/simulator/report.py scripts/simulator/output/regras.jsonl --ml scripts/simulator/output/ml.jsonl
```
