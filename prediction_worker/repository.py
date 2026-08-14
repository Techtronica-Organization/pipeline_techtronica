from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from data_pipeline.database.models import StgSilverTelemetry

SENSOR_EXCLUDE = {
    "timestamp",
    "equipamento_id",
    "hospital_id",
    "tipo",
    "is_interpolated",
    "event_id",
    "numero_serie",
    "processing_status",
    "processing_started_at",
    "processing_finished_at",
    "next_attempt_at",
    "attempt_count",
    "last_error",
    "model_slug",
    "model_version",
    "preprocessing_version",
    "remote_falha_id",
    "remote_chamado_id",
    "lease_until",
    "worker_id",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def recover_expired_leases(session: Session, now: datetime | None = None) -> int:
    now = now or _utcnow()
    rows = (
        session.query(StgSilverTelemetry)
        .filter(
            StgSilverTelemetry.processing_status == "PROCESSING",
            or_(StgSilverTelemetry.lease_until.is_(None), StgSilverTelemetry.lease_until < now),
        )
        .all()
    )
    for row in rows:
        row.processing_status = "PENDING"
        row.next_attempt_at = now
        row.worker_id = None
        row.lease_until = None
        row.last_error = "lease expirado; reenfileirado"
    session.commit()
    return len(rows)


def claim_pending_batch(
    session: Session,
    *,
    worker_id: str,
    batch_size: int,
    lease_seconds: int,
) -> list[StgSilverTelemetry]:
    now = _utcnow()
    lease_until = now + timedelta(seconds=lease_seconds)

    if session.bind and session.bind.dialect.name == "postgresql":
        result = session.execute(
            text(
                """
                SELECT timestamp, equipamento_id
                FROM stg_silver_telemetry
                WHERE processing_status = 'PENDING'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                ORDER BY timestamp ASC
                FOR UPDATE SKIP LOCKED
                LIMIT :limit
                """
            ),
            {"now": now, "limit": batch_size},
        )
        keys = list(result.fetchall())
        if not keys:
            return []
        rows: list[StgSilverTelemetry] = []
        for ts, eq_id in keys:
            row = (
                session.query(StgSilverTelemetry)
                .filter_by(timestamp=ts, equipamento_id=eq_id)
                .one()
            )
            row.processing_status = "PROCESSING"
            row.processing_started_at = now
            row.lease_until = lease_until
            row.worker_id = worker_id
            row.attempt_count = int(row.attempt_count or 0) + 1
            rows.append(row)
        session.commit()
        return rows

    candidates = (
        session.query(StgSilverTelemetry)
        .filter(
            StgSilverTelemetry.processing_status == "PENDING",
            or_(StgSilverTelemetry.next_attempt_at.is_(None), StgSilverTelemetry.next_attempt_at <= now),
        )
        .order_by(StgSilverTelemetry.timestamp.asc())
        .limit(batch_size)
        .with_for_update()
        .all()
    )
    for row in candidates:
        row.processing_status = "PROCESSING"
        row.processing_started_at = now
        row.lease_until = lease_until
        row.worker_id = worker_id
        row.attempt_count = int(row.attempt_count or 0) + 1
    session.commit()
    return candidates


def load_history(
    session: Session,
    *,
    equipamento_id: int,
    up_to: datetime,
    hours: int = 72,
) -> list[dict[str, Any]]:
    start = up_to - timedelta(hours=hours)
    rows = (
        session.query(StgSilverTelemetry)
        .filter(
            StgSilverTelemetry.equipamento_id == equipamento_id,
            StgSilverTelemetry.timestamp >= start,
            StgSilverTelemetry.timestamp <= up_to,
        )
        .order_by(StgSilverTelemetry.timestamp.asc())
        .all()
    )
    return [row_to_dict(r) for r in rows]


def row_to_dict(row: StgSilverTelemetry) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for col in row.__table__.columns:
        data[col.name] = getattr(row, col.name)
    return data


def mark_completed(
    session: Session,
    row: StgSilverTelemetry,
    *,
    model_slug: str,
    model_version: str,
    preprocessing_version: str,
    remote_falha_id: int | None = None,
    remote_chamado_id: int | None = None,
) -> None:
    now = _utcnow()
    row.processing_status = "COMPLETED"
    row.processing_finished_at = now
    row.lease_until = None
    row.worker_id = None
    row.last_error = None
    row.model_slug = model_slug
    row.model_version = model_version
    row.preprocessing_version = preprocessing_version
    row.remote_falha_id = remote_falha_id
    row.remote_chamado_id = remote_chamado_id
    session.commit()


def mark_failed(
    session: Session,
    row: StgSilverTelemetry,
    *,
    error: str,
    retry: bool,
    backoff_seconds: int,
    max_attempts: int,
) -> None:
    now = _utcnow()
    row.last_error = error[:4000]
    row.lease_until = None
    row.worker_id = None
    attempts = int(row.attempt_count or 0)
    if retry and attempts < max_attempts:
        row.processing_status = "PENDING"
        row.next_attempt_at = now + timedelta(seconds=backoff_seconds * max(1, attempts))
    else:
        row.processing_status = "FAILED"
        row.processing_finished_at = now
    session.commit()
