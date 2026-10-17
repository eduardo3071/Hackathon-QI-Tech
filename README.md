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

_A preencher na Fase 2._

## Regras

| Regra | Lógica | Parâmetros | Por quê |
|-------|--------|------------|---------|

_A preencher na Fase 2._

## Como as regras viram decisão

_A preencher na Fase 2._

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
