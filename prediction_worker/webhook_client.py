from __future__ import annotations

import json
import os
from typing import Any

import httpx

from prediction_worker.webhook_signing import webhook_auth_headers


class BackendWebhookClient:
    def __init__(
        self,
        base_url: str | None = None,
        secret: str | None = None,
        timeout_sec: float | None = None,
    ):
        self.base_url = (base_url or os.getenv("BACKEND_API_BASE_URL", "http://host.docker.internal:8000")).rstrip("/")
        self.secret = (secret or os.getenv("TELEMETRY_WEBHOOK_SECRET") or "").strip()
        self.timeout_sec = float(timeout_sec or os.getenv("BACKEND_HTTP_TIMEOUT_SEC", "30"))

    def post_prediction_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.secret:
            raise RuntimeError("TELEMETRY_WEBHOOK_SECRET nao configurado")
        url = f"{self.base_url}/api/v1/internal/webhooks/telemetry-prediction-result"
        raw = json.dumps(payload, default=str).encode("utf-8")
        headers = webhook_auth_headers(self.secret, raw)
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(url, content=raw, headers=headers)
            response.raise_for_status()
            return response.json()
