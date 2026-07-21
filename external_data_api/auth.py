"""Emissão e validação de Bearer JWT para a API externa."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

TOKEN_EXPIRES_SECONDS = int(os.getenv("EXTERNAL_JWT_EXPIRES_SEC", "3600"))
_bearer = HTTPBearer(auto_error=False)


def _api_key() -> str:
    return (os.getenv("EXTERNAL_API_KEY") or "").strip()


def _api_secret() -> str:
    return (os.getenv("EXTERNAL_API_SECRET") or "").strip()


def _jwt_secret() -> str:
    secret = (os.getenv("EXTERNAL_JWT_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("EXTERNAL_JWT_SECRET não configurado")
    return secret


def credentials_configured() -> bool:
    return bool(_api_key() and _api_secret() and (os.getenv("EXTERNAL_JWT_SECRET") or "").strip())


def issue_token(api_key: str, api_secret: str) -> Dict[str, Any]:
    if not credentials_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Credenciais da API externa não configuradas",
        )
    if api_key != _api_key() or api_secret != _api_secret():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api_key ou api_secret inválidos",
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "external_client",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=TOKEN_EXPIRES_SECONDS)).timestamp()),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm="HS256")
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_EXPIRES_SECONDS,
    }


def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_bearer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token obrigatório",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(credentials.credentials)
