"""Error handling and input validation tests.

Verifies that invalid inputs are rejected with clear errors rather than
causing silent failures or crashes.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Pipeline,
    Provenance,
    TfidfSearchIndex,
    TransactionTime,
    ValidTime,
)


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _tx(tx_id=1):
    return TransactionTime(tx_id=tx_id, recorded_at=dt())


def _vt():
    return ValidTime(start=dt())


def _prov():
    return Provenance(source="test")


def _make_pipeline():
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


# ============================================================
# assert_revision validation
# ============================================================

class TestAssertRevisionValidation:

    def test_invalid_status_rejected(self):
        store = KnowledgeStore()
        core = ClaimCore(claim_type="test", slots={"k": "v"})
        with pytest.raises(ValueError, match="Invalid status"):
            store.assert_revision(
                core=core, assertion="x", valid_time=_vt(),
                transaction_time=_tx(), provenance=_prov(),
                confidence_bp=5000, status="pending",  # type: ignore
            )

    def test_negative_confidence_rejected(self):
        store = KnowledgeStore()
        core = ClaimCore(claim_type="test", slots={"k": "v"})
        with pytest.raises(ValueError, match="confidence_bp"):
            store.assert_revision(
                core=core, assertion="x", valid_time=_vt(),
                transaction_time=_tx(), provenance=_prov(),
                confidence_bp=-1,
            )

    def test_confidence_above_10000_rejected(self):
        store = KnowledgeStore()
        core = ClaimCore(claim_type="test", slots={"k": "v"})
        with pytest.raises(ValueError, match="confidence_bp"):
            store.assert_revision(
                core=core, assertion="x", valid_time=_vt(),
                transaction_time=_tx(), provenance=_prov(),
                confidence_bp=10001,
            )

    def test_confidence_at_boundaries_accepted(self):
        """0 and 10000 should both be valid."""
        store = KnowledgeStore()
        core_lo = ClaimCore(claim_type="test", slots={"k": "lo"})
        core_hi = ClaimCore(claim_type="test", slots={"k": "hi"})
        rev_lo = store.assert_revision(
            core=core_lo, assertion="x", valid_time=_vt(),
            transaction_time=_tx(), provenance=_prov(),
            confidence_bp=0,
        )
        rev_hi = store.assert_revision(
            core=core_hi, assertion="x", valid_time=_vt(),
            transaction_time=_tx(2), provenance=_prov(),
            confidence_bp=10000,
        )
        assert rev_lo.confidence_bp == 0
        assert rev_hi.confidence_bp == 10000


# ============================================================
# Search input validation
# ============================================================

class TestSearchValidation:

    def test_empty_query_returns_empty(self):
        pipe = _make_pipeline()
        pipe.ingest_text("Some content here")
        pipe.rebuild_index()
        assert pipe.query("") == []
        assert pipe.query("   ") == []

    def test_query_k_zero_returns_empty(self):
        pipe = _make_pipeline()
        pipe.ingest_text("Some content here")
        pipe.rebuild_index()
        assert pipe.query("content", k=0) == []

    def test_query_on_empty_store_returns_empty(self):
        pipe = _make_pipeline()
        assert pipe.query("anything") == []

    def test_reason_on_empty_store(self):
        pipe = _make_pipeline()
        result = pipe.reason("anything")
        assert result.total_chunks == 0

    def test_synthesize_on_empty_store(self):
        pipe = _make_pipeline()
        result = pipe.synthesize("anything")
        assert result.total_chunks >= 0  # May be 0

    def test_ask_on_empty_store(self):
        pipe = _make_pipeline()
        result = pipe.ask("What is anything?")
        assert result.total_chunks >= 0


# ============================================================
# Annotation validation
# ============================================================

class TestAnnotationValidation:

    def test_annotate_nonexistent_revision_raises(self):
        pipe = _make_pipeline()
        with pytest.raises(ValueError, match="not found"):
            pipe.annotate_chunk("nonexistent_revision_id", tags=["test"])

    def test_annotate_retracted_revision_raises(self):
        pipe = _make_pipeline()
        rids = pipe.ingest_text("Some text", source="test")
        rev = pipe.store.revisions[rids[0]]
        core = pipe.store.cores[rev.core_id]
        pipe.store.assert_revision(
            core=core, assertion="retracted",
            valid_time=rev.valid_time,
            transaction_time=_tx(999),
            provenance=_prov(), confidence_bp=5000,
            status="retracted",
        )
        with pytest.raises(ValueError, match="retracted"):
            pipe.annotate_chunk(rids[0], tags=["test"])


# ============================================================
# Edge cases: empty corpus operations
# ============================================================

class TestEmptyCorpusOperations:

    def test_rebuild_index_on_empty_store(self):
        pipe = _make_pipeline()
        count = pipe.rebuild_index()
        assert count == 0

    def test_stats_on_empty_store(self):
        pipe = _make_pipeline()
        s = pipe.stats()
        assert s["cores"] == 0
        assert s["revisions"] == 0

    def test_list_annotations_on_empty_store(self):
        pipe = _make_pipeline()
        assert pipe.list_annotations() == []

    def test_get_entity_decisions_on_empty_store(self):
        pipe = _make_pipeline()
        assert pipe.get_entity_decisions() == {}

    def test_summarize_corpus_on_empty_store_requires_graph(self):
        """summarize_corpus requires graph — should raise on empty store."""
        pipe = _make_pipeline()
        with pytest.raises(ValueError, match="Graph not built"):
            pipe.summarize_corpus()

    def test_list_sources_on_empty_store(self):
        pipe = _make_pipeline()
        sources = pipe.list_sources()
        assert isinstance(sources, list)
        assert len(sources) == 0

    def test_quality_report_requires_graph(self):
        """quality_report should raise ValueError without graph."""
        pipe = _make_pipeline()
        with pytest.raises(ValueError, match="Graph not built"):
            pipe.quality_report()

    def test_search_after_all_retracted(self):
        """Search should return empty after all content is retracted."""
        pipe = _make_pipeline()
        rids = pipe.ingest_text("Alpha beta gamma", source="test")
        pipe.rebuild_index()
        # Retract all
        for rid in rids:
            rev = pipe.store.revisions[rid]
            core = pipe.store.cores[rev.core_id]
            pipe.store.assert_revision(
                core=core, assertion="retracted",
                valid_time=rev.valid_time,
                transaction_time=_tx(999),
                provenance=_prov(), confidence_bp=5000,
                status="retracted",
            )
        pipe.rebuild_index()
        results = pipe.query("alpha beta")
        assert results == []
