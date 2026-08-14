FROM python:3.11-slim

WORKDIR /app

COPY external_data_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY external_data_api ./external_data_api

ENV PYTHONPATH=/app
ENV CSV_EXPORT_DIR=/app/csv_export

EXPOSE 8000

CMD ["uvicorn", "external_data_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
