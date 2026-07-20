FROM python:3.11-slim

WORKDIR /app

COPY serving_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY data_pipeline ./data_pipeline
COPY monitoring_service ./monitoring_service
COPY serving_api ./serving_api

ENV PYTHONPATH=/app
ENV SIMULATION_DB_PATH=/app/monitoring_service/persistence/simulation.db

EXPOSE 8000

CMD ["uvicorn", "serving_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
