"""Tests for dks.index — embedding-based semantic search with temporal awareness."""
from datetime import datetime, timezone

from dks import (
    ClaimCore,
    KnowledgeStore,
    NumpyIndex,
    Provenance,
    SearchIndex,
    SearchResult,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_store_with_revisions() -> tuple[KnowledgeStore, list[str]]:
    """Create a store with 3 revisions for testing."""
    store = KnowledgeStore()
    revision_ids = []

    cores_data = [
        ("residence", {"subject": "alice"}, "Alice lives in London"),
        ("residence", {"subject": "bob"}, "Bob lives in Paris"),
        ("role", {"subject": "carol"}, "Carol is a CEO"),
    ]

    for i, (ctype, slots, assertion) in enumerate(cores_data):
        core = ClaimCore(claim_type=ctype, slots=slots)
        rev = store.assert_revision(
            core=core,
            assertion=assertion,
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=i + 1, recorded_at=dt(2024)),
            provenance=Provenance(source="test"),
            confidence_bp=8000,
            status="asserted",
        )
        revision_ids.append(rev.revision_id)

    return store, revision_ids


class TestNumpyIndex:
    def test_embed_returns_correct_dimension(self) -> None:
        index = NumpyIndex(dimension=64)
        vectors = index.embed(["hello world"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 64

    def test_embed_batch(self) -> None:
        index = NumpyIndex(dimension=32)
        vectors = index.embed(["hello", "world", "test"])
        assert len(vectors) == 3
        for vec in vectors:
            assert len(vec) == 32

    def test_embed_is_normalized(self) -> None:
        """Vectors should be L2 normalized."""
        import math
        index = NumpyIndex(dimension=64)
        vectors = index.embed(["hello world"])
        norm = math.sqrt(sum(x * x for x in vectors[0]))
        assert abs(norm - 1.0) < 1e-6

    def test_similar_texts_higher_score(self) -> None:
        """Similar texts should have higher cosine similarity."""
        from dks.index import _cosine_similarity

        index = NumpyIndex(dimension=128)
        vecs = index.embed(["alice lives in london", "alice lives in paris", "quantum physics theory"])

        sim_similar = _cosine_similarity(vecs[0], vecs[1])
        sim_different = _cosine_similarity(vecs[0], vecs[2])

        assert sim_similar > sim_different


class TestSearchIndex:
    def test_add_and_search(self) -> None:
        store, revision_ids = _make_store_with_revisions()
        backend = NumpyIndex(dimension=64)
        index = SearchIndex(store, backend)

        # Index all revisions
        index.add(revision_ids[0], "Alice lives in London")
        index.add(revision_ids[1], "Bob lives in Paris")
        index.add(revision_ids[2], "Carol is a CEO")

        assert index.size == 3

        # Search for residence
        results = index.search("lives in a city")
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_returns_k_results(self) -> None:
        store, revision_ids = _make_store_with_revisions()
        backend = NumpyIndex(dimension=64)
        index = SearchIndex(store, backend)

        for rid in revision_ids:
            rev = store.revisions[rid]
            index.add(rid, rev.assertion)

        results = index.search("test query", k=2)
        assert len(results) <= 2

    def test_search_results_sorted_by_score(self) -> None:
        store, revision_ids = _make_store_with_revisions()
        backend = NumpyIndex(dimension=64)
        index = SearchIndex(store, backend)

        for rid in revision_ids:
            rev = store.revisions[rid]
            index.add(rid, rev.assertion)

        results = index.search("test")
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_temporal_filtering(self) -> None:
        """Search should respect bitemporal visibility."""
        store = KnowledgeStore()
        core = ClaimCore(claim_type="fact", slots={"subject": "alpha"})

        # Assert at tx=1
        rev1 = store.assert_revision(
            core=core,
            assertion="Alpha is important",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="test"),
            confidence_bp=8000,
            status="asserted",
        )

        # Retract at tx=2 (same interval)
        store.assert_revision(
            core=core,
            assertion="Alpha retracted",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 2, 1)),
            provenance=Provenance(source="test"),
            confidence_bp=8000,
            status="retracted",
        )

        backend = NumpyIndex(dimension=64)
        index = SearchIndex(store, backend)
        index.add(rev1.revision_id, "Alpha is important")

        # Without temporal filter — should find it
        results = index.search("Alpha")
        assert len(results) == 1

        # With temporal filter at tx=1 — should find it (before retraction)
        results = index.search("Alpha", valid_at=dt(2024, 6, 1), tx_id=1)
        assert len(results) == 1

        # With temporal filter at tx=2 — should NOT find it (retracted)
        results = index.search("Alpha", valid_at=dt(2024, 6, 1), tx_id=2)
        assert len(results) == 0

    def test_add_batch(self) -> None:
        store, revision_ids = _make_store_with_revisions()
        backend = NumpyIndex(dimension=64)
        index = SearchIndex(store, backend)

        items = [
            (rid, store.revisions[rid].assertion)
            for rid in revision_ids
        ]
        index.add_batch(items)
        assert index.size == 3

    def test_empty_index_search(self) -> None:
        store = KnowledgeStore()
        backend = NumpyIndex(dimension=64)
        index = SearchIndex(store, backend)

        results = index.search("anything")
        assert results == []
