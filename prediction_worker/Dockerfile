FROM python:3.11-slim

WORKDIR /app

COPY prediction_worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY data_pipeline ./data_pipeline
COPY monitoring_service ./monitoring_service
COPY prediction_worker ./prediction_worker
COPY models ./models

ENV PYTHONPATH=/app
ENV MODELS_DIR=/app/models

CMD ["python", "-m", "prediction_worker"]
