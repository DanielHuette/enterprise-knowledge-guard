"""Domain objects shared by the modules.

Context: Typed replacements for loose dictionaries that cross module boundaries.
| Input: database rows. | Output: immutable value objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    job_title: str
    role: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> User:
        return cls(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"]),
            job_title=str(row["job_title"]),
            role=str(row["role"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Hit:
    """A chunk the caller is allowed to read, with its distance to the question."""

    chunk_id: int
    document_id: int
    title: str
    content: str
    min_required_role: str
    distance: float

    def as_source(self, excerpt_chars: int = 400) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "min_required_role": self.min_required_role,
            "distance": round(self.distance, 4),
            "excerpt": self.content[:excerpt_chars],
        }


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    blocked_count: int

    @property
    def chunk_ids(self) -> list[int]:
        return [hit.chunk_id for hit in self.hits]

    @property
    def sources(self) -> list[dict[str, Any]]:
        return [hit.as_source() for hit in self.hits]
