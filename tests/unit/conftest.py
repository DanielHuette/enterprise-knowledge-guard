"""Fixtures for unit tests: an isolated environment without keys or database.

Context: Settings are cached per process, so every test starts from a clean cache.
| Input: none. | Output: autouse environment isolation.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from knowledge_guard.config import get_settings

PROVIDER_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "LLM_PROVIDER",
    "EMBEDDING_PROVIDER",
    "TOKEN_SECRET",
)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> Iterator[None]:
    for name in PROVIDER_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
