# Motor Antifraude Pix — Hackathon QI Tech 2026 (Grupo 47)

API que recebe um Pix e devolve `approved`, `two_factor_required` ou `rejected`, com motivo explicável.
Entrega: link do repositório no Slack (grupo da final) até **domingo 18/10, 12h**. Código congela às 10h30.

## Fontes de verdade (leia antes de mudar o desenho)

- `docs/PLANO.md` — plano completo: fases, catálogo das 8 regras e 17 sinais, modelo de dados, contrato, checklist.
- `docs/pesquisa-fraude-pix.md` — a pesquisa com a fonte de cada parâmetro (o "por quê" do README sai daqui).
- `docs/como-o-projeto-e-organizado.md` — padrões do Base Service. Eles valem mais que qualquer preferência sua.
- Se o código e o `docs/PLANO.md` divergirem, pare e pergunte. Não invente regra, parâmetro ou número.

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

## Testes

- Caixa-preta: os testes falam com a API só por HTTP. **Nenhum arquivo de teste importa código de `src/`.**
- TDD: escreva o teste, veja falhar, depois implemente.
- Um cenário por sinal: o Pix que dispara e o que fica logo abaixo do limite.
- Datas fixas no payload (`transaction_date`), nunca o relógio da máquina.
- Testes de concorrência: 10 Pix paralelos do mesmo pagador; 6 pagadores diferentes ao mesmo tempo para a mesma conta PF.

## Contrato

- `POST /pix/transaction` → 201 `{key, status, metadata}` (só esses três campos).
  - mesmo `id` + mesmo conteúdo → 200 com a análise já gravada, sem reavaliar e sem contar de novo;
  - mesmo `id` + conteúdo diferente → 409 (compare hash do payload);
  - fora do schema → 400; CPF/CNPJ com dígito inválido → 422 (use `utils/document_number.py`);
  - recusa antifraude NÃO é erro HTTP: é 201 com `status: rejected`.
- `GET /pix/transaction/{id}` → 200 com a mesma resposta do POST; desconhecido → 404.
- Toda rota, menos `/` e `/health_check`, exige `INTERNAL-TOKEN` (403 sem ele).
- `geolocation` é opcional. Sinal sem dado → `not_evaluated`, nunca aprovar em silêncio.

## Convenções

- Dinheiro em centavos (`BIGINT`). R$ 200 = 20000; R$ 1.000 = 100000.
- `_key` (UUID) sai na resposta; `id` interno nunca sai.
- Horários convertidos para `America/Sao_Paulo` antes de qualquer regra de horário.
- Documentos normalizados só com dígitos. PF = 11 dígitos, PJ = 14.
- Parâmetros vêm da tabela `rule_parameter` (política versionada), nunca de constante no código.

## Como o motor decide

1. **Trava** com `pg_advisory_xact_lock` sobre: documento do pagador, documento do recebedor (só se PF) e `device_id`. Sempre em ordem crescente de chave, para não haver impasse.
2. **Camada 0** (sempre): `MARCACAO.lista` (recusa sozinho), `LIMITE.aparelho_nao_cadastrado` (2FA sozinho), `LIMITE.noturno`, `RITMO.velocidade`, contexto de mesma titularidade.
3. **Camada 1** (sempre, leitura das tabelas agregadas): `PERFIL.valor`, `LIMITE.sem_geolocalizacao`, `QUEM_OPERA.viagem_impossivel`, `CONTA_RECEBEDORA.conta_nova`, `CONTA_RECEBEDORA.fan_in`.
4. **Gatilho**: sem sinal de risco → `approved` pelo caminho rápido (`metadata.path = "fast"`).
5. **Camada 2** (só com sinal; tempo limite 300 ms; estourou → 2FA): os demais sinais e `ANOMALIA.ml`.
6. **Decisão** pelos placares `ato` (conta invadida), `app` (golpe), `mule` (conta laranja):
   - `mule` ou `app` acima do corte → `rejected`;
   - `ato` acima do corte → `two_factor_required`;
   - `app` na faixa de aviso → `approved` com `recommended_action: "warn"`;
   - precedência: `rejected` > `two_factor_required` > `approved`.
7. **Grava** transação, análise, um resultado por sinal, features usadas; atualiza `payer_profile`, `payer_payee_pair`, `device_owner`; hash encadeado com a análise anterior **do mesmo pagador**; commit.

Regras em `src/controllers/rules/`: uma classe por regra (8), interface comum
`evaluate(features, params, camada) -> list[SignalResult]`. Cada sinal devolve código, resultado
(`pass`/`warn`/`two_factor`/`reject`/`not_evaluated`/`not_needed`), pontos, valor observado, limite e mensagem em português.
Consultas de janela ficam em `src/repositories/pix_feature_repository.py`.

## Higiene do histórico

- Perfil do pagador só com Pix **aprovados** (90 dias). Tentativas recusadas contam na velocidade.
- Mesma titularidade fica fora dos sinais de golpe, de conta laranja e do horário noturno.
- `LIMITE.noturno` é sinal, não teto: o motor não sabe o limite configurado do cliente.
  Passa se o valor está dentro do maior Pix noturno já aprovado do pagador; senão 2FA; com sinal de golpe/laranja, recusa.
- `CONTA_RECEBEDORA.fan_in` só vale para recebedor PF.

## Ordem de trabalho

Siga as fases do `docs/PLANO.md`. Não comece uma fase sem o portão da anterior verde.
- Fase 1: banco, schema, POST/GET gravando e consultando, idempotência, erros, testes de contrato.
- Fase 2 (MVP, ponto de segurança): Regras 1 e 4 completas; Regra 2 (aparelho, noturno); Regra 3 (velocidade); Regra 6 (conta nova, fan-in); camadas; trava; metadata.
- Fase 3: sinais restantes, faixa de aviso, política versionada, cadeia de hashes, `latency_ms`.
- Fase 4: simulador por HTTP (`scripts/simulator/`, cenário no prefixo do `id`) e Isolation Forest (`scripts/ml/`, modo sombra primeiro).

Se o tempo apertar, corte sinais dentro das regras, nunca a matriz de erros reais nem o caminho rápido.

## Fora do escopo (não faça)

Front-end, onboarding/cadastro de contas, endpoints de configuração ou qualquer outra API, connectors externos, blockchain.
