from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel, Field


def verify_internal_token(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    expected = (os.getenv("PIPELINE_INTERNAL_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PIPELINE_INTERNAL_TOKEN nao configurado",
        )
    if not x_internal_token or x_internal_token != expected:
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
