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
botão** e **para onde vai o dinheiro**. A decisão segue a definição do
slide da QI Tech: reprovar é "bloquear quando o risco é claro"; 2FA é
"fricção só onde há dúvida".

- **Recusa só com evidência dura**: marcação de fraude, conta sendo
  esvaziada (velocidade no corte de recusa) ou conta laranja vista por
  **dois** sinais diferentes. Um sinal de laranja sozinho é dúvida — pode
  ser o vendedor de carro usado que acabou de abrir conta.
- **Conta invadida** (`ato`) → `two_factor_required` com **biometria facial
  com prova de vida** (`face_liveness`): o invasor não tem o rosto do
  titular, e no SIM swap ele recebe o SMS.
- **Suspeita de golpe** (`app`, ou um sinal forte de conta laranja) →
  `two_factor_required` com **confirmação no app e aviso de golpe**
  (`in_app_confirmation`, `scam_warning: true`). A vítima manipulada passa
  em qualquer segundo fator (o relatório EBA-ECB 2025 achou fraude *maior*
  em transferências autenticadas com SCA); a fricção útil é o aviso.
- **Golpe com sinal fraco** → `approved` com aviso (`recommended_action: warn`).

Cada Pix passa por camadas, e só aprofunda quando a anterior levanta sinal:

| Camada | Quando roda | O que avalia |
|---|---|---|
| 0 | sempre | marcação de fraude, limites de norma (aparelho não confiável, noturno), velocidade |
| 1 | sempre | leituras das tabelas agregadas: perfil do pagador, conta recebedora |
| gatilho | — | sem sinal de risco e sem contexto de risco (destino novo, aparelho não confiável, noite) → `approved` pelo **caminho rápido** (`metadata.path = "fast"`) |
| 2 | só com sinal, tempo limite de 300 ms | regras de rede e ML (Fases 3 e 4). Estourou o tempo → 2FA pelo motivo que levou até ela, nunca aprovar no escuro |

Antes de avaliar, o motor toma uma trava (`pg_advisory_xact_lock`) sobre o
`id` do Pix, o pagador, o recebedor PF e o aparelho, sempre na mesma ordem: dez Pix
simultâneos do mesmo pagador decidem como se viessem em fila, e nenhuma
contagem é enganada.

Tudo fica gravado: o Pix como chegou, a decisão, **um resultado por sinal**
(inclusive os que passaram) e as features usadas. O perfil do pagador é
feito **só de Pix aprovados** — tentativa recusada não "educa" a linha de
base, mas conta na velocidade.

Os parâmetros — inclusive pontos e cortes — moram na tabela
`rule_parameter` (política versionada `2026.10.1`), nunca em constante no
código.

### Confiança do aparelho

Um aparelho só é **confiável** para um pagador quando tem **pelo menos 2
Pix aprovados** desse pagador **e o primeiro deles foi há pelo menos
24 h**, ou quando passou na **biometria facial** no retorno do 2FA (veja
[O que acontece depois do 2FA](#o-que-acontece-depois-do-2fa)). "Pix
aprovado" inclui o Pix que pediu 2FA e teve retorno `passed`. Biometria
**reprovada** num 2FA por suspeita de invasão bloqueia a confiança do
aparelho por 24 h. Enquanto não é confiável, valem os limites do BCB para aparelho não
cadastrado: R$ 200 por Pix e R$ 1.000 por dia, somando **todos** os Pix
aprovados de aparelhos não confiáveis do pagador no dia de Brasília.
Acima disso, 2FA com `face_liveness`. Aparelho não confiável também conta
como aparelho novo no sinal de perfil (pontua invasão, não golpe).

O motivo é uma brecha concreta: se um Pix aprovado bastasse, o ladrão
"aqueceria" o celular roubado com um Pix de R$ 10, e o seguinte, de
R$ 5.000, sairia sem 2FA. Exigir que o primeiro tenha 24 h faz a confiança
atravessar um dia — o tempo de o titular perceber que perdeu o celular.

### Cliente que o motor ainda não conhece

"Desconhecido" é o pagador sem nenhum Pix gravado no motor. Se a conta
pagadora (`source_account.opening_date`) tem **pelo menos 180 dias**, o
aparelho não pede 2FA até o **limite de partida** do perfil (R$ 1.000):
o sinal sai `not_evaluated`, com a mensagem "o motor ainda não tem
histórico deste pagador". Acima do limite de partida, 2FA com
`face_liveness`. Conta pagadora com menos de 180 dias segue a regra
normal de aparelho não confiável.

Em produção o motor nasceria com a carga do histórico dos clientes; na
avaliação o banco nasce vazio. Sem esta regra, todo cliente seria tratado
como fraude no primeiro dia (qualquer Pix acima de R$ 200 viraria 2FA) —
e com ela o limite continua de pé.

## Regras

São 8 regras compostas no plano; as que estão no ar são as do MVP
(Fase 2). Cada parâmetro é **norma** (com a fonte) ou **estimativa**
(calibrável, sem fonte que o valide para o Pix). Valores em centavos no
código (R$ 200 = 20000).

| Regra | Lógica | Parâmetros | Por quê |
|-------|--------|------------|---------|
| **1. Marcação** `MARCACAO.lista` | Pagador ou recebedor com marcação vigente em `fraud_marker` (simula o DICT) → `rejected`. Vale mesmo na mesma titularidade. | Marcação própria: sempre (**norma**). De outro PSP: últimos 90 dias (**norma**, janela d90 do DICT) | A Res. BCB 587/2026 obriga a rejeitar todas as transações do usuário marcado, como pagador ou recebedor. |
| **2. Limite por contexto** `LIMITE.aparelho_nao_cadastrado` | Aparelho **não confiável** (veja acima) e (valor > R$ 200 ou soma do dia em aparelhos não confiáveis > R$ 1.000) → `two_factor_required` com `face_liveness`. Cliente desconhecido com conta pagadora de 180 dias ou mais: `not_evaluated` até R$ 1.000, 2FA acima. | R$ 200 por Pix; R$ 1.000 por dia (**norma**). 2 Pix aprovados, o primeiro há 24 h; 180 dias de conta pagadora; 24 h de bloqueio depois da biometria reprovada (**estimativa**) | Res. BCB 403/2024 e nota BCB 20231: limite para aparelho não cadastrado, "mesmo que [o golpista] tenha obtido a senha". |
| **2. Limite por contexto** `LIMITE.noturno` | Entre 20h e 6h (Brasília), PF→PF entre pessoas distintas: soma da noite > R$ 1.000 **e** acima do maior Pix noturno já aprovado do pagador → 2FA de limite (`in_app_confirmation`). | R$ 1.000; 20h–6h (**norma**) | Res. BCB 142/2021. O motor não recebe o limite que o cliente configurou, então é **sinal, não teto**: quem já teve aprovado um Pix noturno maior mostrou que o limite dele é maior. |
| **3. Ritmo** `RITMO.velocidade` | Tentativas do pagador em 10 min (janela deslizante, contando recusadas): com a janela somando ≥ R$ 1.000, 5 → 2FA e 10 → `rejected`. Abaixo disso, só 10 tentativas pedem 2FA. O mesmo Pix refeito com `id` novo (mesmo recebedor, mesmo valor) conta **uma** vez. | 5 e 10 em 10 min; R$ 1.000 (**estimativa**) | Quem invade tenta esvaziar a conta rápido; janela deslizante é a prática recomendada. A soma separa o ataque do racha da conta do bar (mediana do Pix P2P: R$ 50), e contar o Pix refeito uma vez só evita empurrar para a recusa quem refaz o Pix depois do 2FA. |
| **4. Perfil** `PERFIL.valor` | Valor > P95 **e** > 5× a mediana dos aprovados em 90 dias (mín. 5 Pix); sem histórico, > R$ 1.000. Destino já pago antes → passa (o aluguel), menos o destino que o pagador só pagou depois de um 2FA com aviso de golpe. Aparelho não confiável → +60 `ato`. Aparelho confiável e destino novo → +40 `app`. | P95, 5×, 5 Pix, 90 dias, R$ 1.000 (**estimativa**) | Res. BCB 403 exige detectar o "não compatível com o perfil", critério que o STJ usou em 2026 (REsp 2.209.868). Fraude média R$ 1.735 vs. mediana P2P R$ 50: por isso mediana e percentil, não média. |
| **6. Conta recebedora** `CONTA_RECEBEDORA.conta_nova` | Conta destino com < 30 dias: primeiro crédito **e** valor fora do perfil → +60 `mule` (sozinho, 2FA com aviso de golpe; com outro sinal de laranja, recusa); só a idade → +20. | 30 dias (**estimativa**) | O art. 39-B da Res. BCB 147 cita o tempo desde a abertura da conta. Sozinha a idade é fraca: muitas laranjas são contas antigas alugadas (RUSI/Lloyds), e muita conta nova é gente de bem. |
| **6. Conta recebedora** `CONTA_RECEBEDORA.fan_in` | ≥ 5 pagadores distintos em 1h para um recebedor **PF** → +40 `mule`. Recebedor PJ fica fora. | 5 em 1h (**estimativa**) | Muitas vítimas convergindo para uma pessoa física é o padrão clássico de conta laranja. Lojista recebe de muitos, por isso PJ não pontua. |

**Mesma titularidade** (pagador = recebedor) não é regra, é contexto: tira
o Pix dos sinais de golpe, de conta laranja e do horário noturno, mas
**não** da marcação, do aparelho não confiável nem da velocidade.

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
   ou `mule`. Corte de 60 nos três; faixa de aviso de golpe a partir de 30;
   recusa por conta laranja exige 2 sinais de laranja diferentes
   (**estimativas**).
5. **Decisão**, com precedência `rejected` > `two_factor_required` > `approved`:

| Situação | Status | `step_up_reason` | `step_up_method` | `scam_warning` |
|---|---|---|---|---|
| Marcação de fraude (`typology: fraud_marker`) | `rejected` | — | — | `false` |
| Placar `mule` ≥ 60 **com 2 ou mais sinais** de conta laranja (`mule_account`) | `rejected` | — | — | `false` |
| 10 tentativas em 10 min somando ≥ R$ 1.000 (`account_takeover`) | `rejected` | — | — | `false` |
| Aparelho não confiável acima do limite, velocidade, ou placar `ato` ≥ 60 | `two_factor_required` | `account_takeover` | `face_liveness` | `true` se também houver suspeita de golpe |
| Placar `app` ≥ 60, ou placar `mule` ≥ 60 com **um** sinal de laranja | `two_factor_required` | `possible_scam` | `in_app_confirmation` | `true` |
| Limite noturno, sem outro sinal | `two_factor_required` | `limit` | `in_app_confirmation` | `false` |
| Placar `app` entre 30 e 59 | `approved` (`recommended_action: warn`) | — | — | `false` |
| Nada disso | `approved` | — | — | `false` |

`recommended_action` vale `block` na recusa, `step_up` no 2FA, `warn` no
aviso e `none` no resto. Se a camada 2 estourar o tempo, o 2FA sai pelo
motivo que levou o Pix até ela.

**Exemplo do slide** (R$ 1.500 às 22h15, primeiro Pix de um cliente que o
motor não conhece, para uma conta PF aberta há 7 dias):

| Sinal | Resultado | Placar |
|---|---|---|
| `LIMITE.aparelho_nao_cadastrado` | cliente desconhecido acima do limite de partida → `two_factor` | — |
| `LIMITE.noturno` | R$ 1.500 PF→PF à noite → `two_factor` | — |
| `PERFIL.valor` | sem histórico, acima de R$ 1.000, aparelho não confiável | `ato` +60 |
| `CONTA_RECEBEDORA.conta_nova` | 7 dias, primeiro crédito, fora do perfil | `mule` +60 |

Placares `ato` 60, `app` 0, `mule` 60. A conta laranja tem um sinal só,
então não recusa. Há motivo de invasão (aparelho) e de golpe (conta
laranja): **`two_factor_required`** com `face_liveness` e
`scam_warning: true`.

O `metadata` de toda resposta traz a versão da política, o caminho
(`fast`/`deep`), as camadas executadas, os placares, e cada sinal: os que
dispararam em `reasons` (com valor observado, limite e mensagem em
português), os que passaram em `passed`, e os dispensados ou sem dado em
`not_needed` e `not_evaluated`.

## O que acontece depois do 2FA

O slide define só o `POST` e o `GET`. Sem um retorno, o Pix que pediu 2FA
ficaria gravado como `two_factor_required` para sempre — mesmo que o
cliente tenha confirmado e o dinheiro tenha saído — e o motor nunca
aprenderia com ele: o celular novo do cliente continuaria "novo", e o Pix
confirmado não entraria no perfil. Por isso acrescentamos o retorno do
2FA:

```bash
curl -s -X PATCH http://localhost:3000/pix/transaction/pix-000123 \
  -H "Content-Type: application/json" \
  -H "INTERNAL-TOKEN: default_token" \
  -d '{"two_factor_result": "passed", "completed_at": "2026-10-17T22:16:10-03:00"}'
```

`two_factor_result` é `passed` ou `failed`; `completed_at` é quando o 2FA
terminou, com fuso. A resposta é o dossiê, igual ao do `GET`:

```json
{
  "key": "e0d9ec07-a7ef-4632-81d2-9f80df2e5a17",
  "status": "approved",
  "metadata": {
    "...": "a decisão original, igual à do POST",
    "initial_status": "two_factor_required",
    "two_factor": {"result": "passed", "completed_at": "2026-10-18T01:16:10+00:00"},
    "status_history": [
      {"from_status": null, "to_status": "two_factor_required", "event_datetime": "2026-10-18T01:15:00+00:00"},
      {"from_status": "two_factor_required", "to_status": "approved", "event_datetime": "2026-10-18T01:16:10+00:00"}
    ]
  }
}
```

**A rota é isolada e removível.** Ela tem um método próprio no resource
(`on_patch`), um no controller (`apply_two_factor_result`), um schema
(`src/schemas/patch_pix_transaction.json`) e arquivos de teste próprios
(`tests/integration/pix_transaction/test_pix_transaction_two_factor_return.py`
e `tests/integration/scenarios/test_two_factor_return_scenarios.py`). Se a
QI Tech disser que o retorno está fora do escopo, a rota sai sem quebrar o
`POST` nem o `GET`.

**Trilha de status.** Toda análise grava um evento em
`analysis_status_event` ao nascer (de nenhum status para o status
decidido, na data do Pix), no padrão do `sample_entity_status_event` do
Base Service. O retorno do 2FA grava um segundo evento —
`two_factor_required → approved` (`passed`) ou
`two_factor_required → rejected` (`failed`), na data do `completed_at` — e
troca o status da análise. É a única troca possível: a decisão em si
(placares, motivos, motivo e método do 2FA) nunca muda, e um índice único
no banco impede um segundo retorno para a mesma análise. O `GET` devolve o
status atual com `initial_status`, `two_factor` e `status_history`; o
`POST`, e o reenvio do mesmo `POST`, continuam devolvendo a resposta do
momento da decisão.

**O que cada resultado ensina ao motor:**

| Resultado | O que o motor aprende | Por quê |
|---|---|---|
| `passed` com `face_liveness` | O aparelho fica **confiável na hora** para este pagador. O Pix entra no perfil, na soma noturna e no par pagador-recebedor | A biometria facial com prova de vida é o cadastro do aparelho que o BCB prevê: quem passou nela é o titular |
| `passed` por `limit` (`in_app_confirmation`) | O Pix entra no perfil, na soma noturna e no par. **Não** cadastra o aparelho, mas conta como Pix aprovado para a regra dos 2 Pix com 24 h | Confirmar um limite no app prova que o cliente quis aquele valor, não quem está com o aparelho |
| `passed` com aviso de golpe (`possible_scam`, ou `scam_warning: true`) | O Pix entra no perfil e na soma noturna, mas o destino **não** vira recorrente (`scam_step_up_count` no par): o atenuante "destino já pago antes" do `PERFIL.valor` deixa de valer para ele | A vítima manipulada passa em qualquer 2FA e, no golpe do falso investimento, confirma o Pix e volta a pagar o mesmo golpista. Se o destino virasse "a conta do mês", o segundo Pix sairia sem fricção |
| `failed` | Status `rejected`. Nada entra no perfil. Se o motivo era `account_takeover`, a confiança do aparelho fica **bloqueada por 24 h** (`step_up_failed_at`): ele não é confiável nesse período, e nenhum Pix aprovado nesse período conta para torná-lo confiável | Biometria reprovada é o sinal mais forte de que outra pessoa está com o aparelho; sem o bloqueio, dois Pix pequenos "limpariam" o aparelho no dia seguinte |

O retorno **não reavalia as regras** (a decisão foi tomada no `POST`) e
**não conta como tentativa** na velocidade: nenhum Pix novo é gravado. Ele
toma a mesma trava do `POST` (`id` do Pix, pagador, recebedor PF e
aparelho), porque atualiza as mesmas agregadas: dois retornos simultâneos
com resultados diferentes viram fila, e o segundo recebe 409.

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

O `GET` é o dossiê: a decisão do `POST`, com o status atual, mais
`initial_status`, `two_factor` e `status_history`.

### Mandar o retorno do 2FA

O `curl` do `PATCH` está em [O que acontece depois do 2FA](#o-que-acontece-depois-do-2fa).

### Respostas da API

| Situação | HTTP |
|---|---|
| Pix novo, analisado e gravado (inclusive quando a decisão é `rejected`) | 201 `{key, status, metadata}` |
| Mesmo `id` com o mesmo conteúdo (retentativa) — documentos comparados só com dígitos, com ou sem máscara | 200 com a análise já gravada, sem reavaliar |
| Mesmo `id` com conteúdo diferente | 409 `QIT001002` |
| JSON fora do schema (campo faltando, tipo errado, campo a mais) | 400 `QIT000001` |
| CPF ou CNPJ com dígito verificador inválido | 422 `QIT001003` |
| IP que não é IPv4 nem IPv6 válido | 422 `QIT001006` |
| Data que não existe no calendário | 422 `QIT001004` |
| `GET` de um `id` desconhecido | 404 `QIT001001` |
| `PATCH` de uma análise em `two_factor_required` | 200 com o dossiê atualizado |
| `PATCH` com o mesmo resultado já gravado (retentativa) | 200 com o dossiê, sem gravar nada |
| `PATCH` com resultado diferente do já gravado | 409 `QIT001008` |
| `PATCH` de uma análise que não pediu 2FA | 409 `QIT001009` |
| `PATCH` com `completed_at` anterior ao `transaction_date` do Pix | 422 `QIT001007` |
| `PATCH` de um `id` desconhecido | 404 `QIT001001` |
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
