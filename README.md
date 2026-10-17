# Grupo 47 — Motor Antifraude Pix

**Integrantes:** _a preencher_

API que recebe um Pix e responde, antes de o dinheiro sair, uma de três
decisões — `approved`, `two_factor_required` ou `rejected` — sempre com o
motivo explicável em `metadata`. Feita a partir do Base Service do
Bootcamp QI Tech, com as mesmas camadas e o mesmo padrão de erros.

O plano completo está em [`docs/PLANO.md`](docs/PLANO.md), e a pesquisa
com a fonte de cada parâmetro em
[`docs/pesquisa-fraude-pix.md`](docs/pesquisa-fraude-pix.md).

## Como o motor de decisão funciona

O motor responde duas perguntas antes de decidir: **quem está apertando o
botão** e **para onde vai o dinheiro**. E decide pelo *tipo* de fraude,
não só pela intensidade:

- **Conta invadida** (`ato`) → `two_factor_required`: o invasor não tem o
  segundo fator.
- **Golpe** (`app`) e **conta laranja** (`mule`) → `rejected`: a vítima
  manipulada passa no 2FA, então pedir 2FA não protege ninguém (o
  relatório EBA-ECB 2025 achou fraude *maior* em transferências
  autenticadas com SCA).

Cada Pix passa por camadas, e só aprofunda quando a anterior levanta sinal:

| Camada | Quando roda | O que avalia |
|---|---|---|
| 0 | sempre | marcação de fraude, limites de norma (aparelho não cadastrado, noturno), velocidade |
| 1 | sempre | leituras das tabelas agregadas: perfil do pagador, conta recebedora |
| gatilho | — | sem sinal de risco e sem contexto de risco (destino novo, aparelho novo, noite) → `approved` pelo **caminho rápido** (`metadata.path = "fast"`) |
| 2 | só com sinal, tempo limite de 300 ms | regras de rede e ML (Fases 3 e 4). Estourou o tempo → 2FA, nunca aprovar no escuro |

Antes de avaliar, o motor toma uma trava (`pg_advisory_xact_lock`) sobre o
pagador, o recebedor PF e o aparelho, sempre na mesma ordem: dez Pix
simultâneos do mesmo pagador decidem como se viessem em fila, e nenhuma
contagem é enganada.

Tudo fica gravado: o Pix como chegou, a decisão, **um resultado por sinal**
(inclusive os que passaram) e as features usadas. O perfil do pagador é
feito **só de Pix aprovados** — tentativa recusada não "educa" a linha de
base, mas conta na velocidade.

Os parâmetros moram na tabela `rule_parameter` (política versionada
`2026.10.1`), nunca em constante no código.

## Regras

São 8 regras compostas no plano; as que estão no ar são as do MVP
(Fase 2). Cada parâmetro é **norma** (com a fonte) ou **estimativa**
(calibrável, sem fonte que o valide para o Pix). Valores em centavos no
código (R$ 200 = 20000).

| Regra | Lógica | Parâmetros | Por quê |
|-------|--------|------------|---------|
| **1. Marcação** `MARCACAO.lista` | Pagador ou recebedor com marcação vigente em `fraud_marker` (simula o DICT) → `rejected`. Vale mesmo na mesma titularidade. | Marcação própria: sempre (**norma**). De outro PSP: últimos 90 dias (**norma**, janela d90 do DICT) | A Res. BCB 587/2026 obriga a rejeitar todas as transações do usuário marcado, como pagador ou recebedor. |
| **2. Limite por contexto** `LIMITE.aparelho_nao_cadastrado` | Aparelho sem Pix aprovado deste pagador e (valor > R$ 200 ou soma do dia em aparelhos não cadastrados > R$ 1.000) → `two_factor_required`. O 2FA é o cadastro do aparelho. | R$ 200 por Pix; R$ 1.000 por dia (**norma**) | Res. BCB 403/2024 e nota BCB 20231: limite para aparelho não cadastrado, "mesmo que [o golpista] tenha obtido a senha". |
| **2. Limite por contexto** `LIMITE.noturno` | Entre 20h e 6h (Brasília), PF→PF entre pessoas distintas: soma da noite > R$ 1.000 **e** acima do maior Pix noturno já aprovado do pagador → 2FA; com placar de golpe ou laranja > 0, recusa. | R$ 1.000; 20h–6h (**norma**) | Res. BCB 142/2021. O motor não recebe o limite que o cliente configurou, então é **sinal, não teto**: quem já teve aprovado um Pix noturno maior mostrou que o limite dele é maior. |
| **3. Ritmo** `RITMO.velocidade` | Tentativas do pagador em 10 min (janela deslizante, contando recusadas): com a janela somando ≥ R$ 1.000, 5 → 2FA e 10 → `rejected`. Abaixo disso, só 10 tentativas pedem 2FA. | 5 e 10 em 10 min; R$ 1.000 (**estimativa**) | Quem invade tenta esvaziar a conta rápido; janela deslizante é a prática recomendada. A soma separa o ataque do racha da conta do bar (mediana do Pix P2P: R$ 50). |
| **4. Perfil** `PERFIL.valor` | Valor > P95 **e** > 5× a mediana dos aprovados em 90 dias (mín. 5 Pix); sem histórico, > R$ 1.000. Destino já pago antes → passa (o aluguel). Aparelho novo → +60 `ato`. Aparelho conhecido e destino novo → +40 `app`. | P95, 5×, 5 Pix, 90 dias, R$ 1.000 (**estimativa**) | Res. BCB 403 exige detectar o "não compatível com o perfil", critério que o STJ usou em 2026 (REsp 2.209.868). Fraude média R$ 1.735 vs. mediana P2P R$ 50: por isso mediana e percentil, não média. |
| **6. Conta recebedora** `CONTA_RECEBEDORA.conta_nova` | Conta destino com < 30 dias: primeiro crédito **e** valor fora do perfil → +60 `mule` (recusa sozinho); só a idade → +20. | 30 dias (**estimativa**) | O art. 39-B da Res. BCB 147 cita o tempo desde a abertura da conta. Sozinha a idade é fraca: muitas laranjas são contas antigas alugadas (RUSI/Lloyds). |
| **6. Conta recebedora** `CONTA_RECEBEDORA.fan_in` | ≥ 5 pagadores distintos em 1h para um recebedor **PF** → +40 `mule`. Recebedor PJ fica fora. | 5 em 1h (**estimativa**) | Muitas vítimas convergindo para uma pessoa física é o padrão clássico de conta laranja. Lojista recebe de muitos, por isso PJ não pontua. |

**Mesma titularidade** (pagador = recebedor) não é regra, é contexto: tira
o Pix dos sinais de golpe, de conta laranja e do horário noturno, mas
**não** da marcação, do aparelho não cadastrado nem da velocidade.

**Ainda não implementado** (Fases 3 e 4 do plano): Regra 5 (aparelho
compartilhado, viagem impossível, fora da zona habitual), `LIMITE.sem_geolocalizacao`,
`RITMO.fracionamento`, conta dormente e várias instituições (Regra 6),
Regra 7 (repasse rápido, proximidade de conta marcada), Regra 8 (anomalia
por ML), cadeia de hashes e `latency_ms`.

## Como as regras viram decisão

1. **Trava** por pagador, recebedor PF e aparelho, em ordem crescente de chave.
2. **Camadas 0 e 1** rodam sempre; cada sinal devolve `pass`, `warn`
   (pontua), `two_factor`, `reject`, `not_evaluated` (sem dado ou
   desligado) ou `not_needed` (dispensado: mesma titularidade, recebedor PJ).
3. **Gatilho**: sem sinal e sem contexto de risco → caminho rápido. Senão,
   **camada 2** com tempo limite.
4. **Placares**: cada sinal que pontua soma no seu placar — `ato`, `app`
   ou `mule`. Corte de 60 nos três; faixa de aviso de golpe a partir de 30
   (**estimativas**).
5. **Decisão**, com precedência `rejected` > `two_factor_required` > `approved`:

| Situação | Status | `recommended_action` | `typology` |
|---|---|---|---|
| Marcação de fraude | `rejected` | `block` | `fraud_marker` |
| Placar `mule` ≥ 60 | `rejected` | `block` | `mule_account` |
| Placar `app` ≥ 60 | `rejected` | `hold_timer` | `app_scam` |
| 10 tentativas em 10 min somando ≥ R$ 1.000 | `rejected` | `block` | `account_takeover` |
| Noturno acima do limite **com** placar `app` ou `mule` > 0 | `rejected` | `block` / `hold_timer` | `mule_account` / `app_scam` |
| Aparelho não cadastrado acima do limite, velocidade, ou placar `ato` ≥ 60 | `two_factor_required` | `step_up` | `account_takeover` |
| Noturno acima do limite, sozinho, ou camada 2 estourou o tempo | `two_factor_required` | `step_up` | — |
| Placar `app` entre 30 e 59 | `approved` | `warn` | `app_scam` |
| Nada disso | `approved` | `none` | — |

`hold_timer` é a recusa por **suspeita** de golpe: em produção, viraria a
retenção de 30/60 minutos que o BCB prevê, e não uma recusa definitiva.
`warn` é o aviso antes de concluir (como o Alerta Pix): no golpe com sinal
fraco, 2FA não ajuda e recusar seria fricção demais.

O `metadata` de toda resposta traz a versão da política, o caminho
(`fast`/`deep`), as camadas executadas, os placares, e cada sinal: os que
dispararam em `reasons` (com valor observado, limite e mensagem em
português), os que passaram em `passed`, e os dispensados ou sem dado em
`not_needed` e `not_evaluated`.

## Como rodar e testar

Precisa de **Docker** (com `docker compose`) e de **Python 3.11 ou mais
novo** para os testes.

```bash
docker compose up
```

Espere o `api` ficar `(healthy)`. A API atende em `http://localhost:3000`.

### O `INTERNAL-TOKEN`

Toda rota, menos `/` e `/health_check`, exige o header `INTERNAL-TOKEN`.
O valor padrão é `default_token` (vem do `docker-compose.yml`; para
trocar, copie o `.env.example` para `.env`). Sem ele, a resposta é 403.

### Mandar um Pix

```bash
curl -s -X POST http://localhost:3000/pix/transaction \
  -H "Content-Type: application/json" \
  -H "INTERNAL-TOKEN: default_token" \
  -d '{
    "id": "pix-000123", "amount": 150000, "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {
      "branch": "0001", "account_number": "88213", "opening_date": "2025-03-02T10:00:00-03:00",
      "owner": {"document_number": "123.456.789-09"}
    },
    "destination_account": {
      "participant": "60701190", "branch": "3675", "account_number": "10442",
      "opening_date": "2026-10-10T09:00:00-03:00",
      "owner": {"document_number": "987.654.321-00"}
    },
    "source": {
      "device_id": "dvc-9f2c71a8", "channel": "app", "ip": "198.51.100.23",
      "geolocation": {"latitude": -23.56, "longitude": -46.65}
    }
  }'
```

### Consultar a análise gravada

```bash
curl -s http://localhost:3000/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
```

### Respostas da API

| Situação | HTTP |
|---|---|
| Pix novo, analisado e gravado (inclusive quando a decisão é `rejected`) | 201 `{key, status, metadata}` |
| Mesmo `id` com o mesmo conteúdo (retentativa) | 200 com a análise já gravada, sem reavaliar |
| Mesmo `id` com conteúdo diferente | 409 `QIT001002` |
| JSON fora do schema (campo faltando, tipo errado, campo a mais) | 400 `QIT000001` |
| CPF ou CNPJ com dígito verificador inválido | 422 `QIT001003` |
| Data que não existe no calendário | 422 `QIT001004` |
| `GET` de um `id` desconhecido | 404 `QIT001001` |
| Sem `INTERNAL-TOKEN` ou com o token errado | 403 `QIT000002` |

Uma recusa antifraude **não é erro HTTP**: o Pix foi analisado com
sucesso, e a resposta é 201 com `status: rejected`.

### Marcações de demonstração

O seed do `database/database.sql` traz documentos fictícios marcados, para
a demonstração e para os testes:

| Documento | Marcação | Efeito |
|---|---|---|
| `111.444.777-35` | própria, vigente | recusa |
| `222.555.888-46` | de outro PSP, há menos de 90 dias | recusa |
| `333.666.999-57` | de outro PSP, há mais de 90 dias | não decide |
| `444.777.000-83` | própria, vencida | não decide |

### Rodar os testes

Os testes são caixa-preta: falam com a API só por HTTP e nenhum arquivo
de teste importa código de `src/`. Com a API de pé, em outro terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate          # no Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

### Mudou o `database/database.sql`?

Ele só roda quando o banco nasce. Para recriar o banco do zero:

```bash
docker compose down -v
docker compose up
```

## Como o projeto é organizado

A seta anda num sentido só: `resources → controllers → repositories →
models`. O mapa de cada pasta está em
[`docs/como-o-projeto-e-organizado.md`](docs/como-o-projeto-e-organizado.md).
