# Motor Antifraude Pix — Hackathon QI Tech 2026 (Grupo 47)

API que recebe um Pix e devolve `approved`, `two_factor_required` ou `rejected`, com motivo explicável.
Entrega: link do repositório no Slack (grupo da final) até **domingo 18/10, 12h**. Código congela às 10h30.

## Fontes de verdade (leia antes de mudar o desenho)

- **Este arquivo foi revisado em 17/10, 15h.** Onde ele e o `docs/PLANO.md` divergirem, vale ESTE arquivo
  (seções "Como o motor decide", "Confiança do aparelho", "Cliente que o motor ainda não conhece" e "Sinais novos").
- `docs/PLANO.md` — plano completo: fases, catálogo das 8 regras e dos sinais, modelo de dados, contrato, checklist.
- `docs/pesquisa-fraude-pix.md` — a pesquisa com a fonte de cada parâmetro (o "por quê" do README sai daqui).
- `docs/como-o-projeto-e-organizado.md` — padrões do Base Service. Eles valem mais que qualquer preferência sua.
- Se o código e estes documentos divergirem, pare e pergunte. Não invente regra, parâmetro ou número.

## Padrões do Base Service (obrigatórios: são critério de avaliação)

- A seta anda num sentido só: `resources → controllers → repositories → models`.
- `resources/`: recebe, valida schema, chama UM controller, devolve. Sem SQL, sem regra de negócio.
- `schemas/`: entrada validada por JSON Schema (`@SchemaHandler.validate("post_pix_transaction.json")`). Campo a mais → 400.
- `controllers/`: decidem o que pode. Só o controller chama `get_context()` e faz `self.session.commit()`.
- `repositories/`: só consultas. Nenhum `if` de regra de negócio.
- `dtos/`: montam a resposta. O que o DTO monta é exatamente o que sai.
- `errors/custom_errors.py`: todo erro com `title`, `description`, `translation`, `code` (`QIT...`) e status HTTP.
- `connectors/`: nenhum. O motor não chama serviço externo (requisito de tempo).
- Entidade nova que depende de outra entra DEPOIS dela em `src/models/__init__.py`.
- `database/database.sql` só roda quando o banco nasce: mudou o SQL → `docker compose down -v && docker compose up`.
- Dependência nova → versão exata (`==`) no `requirements.txt` e `docker compose build api`.
- Nunca logue o payload, documento, IP ou geolocalização. O middleware de log já não loga o corpo; não desfaça isso.

## Testes

- Caixa-preta: os testes falam com a API só por HTTP. **Nenhum arquivo de teste importa código de `src/`.**
- TDD: escreva o teste, veja falhar, depois implemente.
- Um cenário por sinal: o Pix que dispara e o que fica logo abaixo do limite.
- Datas fixas no payload (`transaction_date`), nunca o relógio da máquina.
- Testes de concorrência: 10 Pix paralelos do mesmo pagador; 6 pagadores diferentes ao mesmo tempo para a mesma conta PF.
- **Testes de cenário de ponta a ponta** (`tests/integration/scenarios/`), com o status esperado de cada um:

  | Cenário | Status esperado |
  |---|---|
  | Exemplo do slide: R$ 1.500 às 22h15, conta pagadora de 2025-03-02, destino aberto há 7 dias, pagador sem histórico no motor | `two_factor_required` com aviso de golpe |
  | Primeiro Pix de um cliente desconhecido pelo motor, conta pagadora antiga, R$ 300 às 14h para conta antiga | `approved` |
  | Mesmo cliente desconhecido, R$ 1.500 às 14h para conta antiga | `two_factor_required` |
  | Celular roubado: aparelho novo faz Pix de R$ 10 (aprovado) e, 3 minutos depois, R$ 5.000 para destino novo | o segundo é `two_factor_required` com `face_liveness` |
  | Carro usado: cliente com histórico paga R$ 35.000 de dia a conta aberta há 20 dias (primeiro crédito) | `two_factor_required` com aviso de golpe (não `rejected`) |
  | Conta laranja: conta PF aberta há 10 dias recebe Pix de R$ 300 de 5 pagadores distintos em 1 h | o 5º é `rejected` (conta nova + fan-in) |
  | Reenvio do mesmo `id` com o CPF mascarado (`123.456.789-09` em vez de `12345678909`) | 200 com a análise gravada (não 409) |
  | Mesmo pagador reenvia o mesmo valor para o mesmo destino com `id` novo, 3 vezes em 5 min | conta como 1 tentativa na velocidade |

## Contrato

- `POST /pix/transaction` → 201 `{key, status, metadata}` (só esses três campos).
  - mesmo `id` + mesmo conteúdo → 200 com a análise já gravada, sem reavaliar e sem contar de novo;
  - o hash de idempotência é calculado sobre o payload **normalizado** (documentos só com dígitos), não sobre o bruto;
  - mesmo `id` + conteúdo diferente → 409;
  - fora do schema → 400; CPF/CNPJ com dígito inválido → 422; IP que não é IPv4/IPv6 válido → 422;
  - recusa antifraude NÃO é erro HTTP: é 201 com `status: rejected`.
- `GET /pix/transaction/{id}` → 200 com a mesma resposta do POST (é o "dossiê" da análise); desconhecido → 404.
- Toda rota, menos `/` e `/health_check`, exige `INTERNAL-TOKEN` (403 sem ele).
- `geolocation` é opcional. Sinal sem dado → `not_evaluated`, nunca aprovar em silêncio.

## Convenções

- Dinheiro em centavos (`BIGINT`). R$ 200 = 20000; R$ 1.000 = 100000.
- `_key` (UUID) sai na resposta; `id` interno nunca sai.
- Horários convertidos para `America/Sao_Paulo` antes de qualquer regra de horário.
- Documentos normalizados só com dígitos. PF = 11 dígitos, PJ = 14.
- Parâmetros (inclusive pontos e cortes) vêm da tabela `rule_parameter`, nunca de constante no código.

## Como o motor decide (REVISADO)

O slide da QI Tech define: **reprovar = "bloqueia quando o risco é claro"**; **2FA = "fricção só onde há dúvida"**.
A decisão segue isso à risca:

1. **Trava** com `pg_advisory_xact_lock` sobre: `id` do Pix, documento do pagador, documento do recebedor (só se PF)
   e `device_id`, sempre em ordem crescente de chave.
2. **Camadas 0 e 1** sempre; **gatilho**; **camada 2** só com sinal de risco (tempo limite 300 ms).
3. **`rejected` só com evidência dura.** São as únicas formas de recusar:
   - `MARCACAO.lista` (Res. BCB 587/2026);
   - `RITMO.velocidade` no corte de recusa (conta sendo esvaziada);
   - placar `mule` acima do corte **E pelo menos dois sinais de conta laranja diferentes** disparados
     (ex.: conta nova + fan-in; conta nova + repasse rápido);
   - `RASTRO.proximidade_marcada` a 1 salto (Fase 3).
   Um sinal de conta laranja sozinho, por mais pontos que tenha, **não recusa**.
4. **`two_factor_required`** quando há dúvida. O `metadata` diz POR QUE e COMO:
   - `step_up_reason: "account_takeover"` → `step_up_method: "face_liveness"`
     (aparelho não confiável, viagem impossível, fora da zona habitual, velocidade). SMS não serve: no SIM swap o fraudador
     recebe o SMS. Biometria facial com liveness é produto da própria QI Tech.
   - `step_up_reason: "possible_scam"` → `step_up_method: "in_app_confirmation"` + `scam_warning: true`
     (placar `app` acima do corte, ou um único sinal forte de conta laranja). O 2FA sozinho não protege contra golpe;
     a fricção útil é a confirmação com aviso de golpe na tela.
   - `step_up_reason: "limit"` → `step_up_method: "in_app_confirmation"` (limite noturno, sem outro sinal).
   - Se houver motivo de invasão e de golpe ao mesmo tempo, `face_liveness` + `scam_warning: true`.
5. **`approved` com `recommended_action: "warn"`** quando o placar `app` está na faixa de aviso.
6. **`hold_timer` não existe mais** (código, `recommended_action` e CHECK do banco). Valores de `recommended_action`:
   `none`, `warn`, `step_up`, `block`.
7. Precedência: `rejected` > `two_factor_required` > `approved`. Tempo limite da camada 2 estourado → 2FA com
   `step_up_reason` do sinal que levou à camada 2.
8. **Grava** transação, análise, um resultado por sinal, features; atualiza as agregadas; commit.

## Confiança do aparelho (REVISADO — fecha a brecha do Pix pequeno)

- Um aparelho só é **confiável** para um pagador quando tem **pelo menos 2 Pix aprovados** desse pagador
  **e o primeiro deles foi há pelo menos 24 h** (em relação ao `transaction_date` do Pix avaliado).
- Enquanto não é confiável: limite de R$ 200 por Pix e R$ 1.000 por dia **somando todos os Pix aprovados de
  aparelhos não confiáveis** do pagador no dia de Brasília. Acima → `two_factor_required` / `face_liveness`.
- Aparelho não confiável também conta como "aparelho novo" para `PERFIL.valor` (pontua `ato`, não `app`).
- Motivo: hoje um Pix de R$ 10 aprovado torna o aparelho "conhecido", e o próximo Pix de R$ 5.000 do ladrão sai
  `approved` com `warn`. Isso não pode acontecer.

## Cliente que o motor ainda não conhece (NOVO — banco vazio na avaliação)

- "Desconhecido" = nenhum Pix desse pagador gravado no motor.
- Se a conta pagadora (`source_account.opening_date`) tem **pelo menos 180 dias**: o aparelho não pede 2FA até o
  limite de partida (`PERFIL.valor.fallback_amount`, R$ 1.000). O sinal de aparelho sai `not_evaluated` com a mensagem
  "o motor ainda não tem histórico deste pagador". Acima do limite de partida → 2FA (`face_liveness`).
- Se a conta pagadora tem menos de 180 dias: regra normal de aparelho não confiável.
- Explicar no README: em produção o motor nasce com a carga do histórico; isto evita tratar todo cliente como fraude
  no primeiro dia, sem abrir mão do limite.

## Sinais novos (Fase 3 — usam campos do payload que hoje nenhuma regra lê)

- `QUEM_OPERA.canal_incomum` (Regra 5): canal (`source.channel`) que o pagador nunca usou num Pix aprovado,
  com valor acima do limite de partida → pontua `ato`.
- `QUEM_OPERA.ip_compartilhado` (Regra 5): 3 ou mais CPFs pagadores distintos no mesmo IP em 1 h. **Só pontua junto com
  aparelho não confiável** (redes móveis põem muita gente no mesmo IP). Nunca decide sozinho.
- `RASTRO.conta_pagadora_recente` (Regra 7): conta pagadora aberta há menos de 30 dias mandando valor acima do limite
  de partida para destino novo → pontua `mule` (laranja de segundo salto / fraude de abertura).
- Todos com parâmetros em `rule_parameter`, um teste que dispara e um logo abaixo.

## Velocidade

- Reenvio com `id` novo, mesmo pagador, mesmo recebedor e mesmo valor dentro da janela conta como **uma** tentativa.
  Sem isso, o cliente que refaz o Pix depois do 2FA é empurrado para a recusa.

## Higiene do histórico

- Perfil do pagador só com Pix **aprovados** (90 dias). Tentativas recusadas contam na velocidade.
- Mesma titularidade fica fora dos sinais de golpe, de conta laranja e do horário noturno.
- `LIMITE.noturno` é sinal, não teto: o motor não sabe o limite configurado do cliente.
- `CONTA_RECEBEDORA.fan_in` só vale para recebedor PF.

## Ordem de trabalho

- Fases 1 e 2: feitas (67 testes verdes em 17/10 15h). Antes de seguir, aplicar as revisões deste arquivo.
- Fase 3: Regra 5 (aparelho compartilhado, viagem impossível, zona habitual, canal incomum, IP compartilhado),
  Regra 7 (repasse rápido, proximidade de conta marcada, conta pagadora recente), sinais restantes das Regras 2, 3 e 6,
  `latency_ms`. Cadeia de hashes por pagador fica por ÚLTIMO e é a primeira a cortar; se entrar, o README a descreve
  como "evidência de adulteração simples", sem comparar com blockchain.
- Fase 4: simulador por HTTP (`scripts/simulator/`, cenário no prefixo do `id`). **70% dos créditos que as contas
  recebem vêm de fora** (de pagadores que o motor nunca vê), porque o motor só enxerga Pix de clientes da QI Tech.
  Isolation Forest (`scripts/ml/`), treinado DENTRO do container, modo sombra. Os números do simulador são teste de
  regressão e medida de fricção, não eficácia.

Se o tempo apertar, corte sinais dentro das regras, nunca a matriz de erros reais nem o caminho rápido.

## README (Fase 5) — itens obrigatórios além do modelo da banca

- Exemplo resolvido com o payload do slide: cada sinal, pontos, placar e a decisão final (igual ao teste de cenário).
- Coluna "visibilidade" por sinal: o motor só vê Pix de clientes da QI Tech (repasse rápido, fan-in e destino que
  reaparece dependem disso).
- "O que acontece depois do 2FA": o contrato não traz o resultado; por isso o aparelho só vira confiável com Pix
  aprovados em dias diferentes. Próximo passo: retorno do 2FA (`two_factor_required → approved | rejected`) no padrão de
  trilha de status do Base Service.
- Portfólio QI Tech: `face_liveness` no step-up; Background Check e Device Scan como fontes futuras de sinais;
  a tabela `fraud_marker` simula o DICT.
- LGPD: base legal de prevenção à fraude, nada pessoal em log, prazo de retenção, e que `observed`/`threshold` no
  `metadata` seriam internos em produção (não se mostra ao fraudador onde fica o corte).
- Sem superlativos. Toda norma citada conferida no texto oficial.

## Fora do escopo (não faça)

Front-end, onboarding/cadastro de contas, endpoints de configuração ou qualquer outra API (inclusive a rota de retorno
do 2FA, a menos que a QI Tech autorize), connectors externos, blockchain.
