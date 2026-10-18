# Guia para terminar o projeto (passo a passo, na sua máquina)

Este guia leva o projeto de onde ele está hoje (Fases 0 a 4 prontas no `main`, sem validação no Docker) até a
entrega: link do repositório no Slack (grupo da final) até **domingo 18/10, 12h**. O código congela às **10h30**.

Leia a seção 0 inteira antes de começar. Depois, siga as seções em ordem: cada uma tem os comandos, o resultado
esperado e o que fazer se der errado.

---

## 0. Onde estamos e o que falta

**Pronto no `main`** (commit `80f7033` ou mais novo), mas validado **sem Docker**: o ambiente onde o código foi
escrito não conseguia baixar imagens do Docker Hub. Os testes rodaram com Postgres 16 e a API fora do container,
contra o mesmo `database/database.sql`:

| Fase | O que tem | Testes |
|---|---|---|
| 1 | Banco, `POST`/`GET /pix/transaction`, idempotência, erros com código `QIT` | contrato |
| 2 | Motor em camadas, placares (`ato`, `app`, `mule`), trava por pagador/recebedor/aparelho | regras e concorrência |
| Revisões de 17/10 | Recusa só com evidência dura, 2FA com motivo e método, confiança do aparelho, retorno do 2FA (`PATCH`), `suspeita_anterior`, período de aprendizado, perfil graduado | cenários de ponta a ponta |
| 3 | 12 sinais novos (Regras 5 e 7, restos das Regras 2, 3 e 6) e `latency_ms` | um teste por sinal |
| 4 | Simulador (`scripts/simulator/`), Isolation Forest (`scripts/ml/`, `src/ml/`), Regra 8 `ANOMALIA.ml` em modo sombra | 170 testes no total |

**Falta**, nesta ordem (a ordem é o corte: se o tempo acabar, o que ficar no fim sai):

| # | Tarefa | Seção | Tempo estimado |
|---|---|---|---|
| 1 | Preparar a máquina e clonar | 1 | 20 min |
| 2 | **Validar tudo no Docker** (é como o jurado vai rodar) | 2 | 30 min |
| 3 | Retreinar o modelo dentro do container | 3 | 10 min |
| 4 | Correções da bateria de realidade (10 itens) | 4 | 3 a 5 h |
| 5 | Fase 5: README final, clone limpo, congelamento e tag | 5 | 2 a 3 h |
| 6 | Apresentação: roteiro, demo ao vivo, ensaio, perguntas | 6 | 1 h 30 |
| 7 | Entrega no Slack | 7 | 5 min |

**Cronograma sugerido:** seções 1 a 3 hoje à noite; seção 4 até a madrugada; seção 5 no domingo às 8h, com o código
congelado às 10h30; seção 6 em paralelo com a 5 (quem não está com o Claude Code prepara a apresentação); link no
Slack até 11h45.

**Já, antes de tudo:** perguntem no Slack do hackathon se o `PATCH /pix/transaction/{id}` (retorno do 2FA) está
dentro do escopo. O slide só define o POST e o GET. Se a resposta for "fora", a rota é isolada e sai sem quebrar o
resto (ver o README e o CLAUDE.md), mas é melhor saber antes da Fase 5.

**Fica de fora, de propósito:** a cadeia de hashes por pagador (item 14 da Fase 3). O plano a marca como "a
primeira a cortar". Só façam se sobrar tempo depois da seção 6; o README a descreve como "considerado e
descartado" (ver o prompt da Fase 5).

**Como trabalhar com o Claude Code.** As seções 4 e 5 são prompts para colar no Claude Code, aberto na pasta do
repositório (`claude` no terminal). Na sua máquina ele tem Docker, então consegue validar o que o ambiente
anterior não conseguiu. Regras que valem para todos os prompts:

- O `CLAUDE.md` da raiz é a fonte de verdade. Se o Claude Code disser que algo conflita com ele, **leia e decida**:
  não deixe ele seguir sozinho.
- Um prompt de cada vez. Espere a resposta final, confira a contagem da suíte e só então passe ao próximo.
- Cada prompt trabalha num branch próprio e faz o merge no `main` no fim. Confira com `git log --oneline -5`.

---

## 1. Preparar a máquina

### 1.1 Programas

| Programa | Versão | Como conferir |
|---|---|---|
| Git | qualquer recente | `git --version` |
| Docker Desktop, **aberto e rodando** | com `docker compose` | `docker compose version` |
| Python | 3.11 ou mais novo | `python3 --version` (Windows: `python --version`) |
| Claude Code | — | `claude --version` |

**Acesso ao repositório.** O repositório é `eduardo3071/Hackathon-QI-Tech`. Quem for fazer push precisa ser
colaborador com permissão de escrita (o Eduardo adiciona em GitHub → Settings → Collaborators). Confira na 1.3.

### 1.2 Docker Hub

O `docker compose up` baixa `postgres:16` e `python:3.11-slim`. Sem login, o Docker Hub limita os downloads, e o
erro é `429 Too Many Requests`. Para evitar:

```bash
docker login        # conta gratuita do Docker Hub
```

### 1.3 Clonar

```bash
git clone https://github.com/eduardo3071/Hackathon-QI-Tech.git
cd Hackathon-QI-Tech
git checkout main
git pull
git log --oneline -3      # o primeiro deve ser 80f7033 (este guia) ou mais novo
git push --dry-run origin main     # "Everything up-to-date" = você tem acesso de escrita
```

Se o `--dry-run` der `403` ou `Permission denied`, peça o acesso antes de seguir: as seções 3 a 5 fazem push.

### 1.4 Ambiente Python dos testes

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

**No Windows**, crie o `.env` e troque o endereço da API, porque o Windows não conecta em `0.0.0.0`:

```bash
cp .env.example .env               # Windows: copy .env.example .env
# no .env, troque  SERVER_LOCALHOST=0.0.0.0  por  SERVER_LOCALHOST=127.0.0.1
```

Isso também é um risco para o jurado, se ele usar Windows. Anote para a Fase 5 (seção 5.2).

---

## 2. Validar tudo no Docker (Fases 1 a 4)

### 2.1 Subir do zero

```bash
docker compose down -v             # apaga o banco antigo, se existir
docker compose up --build -d
docker compose ps                  # espere a coluna STATUS mostrar "(healthy)" no api e no db
```

Se o `api` não ficar healthy: `docker compose logs api` e `docker compose logs db`.

**Portão da Fase 1:** o banco nasce do zero sem erro (`docker compose logs db` sem `ERROR`) e a API responde:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/health_check     # 204
```

### 2.2 A suíte inteira

```bash
pytest -q
```

**Esperado: `170 passed`.** É o portão das Fases 2, 3 e 4 ao mesmo tempo.

Se falhar:

- `Não consegui falar com a API` → a API não está de pé, ou (no Windows) falta o `SERVER_LOCALHOST=127.0.0.1` da 1.4;
- erro de coluna ou tabela inexistente → o banco é de uma versão anterior: `docker compose down -v && docker compose up -d`;
- teste de concorrência falhando de vez em quando → rode `pytest -q tests/integration/rules/test_concurrency.py` 5 vezes e anote;
- qualquer outra falha → **pare**, cole a saída no Claude Code e peça o diagnóstico, sem mudar regra ainda.

### 2.3 Conferência manual (o que o jurado vê)

No **Windows**, o `curl` do PowerShell é outro programa e não aceita esses comandos. Use o Git Bash (vem com o
Git) e cole os comandos como estão. Ou, no PowerShell, chame `curl.exe`, salve o JSON num arquivo (`pix.json`) e
mande com `-d "@pix.json"`.

**POST do exemplo do slide** (R$ 1.500 às 22h15, destino aberto há 7 dias):

```bash
curl -s -X POST http://localhost:3000/pix/transaction \
  -H "Content-Type: application/json" -H "INTERNAL-TOKEN: default_token" \
  -d '{
    "id": "pix-000123", "amount": 150000, "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {"branch": "0001", "account_number": "88213", "opening_date": "2025-03-02T10:00:00-03:00",
                       "owner": {"document_number": "123.456.789-09"}},
    "destination_account": {"participant": "60701190", "branch": "3675", "account_number": "10442",
                            "opening_date": "2026-10-10T09:00:00-03:00", "owner": {"document_number": "987.654.321-00"}},
    "source": {"device_id": "dvc-9f2c71a8", "channel": "app", "ip": "198.51.100.23",
               "geolocation": {"latitude": -23.56, "longitude": -46.65}}
  }'
```

Esperado: HTTP 201, `"status": "two_factor_required"`, `step_up_method: "face_liveness"`, `scam_warning: true`,
e no `metadata` o bloco `ml` (modo `shadow`) e o `latency_ms`.

**GET** (o dossiê):

```bash
curl -s http://localhost:3000/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
```

Esperado: a mesma decisão, mais `initial_status`, `two_factor: null` e `status_history` com 1 evento.

**PATCH** (retorno do 2FA):

```bash
curl -s -X PATCH http://localhost:3000/pix/transaction/pix-000123 \
  -H "Content-Type: application/json" -H "INTERNAL-TOKEN: default_token" \
  -d '{"two_factor_result": "passed", "completed_at": "2026-10-17T22:16:10-03:00"}'
```

Esperado: HTTP 200, `"status": "approved"`, `initial_status: "two_factor_required"` e 2 eventos no histórico.
Repetir o mesmo PATCH dá 200; mandar `"failed"` depois dá 409.

**Sem token:** o mesmo GET sem o header `INTERNAL-TOKEN` → 403.

### 2.4 Simulador (opcional nesta etapa, ~8 min)

Confere que a Fase 4 roda no Docker. **O `prepare_db.py` apaga o banco.**

```bash
python scripts/simulator/prepare_db.py --ml-mode shadow
python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/regras.jsonl
python scripts/simulator/report.py scripts/simulator/output/regras.jsonl --output scripts/simulator/output/resultado.md
```

A pasta `scripts/simulator/output/` não vai para o Git. Compare o resumo do `scripts/simulator/output/resultado.md` com o do `docs/resultados-simulador.md`. Os números devem ser os
mesmos, porque a semente é fixa; só a latência muda. Depois, volte o banco ao normal antes dos testes:

```bash
docker compose down -v && docker compose up -d
```

---

## 3. Retreinar o modelo dentro do container

O CLAUDE.md pede o treino dentro do container. O ambiente anterior não tinha Docker, então o modelo foi treinado
fora dele, com as mesmas versões do `requirements.txt`. O artefato é um JSON lido em Python puro: a API não depende
da versão de quem treinou. Mesmo assim, retreinar aqui cumpre o combinado:

```bash
docker compose build api                               # a imagem precisa ter o scikit-learn do requirements.txt
python scripts/simulator/prepare_db.py --ml-mode shadow  # APAGA o banco
python scripts/simulator/run.py --seed 1 --output scripts/simulator/output/treino.jsonl   # treino: semente 1
docker compose run --rm -u root -v "$PWD/scripts:/scripts" -e PYTHONPATH=/app api \
    python /scripts/ml/train.py --output /app/ml/artifacts/iforest-v1.json
```

No Windows (PowerShell), troque `"$PWD/scripts:/scripts"` por `"${PWD}/scripts:/scripts"`.

Esperado: `Inferência exportada = scikit-learn (maior diferença 0.0000xx)` e os percentis do escore. Se o
`git diff --stat` mostrar `src/ml/artifacts/iforest-v1.json` alterado, rode `pytest -q` (com o banco recriado) e
faça o commit:

```bash
docker compose down -v && docker compose up -d && pytest -q
git checkout -b claude/ml-container
git add src/ml/artifacts/iforest-v1.json
git commit -m "Modelo de anomalia retreinado dentro do container"
git checkout main && git merge --ff-only claude/ml-container && git push origin main
```

Se o item 10 da seção 4 mudar as features, o retreino acontece lá de novo; este aqui não se perde.

---

## 4. Correções da bateria de realidade

A bateria (`scripts/realidade/bateria_realidade.py`, já no repositório) simula 90 clientes com a distribuição
real do Pix e encena 12 golpes reais. Ela achou falhas de desenho, e o prompt abaixo corrige 10 delas.

### 4.1 Antes de colar o prompt

```bash
git checkout main && git pull
docker compose down -v && docker compose up -d && pytest -q     # 170 passed
```

O que o Claude Code precisa saber, além do prompt. Cole junto, logo abaixo dele:

> **Notas do estado atual (17/10, noite):**
> - O `main` já tem a Fase 4. O simulador está em `scripts/simulator/`, o modelo em `src/ml/` e `scripts/ml/`, e a Regra 8 `ANOMALIA.ml` está em modo sombra.
> - A bateria já está em `scripts/realidade/bateria_realidade.py`. Ela grava a saída em `docs/bateria-realidade.md` (2º argumento muda o caminho) e usa datas de agosto a outubro de 2026, as mesmas dos testes: rode-a **sempre** contra um banco recriado (`docker compose down -v && docker compose up -d`), nunca depois do `pytest`.
> - O item 9 desfaz, de propósito, o "período de aprendizado" (commit "Período de aprendizado do cliente que o motor ainda não conhece"). Os testes `test_learning_period_lasts_while_no_device_is_trusted` e `test_learning_period_ends_once_the_payer_has_a_trusted_device` (em `tests/integration/rules/test_rule_limite.py`) e o cenário "Período de aprendizado" do CLAUDE.md mudam: explique cada um no commit.
> - O simulador já mostrou dois dos problemas que os itens 2 e 3 corrigem: falso investimento passando 100% (destino vira recorrente no 1º Pix) e aluguel com 2FA repetido no 2º mês (`suspeita_anterior`). Ver "Achados para o grupo" em `docs/resultados-simulador.md`.
> - Item 10: o comando para retreinar no container está no topo de `scripts/ml/train.py`. Treine com a semente 1 e avalie com a semente 2. O `prepare_db.py` apaga o banco.
> - Os testes de cenário de ponta a ponta estão em `tests/integration/scenarios/` (dois arquivos: `test_scenarios.py` e `test_two_factor_return_scenarios.py`).

### 4.2 O prompt (cole inteiro)

```text
Rodamos uma bateria de realidade contra o `main`. Foram 90 clientes legítimos com 60 dias de Pix (distribuição do BCB) e 12 golpes reais encenados passo a passo, incluindo o que acontece depois do 2FA. O motor foi bem em vários casos: falsa venda, laranja de passagem, SIM swap, marcação, fazenda de contas e mesma titularidade. Mas a bateria achou falhas que vêm do desenho. Corrija nesta ordem.

Trabalhe num branch novo, `claude/realidade`, a partir do `main` atualizado (que já tem a Fase 4). Em cada item: escreva o teste de cenário primeiro e veja falhar, implemente, rode a suíte inteira até ficar verde e faça um commit por item. Os parâmetros ficam em `rule_parameter`. Atualize o CLAUDE.md a cada decisão.

1. **Golpe confirmado não entra no perfil.** Um 2FA por `possible_scam` com retorno `passed` hoje entra no perfil do pagador. Na bateria, a vítima da falsa central confirmou R$ 4.800 e R$ 4.500, e o terceiro Pix, de R$ 3.900, saiu `approved` sem nenhum sinal: o golpe "educou" o perfil. Correção: o Pix aprovado via 2FA por `possible_scam` não entra no perfil nem torna o destino recorrente. Conta só para a soma noturna e para os tetos diários.
   Teste: 3 Pix de falsa central confirmados pela vítima; o 3º precisa sair `two_factor_required` com aviso de golpe.

2. **Destino só é recorrente com histórico real.** Hoje basta um Pix aprovado para o destino virar "recorrente" e desligar o `PERFIL.valor`. No falso investimento (R$ 500, depois R$ 1.000, R$ 3.000 e R$ 8.000 ao mesmo destino ao longo de 8 dias), tudo saiu `approved` sem aviso. Correção: o atenuante de destino recorrente só vale com 2 ou mais Pix aprovados em dias diferentes para aquele destino e com o valor atual de no máximo 1,5 vez o maior valor já pago a ele. Acima disso é escalada, e o `PERFIL.valor` avalia normalmente.
   Teste: o cenário do falso investimento, em que o Pix de R$ 3.000 e o de R$ 8.000 precisam pedir 2FA com aviso. Caso logo abaixo: aluguel de valor estável todo mês continua aprovado.

3. **`suspeita_anterior` não pode punir conta do mês.** Hoje, se o cliente legítimo passou por um 2FA de golpe com um destino, todo Pix seguinte fora do perfil para esse destino pede 2FA de novo por 90 dias. Na bateria isso gerou 46 dos 2FA em clientes legítimos. Correção: a suspeita não vale quando o novo Pix tem valor parecido (até 25% de diferença) com um pagamento já confirmado a esse destino e foi feito pelo menos 20 dias depois dele (padrão de conta mensal). Continua valendo para valor crescente e para intervalo curto.
   Teste: aluguel do mês 1 com 2FA de golpe e retorno `passed`; aluguel do mês 2 de mesmo valor → `approved`. Falso investimento → continua pedindo 2FA.

4. **Perfil para destino novo.** Hoje o P95 do perfil mistura o aluguel, que é recorrente e alto, com o resto. Assim, o falso parente (R$ 1.890 para conta de 15 dias) passou porque o aluguel "ensinou" o motor a aceitar R$ 2.000. Correção: quando o destino é novo, o `PERFIL.valor` compara com os valores que o pagador já mandou para destinos novos, a partir de 5 casos; com menos, usa o perfil geral. É o mesmo sinal, com uma base de comparação melhor.
   Teste: cliente com aluguel de R$ 2.000 e Pix pequenos para destinos novos manda R$ 1.890 a um destino novo → `two_factor_required` com aviso de golpe.

5. **O método do 2FA depende do contexto.** A confirmação no app (`in_app_confirmation`) não protege quando o próprio celular está com o ladrão. Na bateria, o celular roubado e desbloqueado às 23h, a 9 km de casa, confirmou no app 3 Pix seguidos. O mesmo aconteceu no fracionamento em aparelho novo. Correção: qualquer 2FA vira `face_liveness` quando o aparelho não é confiável, quando houve biometria reprovada nas últimas 24 h, ou quando o Pix está a mais de 5 km de todos os últimos locais aprovados do pagador (é o que o Modo Rua do Nubank faz). `in_app_confirmation` só fica para aparelho confiável no lugar de sempre.
   Teste: celular de sempre, 23h, a 9 km de casa, 2º Pix noturno → 2FA com `face_liveness`.

6. **Rajada para destinos novos.** Na mão fantasma (acesso remoto, 7 Pix em 6 minutos para destinos novos, do aparelho de sempre), 4 Pix e R$ 5.200 saíram antes de o motor pedir 2FA. Crie o sinal `RITMO.destinos_novos` (camada 0): 3 ou mais Pix para destinos novos distintos em 10 minutos, somando R$ 2.000 ou mais, pedem 2FA com `face_liveness` (motivo `account_takeover`).
   Teste: a mão fantasma precisa travar no 3º Pix.

7. **Fan-in com valor mínimo e limite menor para conta nova.** A rifa da formatura (8 amigos mandando R$ 20 a uma conta de 12 dias) foi RECUSADA: falso positivo. Enquanto isso, a falsa venda e a laranja só travaram na 5ª vítima. Correção: o `CONTA_RECEBEDORA.fan_in` só pontua se a soma recebida na janela for de R$ 1.000 ou mais. Para recebedor com conta de menos de 30 dias, o mínimo de pagadores distintos cai para 3.
   Testes: rifa → `approved`; falsa venda de R$ 450 → recusa no 3º comprador.

8. **Loja PJ antiga não é golpe.** Uma TV de R$ 3.500 na Black Friday, numa loja com CNPJ de 12 anos, pediu 2FA com aviso de golpe. Correção: para recebedor PJ com conta de 1 ano ou mais, o `PERFIL.valor` no máximo aprova com aviso e nunca pede 2FA sozinho.
   Teste: o caso da TV → `approved` com `warn`.

9. **Res. BCB 403 vale para todos (decisão do grupo).** Remova o "período de aprendizado" e o alívio do "cliente que o motor ainda não conhece". Aparelho não confiável fica com R$ 200 por Pix e R$ 1.000 por dia para todo pagador, inclusive o que o motor nunca viu, como a Res. BCB 403/2024 manda para aparelho não cadastrado. O "Cadastro de dispositivos Pix" é produto da própria QI Tech.
   - Quando o único motivo do 2FA é um cliente que o motor ainda não conhece com aparelho novo, sem nenhum outro sinal de risco, use `step_up_reason: "device_registration"` com `step_up_method: "face_liveness"`. É o cadastro do aparelho que a norma prevê, feito uma vez só: depois do retorno `passed`, o aparelho fica confiável. Não use `in_app_confirmation` aqui, porque a confirmação no próprio aparelho novo não prova nada (mesmo raciocínio do item 5).
   - O limite de partida do `PERFIL.valor` para quem não tem histórico continua igual.
   - Atualize no CLAUDE.md a seção "Cliente que o motor ainda não conhece" e os testes de cenário que mudarem, explicando cada um no commit.
   - Teste: o primeiro Pix de R$ 300 de um cliente desconhecido do motor, com conta de 5 anos e aparelho nunca visto, sai `two_factor_required` com `device_registration` e `face_liveness`. Com o retorno `passed`, o Pix seguinte de R$ 800 do mesmo aparelho sai `approved`. Caso logo abaixo: o primeiro Pix de R$ 150 sai `approved`.

10. **Reavaliar com os números novos.** A Fase 4 (simulador e ML) já está no `main`. Depois dos itens 1 a 9:
   - rode de novo a avaliação do simulador e atualize `docs/resultados-simulador.md`;
   - confira se o ML, em modo sombra ou ativo, continua funcionando com os sinais novos (o `RITMO.destinos_novos` e as features mudadas do perfil). Se o modelo depende das features, retreine dentro do container.

No fim:
- faça o merge no `main` com a suíte verde;
- adicione o arquivo anexo `bateria_realidade.py` em `scripts/realidade/` e rode-o contra um banco recriado do zero (ele usa a API em 127.0.0.1:3000);
- salve a saída em `docs/bateria-realidade.md`;
- me devolva:
  - a tabela de golpes;
  - a fricção nos clientes legítimos (antes: 94% aprovados e 6% com 2FA nos últimos 15 dias), lembrando que o item 9 aumenta de propósito o 2FA no primeiro Pix de cada cliente;
  - os números novos do simulador;
  - a contagem da suíte.

Se algo conflitar com o CLAUDE.md, pare e pergunte.
```

### 4.3 Enquanto ele trabalha

- Cada item é um commit. Se o tempo apertar, os itens do fim saem. Os mais importantes para a banca são o 1, o 2, o 5, o 7 e o 9.
- O item 9 conflita com o CLAUDE.md atual (seção "Cliente que o motor ainda não conhece", que hoje descreve o período de aprendizado). O próprio prompt manda atualizar essa seção, então é uma decisão do grupo, e não um conflito a parar. Se ele perguntar, responda isso.
- O simulador (item 10) leva cerca de 8 minutos por rodada, e a comparação com o ML são duas rodadas.

### 4.4 Conferência depois

```bash
git checkout main && git pull
docker compose down -v && docker compose up -d && pytest -q          # tudo verde; anote o número
docker compose down -v && docker compose up -d
python scripts/realidade/bateria_realidade.py 2026                     # ~5 min → docs/bateria-realidade.md
git status                                                             # docs/bateria-realidade.md deve estar commitado
```

Leia a tabela de golpes do `docs/bateria-realidade.md`. Ela é a base das "Limitações conhecidas" da Fase 5.

**Referência de "antes"**, rodada no `main` atual (commit `3fc19de`), semente 2026, banco do zero: 4.543 Pix
legítimos em 5 min 15 s; 94,0% aprovados, 3,5% com 2FA por golpe, 1,5% com 2FA de limite, 0,7% aprovados com
aviso e 0,4% com biometria; nos últimos 15 dias, 94,0% aprovados. A bateria roda até o fim sem erro.

---

## 5. Fase 5: README final, clone limpo e congelamento

### 5.1 Antes de colar o prompt

O README **ainda não foi reescrito**: as Fases 3 e 4 combinaram não mexer nele. A Fase 5 é a reescrita completa.

Abaixo, a lista do que o README tem de dizer de cada sinal novo da Fase 3. O Claude Code deve conferir cada valor
contra o seed do `database/database.sql`, porque a bateria pode ter mudado alguns:

| Sinal | Lógica | Parâmetros | Norma ou estimativa | Visibilidade |
|---|---|---|---|---|
| `RASTRO.repasse_rapido` (c2) | recebeu de terceiros nos últimos 60 min e repassa ≥ 80%; mesma titularidade não conta; cruzamento pelo documento. `mule` +60: sozinho 2FA (`possible_scam`), com outro sinal de laranja recusa | 60 min, 80%, 60 pts | estimativa | só créditos de clientes da QI Tech |
| `QUEM_OPERA.aparelho_compartilhado` (c2) | ≥ 3 CPFs pagadores no mesmo aparelho em 30 dias (fazenda de contas). `mule` +60 | 30 dias, 3, 60 | estimativa | aparelhos usados em outros bancos não aparecem |
| `QUEM_OPERA.viagem_impossivel` (c1) | haversine até o último Pix aprovado com local, > 900 km/h. `ato` +60 (biometria); sem local ou Δt ≤ 0 → `not_evaluated`; < 5 km é ruído do GPS | 900 km/h, 5 km | estimativa | último local aprovado no motor |
| `LIMITE.sem_geolocalizacao` (c1) | sem geolocalização e > R$ 500 → 2FA de limite | R$ 500 | norma (IN BCB 669 permite limite menor); o valor é estimativa | — |
| `QUEM_OPERA.canal_incomum` (c1) | canal nunca usado num Pix aprovado, > R$ 1.000. `ato` +30; desconhecido → `not_evaluated` | 30 pts | estimativa | canais vistos no motor |
| `QUEM_OPERA.ip_compartilhado` (c2) | ≥ 3 CPFs no mesmo IP em 1 h, **só** com aparelho não confiável (CGNAT). `ato` +20, nunca decide sozinho | 1 h, 3, 20 | estimativa | Pix que passaram pelo motor |
| `RASTRO.conta_pagadora_recente` (c1) | conta pagadora < 30 dias, > R$ 1.000, destino novo. `mule` +30 | 30 dias, 30 | estimativa | — |
| `RITMO.fracionamento` (c2) | ≥ 3 Pix em 1 h entre 90% e 100% de R$ 200 ou do noturno (R$ 1.000) → 2FA de limite; Pix refeito conta 1 | 1 h, 3, 90% | estimativa (os limites são norma) | — |
| `CONTA_RECEBEDORA.dormente` (c2) | destino que reaparece depois de 60 dias sem movimento **na nossa base**. `mule` +30 | 60 dias, 30 | estimativa | a conta pode ter movimentado em outro banco |
| `RASTRO.proximidade_marcada` (c2) | consulta recursiva de 2 saltos nos Pix aprovados de 24 h; 1 salto recusa, 2 saltos `mule` +30. Só recebedor PF | 24 h, 2 saltos, 30 | estimativa; marcações seguem a Res. BCB 587 | fluxo dentro da base; `fraud_marker` simula o DICT |
| `CONTA_RECEBEDORA.varias_instituicoes` (c2) | mesmo CPF recebedor com contas < 30 dias em ≥ 2 ISPBs. `mule` +30 | 30 dias, 2, 30 | estimativa | contas que já foram destino no motor |
| `QUEM_OPERA.fora_da_zona` (c2) | > 50 km de todos os 20 últimos locais aprovados e > R$ 500 → 2FA `face_liveness`; < 5 locais → `not_evaluated` | 50 km, R$ 500, 5 | estimativa (Modo Rua do Nubank) | locais vistos no motor |
| `PERFIL.valor` 2º degrau | ≥ 10× a mediana e > R$ 1.000, destino novo, aparelho confiável → `app` +60 (2FA com aviso) | 10×, R$ 1.000, 60 | estimativa | — |
| `CONTA_RECEBEDORA.suspeita_anterior` | 2FA por `possible_scam` para este destino em 90 dias e valor fora do perfil → `app` +60 | 90 dias, 60 | estimativa | — |
| `ANOMALIA.ml` (c2) | Isolation Forest só com Pix legítimos; sombra: escore no `metadata`; ativo: `ato` até +60 acima do corte, nunca recusa | corte 0,61, span 0,04, teto 60 | estimativa (p99 do treino) | — |

**Decisões que o README precisa explicar** (estão nos commits e no CLAUDE.md, mas não no PLANO):

- O modelo é exportado como JSON e avaliado em Python puro: sem pickle, e a API não carrega o scikit-learn.
- A feature "destinos distintos nas últimas 24 h" entrou depois de o ML errar o padrão novo na semente de treino. Os números do ML mostram o mecanismo, não a eficácia.
- A `proximidade_marcada` só vale para recebedor PF.
- O `latency_ms` mede a decisão, da chegada do Pix à decisão pronta. A gravação e o commit ficam fora.
- As consultas da camada 2 rodam em todo Pix; só a avaliação dos sinais é que depende do gatilho. Isso entra em "Limitações".

Cole também esta nota, logo abaixo do prompt:

> **Notas do estado atual:** a tabela de sinais novos e as decisões acima estão em `docs/GUIA-PARA-TERMINAR.md`, seção 5.1; use como ponto de partida e confira tudo contra o seed. Riscos do clone limpo a verificar: (1) no Windows os testes chamam `0.0.0.0:3000`, que não conecta; o padrão de `SERVER_LOCALHOST` em `tests/conftest.py`, `tests/utils/requisition.py` e `.env.example` talvez precise virar `127.0.0.1` (é bug, avise antes de corrigir, como o prompt pede); (2) o `docker compose up` sem `docker login` pode tomar 429 do Docker Hub; o README deve dizer isso. **Não** remova o `docs/GUIA-PARA-TERMINAR.md`: a dupla o remove depois, junto com os Integrantes, e move a tag. O demo da apresentação está em `scripts/demo/demo.py`; o README pode citá-lo em "Como rodar e testar".

### 5.2 O prompt (cole inteiro)

```text
Fase 5: README final, verificação de entrega e congelamento. Leia o CLAUDE.md, o docs/PLANO.md, o docs/pesquisa-fraude-pix.md, o docs/resultados-simulador.md e o docs/bateria-realidade.md antes de começar.

Trabalhe num branch novo, `claude/fase-5`, a partir do `main` atualizado. É a correção da banca que começa pelo README: ele precisa descrever exatamente o que o código faz. Nesta fase, nenhuma mudança de comportamento do motor; se achar um bug, me avise antes de corrigir.

1. **README no modelo da banca**, com estas seções, nesta ordem:
   - `# Grupo 47 — Motor Antifraude Pix` e `**Integrantes:**` com o texto `[o grupo preenche]`. Não invente nomes.
   - **Como o motor de decisão funciona.** A tese em três linhas (biometria para invasão, 2FA com aviso para golpe, recusa só com evidência dura), as camadas e o caminho rápido, o retorno do 2FA e o que o motor aprende.
   - **Regras.** A tabela `| Regra | Lógica | Parâmetros | Por quê |` com as 8 regras compostas. Dentro de cada linha, os sinais da regra como subitens, cada um com o valor do parâmetro, a marca "norma" (com a resolução) ou "estimativa" (com o raciocínio) e a fonte.
     - Use só fontes que estão em `docs/pesquisa-fraude-pix.md` e copie o link de lá; não invente link nem número.
     - Todo valor da tabela precisa ser igual ao do seed em `database/database.sql`. Confira um por um e me liste qualquer diferença.
   - **Como as regras viram decisão.** As 4 formas de recusar, a tabela de motivo e método do 2FA (`step_up_reason`, `step_up_method`, `scam_warning`), a faixa de aviso, a precedência, a confiança do aparelho, o cadastro do aparelho (Res. BCB 403) e o retorno do 2FA.
   - **Exemplo resolvido.** Rode o payload do slide da QI Tech contra a API e cole a resposta real. Explique sinal por sinal, com os pontos e o placar, por que a decisão foi aquela.
   - **O que o motor enxerga.** Ele só vê Pix de clientes da QI Tech; diga quais sinais dependem disso.
   - **Limitações conhecidas,** tiradas da bateria de realidade: coação, Pix de centavos sem ML, ladrão que espera 24 h, e o que mais a bateria mostrou. Para cada uma, o próximo passo.
   - **Resultados.** Os números do simulador e da bateria, apresentados como teste de regressão e medida de fricção, não como eficácia. Sem superlativos.
   - **LGPD e dados.** Base legal (prevenção à fraude), nada pessoal em log, retenção, e que `observed`/`threshold` ficariam internos em produção.
   - **Decisões e trade-offs: considerado e descartado.** Blockchain → cadeia de hashes ou nada; ML supervisionado → detecção de anomalia; recusar golpe → 2FA com aviso; DICT real → tabela simulada; retorno do 2FA fora do slide → rota isolada.
   - **Como rodar e testar:**
     - `docker compose up`;
     - esperar o healthcheck;
     - `pip install -r requirements-dev.txt` e `pytest`;
     - exemplos de `curl` de POST, GET e PATCH com o `INTERNAL-TOKEN`;
     - quando usar `docker compose down -v`;
     - como rodar o simulador e a bateria de realidade.

2. **Teste de clone limpo**, exatamente como o jurado vai fazer. Num diretório novo:
   - `git clone` do repositório e checkout do `main`;
   - siga o README ao pé da letra: `docker compose up`, espere o healthcheck, `pytest` e os `curl` do README.

   Se algum passo falhar ou estiver ambíguo, corrija o README e repita até passar. Se o seu ambiente não tiver Docker, diga isso e rode o equivalente sem Docker, deixando claro no relatório.

3. **Coerência entre documentos.** Confira que README, CLAUDE.md e docs/PLANO.md não se contradizem nas decisões finais. Onde o PLANO.md estiver desatualizado, acrescente uma nota no topo dele dizendo que o README e o CLAUDE.md valem.

4. **Higiene final.** Nenhum arquivo temporário, `.env`, `__pycache__` ou relatório solto versionado. O `.gitignore` cobre isso. Nenhum `print` ou log com dado pessoal.

5. **Congelamento.** Faça o merge de `claude/fase-5` no `main` com a suíte verde e crie a tag `v1.0-entrega`.

Me devolva:
- o índice do README com uma linha por seção;
- a lista de diferenças que encontrou entre README e seed (e como resolveu);
- o resultado do clone limpo, passo a passo;
- a contagem final da suíte;
- o hash do commit da tag.

Se algo conflitar com o CLAUDE.md, pare e pergunte.
```

### 5.3 Você mesmo, depois do Claude Code

A tag tem de apontar para a versão final. Por isso estes três passos vêm **antes** de considerar a tag pronta:

1. Preencha os **Integrantes** no README (o Claude Code deixa `[o grupo preenche]`).
2. Remova este guia do `main`, se ainda estiver lá: `git rm docs/GUIA-PARA-TERMINAR.md`.
3. Faça o commit, mova a tag para ele e mande os dois ao GitHub:

   ```bash
   git commit -am "README: integrantes; guia de trabalho removido"
   git tag -f v1.0-entrega
   git push origin main
   git push -f origin v1.0-entrega
   git ls-remote --tags origin        # a tag v1.0-entrega aponta para o mesmo hash do git log -1
   ```

4. Faça o **seu** clone limpo, que é a prova real, numa pasta nova **fora** do repositório:

   ```bash
   cd .. && rm -rf entrega && git clone https://github.com/eduardo3071/Hackathon-QI-Tech.git entrega && cd entrega
   docker compose down -v; docker compose up --build -d     # espere (healthy)
   python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
   pytest -q
   ```

   Antes, pare o docker compose da pasta antiga (`docker compose down` lá), senão as portas 3000 e 5432 estarão
   ocupadas. Depois rode os `curl` do README, copiando direto de lá. Se algo falhar, conserte o README, faça o
   commit e mova a tag de novo (passo 3).
5. **Código congelado às 10h30.** Depois disso, só correção de bug, sempre com a tag movida (passo 3).

---

## 6. Apresentação (7 min + 3 min de perguntas)

### 6.1 Roteiro (do PLANO), com a fonte de cada número

| Tempo | Bloco | O que dizer | De onde sai |
|---|---|---|---|
| 40 s | O problema em um número | O MED recuperou só 9,3% do valor contestado em 2025: a decisão tem de acontecer antes do Pix sair | BCB, MED 2.0 (link em `docs/pesquisa-fraude-pix.md`, linha 23); também: fraude média R$ 1.735 × mediana P2P R$ 50 |
| 1 min | A tese | Biometria para o invasor; 2FA com aviso para o golpe; recusa só com evidência dura; o motor aprende com o retorno do 2FA | README, "Como o motor de decisão funciona" |
| 2 min | Demo ao vivo | 4 histórias: cliente normal, celular roubado, falsa central, conta laranja (6.2) | `scripts/demo/demo.py` |
| 1 min | A rede | O histórico próprio vira fan-in, repasse rápido, aparelho compartilhado, proximidade de conta marcada | README, Regras 5, 6 e 7 |
| 1 min 20 s | Resultados | Fraude pega por tipo e fricção em cliente bom, com e sem ML; **sempre** como teste de regressão e medida de fricção, não eficácia | `docs/resultados-simulador.md` e `docs/bateria-realidade.md` **depois** da seção 4 |
| 1 min | Limites e próximos passos | O que o contrato não traz (ligação ativa, app de acesso remoto), coação, calibração com o resultado real do 2FA e do MED | README, "Limitações conhecidas" |

Ensaiem **com cronômetro**, pelo menos duas vezes. A demo é o bloco que mais estoura o tempo.

### 6.2 Demo ao vivo

Com a API de pé (`docker compose up -d`, `(healthy)`):

```bash
python scripts/demo/demo.py
```

Ela roda em ~3 s, só por HTTP, com documentos novos a cada vez e datas de abril de 2026 (não atrapalha nada), e
mostra para cada Pix a decisão, o motivo e o método do 2FA, os placares, a latência e os sinais. No `main` de
hoje, o resultado é:

| História | O que o motor faz |
|---|---|
| Cliente normal, R$ 180 para o destino de sempre | `approved` pelo caminho rápido |
| Celular roubado: R$ 10 de teste, depois R$ 3.000 | o de R$ 10 sai (cabe nos R$ 200 do BCB); o de R$ 3.000 pede biometria, e o ladrão reprova → `rejected` |
| Falsa central: R$ 4.000 do próprio celular | 2FA com aviso de golpe; a vítima confirma; no dia seguinte, R$ 5.000 ao mesmo golpista pede 2FA de novo |
| Conta laranja: 5 pagadores de R$ 300 para conta de 10 dias | os 4 primeiros saem; o 5º é `rejected` (conta nova + fan-in) |

**Depois da seção 4 (bateria), o resultado muda.** Por exemplo, o item 7 trava a laranja mais cedo, e o item 9
pede cadastro do aparelho no primeiro Pix. Rodem a demo de novo e atualizem a fala.

**Plano B:** se a demo ao vivo falhar (rede, Docker), mostrem a saída gravada. Gravem-na assim que a seção 5
terminar:

```bash
python scripts/demo/demo.py > demo-saida.txt      # não vai para o Git: apague ou deixe fora do commit
```

Em projeção, deixem o terminal com fonte grande e mostrem também um `metadata` inteiro (o `curl` do GET do README).

### 6.3 Perguntas prováveis da banca (preparem a resposta)

| Pergunta | Resposta curta (o detalhe está no README) |
|---|---|
| "De onde veio esse número?" | Cada parâmetro é "norma" (com a resolução) ou "estimativa" (com o raciocínio), e todos ficam na tabela `rule_parameter`, configuráveis sem deploy; o que calibraria: o resultado real do 2FA e do MED |
| "Por que não recusar o golpe?" | A vítima manipulada passa em qualquer 2FA, mas recusar o vendedor de carro usado é prejuízo para o cliente bom; o slide define reprovar como "risco claro" |
| "O simulador prova que o motor funciona?" | Não: os cenários são nossos. É teste de regressão e medida de fricção, e 70% dos créditos ficam invisíveis ao motor de propósito |
| "E o ML?" | Detecção de anomalia, treinada só com Pix legítimos, em modo sombra: o escore separa o padrão novo, mas o ganho na decisão foi pequeno, e o relatório diz isso |
| "Por que o PATCH, se o slide não pede?" | Sem ele o motor não aprende com o 2FA confirmado; a rota é isolada e removível |
| "Quanto tempo o motor leva?" | `latency_ms` em cada análise; p95 do caminho rápido abaixo de 100 ms (o número exato está nos relatórios) |
| "E a LGPD?" | Base legal de prevenção à fraude, nada pessoal em log, `observed`/`threshold` só no dossiê interno em produção |

---

## 7. Entrega

- [ ] `main` com a suíte verde no Docker (contagem anotada)
- [ ] `docs/bateria-realidade.md` e `docs/resultados-simulador.md` atualizados
- [ ] README com Integrantes preenchidos, clone limpo testado por vocês
- [ ] `docs/GUIA-PARA-TERMINAR.md` removido do `main` (5.3, passo 2)
- [ ] tag `v1.0-entrega` no GitHub, apontando para o último commit do `main` (`git ls-remote --tags origin`)
- [ ] demo ensaiada e saída de plano B gravada
- [ ] **link do repositório no Slack, grupo da final, até 11h45** (prazo 12h):
      `https://github.com/eduardo3071/Hackathon-QI-Tech`

---

## 8. Problemas comuns

| Sintoma | Causa | O que fazer |
|---|---|---|
| `429 Too Many Requests` no `docker compose up` | limite do Docker Hub sem login | `docker login`, depois `docker compose up --build` |
| `port is already allocated` | outra coisa na porta 3000 ou 5432 | no `.env`: `API_PORT=3001` ou `DB_PORT=5433` (e ajuste a `DATABASE_URL`) |
| `column ... does not exist` | banco nasceu com um `database.sql` antigo | `docker compose down -v && docker compose up -d` |
| testes: `Não consegui falar com a API` | API fora do ar, ou Windows com `0.0.0.0` | `docker compose ps`; no Windows, `SERVER_LOCALHOST=127.0.0.1` no `.env` |
| 403 em todo `curl` | faltou o header | `-H "INTERNAL-TOKEN: default_token"` |
| números do simulador ou da bateria estranhos | banco com dados dos testes (as datas da bateria cruzam com as dos testes) | recrie o banco antes de cada medição |
| `pytest` falhando logo depois do simulador ou da bateria | o banco ficou em `ml_mode = active`, ou com muitos dados | `docker compose down -v && docker compose up -d` |
| treino no container: `Permission denied` em `/app/ml/artifacts` | a imagem roda com um usuário sem permissão de escrita | use o `-u root` do comando da seção 3 |
| Claude Code quer mudar uma regra no meio da Fase 5 | a Fase 5 não muda comportamento | peça para ele só anotar o bug; decida vocês |
| `curl` no PowerShell dá erro de parâmetro | o `curl` do PowerShell é outro programa | use o Git Bash, ou `curl.exe` com o JSON num arquivo (`-d "@pix.json"`) |
| `git push` dá 403 | sem permissão de escrita no repositório | o Eduardo adiciona como colaborador (1.1) |
| demo mostra decisões diferentes da tabela da 6.2 | a seção 4 mudou regras | é esperado: rodem de novo e atualizem a fala |

---

## 9. O que vocês precisam saber (achados e decisões até aqui)

**Achados do simulador** (`docs/resultados-simulador.md`, seção "Achados para o grupo"):

- falso investimento passa 100% → o item 2 da seção 4 corrige;
- aluguel com 2FA repetido no 2º mês → o item 3 corrige;
- salário pago pela empresa pelo internet banking (sem geolocalização) pede 2FA de limite em todo Pix acima de R$ 500 (`LIMITE.sem_geolocalizacao`). **Não está na lista da bateria**: decidam se o README só registra isso como limitação ou se vale uma exceção;
- celular roubado: o Pix grande é sempre pego, mas o de teste (R$ 10) e a nova tentativa (R$ 199) passam, dentro dos limites do BCB;
- rajada: só trava a partir do 5º Pix → o item 6 corrige para destinos novos.

**ML:** o escore separa (pontua 66% do padrão novo e 0,8% dos legítimos), mas a escala de pontos faz só 3,8% do
padrão novo chegarem a 2FA. Recomendação: entregar em modo sombra (é o padrão do seed).

**Decisões tomadas sem ninguém do grupo** (confirmem ou revertam):

1. A `proximidade_marcada` só vale para recebedor PF: um lojista que recebeu de um marcado bloquearia todos os clientes dele por 24 h.
2. O ML pontua o placar de invasão (`ato`), que só leva a biometria e nunca recusa.
3. O retorno do 2FA conta qualquer 2FA por `possible_scam` (passou, falhou ou sem retorno) para a `suspeita_anterior`.
4. O reenvio do mesmo POST depois de um PATCH devolve a resposta original; o estado atual fica no GET.
5. As datas da trilha de status saem em UTC no JSON.
