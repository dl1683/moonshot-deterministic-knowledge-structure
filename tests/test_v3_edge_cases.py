"""Edge-case tests from Codex Phase 7 review — zero prior coverage.

Covers: non-numeric page_start, empty page_start, stale graph after merge,
graph rebuild after merge, single-document graph, empty-store graph,
empty assertion ingestion, zero-length text ingestion, unicode edge cases
in search, duplicate ingest of same source, delete of nonexistent source,
and retracted_core_ids cache invalidation.
"""

from datetime import datetime, timezone, timedelta

import pytest

from dks import (
    KnowledgeStore,
    ClaimCore,
    ValidTime,
    TransactionTime,
    Provenance,
    Pipeline,
    KnowledgeGraph,
    TfidfSearchIndex,
)


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_pipeline():
    """Create a TF-IDF-backed pipeline (no embedding model needed)."""
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


# ---------------------------------------------------------------------------
# 1. Non-numeric page_start in list_sources
# ---------------------------------------------------------------------------

class TestListSourcesPageStartEdgeCases:
    def test_list_sources_with_non_numeric_page_start(self):
        """A revision with page_start='intro' must not crash list_sources."""
        store = KnowledgeStore()
        core = ClaimCore(
            claim_type="document.chunk@v1",
            slots={"source": "test.txt", "page_start": "intro"},
        )
        store.assert_revision(
            core=core,
            assertion="Some text with a non-numeric page marker.",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="test.txt"),
            confidence_bp=8000,
            status="asserted",
        )
        pipeline = Pipeline(store=store)

        sources = pipeline._explorer.list_sources()

        assert len(sources) == 1
        assert sources[0]["source"] == "test.txt"
        assert sources[0]["chunks"] == 1
        # Non-numeric page cannot be converted, so page_range falls back
        assert sources[0]["page_range"] == "unknown"
        assert sources[0]["total_pages"] == 0

    # -------------------------------------------------------------------
    # 2. Empty page_start in list_sources
    # -------------------------------------------------------------------
    def test_list_sources_with_empty_page_start(self):
        """A revision with page_start='' must not crash list_sources."""
        store = KnowledgeStore()
        core = ClaimCore(
            claim_type="document.chunk@v1",
            slots={"source": "empty_page.txt", "page_start": ""},
        )
        store.assert_revision(
            core=core,
            assertion="Text with an empty page_start slot.",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="empty_page.txt"),
            confidence_bp=8000,
            status="asserted",
        )
        pipeline = Pipeline(store=store)

        sources = pipeline._explorer.list_sources()

        assert len(sources) == 1
        assert sources[0]["source"] == "empty_page.txt"
        assert sources[0]["page_range"] == "unknown"
        assert sources[0]["total_pages"] == 0


# ---------------------------------------------------------------------------
# 3. Stale graph after merge raises ValueError
# ---------------------------------------------------------------------------

class TestStaleGraphAfterMerge:
    def test_stale_graph_after_merge_raises(self):
        """After merge, graph-dependent methods must raise ValueError."""
        sklearn = pytest.importorskip("sklearn")

        p1 = _make_pipeline()
        p1.ingest_text(
            "Quantum mechanics describes behavior of particles at atomic scales. "
            "Wave functions encode probability amplitudes for measurement outcomes.",
            source="physics.txt",
        )
        p1.rebuild_index()
        p1.build_graph(n_clusters=1)

        # Confirm graph works before merge
        assert p1.topics() is not None

        p2 = _make_pipeline()
        p2.ingest_text(
            "General relativity describes gravity as curvature of spacetime.",
            source="relativity.txt",
        )

        p1.merge(p2)

        # Graph was invalidated by merge — all graph-dependent methods must raise
        with pytest.raises(ValueError, match="Graph not built"):
            p1.neighbors("fake-id")

        with pytest.raises(ValueError, match="Graph not built"):
            p1.topics()

        with pytest.raises(ValueError, match="Graph not built"):
            p1.topic_chunks(0)

        with pytest.raises(ValueError, match="Graph not built"):
            p1.profile()


# ---------------------------------------------------------------------------
# 4. Graph rebuild after merge works
# ---------------------------------------------------------------------------

class TestGraphRebuildAfterMerge:
    def test_graph_rebuild_after_merge_works(self):
        """After merge, rebuild_index + build_graph restores graph with merged data."""
        sklearn = pytest.importorskip("sklearn")

        p1 = _make_pipeline()
        p1.ingest_text(
            "Photosynthesis converts sunlight into chemical energy in plants. "
            "Chloroplasts contain chlorophyll that absorbs light for this process.",
            source="biology.txt",
        )
        p1.rebuild_index()
        p1.build_graph(n_clusters=1)

        p2 = _make_pipeline()
        p2.ingest_text(
            "Cellular respiration converts glucose into ATP in mitochondria. "
            "This process requires oxygen and produces carbon dioxide as waste.",
            source="biochemistry.txt",
        )

        p1.merge(p2)

        # Rebuild after merge
        indexed = p1.rebuild_index()
        assert indexed >= 2  # chunks from both pipelines

        graph = p1.build_graph(n_clusters=1)
        assert graph is not None
        # With n_clusters=1, all chunks land in one cluster.
        # total_nodes counts adjacency entries: nodes that have at least one
        # neighbor above the similarity threshold.  With 2+ chunks in one
        # cluster, adjacency is populated when any pair exceeds the threshold.
        assert graph.total_clusters >= 1

        # Graph-dependent methods must work without raising
        topics = p1.topics()
        assert len(topics) >= 1


# ---------------------------------------------------------------------------
# 5. Build graph with a single document
# ---------------------------------------------------------------------------

class TestBuildGraphSingleDocument:
    def test_build_graph_with_single_document(self):
        """Ingesting only ONE document then building graph must not crash."""
        sklearn = pytest.importorskip("sklearn")

        pipeline = _make_pipeline()
        pipeline.ingest_text(
            "A single document about neural networks and deep learning.",
            source="single.txt",
        )
        pipeline.rebuild_index()

        # Should not crash even with a single document
        graph = pipeline.build_graph(n_clusters=1)

        assert graph is not None
        # A single chunk in a cluster has no neighbors, so total_nodes
        # (adjacency count) is 0.  But the cluster itself must exist.
        assert graph.total_clusters >= 1

        topics = pipeline.topics()
        assert len(topics) >= 1
        # The single document should be assigned to a cluster (even with
        # no adjacency edges, topic_chunks returns it).
        members_found = False
        for topic in topics:
            chunks = pipeline.topic_chunks(topic["cluster_id"])
            if len(chunks) > 0:
                members_found = True
        assert members_found


# ---------------------------------------------------------------------------
# 6. Build graph with empty store
# ---------------------------------------------------------------------------

class TestBuildGraphEmptyStore:
    def test_build_graph_with_empty_store(self):
        """Empty pipeline attempting build_graph should handle gracefully."""
        sklearn = pytest.importorskip("sklearn")

        pipeline = _make_pipeline()
        pipeline.rebuild_index()

        # Empty store: build_graph may raise or produce empty graph.
        # Either behavior is acceptable — it must not crash with an
        # unhandled exception like IndexError or ZeroDivisionError.
        try:
            graph = pipeline.build_graph(n_clusters=1)
            # If it succeeds, the graph should be empty
            assert graph.total_nodes == 0
        except (ValueError, RuntimeError):
            # Acceptable: the implementation may choose to raise
            pass


# ---------------------------------------------------------------------------
# 7. Empty assertion ingestion
# ---------------------------------------------------------------------------

class TestEmptyAssertionIngestion:
    def test_empty_assertion_ingestion(self):
        """Ingesting text with an empty assertion via raw store must not crash."""
        store = KnowledgeStore()
        core = ClaimCore(
            claim_type="document.chunk@v1",
            slots={"source": "empty_assert.txt", "chunk_idx": "0", "text": ""},
        )
        revision = store.assert_revision(
            core=core,
            assertion="",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="empty_assert.txt"),
            confidence_bp=5000,
            status="asserted",
        )

        assert revision is not None
        assert revision.assertion == ""
        assert revision.revision_id in store.revisions


# ---------------------------------------------------------------------------
# 8. Zero-length text ingestion
# ---------------------------------------------------------------------------

class TestZeroLengthTextIngestion:
    def test_zero_length_text_ingestion(self):
        """pipeline.ingest_text('') should handle gracefully (return empty list)."""
        pipeline = _make_pipeline()

        result = pipeline.ingest_text("", source="empty.txt")

        # Empty text should produce no revisions
        assert result == []
        assert len(pipeline.store.revisions) == 0

    def test_whitespace_only_text_ingestion(self):
        """pipeline.ingest_text('   ') should also return empty list."""
        pipeline = _make_pipeline()

        result = pipeline.ingest_text("   \n\t  ", source="whitespace.txt")

        assert result == []


# ---------------------------------------------------------------------------
# 9. Unicode edge cases in search
# ---------------------------------------------------------------------------

class TestUnicodeEdgeCasesInSearch:
    def test_unicode_edge_cases_in_search(self):
        """Ingest text with combining characters, zero-width spaces, RTL marks,
        and emoji — search should handle all gracefully without crashes."""
        pipeline = _make_pipeline()

        # Combining characters (e with combining acute accent)
        pipeline.ingest_text(
            "The caf\u0065\u0301 serves excellent coffee every morning.",
            source="unicode_combining.txt",
        )

        # Zero-width spaces and zero-width joiners
        pipeline.ingest_text(
            "Zero\u200bwidth\u200bspaces\u200bare\u200binvisible characters in text.",
            source="unicode_zwsp.txt",
        )

        # RTL marks (right-to-left mark U+200F)
        pipeline.ingest_text(
            "Text with \u200Fright-to-left\u200F marks embedded within.",
            source="unicode_rtl.txt",
        )

        # Emoji
        pipeline.ingest_text(
            "Machine learning is fascinating \U0001f916 and AI is the future \U0001f680.",
            source="unicode_emoji.txt",
        )

        pipeline.rebuild_index()

        # All queries should complete without crashing
        r1 = pipeline.query("coffee")
        assert isinstance(r1, list)

        r2 = pipeline.query("invisible characters")
        assert isinstance(r2, list)

        r3 = pipeline.query("right to left")
        assert isinstance(r3, list)

        r4 = pipeline.query("machine learning")
        assert isinstance(r4, list)


# ---------------------------------------------------------------------------
# 10. Duplicate ingest of same source
# ---------------------------------------------------------------------------

class TestDuplicateIngestSameSource:
    def test_duplicate_ingest_same_source(self):
        """Ingesting the same text with the same source twice must not crash
        and revisions should accumulate."""
        pipeline = _make_pipeline()

        text = "Neural networks learn representations from data through backpropagation."
        source = "duplicate.txt"

        ids1 = pipeline.ingest_text(text, source=source)
        ids2 = pipeline.ingest_text(text, source=source)

        assert len(ids1) > 0
        assert len(ids2) > 0

        # Total revisions should be the sum of both ingestions
        total_revisions = len(pipeline.store.revisions)
        assert total_revisions == len(ids1) + len(ids2)

        # All revision IDs should be unique
        all_ids = ids1 + ids2
        assert len(set(all_ids)) == len(all_ids)


# ---------------------------------------------------------------------------
# 11. Delete nonexistent source
# ---------------------------------------------------------------------------

class TestDeleteNonexistentSource:
    def test_delete_nonexistent_source(self):
        """Deleting a source that does not exist must not crash and return 0 retracted."""
        pipeline = _make_pipeline()

        # Ingest something unrelated to make sure the store is not empty
        pipeline.ingest_text("Some real content here.", source="real.txt")

        result = pipeline.delete_source("nonexistent.txt")

        assert result["retracted_count"] == 0
        assert result["source"] == "nonexistent.txt"

    def test_delete_nonexistent_source_from_empty_store(self):
        """Deleting from a completely empty store must not crash."""
        pipeline = _make_pipeline()

        result = pipeline.delete_source("ghost.txt")

        assert result["retracted_count"] == 0


# ---------------------------------------------------------------------------
# 12. Retracted core_ids cache invalidation
# ---------------------------------------------------------------------------

class TestRetractedCoreIdsCacheInvalidation:
    def test_retracted_core_ids_cache_invalidation(self):
        """Verify the retracted_core_ids cache updates correctly through
        the assert -> retract -> assert lifecycle."""
        store = KnowledgeStore()
        vt = ValidTime(start=dt(2024), end=None)

        # Step 1: Assert a revision
        core1 = ClaimCore(
            claim_type="document.chunk@v1",
            slots={"source": "cache_test.txt", "chunk_idx": "0", "text": "first"},
        )
        rev1 = store.assert_revision(
            core=core1,
            assertion="First claim for cache testing.",
            valid_time=vt,
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="cache_test.txt"),
            confidence_bp=8000,
            status="asserted",
        )

        # Cache should show no retractions
        retracted = store.retracted_core_ids()
        assert rev1.core_id not in retracted
        assert len(retracted) == 0

        # Step 2: Retract it
        store.assert_revision(
            core=core1,
            assertion="First claim for cache testing.",
            valid_time=vt,
            transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 2)),
            provenance=Provenance(source="cache_test.txt"),
            confidence_bp=8000,
            status="retracted",
        )

        # Cache must now include the retracted core_id
        retracted = store.retracted_core_ids()
        assert rev1.core_id in retracted
        assert len(retracted) == 1

        # Step 3: Assert a second, different claim
        core2 = ClaimCore(
            claim_type="document.chunk@v1",
            slots={"source": "cache_test.txt", "chunk_idx": "1", "text": "second"},
        )
        rev2 = store.assert_revision(
            core=core2,
            assertion="Second claim for cache testing.",
            valid_time=vt,
            transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 3)),
            provenance=Provenance(source="cache_test.txt"),
            confidence_bp=8000,
            status="asserted",
        )

        # Cache should still show core1 retracted, core2 not retracted
        retracted = store.retracted_core_ids()
        assert rev1.core_id in retracted
        assert rev2.core_id not in retracted
        assert len(retracted) == 1
