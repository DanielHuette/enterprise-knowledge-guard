"""Vektoren fuer Text.

Zwei Wege:
  openai  echte Einbettungen ueber die OpenAI-Schnittstelle (1536 Werte).
  local   ein eingebauter, rein rechnerischer Textvergleich -- ohne Schluessel,
          ohne Netz, immer gleiches Ergebnis fuer gleichen Text.

Der eingebaute Weg ist der Grund, warum die Vorfuehrung bei jedem sofort
laeuft: kein Schluessel, keine Kosten, kein Wartezimmer. Er bildet Woerter und
Wortteile auf 1536 Stellen ab (Feature Hashing) und erfasst damit auch deutsche
Zusammensetzungen -- "Gehaltsbaender" findet "Gehalt". Die Dimension ist
bewusst dieselbe wie bei text-embedding-3-small, damit ein Wechsel auf echte
Einbettungen keine Schemaaenderung braucht.
"""
from __future__ import annotations

import hashlib
import math
import re

import httpx

from .config import settings

_WORD = re.compile(r"[a-zäöüß0-9]+")

# Fuellwoerter tragen keine Bedeutung und wuerden alle Texte aehnlich machen.
_STOPWORDS = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "eines", "und", "oder", "aber", "ist", "sind", "war", "waren", "wird",
    "werden", "wie", "was", "wer", "wo", "wann", "warum", "fuer", "für", "von",
    "vom", "mit", "ohne", "auf", "aus", "bei", "im", "in", "an", "zu", "zum",
    "zur", "nicht", "kein", "keine", "auch", "noch", "nur", "sich", "dass",
    "man", "wir", "ich", "sie", "es", "er", "the", "and", "for", "with",
}


def _features(text: str) -> dict[str, float]:
    tokens = [t for t in _WORD.findall(text.lower()) if t not in _STOPWORDS]
    feats: dict[str, float] = {}
    for token in tokens:
        feats[token] = feats.get(token, 0.0) + 1.0
        # Wortteile: faengt Zusammensetzungen und Beugungen ab.
        if len(token) > 4:
            for i in range(len(token) - 3):
                part = token[i : i + 4]
                feats["#" + part] = feats.get("#" + part, 0.0) + 0.45
    return feats


def _hash_embed(text: str) -> list[float]:
    dim = settings.embedding_dim
    vec = [0.0] * dim
    for feature, weight in _features(text).items():
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        raw = int.from_bytes(digest, "big")
        index = raw % dim
        sign = 1.0 if (raw >> 61) & 1 else -1.0
        # gedaempfte Haeufigkeit: das zehnte Vorkommen zaehlt weniger als das zweite
        vec[index] += sign * (1.0 + math.log(weight)) if weight > 1 else sign * weight
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        # Leerer Text: ein definierter Punkt, damit die Distanz rechenbar bleibt.
        vec[0] = 1.0
        return vec
    return [v / norm for v in vec]


def _openai_embed(texts: list[str]) -> list[list[float]]:
    response = httpx.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={"model": settings.openai_embedding_model, "input": texts},
        timeout=settings.llm_timeout,
    )
    response.raise_for_status()
    payload = response.json()["data"]
    payload.sort(key=lambda item: item["index"])
    return [item["embedding"] for item in payload]


def embed(texts: list[str]) -> list[list[float]]:
    """Wandelt Texte in Vektoren. Reihenfolge bleibt erhalten."""
    if not texts:
        return []
    if settings.resolved_embedding_provider() == "openai":
        return _openai_embed(texts)
    return [_hash_embed(text) for text in texts]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
