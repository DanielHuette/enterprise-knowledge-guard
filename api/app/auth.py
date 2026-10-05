"""Anmeldung fuer die Vorfuehrung.

Kein Passwort -- es gibt nichts zu schuetzen ausser der Vorfuehrung selbst.
Entscheidend ist etwas anderes: die Identitaet kommt aus einem signierten
Token, nicht aus einem Feld, das der Aufrufer frei setzen kann. Wer die
Nutzerkennung im Aufruf aendert, erhaelt 401 statt fremder Daten.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from .config import settings


class AuthError(Exception):
    pass


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    return hmac.new(
        settings.token_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def issue_token(user: dict) -> str:
    body = {
        "uid": user["id"],
        "username": user["username"],
        "role": user["role"],
        "exp": int(time.time()) + settings.token_ttl_seconds,
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> dict:
    try:
        payload, signature = token.split(".", 1)
    except ValueError as exc:
        raise AuthError("Token unlesbar") from exc
    if not hmac.compare_digest(signature, _sign(payload)):
        raise AuthError("Token-Signatur stimmt nicht")
    body = json.loads(_unb64(payload))
    if body.get("exp", 0) < time.time():
        raise AuthError("Token abgelaufen")
    return body
