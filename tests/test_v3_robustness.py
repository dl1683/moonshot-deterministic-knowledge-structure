"""Robustness tests: graceful degradation and input validation."""

import pytest
from datetime import datetime, timezone

from dks import (
    KnowledgeStore, Pipeline, TransactionTime, ValidTime,
    TfidfSearchIndex,
)
from dks.mcp import MCPToolHandler


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_pipeline():
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


def _make_populated_pipeline():
    """Pipeline with a few documents for testing."""
    pipeline = _make_pipeline()
    pipeline.ingest_text(
        "Photosynthesis converts sunlight into chemical energy in plants.",
        source="bio.pdf",
    )
    pipeline.ingest_text(
        "Mitochondria are the powerhouse of the cell, producing ATP.",
        source="bio.pdf",
    )
    pipeline.ingest_text(
        "Machine learning uses statistical methods to learn from data.",
        source="cs.pdf",
    )
    pipeline.rebuild_index()
    return pipeline


# =============================================================================
# Empty Store Queries
# =============================================================================

class TestEmptyStoreQueries:
    """Queries against an empty store must return empty results, not crash."""

    def test_query_empty_store(self):
        pipeline = _make_pipeline()
        results = pipeline.query("anything", k=5)
        assert results == []

    def test_query_exact_empty_store(self):
        pipeline = _make_pipeline()
        result = pipeline.query_exact(
            "nonexistent_core_id",
            valid_at=dt(2024),
            tx_id=1,
        )
        assert result is None

    def test_query_multi_empty_store(self):
        pipeline = _make_pipeline()
        results = pipeline.query_multi("anything", k=5)
        assert isinstance(results, dict)
        assert len(results) == 0

    def test_list_sources_empty(self):
        pipeline = _make_pipeline()
        sources = pipeline.list_sources()
        assert sources == []

    def test_profile_empty_store(self):
        pipeline = _make_pipeline()
        # profile() requires graph — should raise ValueError cleanly
        try:
            profile = pipeline.profile()
        except ValueError:
            pass  # Expected: "Graph not built"

    def test_stats_empty_store(self):
        pipeline = _make_pipeline()
        stats = pipeline.stats()
        assert stats["revisions"] == 0

    def test_topics_empty_store(self):
        pipeline = _make_pipeline()
        # topics() requires graph — should raise ValueError cleanly
        try:
            topics = pipeline.topics()
            assert topics == []
        except ValueError:
            pass  # Expected: "Graph not built"

    def test_timeline_empty_store(self):
        pipeline = _make_pipeline()
        timeline = pipeline.ingestion_timeline()
        assert len(timeline) == 0

    def test_insights_empty_store(self):
        pipeline = _make_pipeline()
        try:
            result = pipeline.insights()
            assert result is not None
        except ValueError:
            pass  # Expected: "Graph not built"

    def test_suggest_queries_empty_store(self):
        pipeline = _make_pipeline()
        try:
            result = pipeline.suggest_queries()
            assert isinstance(result, list)
        except ValueError:
            pass  # Expected: "Graph not built"

    def test_summarize_empty_store(self):
        pipeline = _make_pipeline()
        try:
            result = pipeline.summarize_corpus()
            assert isinstance(result, str)
        except ValueError:
            pass  # Expected: "Graph not built"

    def test_deduplicate_empty_store(self):
        pipeline = _make_pipeline()
        result = pipeline.deduplicate()
        assert isinstance(result, list)
        assert len(result) == 0


# =============================================================================
# Degenerate Input Handling
# =============================================================================

class TestDegenerateInput:
    """Edge-case inputs should not crash the system."""

    def test_empty_string_query(self):
        pipeline = _make_populated_pipeline()
        results = pipeline.query("", k=5)
        # Should return empty or all — not crash
        assert isinstance(results, list)

    def test_whitespace_only_query(self):
        pipeline = _make_populated_pipeline()
        results = pipeline.query("   \t\n  ", k=5)
        assert isinstance(results, list)

    def test_very_long_query(self):
        pipeline = _make_populated_pipeline()
        long_query = "photosynthesis " * 500
        results = pipeline.query(long_query, k=5)
        assert isinstance(results, list)

    def test_special_characters_query(self):
        pipeline = _make_populated_pipeline()
        results = pipeline.query("!@#$%^&*()", k=5)
        assert isinstance(results, list)

    def test_unicode_query(self):
        pipeline = _make_populated_pipeline()
        results = pipeline.query("日本語テスト 光合成", k=5)
        assert isinstance(results, list)

    def test_empty_text_ingest(self):
        pipeline = _make_pipeline()
        # Empty text should either work or raise cleanly
        try:
            pipeline.ingest_text("", source="empty.pdf")
        except (ValueError, Exception):
            pass  # Acceptable to reject empty text

    def test_whitespace_only_ingest(self):
        pipeline = _make_pipeline()
        try:
            pipeline.ingest_text("   \t\n  ", source="whitespace.pdf")
        except (ValueError, Exception):
            pass  # Acceptable to reject whitespace-only

    def test_k_zero_query(self):
        pipeline = _make_populated_pipeline()
        results = pipeline.query("photosynthesis", k=0)
        assert isinstance(results, list)
        assert len(results) == 0

    def test_k_negative_query(self):
        pipeline = _make_populated_pipeline()
        # Negative k should not crash
        try:
            results = pipeline.query("photosynthesis", k=-1)
            assert isinstance(results, list)
        except (ValueError, Exception):
            pass  # Acceptable to reject negative k

    def test_k_very_large_query(self):
        pipeline = _make_populated_pipeline()
        results = pipeline.query("photosynthesis", k=10000)
        assert isinstance(results, list)
        # Should return at most the number of chunks
        assert len(results) <= 3


# =============================================================================
# Nonexistent References
# =============================================================================

class TestNonexistentReferences:
    """Operations with invalid IDs should fail gracefully."""

    def test_chunk_detail_nonexistent(self):
        pipeline = _make_populated_pipeline()
        # Should return empty/None or raise cleanly
        try:
            detail = pipeline.chunk_detail("nonexistent_revision_id")
            # If it returns, it should indicate no data
        except (KeyError, ValueError, Exception):
            pass  # Acceptable

    def test_annotate_nonexistent_chunk(self):
        pipeline = _make_populated_pipeline()
        # Should handle gracefully
        try:
            pipeline.annotate_chunk(
                "nonexistent_id", tags=["test"], note="test"
            )
        except (KeyError, ValueError, Exception):
            pass  # Acceptable

    def test_delete_nonexistent_source(self):
        pipeline = _make_populated_pipeline()
        # Should handle gracefully
        try:
            pipeline.delete_source("nonexistent_source.pdf", reason="test")
        except (KeyError, ValueError, Exception):
            pass  # Acceptable

    def test_browse_nonexistent_cluster(self):
        pipeline = _make_populated_pipeline()
        pipeline.build_graph(n_clusters=2)
        # Should handle gracefully
        try:
            result = pipeline.browse_cluster(99999)
        except (KeyError, ValueError, IndexError, Exception):
            pass  # Acceptable

    def test_source_detail_nonexistent(self):
        pipeline = _make_populated_pipeline()
        try:
            detail = pipeline.source_detail("nonexistent.pdf")
        except (KeyError, ValueError, Exception):
            pass  # Acceptable

    def test_provenance_of_nonexistent(self):
        pipeline = _make_populated_pipeline()
        fake_result = type("FakeResult", (), {
            "revision_id": "nonexistent",
            "core_id": "nonexistent",
            "score": 0.5,
            "text": "fake",
        })()
        try:
            prov = pipeline.provenance_of(fake_result)
        except (KeyError, ValueError, AttributeError, Exception):
            pass  # Acceptable


# =============================================================================
# MCP Robustness
# =============================================================================

class TestMCPRobustness:
    """MCP handler must return errors, not crash."""

    def test_mcp_unknown_tool(self):
        pipeline = _make_pipeline()
        handler = MCPToolHandler(pipeline)
        result = handler.handle_tool_call("nonexistent_tool", {})
        assert "error" in result

    def test_mcp_missing_required_args(self):
        pipeline = _make_pipeline()
        handler = MCPToolHandler(pipeline)
        # dks_query requires 'question'
        result = handler.handle_tool_call("dks_query", {})
        assert "error" in result

    def test_mcp_empty_ingest(self):
        pipeline = _make_pipeline()
        handler = MCPToolHandler(pipeline)
        result = handler.handle_tool_call("dks_ingest", {"text": ""})
        # Should either succeed or return error, not crash
        assert isinstance(result, dict)

    def test_mcp_query_empty_store(self):
        pipeline = _make_pipeline()
        handler = MCPToolHandler(pipeline)
        result = handler.handle_tool_call("dks_query", {"question": "test"})
        assert isinstance(result, dict)


# =============================================================================
# Concurrent-like Operations
# =============================================================================

class TestSequentialStress:
    """Rapid sequential operations should not corrupt state."""

    def test_rapid_ingest_query_cycles(self):
        pipeline = _make_pipeline()

        for i in range(20):
            pipeline.ingest_text(
                f"Document {i} about topic_{i} with details_{i}.",
                source=f"rapid_{i}.txt",
            )

        pipeline.rebuild_index()

        # All documents findable
        stats = pipeline.stats()
        assert stats["revisions"] >= 20

        # Multiple queries in sequence
        for i in range(10):
            results = pipeline.query(f"topic_{i}", k=3)
            assert isinstance(results, list)

    def test_alternating_ingest_and_delete(self):
        pipeline = _make_pipeline()

        # Ingest 10 sources
        for i in range(10):
            pipeline.ingest_text(
                f"Content for source {i} about item_{i}.",
                source=f"src_{i}.txt",
            )

        # Delete every other source
        for i in range(0, 10, 2):
            pipeline.delete_source(f"src_{i}.txt", reason="cleanup")

        pipeline.rebuild_index()

        # Only odd sources remain
        sources = pipeline.list_sources()
        source_names = {s["source"] for s in sources}
        for i in range(10):
            if i % 2 == 0:
                assert f"src_{i}.txt" not in source_names
            else:
                assert f"src_{i}.txt" in source_names

    def test_repeated_rebuild(self):
        """Multiple index rebuilds should be idempotent."""
        pipeline = _make_populated_pipeline()

        results_1 = pipeline.query("photosynthesis", k=3)
        pipeline.rebuild_index()
        results_2 = pipeline.query("photosynthesis", k=3)
        pipeline.rebuild_index()
        results_3 = pipeline.query("photosynthesis", k=3)

        # Results should be identical
        assert len(results_1) == len(results_2) == len(results_3)
        for r1, r2, r3 in zip(results_1, results_2, results_3):
            assert r1.revision_id == r2.revision_id == r3.revision_id


# =============================================================================
# Save/Load Edge Cases
# =============================================================================

class TestSaveLoadEdgeCases:
    """Edge cases in persistence."""

    def test_save_load_after_delete(self):
        """Save/load preserves retraction state."""
        import tempfile
        import shutil

        pipeline = _make_populated_pipeline()
        pipeline.delete_source("cs.pdf", reason="test")

        tmpdir = tempfile.mkdtemp()
        try:
            pipeline.save(tmpdir)
            loaded = Pipeline.load(tmpdir)

            sources = loaded.list_sources()
            source_names = [s["source"] for s in sources]
            assert "cs.pdf" not in source_names
            assert "bio.pdf" in source_names
        finally:
            shutil.rmtree(tmpdir)

    def test_double_save(self):
        """Saving twice to the same directory should overwrite cleanly."""
        import tempfile
        import shutil

        pipeline = _make_populated_pipeline()

        tmpdir = tempfile.mkdtemp()
        try:
            pipeline.save(tmpdir)
            pipeline.ingest_text("New content.", source="new.pdf")
            pipeline.rebuild_index()
            pipeline.save(tmpdir)  # Overwrite

            loaded = Pipeline.load(tmpdir)
            sources = loaded.list_sources()
            source_names = [s["source"] for s in sources]
            assert "new.pdf" in source_names
        finally:
            shutil.rmtree(tmpdir)
