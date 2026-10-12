"""JSON over HTTPS with timeout and retries.

Context: Model and embedding providers fail transiently under load (429, 5xx, dropped
connections). Those are retried with exponential backoff; every other failure surfaces
at once as UpstreamError. | Input: URL, headers, JSON body. | Output: decoded JSON.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from knowledge_guard.errors import UpstreamError

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
BASE_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 8.0


def post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    retries: int,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """POST a JSON payload and return the JSON response.

    Raises:
        UpstreamError: On a non-retryable error or when all retries are used up.
    """
    session = client or httpx.Client()
    try:
        for attempt in range(retries + 1):
            try:
                response = session.post(url, headers=headers, json=payload, timeout=timeout)
            except httpx.TransportError as error:
                failure = f"{type(error).__name__}: {error}"
            else:
                if response.is_success:
                    body: dict[str, Any] = response.json()
                    return body
                failure = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in RETRYABLE_STATUS:
                    break
            if attempt < retries:
                delay = _backoff(attempt)
                logger.warning(
                    "%s failed (%s), retry %d in %.1fs", url, failure, attempt + 1, delay
                )
                time.sleep(delay)
    finally:
        if client is None:
            session.close()
    raise UpstreamError(f"Request to {httpx.URL(url).host} failed: {failure}")


def _backoff(attempt: int) -> float:
    return float(min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * 2**attempt))
