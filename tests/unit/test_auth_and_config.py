"""Token signing and provider resolution."""

from __future__ import annotations

import pytest

from knowledge_guard.auth import issue_token, read_token
from knowledge_guard.config import get_settings
from knowledge_guard.errors import AuthError
from knowledge_guard.models import User

TOM = User(5, "tom.schaefer", "Tom Schaefer", "Engineering Intern", "Intern")


def test_token_round_trip() -> None:
    claims = read_token(issue_token(TOM, now=1_000), now=1_001)
    assert (claims.user_id, claims.username) == (5, "tom.schaefer")


def test_expired_token_is_rejected() -> None:
    token = issue_token(TOM, now=1_000)
    with pytest.raises(AuthError, match="expired"):
        read_token(token, now=1_000 + get_settings().token_ttl_seconds + 1)


@pytest.mark.parametrize("token", ["", "no-dot", "abc.def", "e30.0", "abc.é", "é.é"])
def test_malformed_tokens_are_rejected(token: str) -> None:
    with pytest.raises(AuthError):
        read_token(token)


def test_tampered_payload_is_rejected() -> None:
    payload, signature = issue_token(TOM).split(".")
    with pytest.raises(AuthError, match="signature"):
        read_token(f"{payload}x.{signature}")


def test_token_signed_with_another_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    token = issue_token(TOM)
    monkeypatch.setenv("TOKEN_SECRET", "a-different-secret")
    get_settings.cache_clear()
    with pytest.raises(AuthError):
        read_token(token)


def test_demo_secret_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_settings().uses_demo_secret
    monkeypatch.setenv("TOKEN_SECRET", "real-secret")
    get_settings.cache_clear()
    assert not get_settings().uses_demo_secret


@pytest.mark.parametrize(
    ("env", "llm", "embedding"),
    [
        ({}, "none", "local"),
        ({"ANTHROPIC_API_KEY": "k"}, "anthropic", "local"),
        ({"OPENAI_API_KEY": "k"}, "openai", "openai"),
        ({"OPENAI_API_KEY": "k", "EMBEDDING_PROVIDER": "local"}, "openai", "local"),
        ({"ANTHROPIC_API_KEY": "k", "LLM_PROVIDER": "none"}, "none", "local"),
        ({"ANTHROPIC_API_KEY": " "}, "none", "local"),
    ],
)
def test_provider_resolution(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], llm: str, embedding: str
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = get_settings()
    assert settings.resolved_llm_provider() == llm
    assert settings.resolved_embedding_provider() == embedding
