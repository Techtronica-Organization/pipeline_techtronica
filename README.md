# Pipeline de Telemetria Hospitalar

Simula/ingere telemetria de equipamentos, materializa no serving DB (PostgreSQL), roda **modelos de regressão/classificação** (`.pkl`) e notifica o **techtronica_web_backend** quando detecta falha.

## Propósito

| Componente | Função |
|------------|--------|
| `monitoring_service` | Simulador + Kafka + orquestração Docker |
| `data_pipeline` | Bronze → Silver → Gold / serving |
| `serving_api` (:8100) | API interna (ativar telemetria por `numero_serie`) |
| `prediction_worker` | Lê telemetria `PENDING`, prediz, chama webhook do backend |
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
| Ativar telemetria | `PUT /internal/v1/equipments/{numero_serie}/telemetry` (token interno) |
| MinIO console | http://localhost:9001 (`admin` / `strongpassword123`) |
| PostgreSQL serving | `localhost:5432` (`postgres` / `strongpassword123` / `serving_db`) |
| Kafka | `localhost:29092` |

### Variáveis (ver `.env.example`)

Arquivo: [`monitoring_service/.env.example`](monitoring_service/.env.example).

Principais:

- `PIPELINE_INTERNAL_TOKEN` — auth da serving API (igual ao backend)
- `TELEMETRY_WEBHOOK_SECRET` — webhook para o backend (igual ao backend)
- `BACKEND_API_BASE_URL` — onde o prediction_worker posta o resultado
- `SIMULATION_INTERVAL_SEC` / `NUM_HOSPITALS` — ritmo e escala do simulador (também no `docker-compose.yml`)

### Simulação

No `docker-compose.yml` (serviço de monitoramento):

- `SIMULATION_INTERVAL_SEC=3600` → tempo real; `5` → acelerado para teste
- `NUM_HOSPITALS=10` → hospitais 1..N

## Modelos

Artefatos em `pipeline_techtronica/models/` (ex.: `best_model_tc.pkl`). O worker escolhe pelo tipo do equipamento.

## Branch de trabalho

Integração regressão + webhook: `feature/main/regression-models-integration`.

## Testes rápidos

```bash
# na raiz do pipeline (com deps do worker)
# pytest prediction_worker/tests
```

Health serving (com stack no ar):

```bash
curl http://localhost:8100/api/v1/health
```
