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


-- A decisão. Nasce final e nunca muda (append-only): o contrato não tem
-- retorno do 2FA, então não há troca de status para registrar.
CREATE TABLE analysis(
    id                              SERIAL PRIMARY KEY,
    analysis_key                    CHAR(36) NOT NULL,
    pix_transaction_id              INTEGER NOT NULL REFERENCES pix_transaction(id),
    status_id                       INTEGER NOT NULL REFERENCES analysis_status(id),
    policy_version_id               INTEGER NOT NULL REFERENCES policy_version(id),
    typology                        VARCHAR(30),
    recommended_action              VARCHAR(20) NOT NULL CHECK (
                                        recommended_action IN ('none', 'warn', 'step_up', 'hold_timer', 'block')
                                    ),
    score_ato                       INTEGER NOT NULL,
    score_app                       INTEGER NOT NULL,
    score_mule                      INTEGER NOT NULL,
    path                            VARCHAR(10) NOT NULL CHECK (path IN ('fast', 'deep')),
    layers                          SMALLINT[] NOT NULL,
    features                        JSONB NOT NULL,
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
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(payer_document_number, destination_account_id)
);

-- Aparelho × documento: "este aparelho já fez Pix aprovado para esta pessoa?"
CREATE TABLE device_owner(
    id                              SERIAL PRIMARY KEY,
    device_id                       INTEGER NOT NULL REFERENCES device(id),
    document_number                 VARCHAR(14) NOT NULL,
    first_seen_at                   TIMESTAMPTZ NOT NULL,
    first_approved_at               TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(device_id, document_number)
);


-- ─────────────────────────────────────────────────────────────────
-- Seed: a política ativa.
-- ─────────────────────────────────────────────────────────────────
INSERT INTO policy_version (version, ml_mode, is_active) VALUES
('2026.10.1', 'shadow', TRUE);
