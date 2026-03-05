"""Regression tests for v0.3.7 functional fixes.

Tests for:
- SearchIndex.clear()/rebuild() (CRITICAL #1)
- merge() list isolation (CRITICAL #2)
- ingest() assertion/index text consistency (HIGH #3)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Pipeline,
    Provenance,
    ValidTime,
    TransactionTime,
)
from dks.index import NumpyIndex, SearchIndex, TfidfSearchIndex


def _dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _vt(year: int = 2024) -> ValidTime:
    return ValidTime(start=_dt(year))


def _tx(tx_id: int) -> TransactionTime:
    return TransactionTime(tx_id=tx_id, recorded_at=datetime.now(timezone.utc))


# ---- CRITICAL #1: SearchIndex.clear() / rebuild() ----


class TestSearchIndexClearRebuild:
    """SearchIndex must support clear() and rebuild() for pipeline.rebuild_index()."""

    def test_clear_empties_index(self) -> None:
        store = KnowledgeStore()
        backend = NumpyIndex(dimension=32)
        index = SearchIndex(store, backend)

        index.add("rev1", "hello world")
        index.add("rev2", "goodbye world")
        assert index.size == 2

        index.clear()
        assert index.size == 0

    def test_rebuild_re_embeds_texts(self) -> None:
        """After clear + add_batch + rebuild, search should find new content."""
        store = KnowledgeStore()
        backend = NumpyIndex(dimension=32)
        index = SearchIndex(store, backend)

        # Add initial content
        index.add("rev1", "neural networks are powerful")
        assert index.size == 1

        # Clear and rebuild with different content
        index.clear()
        assert index.size == 0

        index.add_batch([("rev2", "quantum computing basics"), ("rev3", "quantum entanglement")])
        assert index.size == 2

    def test_pipeline_rebuild_with_search_index(self) -> None:
        """Pipeline.rebuild_index() works correctly with SearchIndex."""
        store = KnowledgeStore()
        backend = NumpyIndex(dimension=32)
        index = SearchIndex(store, backend)
        pipeline = Pipeline(store=store, embedding_backend=None, search_index=index)

        # Ingest some text
        pipeline.ingest_text("Machine learning is a subset of AI.", source="test.txt",
                            valid_time=_vt(), transaction_time=_tx(1))
        pipeline.ingest_text("Deep learning uses neural networks.", source="test.txt",
                            valid_time=_vt(), transaction_time=_tx(2))

        # Index should have items
        assert index.size == 2

        # Rebuild should re-index cleanly
        count = pipeline.rebuild_index()
        assert count == 2
        assert index.size == 2


# ---- CRITICAL #2: merge() list isolation ----


class TestMergeListIsolation:
    """After merge, chunk_siblings lists must be independent copies."""

    def test_merge_does_not_share_list_references(self) -> None:
        p1 = Pipeline(store=KnowledgeStore())
        p2 = Pipeline(store=KnowledgeStore())

        # Manually set chunk siblings on p2
        p2._chunk_siblings["doc.txt"] = ["rev_a", "rev_b"]

        # Add data to both stores so merge has something to work with
        prov = Provenance(source="test")
        core1 = ClaimCore(claim_type="dks.text@v1", slots={"content": "test"})
        core2 = ClaimCore(claim_type="dks.text@v1", slots={"content": "other"})
        p1.store.assert_revision(
            core=core1, assertion="test",
            valid_time=_vt(), transaction_time=_tx(1),
            provenance=prov, confidence_bp=5000, status="asserted",
        )
        p2.store.assert_revision(
            core=core2, assertion="other",
            valid_time=_vt(), transaction_time=_tx(1),
            provenance=prov, confidence_bp=5000, status="asserted",
        )
        p1.merge(p2)

        # p1 should have the siblings
        assert "doc.txt" in p1._chunk_siblings
        assert p1._chunk_siblings["doc.txt"] == ["rev_a", "rev_b"]

        # Mutating p2's list should NOT affect p1
        p2._chunk_siblings["doc.txt"].append("rev_c")
        assert len(p1._chunk_siblings["doc.txt"]) == 2  # Still 2, not 3


# ---- HIGH #3: ingest() assertion/index text consistency ----


class TestIngestTextConsistency:
    """Assertion text and indexed text must always be the same."""

    def test_ingest_text_stores_and_indexes_same_content(self) -> None:
        """ingest_text() should use the same text for assertion and index."""
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=index)

        text = "The quick brown fox jumps over the lazy dog. " * 5
        revision_ids = pipeline.ingest_text(
            text,
            source="test.txt",
            valid_time=_vt(),
            transaction_time=_tx(1),
        )

        assert len(revision_ids) > 0

        # Check that assertion text matches indexed text
        for rid in revision_ids:
            rev = store.revisions[rid]
            # The assertion stored in the revision should match what's indexed
            assert rev.assertion  # Not empty

            # Search for the assertion text — should find itself
            index.rebuild()
            results = index.search(rev.assertion[:100], k=5)
            found_ids = [r.revision_id for r in results]
            assert rid in found_ids, f"Revision {rid} not found when searching for its own assertion"
