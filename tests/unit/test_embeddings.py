"""The built-in feature-hashing embedding."""

from __future__ import annotations

import math

from knowledge_guard.embeddings import EMBEDDING_DIM, embed, hash_embed


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_vectors_are_unit_length_with_the_schema_dimension() -> None:
    vector = hash_embed("salary bands for software engineering")
    assert len(vector) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)


def test_deterministic() -> None:
    assert hash_embed("leave policy") == hash_embed("leave policy")


def test_related_texts_are_closer_than_unrelated_ones() -> None:
    query = hash_embed("annual salary of a senior developer")
    related = hash_embed("Senior EUR 92,000 annual salary in the engineering salary band")
    unrelated = hash_embed("The company badge is handed out at reception")
    assert cosine(query, related) > cosine(query, unrelated)


def test_fragments_match_compound_words() -> None:
    assert cosine(hash_embed("salarybands"), hash_embed("salary")) > 0


def test_stopwords_only_gives_a_defined_vector() -> None:
    vector = hash_embed("the and of")
    assert vector[0] == 1.0
    assert sum(abs(v) for v in vector) == 1.0


def test_embed_keeps_order_and_handles_empty_input() -> None:
    assert embed([]) == []
    assert embed(["a b", "c d"]) == [hash_embed("a b"), hash_embed("c d")]
