-- ─────────────────────────────────────────────────────────────────
-- Motor antifraude Pix: o banco guarda TUDO o que chegou, inclusive o
-- que foi recusado, e cada decisão com o seu porquê.
--
-- Este arquivo roda UMA vez, quando o banco nasce. Mudou alguma coisa
-- aqui? `docker compose down -v && docker compose up`.
--
-- Convenções:
--   • dinheiro em centavos (BIGINT): R$ 200 = 20000;
--   • datas de negócio em TIMESTAMPTZ: o Postgres guarda o instante, e
--     o fuso de Brasília só entra na regra que fala de horário;
--   • documento (CPF/CNPJ) só com dígitos: 11 = PF, 14 = PJ;
--   • `_key` (UUID) é o que sai na API; `id` nunca sai.
-- ─────────────────────────────────────────────────────────────────


-- Enumerador do status da análise, no padrão do Base Service: o status
-- é uma linha, e a análise aponta para ela.
CREATE TABLE analysis_status(
    id                              SERIAL PRIMARY KEY,
    enumerator                      VARCHAR(50) NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO analysis_status (enumerator) VALUES
('approved'),
('two_factor_required'),
('rejected');


-- Conta de origem ou de destino. Nasce do próprio Pix: não existe
-- cadastro de conta (fora do escopo).
--
-- A origem chega sem ISPB (o contrato não informa), por isso `ispb` é
-- nulo nela. O NULLS NOT DISTINCT faz duas origens com a mesma agência
-- e conta serem a MESMA linha — sem ele, o NULL nunca colide e cada Pix
-- criaria uma conta nova.
CREATE TABLE account(
    id                              SERIAL PRIMARY KEY,
    ispb                            CHAR(8),
    branch                          VARCHAR(10) NOT NULL,
    account_number                  VARCHAR(20) NOT NULL,
    opening_date                    TIMESTAMPTZ NOT NULL,
    owner_document_number           VARCHAR(14) NOT NULL,
    owner_type                      CHAR(2) NOT NULL CHECK (owner_type IN ('PF', 'PJ')),
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE NULLS NOT DISTINCT (ispb, branch, account_number)
);


-- Aparelho visto pelo motor, pelo `device_id` que o app manda.
CREATE TABLE device(
    id                              SERIAL PRIMARY KEY,
    device_id                       VARCHAR(128) NOT NULL,
    first_seen_at                   TIMESTAMPTZ NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(device_id)
);


-- Política versionada: os parâmetros de cada sinal moram aqui, e não em
-- constante no código. Uma única versão ativa, garantida pelo índice
-- único parcial logo abaixo.
CREATE TABLE policy_version(
    id                              SERIAL PRIMARY KEY,
    version                         VARCHAR(20) NOT NULL,
    ml_mode                         VARCHAR(10) NOT NULL CHECK (ml_mode IN ('shadow', 'active')),
    is_active                       BOOLEAN NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(version)
);

CREATE UNIQUE INDEX policy_version_single_active ON policy_version (is_active) WHERE is_active;

CREATE TABLE rule_parameter(
    id                              SERIAL PRIMARY KEY,
    policy_version_id               INTEGER NOT NULL REFERENCES policy_version(id),
    signal_code                     VARCHAR(60) NOT NULL,
    enabled                         BOOLEAN NOT NULL,
    parameters                      JSONB NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(policy_version_id, signal_code)
);


-- Marcações que simulam o DICT e a Res. BCB 587/2026. Carregada por seed:
-- não existe endpoint para marcar (fora do escopo).
--   origin = 'own'          → marcação feita por nós (rejeição obrigatória)
--   origin = 'third_party'  → marcação de outro PSP, vista no DICT
CREATE TABLE fraud_marker(
    id                              SERIAL PRIMARY KEY,
    document_number                 VARCHAR(14) NOT NULL,
    marker_type                     VARCHAR(30) NOT NULL CHECK (
                                        marker_type IN ('mule_account', 'scammer_account', 'application_fraud', 'other_fraud')
                                    ),
    origin                          VARCHAR(20) NOT NULL CHECK (origin IN ('own', 'third_party')),
    marked_at                       TIMESTAMPTZ NOT NULL,
    valid_until                     TIMESTAMPTZ NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW())
);

CREATE INDEX fraud_marker_document ON fraud_marker (document_number);


-- O Pix como chegou. O payload bruto fica guardado inteiro; os campos
-- que as regras consultam viram colunas (com índice), e os documentos de
-- pagador e recebedor são copiados da conta para a consulta em janela
-- não precisar de JOIN.
CREATE TABLE pix_transaction(
    id                              SERIAL PRIMARY KEY,
    external_id                     VARCHAR(64) NOT NULL,
    payload_hash                    CHAR(64) NOT NULL,
    amount                          BIGINT NOT NULL CHECK (amount > 0),
    transaction_date                TIMESTAMPTZ NOT NULL,
    source_account_id               INTEGER NOT NULL REFERENCES account(id),
    destination_account_id          INTEGER NOT NULL REFERENCES account(id),
    device_id                       INTEGER NOT NULL REFERENCES device(id),
    payer_document_number           VARCHAR(14) NOT NULL,
    payee_document_number           VARCHAR(14) NOT NULL,
    channel                         VARCHAR(30) NOT NULL,
    ip                              VARCHAR(45) NOT NULL,
    latitude                        NUMERIC(9, 6),
    longitude                       NUMERIC(9, 6),
    raw_payload                     JSONB NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(external_id),
    CHECK ((latitude IS NULL) = (longitude IS NULL))
);

-- Cada regra de janela é uma consulta sobre um destes índices.
CREATE INDEX pix_transaction_payer_date ON pix_transaction (payer_document_number, transaction_date);
CREATE INDEX pix_transaction_payee_date ON pix_transaction (payee_document_number, transaction_date);
CREATE INDEX pix_transaction_device_date ON pix_transaction (device_id, transaction_date);
CREATE INDEX pix_transaction_source_date ON pix_transaction (source_account_id, transaction_date);
CREATE INDEX pix_transaction_destination_date ON pix_transaction (destination_account_id, transaction_date);


-- A decisão. O que foi decidido (placares, motivo e método do 2FA,
-- features) nasce aqui e nunca muda. O status muda UMA única vez, pelo
-- retorno do 2FA (`PATCH /pix/transaction/{id}`): `two_factor_required`
-- vira `approved` ou `rejected`. Cada status, inclusive o primeiro, é uma
-- linha em `analysis_status_event`, e é lá que o status inicial continua
-- gravado depois da troca.
CREATE TABLE analysis(
    id                              SERIAL PRIMARY KEY,
    analysis_key                    CHAR(36) NOT NULL,
    pix_transaction_id              INTEGER NOT NULL REFERENCES pix_transaction(id),
    status_id                       INTEGER NOT NULL REFERENCES analysis_status(id),
    policy_version_id               INTEGER NOT NULL REFERENCES policy_version(id),
    typology                        VARCHAR(30),
    recommended_action              VARCHAR(20) NOT NULL CHECK (
                                        recommended_action IN ('none', 'warn', 'step_up', 'block')
                                    ),
    -- Só no two_factor_required: POR QUE o 2FA, COMO, e se a tela mostra
    -- aviso de golpe. Fora dele, os dois primeiros ficam nulos e o aviso falso.
    step_up_reason                  VARCHAR(20) CHECK (
                                        step_up_reason IN (
                                            'account_takeover', 'possible_scam', 'limit', 'device_registration'
                                        )
                                    ),
    step_up_method                  VARCHAR(30) CHECK (
                                        step_up_method IN ('face_liveness', 'in_app_confirmation')
                                    ),
    scam_warning                    BOOLEAN NOT NULL,
    score_ato                       INTEGER NOT NULL,
    score_app                       INTEGER NOT NULL,
    score_mule                      INTEGER NOT NULL,
    path                            VARCHAR(10) NOT NULL CHECK (path IN ('fast', 'deep')),
    -- Se o aparelho era confiável NO MOMENTO deste Pix. Fica gravado porque
    -- a confiança muda com o tempo, e o teto diário de R$ 1.000 soma os Pix
    -- que saíram de aparelho não confiável — no momento em que saíram.
    device_trusted                  BOOLEAN NOT NULL,
    layers                          SMALLINT[] NOT NULL,
    features                        JSONB NOT NULL,
    -- Quanto o motor levou para decidir, em milissegundos: da chegada do
    -- Pix ao controller até a decisão pronta (inclui a espera na trava).
    latency_ms                      INTEGER NOT NULL CHECK (latency_ms >= 0),
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(analysis_key),
    UNIQUE(pix_transaction_id)
);

-- Uma linha por sinal avaliado — inclusive os que passaram, os que não
-- tinham dado (not_evaluated) e os que não precisaram rodar (not_needed).
CREATE TABLE analysis_rule_result(
    id                              SERIAL PRIMARY KEY,
    analysis_id                     INTEGER NOT NULL REFERENCES analysis(id),
    rule_code                       VARCHAR(40) NOT NULL,
    signal_code                     VARCHAR(60) NOT NULL,
    layer                           SMALLINT NOT NULL CHECK (layer IN (0, 1, 2)),
    outcome                         VARCHAR(20) NOT NULL CHECK (
                                        outcome IN ('pass', 'warn', 'two_factor', 'reject', 'not_evaluated', 'not_needed')
                                    ),
    typology                        VARCHAR(10) CHECK (typology IN ('ato', 'app', 'mule')),
    points                          INTEGER NOT NULL,
    observed                        JSONB NOT NULL,
    threshold                       JSONB NOT NULL,
    message                         TEXT NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW())
);

CREATE INDEX analysis_rule_result_analysis ON analysis_rule_result (analysis_id);

-- Trilha de status da análise, no padrão do `sample_entity_status_event`
-- do Base Service. Toda análise grava um evento ao nascer (`from_status_id`
-- nulo → status decidido, na data do Pix) e, se houver retorno do 2FA, um
-- segundo (`two_factor_required` → `approved` ou `rejected`, na data em que
-- o 2FA terminou). Só se acrescenta: nenhum evento é alterado ou apagado.
-- Se a cadeia de hashes da Fase 3 entrar, ela cobre a análise original, e
-- os eventos ficam fora dela, só acrescentados.
--
-- O índice único é a regra "um nascimento e no máximo uma troca" escrita
-- no banco: um segundo retorno do 2FA para a mesma análise não grava.
CREATE TABLE analysis_status_event(
    id                              SERIAL PRIMARY KEY,
    analysis_id                     INTEGER NOT NULL REFERENCES analysis(id),
    from_status_id                  INTEGER REFERENCES analysis_status(id),
    to_status_id                    INTEGER NOT NULL REFERENCES analysis_status(id),
    event_datetime                  TIMESTAMPTZ NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW())
);

CREATE UNIQUE INDEX analysis_status_event_single_change
    ON analysis_status_event (analysis_id, (from_status_id IS NULL));


-- ─────────────────────────────────────────────────────────────────
-- Tabelas agregadas do caminho rápido. Atualizadas no MESMO commit de
-- cada Pix: o motor grava um pouco mais em cada Pix e lê muito menos,
-- em vez de recalcular 90 dias de histórico a cada requisição.
-- ─────────────────────────────────────────────────────────────────

-- Perfil do pagador, só com Pix APROVADOS: tentativa recusada não
-- "educa" a linha de base. `recent_approved` guarda os últimos 50 Pix
-- aprovados como [{"amount": 15000, "at": "2026-10-01T14:00:00+00:00"}];
-- a janela de 90 dias é aplicada na leitura, com a data do Pix avaliado.
CREATE TABLE payer_profile(
    id                              SERIAL PRIMARY KEY,
    payer_document_number           VARCHAR(14) NOT NULL,
    recent_approved                 JSONB NOT NULL,
    approved_count                  INTEGER NOT NULL,
    max_night_approved_amount       BIGINT NOT NULL,
    -- Os locais dos últimos 20 Pix aprovados com geolocalização, como
    -- [{"latitude": -23.56, "longitude": -46.65, "at": "..."}]: a zona
    -- habitual do QUEM_OPERA.fora_da_zona.
    recent_locations                JSONB NOT NULL,
    last_latitude                   NUMERIC(9, 6),
    last_longitude                  NUMERIC(9, 6),
    last_geolocation_at             TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(payer_document_number)
);

-- Par pagador → conta recebedora: "esse destino já foi pago antes?"
CREATE TABLE payer_payee_pair(
    id                              SERIAL PRIMARY KEY,
    payer_document_number           VARCHAR(14) NOT NULL,
    destination_account_id          INTEGER NOT NULL REFERENCES account(id),
    first_seen_at                   TIMESTAMPTZ NOT NULL,
    last_seen_at                    TIMESTAMPTZ NOT NULL,
    approved_count                  INTEGER NOT NULL,
    approved_amount                 BIGINT NOT NULL,
    -- Para o destino ser "recorrente" não basta um Pix aprovado: são
    -- precisos Pix aprovados em DIAS diferentes (`approved_days`, com o
    -- dia do último em `last_approved_day`, dia de Brasília) e o valor
    -- atual não pode passar de uma fração acima do maior já pago a ele
    -- (`max_approved_amount`). Sem isso, o falso investimento (R$ 500,
    -- 1.000, 3.000, 8.000 ao mesmo destino) vira "a conta do mês" no 1º Pix.
    approved_days                   INTEGER NOT NULL,
    last_approved_day               DATE,
    max_approved_amount             BIGINT NOT NULL,
    -- Quantas vezes o pagador confirmou um Pix para este destino depois de
    -- um 2FA com aviso de golpe. Esses Pix entram no perfil, mas não em
    -- `approved_count`: a vítima que confirma o golpe costuma pagar o mesmo
    -- golpista de novo, e o destino não pode virar "recorrente" por isso.
    scam_step_up_count              INTEGER NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(payer_document_number, destination_account_id)
);

-- Aparelho × documento: "este aparelho é confiável para esta pessoa?"
--
-- Confiável = pelo menos 2 Pix aprovados deste pagador, o primeiro há pelo
-- menos 24 h (parâmetros em LIMITE.aparelho_nao_cadastrado), OU biometria
-- facial aprovada no retorno do 2FA (`face_liveness_passed_at`). Um Pix de
-- R$ 10 aprovado não basta: senão, o ladrão "aquece" o aparelho com um Pix
-- pequeno e o seguinte, grande, sai sem 2FA.
--
-- Biometria REPROVADA num 2FA por suspeita de invasão (`step_up_failed_at`)
-- bloqueia a confiança por 24 h: nesse período o aparelho não é confiável, e
-- nenhum Pix aprovado conta para torná-lo confiável.
CREATE TABLE device_owner(
    id                              SERIAL PRIMARY KEY,
    device_id                       INTEGER NOT NULL REFERENCES device(id),
    document_number                 VARCHAR(14) NOT NULL,
    first_seen_at                   TIMESTAMPTZ NOT NULL,
    first_approved_at               TIMESTAMPTZ,
    approved_count                  INTEGER NOT NULL,
    face_liveness_passed_at         TIMESTAMPTZ,
    step_up_failed_at               TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(device_id, document_number)
);


-- ─────────────────────────────────────────────────────────────────
-- Seed: a política ativa e os parâmetros de cada sinal.
--
-- Valores em centavos (R$ 200 = 20000). Cada parâmetro é "norma" (com a
-- fonte) ou "estimativa" (calibrável, sem fonte que o valide para o Pix);
-- a origem de cada um está no README e em docs/pesquisa-fraude-pix.md.
--
-- Pontos e cortes dos placares (ato/app/mule) são estimativas do grupo:
-- um sinal de conta laranja forte (conta nova recebendo o primeiro
-- crédito fora do perfil, 60) chega ao corte e pede 2FA com aviso de
-- golpe; recusar exige dois sinais de laranja diferentes (conta nova 20 +
-- fan-in 40, por exemplo).
-- ─────────────────────────────────────────────────────────────────
INSERT INTO policy_version (version, ml_mode, is_active) VALUES
('2026.10.1', 'shadow', TRUE);

INSERT INTO rule_parameter (policy_version_id, signal_code, enabled, parameters)
SELECT policy_version.id, parameter.signal_code, TRUE, parameter.parameters::JSONB
FROM policy_version
CROSS JOIN (VALUES
    -- Res. BCB 587/2026 (norma): marcação própria recusa sempre. Marcação
    -- de outro PSP vale na janela de 90 dias do DICT (d90).
    ('MARCACAO.lista',
     '{"third_party_window_days": 90}'),

    -- Res. BCB 403/2024 e nota BCB 20231 (norma): R$ 200 por Pix e
    -- R$ 1.000 por dia em aparelho não cadastrado. Estimativa: o aparelho
    -- só vira confiável com 2 Pix aprovados, o primeiro há 24 h ou mais (ou
    -- com a biometria aprovada, que é o cadastro do aparelho), e a biometria
    -- reprovada bloqueia a confiança por 24 h. A norma vale para TODOS os
    -- pagadores, inclusive o que o motor nunca viu: o 1º Pix acima do limite,
    -- sem outro sinal de risco, pede o cadastro (device_registration).
    ('LIMITE.aparelho_nao_cadastrado',
     '{"max_amount_per_pix": 20000, "max_amount_per_day": 100000, "trusted_min_approved_pix": 2, "trusted_min_hours": 24, "step_up_failed_block_hours": 24}'),

    -- Res. BCB 142/2021 (norma): R$ 1.000 entre 20h e 6h, PF para PF.
    ('LIMITE.noturno',
     '{"night_start_hour": 20, "night_end_hour": 6, "max_night_amount": 100000}'),

    -- Estimativa: 5 tentativas em 10 min pedem 2FA, 10 recusam — se a
    -- janela somar R$ 1.000 ou mais. Abaixo disso é rajada de valor baixo
    -- (racha de conta), e só 10 tentativas pedem 2FA.
    ('RITMO.velocidade',
     '{"window_minutes": 10, "two_factor_count": 5, "reject_count": 10, "min_window_amount": 100000}'),

    -- Estimativa: 3 ou mais destinos NOVOS distintos em 10 min, somando R$ 2.000
    -- ou mais, pedem biometria (a mão fantasma do acesso remoto, que o
    -- sinal de velocidade só pegava a partir do 5º Pix).
    ('RITMO.destinos_novos',
     '{"window_minutes": 10, "min_count": 3, "min_amount": 200000}'),

    -- Estimativa: 3 ou mais Pix em 1 h, cada um entre 90 e 100 por cento de um
    -- limite da política (R$ 200 do aparelho não cadastrado, R$ 1.000 do
    -- noturno), pedem 2FA de limite.
    ('RITMO.fracionamento',
     '{"window_minutes": 60, "min_count": 3, "band_floor_percent": 90}'),

    -- Estimativa: acima do P95 e de 5x a mediana dos aprovados em 90 dias,
    -- com pelo menos 5 Pix; sem histórico, R$ 1.000 (entre o Pix médio
    -- entre pessoas, R$ 273, e a fraude média, R$ 1.735). Segundo degrau:
    -- 10x a mediana ou mais e acima de R$ 1.000, para destino novo e do
    -- aparelho confiável, pontua golpe no corte (60): 2FA com aviso.
    -- Destino recorrente (atenuante): 2 ou mais Pix aprovados em dias
    -- diferentes e valor atual de no máximo 150 por cento do maior já pago.
    -- Destino novo: compara com os valores que o pagador já mandou para
    -- destinos novos, a partir de 5 casos; com menos, usa o perfil geral.
    -- Recebedor PJ com conta de 365 dias ou mais: o sinal só chega à faixa
    -- de aviso (aprova com warn), nunca pede 2FA sozinho.
    ('PERFIL.valor',
     '{"window_days": 90, "min_history": 5, "percentile": 95, "median_multiplier": 5, "fallback_amount": 100000, "app_points": 40, "ato_points": 60, "high_median_multiplier": 10, "high_min_amount": 100000, "high_app_points": 60, "recurring_min_days": 2, "recurring_max_growth_percent": 150, "new_payee_min_history": 5, "company_min_account_age_days": 365}'),

    -- Estimativa: conta destino com menos de 30 dias (fator do art. 39-B da
    -- Res. BCB 147). Primeiro crédito fora do perfil pontua 60; só a
    -- idade, 20.
    ('CONTA_RECEBEDORA.conta_nova',
     '{"max_account_age_days": 30, "points": 60, "age_only_points": 20}'),

    -- Estimativa: 5 pagadores distintos em 1h para uma conta PF, somando
    -- R$ 1.000 ou mais (a rifa de 8 amigos com R$ 20 não é golpe). Para
    -- conta com menos de 30 dias, bastam 3 pagadores.
    ('CONTA_RECEBEDORA.fan_in',
     '{"window_minutes": 60, "min_distinct_payers": 5, "points": 40, "min_window_amount": 100000, "new_account_max_age_days": 30, "new_account_min_distinct_payers": 3}'),

    -- Estimativa: o pagador já tomou 2FA por suspeita de golpe para esta
    -- conta nos últimos 90 dias e o valor está fora do perfil → pontua
    -- golpe no valor do corte de golpe (60): o golpe repetido do falso
    -- investimento volta a pedir confirmação com aviso. Não vale para a
    -- conta do mês: valor até 25 por cento diferente de um pagamento já
    -- confirmado a esta conta, feito há 20 dias ou mais.
    ('CONTA_RECEBEDORA.suspeita_anterior',
     '{"window_days": 90, "points": 60, "monthly_min_days": 20, "monthly_amount_tolerance_percent": 25}'),

    -- Estimativa: o pagador recebeu de terceiros nos últimos 60 min e
    -- repassa 80 por cento ou mais disso. Pontua conta laranja no corte (60):
    -- sozinho pede 2FA com aviso de golpe; com outro sinal de laranja,
    -- recusa pela regra dos dois sinais.
    ('RASTRO.repasse_rapido',
     '{"window_minutes": 60, "min_forward_share_percent": 80, "points": 60}'),

    -- Estimativa: 3 ou mais CPFs pagadores no mesmo aparelho em 30 dias é
    -- a fazenda de contas. Pontua conta laranja no corte (60): sozinho
    -- pede 2FA; com outro sinal de laranja, recusa.
    ('QUEM_OPERA.aparelho_compartilhado',
     '{"window_days": 30, "min_distinct_payers": 3, "points": 60}'),

    -- Estimativa: mais de 900 km/h desde o último Pix aprovado com
    -- geolocalização (acima de um avião comercial), ignorando menos de
    -- 5 km (imprecisão do GPS). Pontua invasão no corte (60): biometria.
    ('QUEM_OPERA.viagem_impossivel',
     '{"max_speed_kmh": 900, "min_distance_km": 5, "points": 60}'),

    -- IN BCB 669 (norma): a instituição pode adotar limite menor quando a
    -- geolocalização está desligada. O valor de R$ 500 é estimativa.
    ('LIMITE.sem_geolocalizacao',
     '{"max_amount_without_geolocation": 50000}'),

    -- Estimativa: canal que o pagador nunca usou num Pix aprovado, acima
    -- do limite de partida do PERFIL.valor (R$ 1.000), pontua invasão
    -- abaixo do corte (30): reforça outro sinal, não decide sozinho.
    ('QUEM_OPERA.canal_incomum',
     '{"points": 30}'),

    -- Estimativa: 3 ou mais CPFs pagadores no mesmo IP em 1 h, SÓ com
    -- aparelho não confiável (CGNAT põe muita gente no mesmo IP). Pontua
    -- invasão abaixo do corte (20): nunca decide sozinho.
    ('QUEM_OPERA.ip_compartilhado',
     '{"window_minutes": 60, "min_distinct_payers": 3, "points": 20}'),

    -- Estimativa: conta pagadora com menos de 30 dias mandando acima do
    -- limite de partida (R$ 1.000) para destino novo. Pontua conta laranja
    -- abaixo do corte (30): reforça outro sinal de laranja.
    ('RASTRO.conta_pagadora_recente',
     '{"max_account_age_days": 30, "points": 30}'),

    -- Estimativa: destino que reaparece depois de 60 dias sem movimento na
    -- nossa base (o motor não vê outros bancos). Pontua conta laranja
    -- abaixo do corte (30): reforça outro sinal de laranja.
    ('CONTA_RECEBEDORA.dormente',
     '{"min_days_without_movement": 60, "points": 30}'),

    -- Estimativa: nas últimas 24 h, o recebedor (PF) recebeu de documento
    -- com marcação vigente. A 1 salto recusa (evidência dura); a 2 saltos
    -- pontua conta laranja abaixo do corte (30). Consulta recursiva
    -- limitada a 2 saltos.
    ('RASTRO.proximidade_marcada',
     '{"window_hours": 24, "reject_hops": 1, "max_hops": 2, "points": 30}'),

    -- Estimativa: o mesmo CPF recebedor com contas abertas há menos de 30
    -- dias em 2 ou mais ISPBs. Pontua conta laranja abaixo do corte (30).
    ('CONTA_RECEBEDORA.varias_instituicoes',
     '{"max_account_age_days": 30, "min_institutions": 2, "points": 30}'),

    -- Estimativa (inspiração no Modo Rua do Nubank): Pix a mais de 50 km
    -- de todos os locais dos últimos 20 Pix aprovados, acima de R$ 500,
    -- pede biometria. Exige pelo menos 5 locais conhecidos.
    ('QUEM_OPERA.fora_da_zona',
     '{"radius_km": 50, "min_amount": 50000, "min_known_locations": 5}'),

    -- Estimativa: corte no p99 do escore dos Pix legítimos do treino
    -- (scripts/ml/train.py, semente 1). No modo ativo, acima do corte
    -- pontua invasão, crescendo até 60 em +0,04 de escore: sozinho chega a
    -- 2FA (biometria) e nunca recusa. No modo sombra (o padrão da política)
    -- o escore só vai para o metadata.
    ('ANOMALIA.ml',
     '{"score_threshold": 0.61, "score_span": 0.04, "max_points": 60}'),

    -- Estimativa: primeiro Pix (nenhum aprovado sem aviso de golpe) de
    -- R$ 1.000 ou mais para PF com conta de menos de 30 dias — o falso
    -- parente. Pontua golpe no corte (60): 2FA com aviso; nunca recusa.
    ('CONTA_RECEBEDORA.primeiro_pix_alto',
     '{"max_account_age_days": 30, "min_amount": 100000, "points": 60}'),

    -- Estimativa: 2 ou mais Pix aprovados (inclusive sob aviso de golpe)
    -- para o mesmo destino em 7 dias, estritamente crescentes, e o atual
    -- pelo menos 3x o primeiro — o falso investimento. A partir de R$ 300
    -- pontua golpe no corte (60, 2FA com aviso); abaixo, 40 (aviso). PJ
    -- com conta de 1 ano ou mais fica de fora (corretora de verdade).
    ('PERFIL.escalada',
     '{"window_days": 7, "min_previous_pix": 2, "min_multiple_of_first": 3, "high_min_amount": 30000, "high_points": 60, "points": 40, "company_min_account_age_days": 365}'),

    -- Res. BCB 142 (norma: R$ 1.000 à noite, PF→PF; aumento só 24 h depois
    -- do pedido) aplicada sem exceção quando o Pix é para destino novo e a
    -- mais de 5 km (estimativa) de todos os locais habituais: recusa. É o
    -- contexto de coação, em que a vítima passa no próprio 2FA.
    ('LIMITE.noturno_fora_de_casa',
     '{"min_distance_km": 5}'),

    -- Estimativa: cortes dos placares e tempo limite da camada 2. Recusar
    -- por conta laranja exige o placar no corte E 2 sinais de laranja
    -- diferentes: um sinal sozinho não é "risco claro". Todo 2FA vira
    -- biometria (e não confirmação no app) quando o aparelho não é confiável,
    -- houve biometria reprovada em 24 h ou o Pix está a mais de 5 km de todos
    -- os últimos locais aprovados (inspiração: Modo Rua do Nubank).
    ('DECISAO.placares',
     '{"ato_cut": 60, "app_cut": 60, "mule_cut": 60, "app_warn_cut": 30, "mule_min_distinct_signals": 2, "deep_layer_timeout_ms": 300, "street_mode_km": 5, "habitual_location_min_hours": 24}')
) AS parameter(signal_code, parameters)
WHERE policy_version.version = '2026.10.1';


-- ─────────────────────────────────────────────────────────────────
-- Seed: marcações de fraude de demonstração, simulando o DICT.
--
-- Os documentos são fictícios (dígitos verificadores válidos) e servem
-- à demonstração e aos testes. Os testes NÃO escrevem no banco: o
-- cenário de marcação nasce aqui.
-- ─────────────────────────────────────────────────────────────────
INSERT INTO fraud_marker (document_number, marker_type, origin, marked_at, valid_until) VALUES
-- marcação própria vigente → recusa
('11144477735', 'mule_account', 'own', '2026-09-01T10:00:00-03:00', '2031-09-01T10:00:00-03:00'),
-- marcação de outro PSP há menos de 90 dias → recusa
('22255588846', 'scammer_account', 'third_party', '2026-09-20T10:00:00-03:00', '2031-09-20T10:00:00-03:00'),
-- marcação de outro PSP há mais de 90 dias → fora da janela do DICT
('33366699957', 'mule_account', 'third_party', '2025-01-10T10:00:00-03:00', '2030-01-10T10:00:00-03:00'),
-- marcação própria vencida → não vale mais
('44477700083', 'mule_account', 'own', '2021-01-01T10:00:00-03:00', '2026-01-01T10:00:00-03:00');
