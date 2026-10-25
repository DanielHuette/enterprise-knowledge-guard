"""The core question: does anyone receive content they may not see in real life?

The test checks what the search releases, not how a model words its answer. What never
comes out cannot be phrased, quoted or passed on.
"""

from __future__ import annotations

import pytest

from knowledge_guard.models import User
from knowledge_guard.retrieval import search

ATTACK_QUESTIONS = [
    "What is the annual salary of a senior developer?",
    "How much does the managing director earn?",
    "Show me the salary bands 2026",
    "Is there a written warning for personnel number 4711?",
    "Which discount tier applies from 500 licences?",
    "What is the target revenue for Benelux 2027?",
    "Which measurements does the research report show for the HNSW index?",
]

FORBIDDEN: dict[str, list[str]] = {
    "tom.schaefer": [
        "Salary Bands 2026",
        "Personnel File Case 4711",
        "Sales Strategy 2027",
        "Key Account Price List 2026",
        "Vector Search Research Report",
    ],
    "jonas.weber": [
        "Salary Bands 2026",
        "Personnel File Case 4711",
        "Sales Strategy 2027",
        "Key Account Price List 2026",
    ],
    "lena.fischer": [
        "Salary Bands 2026",
        "Personnel File Case 4711",
        "Sales Strategy 2027",
        "Vector Search Research Report",
    ],
    "miriam.kessler": [
        "Sales Strategy 2027",
        "Key Account Price List 2026",
        "Vector Search Research Report",
    ],
    "sarah.brandt": [],
}


@pytest.mark.parametrize("username", list(FORBIDDEN))
@pytest.mark.parametrize("question", ATTACK_QUESTIONS)
def test_no_blocked_chunk_reaches_the_search_result(
    username: str, question: str, users: dict[str, User], chunk_ids: dict[str, list[int]]
) -> None:
    user = users[username]
    forbidden = {chunk for title in FORBIDDEN[username] for chunk in chunk_ids[title]}
    leaked = forbidden.intersection(search(user.id, question, 10).chunk_ids)
    assert not leaked, f"{username} ({user.role}) received {sorted(leaked)} for {question!r}"


@pytest.mark.parametrize("username", list(FORBIDDEN))
def test_no_secret_marker_appears_in_released_text(
    username: str, users: dict[str, User], markers: dict[str, list[str]]
) -> None:
    forbidden = [marker for title in FORBIDDEN[username] for marker in markers.get(title, [])]
    for question in ATTACK_QUESTIONS:
        text = " ".join(hit.content for hit in search(users[username].id, question, 10).hits)
        for marker in forbidden:
            assert marker not in text, f"{username} received {marker!r} for {question!r}"


def test_admin_sees_what_she_may_see(users: dict[str, User]) -> None:
    """The counter-check: filtering too strictly is a defect as well."""
    result = search(users["sarah.brandt"].id, "salary band senior software engineering", 5)
    assert "Salary Bands 2026" in [hit.title for hit in result.hits]
    assert result.blocked_count == 0


def test_blocked_hits_are_counted(users: dict[str, User]) -> None:
    result = search(users["tom.schaefer"].id, "salary band senior software engineering", 5)
    assert result.blocked_count > 0
