from __future__ import annotations

import logging
import os
import socket
import time
import uuid

from data_pipeline.database.connection import SessionLocal, init_sql_db
from data_pipeline.production_checks import assert_pipeline_production_ready
from prediction_worker.registry import PREPROCESSING_VERSION
from prediction_worker.repository import (
    claim_pending_batch,
    load_history,
    mark_completed,
    mark_failed,
    recover_expired_leases,
    row_to_dict,
)
from prediction_worker.runner import predict_for_event
from prediction_worker.webhook_client import BackendWebhookClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("prediction_worker")


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def process_once(worker_id: str, client: BackendWebhookClient) -> int:
    batch_size = _env_int("PREDICTION_BATCH_SIZE", 20)
    lease_seconds = _env_int("PREDICTION_LEASE_SECONDS", 120)
    max_attempts = _env_int("PREDICTION_MAX_ATTEMPTS", 5)
    backoff_seconds = _env_int("PREDICTION_BACKOFF_SECONDS", 30)

    session = SessionLocal()
    processed = 0
    try:
        recover_expired_leases(session)
        rows = claim_pending_batch(
            session,
            worker_id=worker_id,
            batch_size=batch_size,
            lease_seconds=lease_seconds,
        )
        for row in rows:
            try:
                current = row_to_dict(row)
                history = load_history(session, equipamento_id=row.equipamento_id, up_to=row.timestamp)
                result = predict_for_event(tipo=row.tipo, current_row=current, history_rows=history)

                remote_falha_id = None
                remote_chamado_id = None
                if result.failure_detected:
                    payload = {
                        "event_id": row.event_id,
                        "numero_serie": row.numero_serie or f"SN-{row.equipamento_id}",
                        "model_slug": result.model_slug,
                        "model_version": result.model_version,
                        "preprocessing_version": result.preprocessing_version,
                        "failure_detected": True,
                        "probability": result.probability,
                        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                        "details": result.details,
                    }
                    remote = client.post_prediction_result(payload)
                    remote_falha_id = remote.get("falha_id")
                    remote_chamado_id = remote.get("chamado_id")

                # COMPLETED só após webhook ok (backend idempotente por event_id).
                mark_completed(
                    session,
                    row,
                    model_slug=result.model_slug,
                    model_version=result.model_version,
                    preprocessing_version=result.preprocessing_version or PREPROCESSING_VERSION,
                    remote_falha_id=remote_falha_id,
                    remote_chamado_id=remote_chamado_id,
                )

                processed += 1
            except Exception as e:
                logger.exception(
                    "Falha ao processar equipamento_id=%s timestamp=%s: %s",
                    row.equipamento_id,
                    row.timestamp,
                    e,
                )
                retryable = True
                mark_failed(
                    session,
                    row,
                    error=str(e),
                    retry=retryable,
                    backoff_seconds=backoff_seconds,
                    max_attempts=max_attempts,
                )
        return processed
    finally:
        session.close()


def main() -> None:
    worker_id = os.getenv("WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    interval = float(os.getenv("PREDICTION_POLL_INTERVAL_SEC", "10"))
    logger.info("Iniciando prediction_worker id=%s", worker_id)
    assert_pipeline_production_ready(role="worker")
    init_sql_db()
    client = BackendWebhookClient()
    process_once(worker_id, client)
    while True:
        time.sleep(interval)
        process_once(worker_id, client)


if __name__ == "__main__":
    main()
