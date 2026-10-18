# Grupo 17 — Motor Antifraude Pix

**Integrantes:** Eduardo Oliveira Rodrigues Cardoso · Ingrid Carvalho Godoy

API que recebe um Pix e responde, antes de o dinheiro sair, uma de três decisões — `approved`, `two_factor_required` ou `rejected` — sempre com o motivo explicável em `metadata`. Feita a partir do Base Service do Bootcamp QI Tech, com as mesmas camadas e o mesmo padrão de erros.

- RFC (versão 2): [`docs/RFC.md`](docs/RFC.md)
- Pesquisa com a fonte de cada parâmetro: [`docs/pesquisa-fraude-pix.md`](docs/pesquisa-fraude-pix.md)
- Plano do projeto (histórico; onde divergir, vale este README e o `CLAUDE.md`): [`docs/PLANO.md`](docs/PLANO.md)
- Medidas: [`docs/resultados-simulador.md`](docs/resultados-simulador.md) e [`docs/bateria-realidade.md`](docs/bateria-realidade.md)

## Como o motor de decisão funciona

**A tese, em três linhas:**

1. **Biometria facial para quem pode ser um invasor.** Se o motor desconfia de *quem* aperta o botão (aparelho novo, rajada, local impossível), o 2FA é `face_liveness`: o invasor não tem o rosto do titular, e no SIM swap ele recebe o SMS.
2. **2FA com aviso de golpe para quem pode ser uma vítima.** A vítima manipulada passa em qualquer segundo fator (o relatório EBA-ECB 2025 achou taxas de fraude *maiores* em transferências autenticadas com SCA), então a fricção útil é o aviso na tela.
3. **Recusa só com evidência dura.** O slide define reprovar como "bloquear quando o risco é claro" e 2FA como "fricção só onde há dúvida". Um sinal de conta laranja sozinho é dúvida: pode ser o vendedor de carro usado que acabou de abrir conta.

**Camadas e caminho rápido.** Cada Pix passa por camadas e só aprofunda quando a anterior levanta sinal:

| Camada | Quando roda | O que avalia |
|---|---|---|
| 0 | sempre | marcação de fraude, limites de norma (aparelho não cadastrado, noturno), velocidade, rajada para destinos novos |
| 1 | sempre | leituras das tabelas agregadas: perfil do pagador, conta recebedora, geolocalização ausente, canal |
| gatilho | — | sem sinal de risco e sem contexto de risco (destino sem histórico, aparelho não confiável, noite) → `approved` pelo **caminho rápido** (`metadata.path = "fast"`) |
| 2 | só com sinal, tempo limite de 300 ms | regras de rede (consultas sobre o histórico) e o modelo de anomalia. Estourou o tempo → 2FA pelo motivo que levou até ela, nunca aprovar no escuro |

Antes de avaliar, o motor toma uma trava (`pg_advisory_xact_lock`) sobre o `id` do Pix, o pagador, o recebedor PF e o aparelho, sempre na mesma ordem: dez Pix simultâneos do mesmo pagador decidem como se viessem em fila, e nenhuma contagem é enganada.

**O que fica gravado.** O Pix como chegou, a decisão, **um resultado por sinal** (inclusive os que passaram) e as features usadas. O perfil do pagador é feito **só de Pix aprovados**: tentativa recusada não "educa" a linha de base, mas conta na velocidade.

**Parâmetros.** Todos — inclusive pontos e cortes — moram na tabela `rule_parameter` (política versionada `2026.10.1`), nunca em constante no código. Mudar um número é um `UPDATE`, sem deploy.

**O que o motor aprende.** Com o retorno do 2FA (`PATCH`, veja [Depois do 2FA](#depois-do-2fa-o-patch-de-retorno)) ele registra o aparelho do cliente, o destino recorrente e o perfil. Pix confirmado sob aviso de golpe **não** entra no perfil: o golpe não pode "educar" o motor.

### Confiança do aparelho

Um aparelho é **confiável** para um pagador quando tem **pelo menos 2 Pix aprovados** desse pagador **e o primeiro deles foi há pelo menos 24 h**, ou quando passou na **biometria facial** no retorno do 2FA. "Pix aprovado" inclui o Pix que pediu 2FA e teve retorno `passed`. Biometria **reprovada** (em qualquer 2FA que pedia `face_liveness`) bloqueia a confiança do aparelho por 24 h: nenhum Pix aprovado nesse período o torna confiável.

Enquanto não é confiável, valem os limites do BCB para aparelho não cadastrado: **R$ 200 por Pix e R$ 1.000 por dia**, somando **todos** os Pix aprovados de aparelhos não confiáveis do pagador no dia de Brasília. Acima disso, 2FA com `face_liveness`. Aparelho não confiável também conta como aparelho novo no sinal de perfil (pontua invasão, não golpe).

O motivo é uma brecha concreta: se um Pix aprovado bastasse, o ladrão "aqueceria" o celular roubado com um Pix de R$ 10, e o seguinte, de R$ 5.000, sairia sem 2FA. Exigir que o primeiro tenha 24 h faz a confiança atravessar um dia, o tempo de o titular perceber que perdeu o celular.

### Cliente que o motor ainda não conhece: a norma vale para todos

Não há "período de aprendizado": a Res. BCB 403/2024 vale para o pagador que o motor nunca viu, como para qualquer outro. O primeiro Pix acima de R$ 200 de um aparelho novo, **sem nenhum outro sinal de risco**, pede o **cadastro do aparelho**: `step_up_reason: "device_registration"` com `face_liveness` e sem aviso de golpe. É o cadastro que a norma prevê, feito uma vez só: com o retorno `passed`, o aparelho fica confiável. Se o pagador já tem um aparelho confiável, um aparelho novo é o caso do celular roubado, e o 2FA é `account_takeover`.

Consequência assumida: na avaliação, com o banco vazio, o primeiro Pix de cada cliente acima de R$ 200 pede esse cadastro (64 dos 188 Pix legítimos com 2FA do simulador). Em produção o motor nasce com a carga do histórico (aparelhos já cadastrados) e isso some. O "Cadastro de dispositivos Pix" é, aliás, produto da própria QI Tech.

## Regras

São 8 regras compostas. Cada parâmetro é **norma** (com a resolução) ou **estimativa** (com o raciocínio, calibrável). Valores em centavos no código (R$ 200 = 20000). Todos os números abaixo foram conferidos contra o seed de `database/database.sql`.

| Regra | Lógica | Parâmetros | Por quê |
|-------|--------|------------|---------|
| **1. Marcação** `MARCACAO.lista` | Pagador ou recebedor com marcação vigente em `fraud_marker` (simula o DICT) → `rejected`. Vale mesmo na mesma titularidade. | Marcação própria: sempre (**norma**). De outro PSP: últimos 90 dias (**norma**, janela d90 do DICT) | A Res. BCB 587/2026 obriga a rejeitar todas as transações do usuário marcado, como pagador ou recebedor, salvo devoluções ([Res. 587](https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Resolu%C3%A7%C3%A3o%20BCB&numero=587); [API DICT](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/API-DICT.html)). |
| **2. Limite por contexto** | **`LIMITE.aparelho_nao_cadastrado`**: aparelho não confiável e (valor > R$ 200 ou soma do dia em aparelhos não confiáveis > R$ 1.000) → 2FA com `face_liveness`. **`LIMITE.noturno`**: entre 20h e 6h (Brasília), PF→PF entre pessoas distintas, soma da noite > R$ 1.000 **e** acima do maior Pix noturno já aprovado do pagador → 2FA de limite. **`LIMITE.sem_geolocalizacao`**: sem `geolocation` e valor > R$ 500 → 2FA de limite. | Aparelho: R$ 200 por Pix, R$ 1.000 por dia (**norma**); 2 Pix aprovados, o primeiro há 24 h, e 24 h de bloqueio depois da biometria reprovada (**estimativa**). Noturno: R$ 1.000, 20h–6h (**norma**). Sem geolocalização: R$ 500 (**norma** que permite o limite menor; o valor é **estimativa**) | Desde nov/2024 o BCB limita o aparelho não cadastrado "mesmo que [o golpista] tenha obtido a senha" ([nota BCB 20231](https://www.bcb.gov.br/detalhenoticia/20231/noticia); Res. BCB 403/2024). O limite noturno é da Res. BCB 142/2021 ([texto](https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=142&tipo=Resolu%C3%A7%C3%A3o+BCB)); como o motor não recebe o limite que o cliente configurou, é **sinal, não teto**: quem já teve aprovado um Pix noturno maior mostrou que o limite dele é maior. A IN BCB 669 permite limite menor com a geolocalização desligada ([Fórum Pix](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/Forum_Pix_Plenaria/20251002-Forum_Pix.pdf)). |
| **3. Ritmo** | **`RITMO.velocidade`**: tentativas do pagador em 10 min (janela deslizante, recusadas incluídas). Com a janela somando ≥ R$ 1.000, 5 → 2FA e 10 → `rejected`; abaixo disso só 10 pedem 2FA. O mesmo Pix refeito com `id` novo (mesmo recebedor, mesmo valor) conta **uma** vez. **`RITMO.destinos_novos`**: 3 ou mais destinos **novos** distintos em 10 min, somando ≥ R$ 2.000 → 2FA com `face_liveness`. **`RITMO.fracionamento`**: 3 ou mais Pix em 1 h, cada um entre 90% e 100% de R$ 200 ou de R$ 1.000 (noturno) → 2FA de limite. | Velocidade: 10 min, 5 e 10 tentativas, R$ 1.000 (**estimativa**). Destinos novos: 10 min, 3 destinos, R$ 2.000 (**estimativa**). Fracionamento: 1 h, 3 Pix, 90% (**estimativa**; os limites que ele observa são **norma**) | Quem invade uma conta tenta esvaziá-la rápido; a janela deslizante é a prática recomendada para velocidade em tempo real ([Redis](https://redis.io/blog/real-time-fraud-detection)). A soma separa o ataque do racha da conta do bar (mediana do Pix P2P: R$ 50). A "mão fantasma" (acesso remoto, do aparelho de sempre) manda vários Pix a contas que o titular nunca pagou e passava até o 5º Pix; por isso o sinal de destinos novos. Os tetos regulatórios são cumulativos, e picar o valor para ficar abaixo deles é tentar contorná-los ([BCB](https://www.bcb.gov.br/detalhenoticia/20231/noticia)). |
| **4. Perfil** `PERFIL.valor` | Valor > P95 **e** > 5× a mediana dos aprovados em 90 dias (mín. 5 Pix); sem histórico, > R$ 1.000. O mesmo valor muda de sentido: **destino recorrente** (2 ou mais Pix aprovados em dias diferentes e valor ≤ 1,5× o maior já pago a ele; nunca para quem só o pagou depois de um 2FA com aviso) → passa, é o aluguel; **aparelho não confiável** → +60 `ato`; **aparelho confiável e destino novo** → +40 `app` (faixa de aviso), ou +60 com 10× a mediana e mais de R$ 1.000 (2FA com aviso). Para **destino novo**, a comparação é com os valores que o pagador já mandou para destinos novos (a partir de 5 casos). **Recebedor PJ com conta de 1 ano ou mais**: no máximo o aviso (+40), nunca 2FA sozinho. | P95, 5×, 5 Pix, 90 dias, R$ 1.000; 10× e R$ 1.000 do 2º degrau; recorrente: 2 dias e 150%; destino novo: 5 casos; PJ antiga: 365 dias (**estimativas**) | A Res. BCB 403 exige identificar o "não compatível com o perfil do cliente" ([DOU](https://www.in.gov.br/web/dou/-/resolucao-bcb-n-403-de-22-de-julho-de-2024-573678500)), critério que o STJ usou em 2026 ([REsp 2.209.868](https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias/2026/15072026-Sem-transacoes-incompativeis-com-perfil-de-cliente--banco-nao-responde-por-golpe-da-falsa-central.aspx)). A fraude média (R$ 1.735) é 35× a mediana do Pix P2P (R$ 50): por isso mediana e percentil, não média. Um único Pix aprovado já tornava o destino "recorrente" e o falso investimento (R$ 500, 1.000, 3.000, 8.000) passava inteiro; o aluguel de R$ 2.000 elevava o P95 que decidia sobre o falso parente; a loja de 12 anos não é golpe. |
| **5. Quem opera** | **`QUEM_OPERA.aparelho_compartilhado`**: 3 ou mais CPFs pagadores no mesmo aparelho em 30 dias → +60 `mule`. **`QUEM_OPERA.viagem_impossivel`**: velocidade desde o último Pix aprovado com local > 900 km/h (ignora < 5 km) → +60 `ato`. **`QUEM_OPERA.canal_incomum`**: canal nunca usado num Pix aprovado, acima de R$ 1.000 → +30 `ato`. **`QUEM_OPERA.ip_compartilhado`**: 3 ou mais CPFs no mesmo IP em 1 h, **só** com aparelho não confiável → +20 `ato`, nunca decide sozinho. **`QUEM_OPERA.fora_da_zona`**: a mais de 50 km de todos os 20 últimos locais aprovados e valor > R$ 500 → 2FA com `face_liveness` (com menos de 5 locais conhecidos: `not_evaluated`). | 30 dias, 3 CPFs, 60 pts; 900 km/h, 5 km, 60 pts; 30 pts; 1 h, 3 CPFs, 20 pts; 50 km, R$ 500, 5 locais (todas **estimativas**) | Operadores de conta laranja controlam várias contas do mesmo aparelho, e no "sequestro do Pix" o celular da vítima abre contas em outros CPFs ([Serasa](https://www.serasaexperian.com.br/conteudos/entenda-como-o-pix-impulsiona-a-abertura-de-contas-laranjas)); 3 CPFs evita alertas em aparelho de família. O titular não está em dois lugares distantes em minutos. O IP de operadora móvel põe muita gente no mesmo endereço (CGNAT), por isso o sinal nunca decide sozinho. A zona habitual reproduz o Modo Rua do Nubank ([Nubank](https://international.nubank.com.br/pt-br/consumidores/carnaval-seguro-pioneiro-modo-rua-do-nubank-ja-protege-mais-de-5-milhoes-de-clientes/)). |
| **6. Conta recebedora** | **`conta_nova`**: conta destino com < 30 dias: primeiro crédito **e** valor fora do perfil → +60 `mule` (sozinho, 2FA com aviso; com outro sinal de laranja, recusa); só a idade → +20. **`fan_in`**: 5 ou mais pagadores distintos em 1 h para recebedor **PF**, somando ≥ R$ 1.000 → +40 `mule`; para conta com < 30 dias bastam 3 pagadores. **`suspeita_anterior`**: o pagador já teve 2FA por `possible_scam` para esta conta nos últimos 90 dias e o valor está fora do perfil → +60 `app`; não vale para a conta do mês (valor até 25% parecido com um pagamento já confirmado, feito há 20 dias ou mais). **`dormente`**: destino que reaparece depois de 60 dias sem movimento **na nossa base** → +30 `mule`. **`varias_instituicoes`**: mesmo CPF recebedor com contas de < 30 dias em 2 ou mais ISPBs → +30 `mule`. | 30 dias, 60 e 20 pts; 1 h, 5 pagadores (3 para conta nova), R$ 1.000, 40 pts; 90 dias, 60 pts, 20 dias, 25%; 60 dias, 30 pts; 30 dias, 2 ISPBs, 30 pts (todas **estimativas**) | A conta laranja passa no onboarding, então só se denuncia pelo comportamento, na hora de receber. O art. 39-B da Res. BCB 147 cita o tempo desde a abertura da conta ([texto](https://legismap.com.br/leis-e-normas/resolucao-bcb-n-147-de-28-09-2021)), mas sozinha a idade é fraca: muitas laranjas são contas antigas alugadas ([RUSI via Outseer](https://www.outseer.com/blog/following-the-fraud-new-research-about-money-mule-networks)). Muitas vítimas convergindo para uma pessoa física é o padrão clássico ([FinEye](https://blogs.fineye.co/mule-account-detection)); o piso de valor tira a rifa da formatura (8 × R$ 20), e a conta nova converge com menos pagadores. A `suspeita_anterior` pega o golpe repetido do falso investimento, sem punir o aluguel do mês seguinte. A conta dormente reativada escapa da regra de idade ([DD News](https://ddnews.gov.in/en/mule-accounts-become-key-conduit-for-cyber-fraud-agencies-deploy-ai-tools-to-curb-misuse/)). |
| **7. Rastro do dinheiro** | **`RASTRO.repasse_rapido`**: recebeu de terceiros nos últimos 60 min e repassa ≥ 80% → +60 `mule` (sozinho, 2FA com aviso; com outro sinal de laranja, recusa); mesma titularidade não conta. **`RASTRO.conta_pagadora_recente`**: conta pagadora com < 30 dias, acima de R$ 1.000, para destino novo → +30 `mule`. **`RASTRO.proximidade_marcada`**: consulta recursiva de 2 saltos nos Pix aprovados das últimas 24 h: recebedor PF que recebeu de documento marcado — 1 salto recusa, 2 saltos +30 `mule`. | 60 min, 80%, 60 pts; 30 dias, R$ 1.000, 30 pts; 24 h, 2 saltos, 30 pts (**estimativas**) | Mais da metade do dinheiro sai da conta laranja em até uma hora, muitas vezes em menos de 15 minutos ([RUSI via Outseer](https://www.outseer.com/blog/following-the-fraud-new-research-about-money-mule-networks)); por isso o MED recuperou só 9,3% em 2025 ([BCB, MED 2.0](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/MED/MED_2-0_Circuito_Pix-Dia_1.pdf)). O saque costuma ocorrer entre a 2ª e a 5ª conta ([FCA](https://www.fca.org.uk/publications/multi-firm-reviews/money-mules-activity-cashing-out-findings)); a consulta recursiva imita o grafo do MED 2.0. Só vale para recebedor PF: um lojista que recebeu de um marcado bloquearia todos os clientes dele por 24 h. |
| **8. Anomalia** `ANOMALIA.ml` | Isolation Forest treinado só com Pix legítimos. **Modo sombra (o padrão da política):** o escore vai para o `metadata.ml` e não decide. **Modo ativo:** acima do corte, pontua invasão até +60; nunca recusa. | Corte 0,61 (p99 dos legítimos do treino), escala de 0,04 até o teto, teto 60 pts (**estimativas**) | Pega o que nenhuma regra descreve (o teste de contas com Pix de centavos). Detecção de anomalia, e não ML supervisionado, porque não há rótulo de fraude real para treinar. O modelo é exportado como JSON e avaliado em Python puro (`src/ml/`): sem `pickle`, e a API não carrega o scikit-learn. |

**Mesma titularidade** (pagador = recebedor) não é regra, é contexto: tira o Pix dos sinais de golpe, de conta laranja e do horário noturno, mas **não** da marcação, do aparelho não confiável nem da velocidade.

**Higiene do histórico.** Perfil só com Pix **aprovados**; Pix confirmado sob aviso de golpe fora do perfil; `fan_in` só para recebedor PF; datas convertidas para `America/Sao_Paulo` antes de qualquer regra de horário.

## Como as regras viram decisão

1. **Trava** por `id`, pagador, recebedor PF e aparelho, em ordem crescente de chave.
2. **Camadas 0 e 1** rodam sempre; cada sinal devolve `pass`, `warn` (pontua), `two_factor`, `reject`, `not_evaluated` (sem dado ou desligado) ou `not_needed` (dispensado: mesma titularidade, recebedor PJ...).
3. **Gatilho**: sem sinal e sem contexto de risco → caminho rápido. Senão, **camada 2** com tempo limite.
4. **Placares**: cada sinal que pontua soma no seu placar: `ato` (invasão), `app` (golpe com vítima autenticada) ou `mule` (conta laranja). Corte de 60 nos três (`DECISAO.placares`); faixa de aviso de golpe a partir de 30.
5. **Decisão**, com precedência `rejected` > `two_factor_required` > `approved`.

**As quatro formas de recusar** (`rejected`): marcação de fraude (`fraud_marker`); velocidade no corte de recusa (10 tentativas somando ≥ R$ 1.000: conta sendo esvaziada); placar `mule` ≥ 60 **com pelo menos 2 sinais de laranja diferentes** (`mule_account`); e `RASTRO.proximidade_marcada` a 1 salto. Um sinal de laranja sozinho não recusa.

| Situação | Status | `step_up_reason` | `step_up_method` | `scam_warning` |
|---|---|---|---|---|
| Marcação, conta laranja com 2 sinais, conta esvaziada, 1 salto de conta marcada | `rejected` | — | — | `false` |
| Aparelho não confiável acima do limite com outro sinal, velocidade, rajada de destinos novos, viagem impossível, fora da zona, ou placar `ato` ≥ 60 | `two_factor_required` | `account_takeover` | `face_liveness` | `true` se também houver suspeita de golpe |
| Cliente que o motor não conhece, aparelho novo, só o limite do aparelho (sem outro sinal) | `two_factor_required` | `device_registration` | `face_liveness` | `false` |
| Placar `app` ≥ 60 (inclusive `suspeita_anterior` sozinha), ou placar `mule` ≥ 60 com **um** sinal de laranja | `two_factor_required` | `possible_scam` | `in_app_confirmation`* | `true` |
| Limite noturno, fracionamento ou geolocalização ausente, sem outro sinal | `two_factor_required` | `limit` | `in_app_confirmation`* | `false` |
| Placar `app` entre 30 e 59 | `approved` (`recommended_action: warn`) | — | — | `false` |
| Nada disso | `approved` | — | — | `false` |

\* **O método depende do contexto.** A confirmação no app não protege quando o próprio celular está com o ladrão (na bateria de realidade, o celular roubado e desbloqueado confirmou 3 Pix seguidos no app). Qualquer 2FA vira `face_liveness` quando o aparelho não é confiável, quando houve biometria reprovada nas últimas 24 h em qualquer aparelho do pagador, ou quando o Pix está a mais de 5 km de todos os últimos locais aprovados (como o Modo Rua do Nubank). `in_app_confirmation` só fica para o aparelho confiável, perto do costume.

`recommended_action` vale `block` na recusa, `step_up` no 2FA, `warn` no aviso e `none` no resto. Se a camada 2 estourar o tempo, o 2FA sai pelo motivo que levou o Pix até ela.

O `metadata` de toda resposta traz a versão da política, o caminho (`fast`/`deep`), as camadas executadas, os placares, e cada sinal: os que dispararam em `reasons` (com valor observado, limite e mensagem em português), os que passaram em `passed`, e os dispensados ou sem dado em `not_needed` e `not_evaluated`. Traz ainda `ml` (escore e as features que mais pesaram) e `latency_ms` (da chegada do Pix à decisão pronta; a gravação e o commit ficam fora).

### Depois do 2FA: o `PATCH` de retorno

O slide define só o `POST` e o `GET`. Sem um retorno, o Pix que pediu 2FA ficaria gravado como `two_factor_required` para sempre, mesmo que o cliente tenha confirmado e o dinheiro tenha saído, e o motor nunca aprenderia com ele: o celular novo do cliente continuaria "novo". Por isso acrescentamos o retorno:

```bash
curl -s -X PATCH http://localhost:3000/pix/transaction/pix-000123 \
  -H "Content-Type: application/json" \
  -H "INTERNAL-TOKEN: default_token" \
  -d '{"two_factor_result": "passed", "completed_at": "2026-10-17T22:16:10-03:00"}'
```

`two_factor_result` é `passed` ou `failed`; `completed_at` é quando o 2FA terminou, com fuso. A resposta é o dossiê, igual ao do `GET`, com `initial_status`, `two_factor` e `status_history` (`null → two_factor_required → approved`).

**A rota é isolada e removível**: um método próprio no resource (`on_patch`), um no controller (`apply_two_factor_result`), um schema (`src/schemas/patch_pix_transaction.json`) e arquivos de teste próprios (`tests/integration/pix_transaction/test_pix_transaction_two_factor_return.py` e `tests/integration/scenarios/test_two_factor_return_scenarios.py`). Se a QI Tech disser que o retorno está fora do escopo, a rota sai sem quebrar o `POST` nem o `GET`.

**Trilha de status.** Toda análise grava um evento em `analysis_status_event` ao nascer (de nenhum status para o status decidido), no padrão do `sample_entity_status_event` do Base Service. O retorno grava um segundo evento (`two_factor_required → approved` ou `→ rejected`) e troca o status da análise. A decisão em si (placares, motivos, método) nunca muda, e um índice único impede um segundo retorno para a mesma análise.

**O que cada resultado ensina ao motor:**

| Resultado | O que o motor aprende | Por quê |
|---|---|---|
| `passed` com `face_liveness` | O aparelho fica **confiável na hora** para este pagador. O Pix entra no perfil, na soma noturna e no par pagador-recebedor | A biometria facial com prova de vida é o cadastro do aparelho que o BCB prevê: quem passou nela é o titular |
| `passed` por limite (`in_app_confirmation`) | O Pix entra no perfil, na soma noturna e no par. Conta como Pix aprovado para a regra dos 2 Pix com 24 h, mas **não** cadastra o aparelho | Confirmar um limite no app prova que o cliente quis aquele valor, não quem está com o aparelho |
| `passed` com aviso de golpe | **Não entra no perfil** e **não torna o destino recorrente**; conta só para a soma noturna e os tetos diários. E, por 90 dias, um novo Pix fora do perfil para o mesmo destino pede de novo 2FA com aviso (`suspeita_anterior`) | A vítima manipulada passa em qualquer 2FA e costuma pagar o mesmo golpista de novo. Se o Pix confirmado entrasse no perfil, o terceiro Pix de uma falsa central sairia sem sinal nenhum |
| `failed` | Status `rejected`. Nada entra no perfil. Se o 2FA pedia biometria, a confiança do aparelho fica **bloqueada por 24 h** | Biometria reprovada é o sinal mais forte de que outra pessoa está com o aparelho |

O retorno **não reavalia as regras** e **não conta como tentativa** na velocidade. Ele toma a mesma trava do `POST`: dois retornos simultâneos com resultados diferentes viram fila, e o segundo recebe 409.

## Exemplo resolvido

O payload do slide da QI Tech (R$ 1.500 às 22h15; conta pagadora de 2025-03-02; destino aberto há 7 dias; pagador sem histórico no motor), rodado contra o código deste repositório (banco recém-criado). Resposta real, resumida:

```json
{
  "key": "311731fe-40f6-4a9e-a2b1-5a3770659aff",
  "status": "two_factor_required",
  "metadata": {
    "policy_version": "2026.10.1", "path": "deep", "layers": [0, 1, 2],
    "typology": "account_takeover", "recommended_action": "step_up",
    "step_up_reason": "account_takeover", "step_up_method": "face_liveness", "scam_warning": true,
    "scores": {"ato": 60, "app": 0, "mule": 60},
    "reasons": [ "...os 4 sinais abaixo..." ],
    "ml": {"mode": "shadow", "status": "evaluated", "model_version": "iforest-v1", "anomaly_score": 0.6295},
    "latency_ms": 272
  }
}
```

| Sinal | Resultado | Pontos |
|---|---|---|
| `LIMITE.aparelho_nao_cadastrado` | R$ 1.500 num aparelho ainda não confiável, acima dos R$ 200 por Pix → `two_factor` (invasão) | — |
| `LIMITE.noturno` | R$ 1.500 PF→PF às 22h, acima de R$ 1.000 e do maior Pix noturno já aprovado (R$ 0) → `two_factor` (limite) | — |
| `PERFIL.valor` | sem histórico, acima do limite de partida de R$ 1.000, aparelho não confiável | `ato` +60 |
| `CONTA_RECEBEDORA.conta_nova` | 7 dias, primeiro crédito, fora do perfil | `mule` +60 |

Placares: `ato` 60, `app` 0, `mule` 60. A conta laranja tem **um** sinal só, então **não recusa** (a recusa exige dois). Há motivo de invasão (aparelho não confiável, com outros sinais de risco junto, então não é só o cadastro do aparelho) e de golpe (conta laranja ≥ corte): **`two_factor_required`**, `account_takeover`, `face_liveness` e `scam_warning: true`. Os sinais de local (viagem impossível, fora da zona) e de canal saíram `not_evaluated` porque o pagador não tem histórico para comparar, e o escore de anomalia (0,6295, acima do corte de 0,61) aparece só no modo sombra. A mesma sequência é um teste de cenário (`tests/integration/scenarios/test_scenarios.py`).

## O que o motor enxerga

O motor só vê os Pix **de clientes da QI Tech que passam por ele**. Ele não consulta o DICT nem outros bancos (requisito de tempo e escopo). Isso limita quatro tipos de sinal:

| Sinal | Depende de | O que não aparece |
|---|---|---|
| `RASTRO.repasse_rapido` | créditos recebidos por clientes da QI Tech | dinheiro que a conta recebeu de fora |
| `CONTA_RECEBEDORA.fan_in` | pagadores que passam pelo motor | a mesma laranja recebendo de outras 40 instituições |
| `CONTA_RECEBEDORA.dormente` | movimento na nossa base | a conta pode ter movimentado em outro banco |
| `CONTA_RECEBEDORA.varias_instituicoes` | contas que já foram destino no motor | as demais contas do CPF |
| `QUEM_OPERA.aparelho_compartilhado`, `ip_compartilhado` | Pix que passaram pelo motor | aparelhos e IPs usados em outros bancos |
| `QUEM_OPERA.viagem_impossivel`, `fora_da_zona` | último(s) local(is) de Pix aprovados no motor | deslocamentos entre Pix feitos em outros bancos |
| `RASTRO.proximidade_marcada` | fluxo dentro da base; a tabela `fraud_marker` simula o DICT | marcações reais do DICT |

O caminho para superar essa cegueira é a consulta ao DICT (estatísticas de marcações em janelas de 90 dias, 12 meses e 60 meses). No portfólio da QI Tech, a biometria `face_liveness` é o passo de 2FA; Background Check e Device Scan seriam fontes futuras de sinal.

## Limitações conhecidas

Tiradas da bateria de realidade (`docs/bateria-realidade.md`), que encena 12 golpes passo a passo e 90 clientes legítimos por 60 dias. Cada uma com o próximo passo:

| Limitação | O que aconteceu | Próximo passo |
|---|---|---|
| **Falso parente** (conta de 15 dias, R$ 1.890 e R$ 2.300) | Os dois saem `approved`: o cliente simulado já paga R$ 2–3 mil a destinos novos, então o valor está dentro do perfil dele | Sinal de "primeiro Pix para conta nova acima de X" independente do perfil, calibrado com o resultado real do 2FA |
| **Celular roubado na rua** | O 1º Pix de R$ 900, aprovado longe de casa, passa a valer como zona habitual, e o 2º Pix já não parece distante | Só aprender local novo depois de confirmação de titularidade (ou local fora da zona só entra no perfil após 24 h) |
| **Coação** (sequestro relâmpago) | A vítima coagida passa no 2FA; só o limite noturno e a rajada seguram | Sem sinal no payload; exigiria biometria comportamental ou botão de pânico no app |
| **Teste de contas** (25 Pix de R$ 0,01) | Todos aprovados; só o ML pegaria, e em modo sombra ele só registra | Decidir, com dados reais, se o modo ativo entra e com que escala de pontos |
| **Ladrão que espera 24 h** | Se ele espera o aparelho "esfriar" e faz Pix pequenos, o aparelho vira confiável | Aumentar o tempo de confiança para clientes de alto valor, ou exigir biometria para o 1º Pix acima de R$ 1.000 |
| **Golpe sem sinal no contrato** | Ligação em andamento e app de acesso remoto instalado não chegam no payload | SDK no app e sinais do Device Scan |
| **Salário pelo internet banking** | Sem geolocalização, todo Pix acima de R$ 500 pede 2FA de limite (62 Pix no simulador) | Exceção por canal ou por PJ pagadora, decisão do grupo |
| **Todo primeiro Pix acima de R$ 200** | Pede o cadastro do aparelho, de propósito | Some com a carga do histórico em produção |
| **Consultas da camada 2** | Rodam em todo Pix; só a *avaliação* dos sinais depende do gatilho | Condicionar as consultas ao gatilho, se o custo pesar |
| **Latência** | Medida nesta máquina (Windows, Docker Desktop, código montado por volume) o p95 passa de 200 ms; em outro ambiente foi de ~50 ms | Medir na máquina da demonstração antes de prometer um número |

## Resultados

**Leia antes dos números.** O simulador e a bateria são do próprio grupo: os cenários de fraude foram desenhados por nós, conhecendo as regras. Os números são **teste de regressão da política e medida de fricção**, e **não eficácia**: não dizem quanto o motor pegaria de fraude real. O motor só vê Pix de clientes da QI Tech, e o simulador reproduz isso (70% dos créditos que as contas recebem vêm de pagadores que o motor nunca vê).

**Simulador** (semente 2, 200 clientes, 6.915 Pix, modelo treinado com a semente 1; `docs/resultados-simulador.md`):

| Tipologia | Pix | Pego (Pix) | Pego (valor) |
|---|---:|---:|---:|
| Conta invadida | 103 | 63,1% | 84,0% |
| Golpe | 48 | 43,8% | 71,5% |
| Conta laranja | 44 | 100% | 100% |
| Padrão novo (nenhuma regra cobre) | 106 | 0,0% | 0,0% |

Clientes legítimos: 6.614 Pix, **2,8% com 2FA, 0,0% recusados**. Com o ML em modo ativo, o ganho é de +2,8 p.p. só no padrão novo, sem mudar a fricção: por isso o padrão da política é o modo sombra.

**Bateria de realidade** (semente 2026, banco do zero; `docs/bateria-realidade.md`): 4.543 Pix legítimos em 60 dias: 89,4% aprovados sem aviso, 4,1% aprovados com aviso e 6,5% com 2FA; nos últimos 15 dias, 92,6% aprovados sem aviso, 2,7% com aviso e o resto com 2FA. Dos 12 golpes encenados, a falsa central, o falso investimento, a falsa venda, a mão fantasma, o SIM swap, a laranja de passagem, a fazenda de contas e a marcação são travados; o falso parente, o teste de contas e o 2º Pix do celular roubado na rua são as limitações acima.

Reproduzir:

```bash
python scripts/simulator/prepare_db.py --ml-mode shadow   # APAGA o banco
python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/regras.jsonl   # ~25 min
python scripts/simulator/report.py scripts/simulator/output/regras.jsonl
python scripts/realidade/bateria_realidade.py 2026       # ~20 min, contra um banco recriado
```

## LGPD e dados

- **Base legal**: prevenção à fraude e à segurança do titular. O enquadramento exato na LGPD deve ser confirmado com o jurídico da QI Tech; este README não cita artigo porque a pesquisa do grupo não o verificou no texto oficial. A biometria facial não é tratada pelo motor: ele só recebe o resultado do 2FA.
- **Nada pessoal em log.** O middleware de log não grava o corpo da requisição; documento, IP e geolocalização nunca vão para o log da aplicação. Os documentos ficam normalizados (só dígitos) no banco.
- **Retenção.** O motor guarda o histórico que as regras usam (janelas de até 90 dias, e 24 h de bloqueio). Ele **não implementa expurgo**: em produção, o prazo de guarda e a anonimização seriam definidos pelo controlador. Referência: as marcações de fraude duram 5 anos (Res. BCB 587/2026).
- **`observed` e `threshold`** no `metadata` seriam internos em produção: não se mostra ao fraudador onde fica o corte. Aqui eles aparecem porque o `GET` é o dossiê de auditoria.
- A mesma trilha (versão da política, motivo, valor observado e limite de cada sinal) é o que a Res. BCB 403 pede como documentação da solução de risco e o que o STJ cobra como prova de diligência.

## Decisões e trade-offs: considerado e descartado

| Considerado | Decisão | Por quê |
|---|---|---|
| Blockchain | Descartado. A cadeia de hashes por pagador ("evidência de adulteração simples") foi cortada | Complexidade sem ganho para o escopo; o banco já guarda cada decisão com versão e motivo |
| ML supervisionado | Isolation Forest (detecção de anomalia), só em modo sombra | Não há rótulo de fraude real para treinar; o ganho medido em modo ativo foi pequeno |
| Recusar o golpe (`rejected`) | 2FA com aviso de golpe; `rejected` só com evidência dura | A vítima manipulada passa em qualquer 2FA, mas recusar o vendedor de carro usado é prejuízo para o cliente bom; o slide define reprovar como "risco claro" |
| `hold_timer` (retenção de 30/60 min da pesquisa) | Removido: o contrato só tem três status | A "suspeita" vira 2FA com aviso ou `approved` com aviso; em produção o timer regulatório entraria aqui |
| DICT real | Tabela `fraud_marker` simulada | Requisito de tempo e escopo: o motor não chama serviço externo |
| Retorno do 2FA fora do slide | `PATCH` isolado e removível | Sem ele o motor não aprende com o 2FA confirmado |
| Período de aprendizado do cliente desconhecido | Removido: a Res. BCB 403 vale para todos, com `device_registration` | Decisão do grupo; a norma vale para todos e o cadastro de dispositivo é produto da QI Tech |

## Como rodar e testar

Precisa de **Docker** (com `docker compose`) e de **Python 3.11 ou 3.12** para os testes (as versões fixadas em `requirements.txt` não têm pacote pronto para o Python 3.14).

```bash
docker compose up
```

Espere o `api` e o `db` ficarem `(healthy)`. A API atende em `http://localhost:3000`. Na primeira vez o Docker baixa `postgres:16` e `python:3.11-slim`; **sem `docker login`, o Docker Hub pode responder `429 Too Many Requests`**: rode `docker login` (conta gratuita) e tente de novo.

### O `INTERNAL-TOKEN`

Toda rota, menos `/` e `/health_check`, exige o header `INTERNAL-TOKEN`. O valor padrão é `default_token` (vem do `docker-compose.yml`; para trocar, copie o `.env.example` para `.env`). Sem ele, a resposta é 403.

### Mandar um Pix

No Windows, use o Git Bash (vem com o Git) ou `curl.exe` com o JSON num arquivo (`-d "@pix.json"`): o `curl` do PowerShell é outro programa.

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

Resposta esperada: HTTP 201 com `"status": "two_factor_required"`, `"step_up_method": "face_liveness"` e `"scam_warning": true` (veja o [exemplo resolvido](#exemplo-resolvido)).

### Consultar a análise gravada

```bash
curl -s http://localhost:3000/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
```

O `GET` é o dossiê: a decisão do `POST`, com o status atual, mais `initial_status`, `two_factor` e `status_history`.

### Mandar o retorno do 2FA

O `curl` do `PATCH` está em [Depois do 2FA](#depois-do-2fa-o-patch-de-retorno). Repetir o mesmo `PATCH` dá 200; mandar `"failed"` depois de `"passed"` dá 409.

### Respostas da API

| Situação | HTTP |
|---|---|
| Pix novo, analisado e gravado (inclusive quando a decisão é `rejected`) | 201 `{key, status, metadata}` |
| Mesmo `id` com o mesmo conteúdo (retentativa), documentos comparados só com dígitos | 200 com a análise já gravada, sem reavaliar |
| Mesmo `id` com conteúdo diferente | 409 `QIT001002` |
| JSON fora do schema (campo faltando, tipo errado, campo a mais) | 400 `QIT000001` |
| CPF ou CNPJ com dígito verificador inválido | 422 `QIT001003` |
| IP que não é IPv4 nem IPv6 válido | 422 `QIT001006` |
| Data que não existe no calendário | 422 `QIT001004` |
| `GET` de um `id` desconhecido | 404 `QIT001001` |
| `PATCH` de uma análise em `two_factor_required` | 200 com o dossiê atualizado |
| `PATCH` com resultado diferente do já gravado | 409 `QIT001008` |
| `PATCH` de uma análise que não pediu 2FA | 409 `QIT001009` |
| `PATCH` com `completed_at` anterior ao `transaction_date` do Pix | 422 `QIT001007` |
| Sem `INTERNAL-TOKEN` ou com o token errado | 403 `QIT000002` |

Uma recusa antifraude **não é erro HTTP**: o Pix foi analisado com sucesso, e a resposta é 201 com `status: rejected`.

### Marcações de demonstração

O seed do `database/database.sql` traz documentos fictícios marcados, para a demonstração e para os testes:

| Documento | Marcação | Efeito |
|---|---|---|
| `111.444.777-35` | própria, vigente | recusa |
| `222.555.888-46` | de outro PSP, há menos de 90 dias | recusa |
| `333.666.999-57` | de outro PSP, há mais de 90 dias | não decide |
| `444.777.000-83` | própria, vencida | não decide |

### Rodar os testes

Os testes são caixa-preta: falam com a API só por HTTP e nenhum arquivo de teste importa código de `src/`. Com a API de pé, em outro terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate          # no Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

No Windows, o endereço `0.0.0.0` não conecta: crie o `.env` (`copy .env.example .env`) e troque `SERVER_LOCALHOST=0.0.0.0` por `SERVER_LOCALHOST=127.0.0.1`. Se a porta 5432 ou 3000 já estiver ocupada (um Postgres local, por exemplo), ponha `DB_PORT=5433` ou `API_PORT=3001` no `.env` e ajuste a `DATABASE_URL`. A suíte inteira leva de 2 a 4 minutos (depende da máquina) e termina com **193 passed**.

### Mudou o `database/database.sql`?

Ele só roda quando o banco nasce. Para recriar o banco do zero (também antes de cada medição do simulador ou da bateria, e depois de rodá-los):

```bash
docker compose down -v
docker compose up
```

### Demonstração, simulador e bateria

```bash
python scripts/demo/demo.py                       # ~3 s: quatro histórias, só por HTTP
python scripts/simulator/prepare_db.py --ml-mode shadow   # APAGA o banco
python scripts/simulator/run.py --seed 2 --output scripts/simulator/output/regras.jsonl
python scripts/realidade/bateria_realidade.py 2026       # contra um banco recriado do zero
```

O modelo de anomalia se treina dentro do container (`scripts/ml/train.py`; o comando está no topo do arquivo).

## Como o projeto é organizado

A seta anda num sentido só: `resources → controllers → repositories → models`. O mapa de cada pasta está em [`docs/como-o-projeto-e-organizado.md`](docs/como-o-projeto-e-organizado.md).
