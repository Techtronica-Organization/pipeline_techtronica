from __future__ import annotations

import hashlib
import hmac
import time


def sign_webhook_body(secret: str, body: bytes, *, timestamp: int | None = None) -> tuple[str, str]:
    ts = str(int(time.time() if timestamp is None else timestamp))
    msg = ts.encode("utf-8") + b"." + body
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return ts, sig


def webhook_auth_headers(secret: str, body: bytes, *, timestamp: int | None = None) -> dict[str, str]:
    ts, sig = sign_webhook_body(secret, body, timestamp=timestamp)
    return {
        "X-Webhook-Timestamp": ts,
        "X-Webhook-Signature": sig,
        "X-Webhook-Secret": secret,
        "Content-Type": "application/json",
    }
