"""Tests for search index dirty flag — auto-rebuild after retraction.

Verifies that the search index automatically rebuilds when queries
are made after retraction operations, ensuring IDF calculations
reflect the current corpus state.
"""
from __future__ import annotations

from dks import KnowledgeStore, Pipeline, TfidfSearchIndex


def _make_pipeline():
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


class TestIndexDirtyFlag:

    def test_index_starts_clean(self):
        """Index starts as not dirty."""
        pipe = _make_pipeline()
        assert pipe._index_dirty is False

    def test_delete_source_sets_dirty(self):
        """delete_source should mark index as dirty."""
        pipe = _make_pipeline()
        pipe.ingest_text("Alpha beta gamma content", source="test_source")
        pipe.rebuild_index()
        assert pipe._index_dirty is False

        pipe.delete_source("test_source")
        assert pipe._index_dirty is True

    def test_delete_cluster_sets_dirty(self):
        """delete_cluster should mark index as dirty."""
        pipe = _make_pipeline()
        pipe.ingest_text("Delta epsilon zeta topic A", source="a")
        pipe.ingest_text("Eta theta iota topic B", source="b")
        pipe.rebuild_index()
        pipe.build_graph(n_clusters=1)
        assert pipe._index_dirty is False

        pipe.delete_cluster(0, reason="test")
        assert pipe._index_dirty is True

    def test_rebuild_clears_dirty(self):
        """rebuild_index should clear the dirty flag."""
        pipe = _make_pipeline()
        pipe.ingest_text("Some content here", source="test")
        pipe.rebuild_index()
        pipe.delete_source("test")
        assert pipe._index_dirty is True

        pipe.rebuild_index()
        assert pipe._index_dirty is False

    def test_query_auto_rebuilds_after_retraction(self):
        """query() should auto-rebuild index after retraction."""
        pipe = _make_pipeline()
        pipe.ingest_text("Alpha beta gamma about topic one", source="keep")
        pipe.ingest_text("Delta epsilon zeta about topic two", source="remove")
        pipe.rebuild_index()

        # Delete one source
        pipe.delete_source("remove")
        assert pipe._index_dirty is True

        # Query should auto-rebuild and return results from remaining source
        results = pipe.query("alpha beta gamma topic")
        assert pipe._index_dirty is False
        assert len(results) >= 1

    def test_retracted_source_not_in_results_after_auto_rebuild(self):
        """After delete_source + query, retracted content should be gone."""
        pipe = _make_pipeline()
        pipe.ingest_text("Machine learning uses gradient descent", source="ml_book")
        pipe.ingest_text("Quantum computing uses qubits and superposition", source="quantum_book")
        pipe.rebuild_index()

        # Verify both are searchable
        ml_results = pipe.query("machine learning gradient")
        assert len(ml_results) >= 1

        # Delete quantum source
        pipe.delete_source("quantum_book")

        # Query for quantum should return nothing (auto-rebuild happens)
        quantum_results = pipe.query("quantum computing qubits")
        assert len(quantum_results) == 0

        # ML content should still be findable
        ml_results2 = pipe.query("machine learning gradient")
        assert len(ml_results2) >= 1

    def test_no_auto_rebuild_when_clean(self):
        """query() should NOT rebuild when index is not dirty."""
        pipe = _make_pipeline()
        pipe.ingest_text("Some content for testing", source="test")
        pipe.rebuild_index()

        # Index is clean — query should NOT trigger rebuild
        assert pipe._index_dirty is False
        results = pipe.query("content testing")
        assert pipe._index_dirty is False
        assert len(results) >= 1

    def test_delete_source_no_match_doesnt_set_dirty(self):
        """Deleting a nonexistent source shouldn't set dirty."""
        pipe = _make_pipeline()
        pipe.ingest_text("Some content", source="real_source")
        pipe.rebuild_index()

        result = pipe.delete_source("nonexistent_source")
        # If nothing was retracted, dirty should stay False
        if result.get("retracted_count", 0) == 0:
            assert pipe._index_dirty is False
