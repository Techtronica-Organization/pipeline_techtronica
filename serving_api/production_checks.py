from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)
_WEAK = ("dev-", "troque", "change-me", "insecure", "strongpassword", "guest")


def is_prod_pipeline() -> bool:
    return (os.getenv("PIPELINE_ENV") or "").strip().lower() in ("prod", "production")


def _looks_weak(value: str) -> bool:
    v = (value or "").strip().lower()
    return not v or any(w in v for w in _WEAK) or len(v) < 16


def assert_pipeline_production_ready(*, role: str = "serving") -> None:
    """role: serving | worker | full"""
    if not is_prod_pipeline():
        return
    errors: list[str] = []
    if _looks_weak(os.getenv("PIPELINE_INTERNAL_TOKEN") or ""):
        errors.append("PIPELINE_INTERNAL_TOKEN fraco ou ausente")
    db_pass = (os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or "").strip()
    if _looks_weak(db_pass):
        errors.append("DB_PASSWORD/POSTGRES_PASSWORD fraco ou ausente")
    if role in ("worker", "full"):
        if _looks_weak(os.getenv("TELEMETRY_WEBHOOK_SECRET") or ""):
            errors.append("TELEMETRY_WEBHOOK_SECRET fraco ou ausente")
        if not (os.getenv("BACKEND_API_BASE_URL") or "").strip():
            errors.append("BACKEND_API_BASE_URL obrigatorio")
    if errors:
        raise RuntimeError("Configuracao insegura para producao: " + "; ".join(errors))
    logger.info("PIPELINE_ENV=prod checks OK (role=%s)", role)
