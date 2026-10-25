"""Signed bearer tokens for the demo login.

Context: The demo has no passwords, but identity always comes from an HMAC-signed token,
never from a field the caller can set freely. Changing the user id in a request yields
401 instead of someone else's data. | Input: user row or token string. | Output: token
or verified claims.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from knowledge_guard.config import get_settings
from knowledge_guard.errors import AuthError
from knowledge_guard.models import User


@dataclass(frozen=True)
class Claims:
    user_id: int
    username: str
    expires_at: int


def issue_token(user: User, now: float | None = None) -> str:
    """Create a token valid for the configured lifetime."""
    issued = int(now if now is not None else time.time())
    body = {
        "uid": user.id,
        "username": user.username,
        "exp": issued + get_settings().token_ttl_seconds,
    }
    payload = _encode(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def read_token(token: str, now: float | None = None) -> Claims:
    """Verify signature and expiry and return the claims.

    Raises:
        AuthError: If the token is malformed, forged or expired.
    """
    payload, separator, signature = token.partition(".")
    if not separator or not hmac.compare_digest(signature.encode(), _sign(payload).encode()):
        raise AuthError("Invalid token signature")
    try:
        body = json.loads(_decode(payload))
        claims = Claims(int(body["uid"]), str(body["username"]), int(body["exp"]))
    except (ValueError, KeyError, TypeError, binascii.Error) as error:
        raise AuthError("Unreadable token") from error
    if claims.expires_at < (now if now is not None else time.time()):
        raise AuthError("Token expired")
    return claims


def _sign(payload: str) -> str:
    secret = get_settings().token_secret.get_secret_value().encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
