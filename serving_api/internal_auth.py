from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional


def verify_internal_token(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    expected = (os.getenv("PIPELINE_INTERNAL_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PIPELINE_INTERNAL_TOKEN nao configurado",
        )
    provided = (x_internal_token or "").encode("utf-8")
    target = expected.encode("utf-8")
    if len(provided) != len(target) or not hmac.compare_digest(provided, target):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token interno invalido")


class TelemetryActivationRequest(BaseModel):
    tipo: str = Field(..., min_length=1, max_length=100)
    modelo: Optional[str] = Field(None, max_length=100)
    fabricante: Optional[str] = Field(None, max_length=100)
    hospital_id: Optional[int] = None
    telemetry_enabled: bool = True


class TelemetryActivationResponse(BaseModel):
    numero_serie: str
    tipo: str
    tipo_slug: str
    equipamento_id: int
    telemetry_enabled: bool
