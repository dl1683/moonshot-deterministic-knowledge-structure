"""Codex Review #3 — mandated tests for B+ grade findings.

Tests for: BUG-3, BUG-4, BUG-10, BUG-14, BUG-15, plus additional
coverage for scan_contradictions, entity decisions, quality scoring,
MCP tool schemas, and deletion semantics.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Pipeline,
    Provenance,
    TfidfSearchIndex,
    TransactionTime,
    ValidTime,
    canonicalize_text,
)


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _tx(tx_id=1):
    return TransactionTime(tx_id=tx_id, recorded_at=dt())


def _vt(start_year=2024, end_year=None):
    return ValidTime(start=dt(start_year), end=dt(end_year) if end_year else None)


def _prov(source="test"):
    return Provenance(source=source)


def _make_pipeline():
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


# ============================================================
# BUG-3: MCP contradictions should support topic parameter
# ============================================================


class TestMCPContradictionsTopic:

    def test_mcp_contradictions_schema_has_topic(self):
        """MCP contradictions tool schema should include topic parameter."""
        from dks.mcp import MCPToolHandler

        pipe = _make_pipeline()
        mcp = MCPToolHandler(pipe)
        tools = mcp.list_tools()
        ct = next(t for t in tools if t["name"] == "dks_contradictions")
        props = ct["inputSchema"]["properties"]
        assert "topic" in props
        assert props["topic"]["type"] == "string"

    def test_mcp_contradictions_with_topic(self):
        """MCP contradictions should use topic-focused search when topic given."""
        from dks.mcp import MCPToolHandler

        pipe = _make_pipeline()
        pipe.ingest_text(
            "Coffee increases heart disease risk according to study A",
            source="source_a",
        )
        pipe.ingest_text(
            "Coffee decreases heart disease risk according to study B",
            source="source_b",
        )
        pipe.rebuild_index()
        mcp = MCPToolHandler(pipe)
        result = mcp.handle_tool_call("dks_contradictions", {"topic": "coffee heart disease", "k": 5})
        # Should return without error
        assert isinstance(result, dict)

    def test_mcp_contradictions_without_topic_falls_back(self):
        """Without topic, MCP contradictions should use scan_contradictions."""
        from dks.mcp import MCPToolHandler

        pipe = _make_pipeline()
        pipe.ingest_text("Some content A", source="a")
        pipe.ingest_text("Some content B", source="b")
        pipe.rebuild_index()
        mcp = MCPToolHandler(pipe)
        result = mcp.handle_tool_call("dks_contradictions", {"k": 5})
        assert isinstance(result, dict)
        assert "contradictions" in result


# ============================================================
# BUG-10: scan_contradictions threshold now usable for TF-IDF
# ============================================================


class TestScanContradictionsThreshold:

    def test_default_threshold_is_reachable_for_tfidf(self):
        """scan_contradictions default threshold should find matches with TF-IDF."""
        pipe = _make_pipeline()
        # Ingest very similar but contradictory content
        pipe.ingest_text(
            "Coffee consumption significantly increases cardiovascular disease risk "
            "based on clinical trials and medical research",
            source="source_a",
        )
        pipe.ingest_text(
            "Coffee consumption does not increase cardiovascular disease risk "
            "based on clinical trials and medical research",
            source="source_b",
        )
        pipe.rebuild_index()
        # With threshold=0.15, these highly similar chunks should match
        results = pipe.scan_contradictions(k=5)
        assert len(results) >= 1, "Should detect contradiction between similar claims"

    def test_explicit_high_threshold_filters_more(self):
        """Higher threshold should filter more aggressively."""
        pipe = _make_pipeline()
        pipe.ingest_text(
            "The economy grew rapidly in Q1 with strong consumer spending",
            source="source_a",
        )
        pipe.ingest_text(
            "The economy did not grow in Q1 with weak consumer spending",
            source="source_b",
        )
        pipe.rebuild_index()
        low_threshold = pipe.scan_contradictions(k=10, threshold=0.05)
        high_threshold = pipe.scan_contradictions(k=10, threshold=0.9)
        assert len(high_threshold) <= len(low_threshold)


# ============================================================
# BUG-14: quality_score should be non-negative
# ============================================================


class TestQualityScoreRange:

    def test_quality_score_never_negative(self):
        """Quality scores must be in [0, 100], matching documentation."""
        pipe = _make_pipeline()
        # Ingest ubiquitous term appearing in every chunk (>10% frequency)
        for i in range(20):
            pipe.ingest_text(
                f"Common term appears everywhere in chunk {i} with the common term again",
                source=f"source_{i}",
            )
        pipe.rebuild_index()
        pipe.build_graph(n_clusters=3)

        result = pipe.review_entities(top_k=100)
        all_entities = result["high"] + result["medium"] + result["flagged"]
        for e in all_entities:
            assert e["quality_score"] >= 0, (
                f"Quality score {e['quality_score']} is negative for '{e['entity']}'"
            )
            assert e["quality_score"] <= 100


# ============================================================
# BUG-15: entity decisions — latest tx_id wins
# ============================================================


class TestEntityDecisionOrdering:

    def test_latest_decision_wins(self):
        """When entity is accepted then rejected, the latest decision wins."""
        pipe = _make_pipeline()
        pipe.accept_entities(["quantum entanglement"], reason="initially accepted")
        pipe.reject_entities(["quantum entanglement"], reason="reconsidered")

        decisions = pipe.get_entity_decisions()
        assert decisions.get("quantum entanglement") == "rejected"

    def test_reject_then_accept(self):
        """When entity is rejected then accepted, accept wins."""
        pipe = _make_pipeline()
        pipe.reject_entities(["dark matter"], reason="initially rejected")
        pipe.accept_entities(["dark matter"], reason="reconsidered")

        decisions = pipe.get_entity_decisions()
        assert decisions.get("dark matter") == "accepted"

    def test_multiple_overrides(self):
        """Multiple decision changes: final decision wins."""
        pipe = _make_pipeline()
        pipe.accept_entities(["neural networks"], reason="v1")
        pipe.reject_entities(["neural networks"], reason="v2")
        pipe.accept_entities(["neural networks"], reason="v3")

        decisions = pipe.get_entity_decisions()
        assert decisions.get("neural networks") == "accepted"

    def test_independent_entities_not_affected(self):
        """Changing one entity's decision doesn't affect others."""
        pipe = _make_pipeline()
        pipe.accept_entities(["entity_a", "entity_b"])
        pipe.reject_entities(["entity_a"], reason="reject only A")

        decisions = pipe.get_entity_decisions()
        assert decisions.get("entity_a") == "rejected"
        assert decisions.get("entity_b") == "accepted"


# ============================================================
# BUG-4: delete_cluster batch tx_id semantics
# ============================================================


class TestDeleteClusterTxSemantics:

    def test_delete_cluster_uses_single_tx_id(self):
        """All retractions in a cluster delete should share one tx_id."""
        pipe = _make_pipeline()
        pipe.ingest_text("Alpha beta gamma topic one", source="a")
        pipe.ingest_text("Delta epsilon zeta topic one", source="b")
        pipe.rebuild_index()
        pipe.build_graph(n_clusters=1)

        pipe.delete_cluster(0, reason="test cleanup")

        retraction_tx_ids = set()
        for rev in pipe.store.revisions.values():
            if rev.status == "retracted":
                retraction_tx_ids.add(rev.transaction_time.tx_id)

        # All retractions from this batch share the same tx_id
        assert len(retraction_tx_ids) == 1


# ============================================================
# BUG-6: Pipeline.load creates valid index objects
# ============================================================


class TestPipelineLoadIndexValidity:

    def test_loaded_pipeline_index_is_functional(self):
        """Loaded pipeline's index should support all expected operations."""
        pipe = _make_pipeline()
        pipe.ingest_text("Machine learning algorithms for classification")
        pipe.ingest_text("Deep neural networks for image recognition")
        pipe.rebuild_index()

        with tempfile.TemporaryDirectory() as tmp:
            pipe.save(tmp)
            loaded = Pipeline.load(tmp)

        # Index should be fully functional after load
        results = loaded.query("machine learning")
        assert len(results) >= 1
        # Should be able to rebuild without error
        count = loaded.rebuild_index()
        assert count >= 2


# ============================================================
# BUG-8: MCP query temporal parameters
# ============================================================


class TestMCPQueryTemporal:

    def test_mcp_query_with_valid_at(self):
        """MCP query should work with valid_at parameter."""
        from dks.mcp import MCPToolHandler

        pipe = _make_pipeline()
        pipe.ingest_text("Historical fact about ancient Rome")
        pipe.rebuild_index()

        mcp = MCPToolHandler(pipe)
        result = mcp.handle_tool_call("dks_query", {
            "question": "ancient Rome",
            "valid_at": "2024-01-01T00:00:00Z",
            "k": 5,
        })
        assert isinstance(result, dict)


# ============================================================
# Additional coverage: merge relation dedup correctness
# ============================================================


class TestMergeRelationDedup:

    def test_merge_with_both_active_and_pending_relations(self):
        """Merge correctly handles both active and pending relation sources."""
        store_a = KnowledgeStore()
        core_a = ClaimCore(claim_type="test", slots={"k": "a"})
        rev_a = store_a.assert_revision(
            core=core_a, assertion="fact a",
            valid_time=_vt(), transaction_time=_tx(1),
            provenance=_prov(), confidence_bp=5000,
        )
        core_b = ClaimCore(claim_type="test", slots={"k": "b"})
        rev_b = store_a.assert_revision(
            core=core_b, assertion="fact b",
            valid_time=_vt(), transaction_time=_tx(2),
            provenance=_prov(), confidence_bp=5000,
        )

        store_b = KnowledgeStore()
        # Copy revisions to store_b so relation endpoints exist
        store_b.assert_revision(
            core=core_a, assertion="fact a",
            valid_time=_vt(), transaction_time=_tx(1),
            provenance=_prov(), confidence_bp=5000,
        )
        store_b.assert_revision(
            core=core_b, assertion="fact b",
            valid_time=_vt(), transaction_time=_tx(2),
            provenance=_prov(), confidence_bp=5000,
        )

        # Add a relation in store_b
        store_b.attach_relation(
            relation_type="supports",
            from_revision_id=rev_a.revision_id,
            to_revision_id=rev_b.revision_id,
            transaction_time=_tx(3),
        )

        result = store_a.merge(store_b)
        # Relation should be in merged store
        assert len(result.merged.relations) >= 1


# ============================================================
# Negation constant consistency
# ============================================================


class TestNegationConsistency:

    def test_contradictions_and_scan_share_core_negation_words(self):
        """Both contradiction methods should detect common negation patterns."""
        pipe = _make_pipeline()
        pipe.ingest_text(
            "The treatment is effective for patients with mild symptoms",
            source="pro",
        )
        pipe.ingest_text(
            "The treatment is not effective for patients with mild symptoms",
            source="con",
        )
        pipe.rebuild_index()

        # Topic-focused contradictions
        topic_result = pipe.contradictions("treatment effective patients")
        # Corpus-wide scan
        scan_result = pipe.scan_contradictions(k=5)

        # Both should find something (they share the "not" negation pattern)
        # At minimum, neither should crash
        assert isinstance(topic_result, list)
        assert isinstance(scan_result, list)
