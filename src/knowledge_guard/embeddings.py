"""Text embeddings.

Context: Two providers. `openai` calls the embeddings API; `local` is a deterministic
feature-hashing embedding that needs no key and no network, so the demo runs for anyone
immediately. Words and four-letter fragments are hashed into the same 1536 dimensions as
text-embedding-3-small, so switching to real embeddings needs no schema change.
| Input: texts. | Output: one unit vector per text, order preserved.
"""

from __future__ import annotations

import hashlib
import math
import re

from knowledge_guard.config import get_settings
from knowledge_guard.upstream import post_json

EMBEDDING_DIM = 1536
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
FRAGMENT_LENGTH = 4
FRAGMENT_WEIGHT = 0.45
SIGN_BIT = 61

WORD_PATTERN = re.compile(r"[^\W_]+")
_STOPWORD_TEXT = (
    "a an and are as at be by can do does for from has have how i in is it its me my of on "
    "or our so that the their them there this to was we were what when where which who why "
    "will with you your"
)
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts with the configured provider."""
    if not texts:
        return []
    if get_settings().resolved_embedding_provider() == "openai":
        return _openai_embed(texts)
    return [hash_embed(text) for text in texts]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def hash_embed(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic unit vector from hashed word and fragment features."""
    vector = [0.0] * dim
    for feature, weight in _features(text).items():
        raw = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
        sign = 1.0 if (raw >> SIGN_BIT) & 1 else -1.0
        damped = 1.0 + math.log(weight) if weight > 1 else weight
        vector[raw % dim] += sign * damped
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


def _features(text: str) -> dict[str, float]:
    features: dict[str, float] = {}
    for token in WORD_PATTERN.findall(text.lower()):
        if token in STOPWORDS:
            continue
        features[token] = features.get(token, 0.0) + 1.0
        if len(token) > FRAGMENT_LENGTH:
            for start in range(len(token) - FRAGMENT_LENGTH + 1):
                fragment = "#" + token[start : start + FRAGMENT_LENGTH]
                features[fragment] = features.get(fragment, 0.0) + FRAGMENT_WEIGHT
    return features


def _openai_embed(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    body = post_json(
        OPENAI_EMBEDDINGS_URL,
        headers={"Authorization": f"Bearer {key}"},
        payload={"model": settings.openai_embedding_model, "input": texts},
        timeout=settings.llm_timeout,
        retries=settings.llm_max_retries,
    )
    items = sorted(body["data"], key=lambda item: item["index"])
    return [list(item["embedding"]) for item in items]
