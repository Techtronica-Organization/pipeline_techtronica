# Pipeline de Telemetria Hospitalar

Simula/ingere telemetria de equipamentos, materializa no serving DB (PostgreSQL), roda **modelos de regressão/classificação** (`.pkl`) e notifica o **techtronica_web_backend** quando detecta falha.

## Propósito

| Componente | Função |
|------------|--------|
| `monitoring_service` | Simulador + Kafka + orquestração Docker |
| `data_pipeline` | Bronze → Silver → Gold / serving |
| `serving_api` (:8100) | API interna (ativar telemetria por `numero_serie`) |
| `prediction_worker` | Lê telemetria `PENDING`, prediz, chama webhook do backend |
| `external_data_api` (:8200) | Mock de API externa (token + datasets CSV) para sync do backend |
| `models/` | Artefatos `.pkl` por tipo de equipamento |

## Integração com o backend

```
Backend  PUT/POST ativar telemetria
   │     (PIPELINE_API_BASE_URL + PIPELINE_INTERNAL_TOKEN)
   ▼
serving_api :8100  →  marca equipamento / libera ingestão
   │
   ▼
telemetria → silver (PENDING)
   │
   ▼
prediction_worker
   │  se failure_detected
   ▼
POST {BACKEND}/api/v1/internal/webhooks/telemetry-prediction-result
   headers: X-Webhook-Secret = TELEMETRY_WEBHOOK_SECRET
   │
   ▼
Backend cria Falha + Chamado e pode enfileirar recomendação MLOps
```

**Chaves que devem bater com o backend:**

| Pipeline | Backend |
|----------|---------|
| `TELEMETRY_WEBHOOK_SECRET` | `TELEMETRY_WEBHOOK_SECRET` |
| `PIPELINE_INTERNAL_TOKEN` | `PIPELINE_INTERNAL_TOKEN` |
| `BACKEND_API_BASE_URL` | URL da API (ex. `http://host.docker.internal:8000`) |

## Como rodar

Pré-requisito: Docker Desktop. Backend Techtrônica preferencialmente no ar em `:8000`.

```bash
cd monitoring_service
cp .env.example .env   # ajuste secrets se necessário
docker compose up -d --build
```

(Use `docker compose` v2; `docker-compose` legado também funciona.)

### Portas

| Serviço | URL / porta |
|---------|-------------|
| Serving API | http://localhost:8100 — docs `/docs` |
| External Data API (mock integração) | http://localhost:8200 — `GET /health` |
| Ativar telemetria | `PUT /internal/v1/equipments/{numero_serie}/telemetry` (token interno) |
| MinIO console | http://localhost:9001 (`admin` / `strongpassword123`) |
| PostgreSQL serving | `localhost:5432` (`postgres` / `strongpassword123` / `serving_db`) |
| Kafka | `localhost:29092` |

### API externa mock (`external_data_api`)

Usada pelo backend em `POST /api/v1/integrations/.../sync` (não misturar com `PIPELINE_INTERNAL_TOKEN` da serving).

| Método | Path | Auth | Resposta |
|--------|------|------|----------|
| `POST` | `/auth/token` | body `{api_key, api_secret}` | `{access_token, token_type, expires_in}` |
| `GET` | `/v1/datasets/{part}` | Bearer | `{part, items:[...]}` |
| `GET` | `/health` | livre | `{status:"ok"}` |

Parts: `hospitais`, `tecnicos`, `equipamentos`, `falhas`, `chamados`, `acoes`  
(dados de `csv_export/`; `manutencao.csv` → part `acoes`).

Env (`.env.example`): `EXTERNAL_DATA_API_PORT=8200`, `EXTERNAL_API_KEY`, `EXTERNAL_API_SECRET`, `EXTERNAL_JWT_SECRET`.

Testes:

```bash
# na raiz do repo pipeline
PYTHONPATH=. python -m unittest external_data_api.test_external_data_api
```

### Variáveis (ver `.env.example`)

Arquivo: [`monitoring_service/.env.example`](monitoring_service/.env.example).

Principais:

- `PIPELINE_INTERNAL_TOKEN` — auth da serving API (igual ao backend)
- `TELEMETRY_WEBHOOK_SECRET` — webhook para o backend (igual ao backend)
- `BACKEND_API_BASE_URL` — onde o prediction_worker posta o resultado
- `SIMULATION_INTERVAL_SEC` / `NUM_HOSPITALS` — ritmo e escala do simulador (também no `docker-compose.yml`)
- `EXTERNAL_API_KEY` / `EXTERNAL_API_SECRET` / `EXTERNAL_JWT_SECRET` — mock de integração (:8200)

### Simulação

No `docker-compose.yml` (serviço de monitoramento):

- `SIMULATION_INTERVAL_SEC=60` (default compose/config) → demo; `5` → teste rápido; `3600` → tempo real
- `NUM_HOSPITALS` — hospitais 1..N

## Modelos

Artefatos em `pipeline_techtronica/models/` (ex.: `best_model_tc.pkl`). O worker escolhe pelo tipo do equipamento.

## Branch de trabalho

Integração regressão + webhook: `feature/main/regression-models-integration`.

## Produção (`PIPELINE_ENV=prod`)

No `.env` do `monitoring_service`:

```env
PIPELINE_ENV=prod
POSTGRES_PASSWORD=<forte>
MINIO_ROOT_PASSWORD=<forte>
PIPELINE_INTERNAL_TOKEN=<forte, igual ao backend>
TELEMETRY_WEBHOOK_SECRET=<forte, igual ao backend>
BACKEND_API_BASE_URL=https://api.seudominio.com
```

Boot da serving API e do prediction_worker **falha** se secrets forem fracos.

- Rotas `/api/v1/*` (exceto `/health`) exigem header `X-Internal-Token`
- Webhook ao backend envia **HMAC** (`X-Webhook-Timestamp` + `X-Webhook-Signature`) + secret legado
- No backend: `WEBHOOK_REQUIRE_SIGNATURE=1`, `WEBHOOK_ALLOW_LEGACY_SECRET=0`, secrets alinhados

## Testes

```bash
# na raiz do pipeline
pip install pytest
pytest prediction_worker/tests -q

# scripts offline (não precisam da stack completa)
python monitoring_service/test_simulation.py
python data_pipeline/test_pipeline.py
```

Health da serving API (stack no ar):

```bash
curl http://localhost:8100/api/v1/health
```

O `prediction_worker` inclui em `details.features` o **mapa completo** de features da inferência (usado pelo backend/MLOps).
