"""API externa mock: token + datasets no formato do import do backend."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from external_data_api import auth
from external_data_api.data_store import PARTS, load_dataset

app = FastAPI(title="External Data API", version="1.0.0")


class TokenRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
    api_secret: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/token", response_model=TokenResponse)
def create_token(body: TokenRequest) -> Dict[str, Any]:
    return auth.issue_token(body.api_key, body.api_secret)


@app.get("/v1/datasets/{part}")
def get_dataset(
    part: str,
    _claims: Dict[str, Any] = Depends(auth.require_bearer),
) -> Dict[str, Any]:
    if part not in PARTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset desconhecido: {part}. Válidos: {', '.join(PARTS)}",
        )
    try:
        items = load_dataset(part)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"part": part, "items": items}
