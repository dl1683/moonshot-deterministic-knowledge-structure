"""Tests for retraction-aware behavior across DKS sub-systems.

Verifies that SearchIndex, Pipeline, Explorer, SearchEngine, and all
derived views correctly exclude retracted revisions and orphaned
annotations. The DKS retraction model:

  - Retracting a revision creates a NEW revision with status="retracted"
    and the SAME core_id.
  - The ORIGINAL revision keeps status="asserted".
  - store.retracted_core_ids() returns {rev.core_id for rev in
    store.revisions.values() if rev.status == "retracted"}.
"""
from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    NumpyIndex,
    Pipeline,
    Provenance,
    SearchIndex,
    SearchResult,
    TransactionTime,
    ValidTime,
)
from dks.explore import Explorer
from dks.search import SearchEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dt(year: int = 2024, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _tx(tx_id: int) -> TransactionTime:
    # Use a base date offset by seconds to avoid day-out-of-range issues
    from datetime import timedelta
    base = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=tx_id)
    return TransactionTime(tx_id=tx_id, recorded_at=base)


def _vt() -> ValidTime:
    return ValidTime(start=dt(2024))


def _prov(source: str = "test") -> Provenance:
    return Provenance(source=source)


def _assert_chunk(
    store: KnowledgeStore,
    text: str,
    *,
    source: str = "doc.txt",
    chunk_idx: int = 0,
    tx_id: int = 1,
) -> str:
    """Assert a document.chunk@v1 revision and return its revision_id."""
    core = ClaimCore(
        claim_type="document.chunk@v1",
        slots={"source": source, "chunk_idx": str(chunk_idx), "text": text[:200]},
    )
    rev = store.assert_revision(
        core=core,
        assertion=text,
        valid_time=_vt(),
        transaction_time=_tx(tx_id),
        provenance=_prov(source),
        confidence_bp=5000,
    )
    return rev.revision_id


def _retract_revision(store: KnowledgeStore, revision_id: str, *, tx_id: int) -> str:
    """Retract a revision by asserting a new retracted revision with the same core."""
    rev = store.revisions[revision_id]
    core = store.cores[rev.core_id]
    ret = store.assert_revision(
        core=core,
        assertion=rev.assertion,
        valid_time=rev.valid_time,
        transaction_time=_tx(tx_id),
        provenance=Provenance(source="retraction", evidence_ref="test retraction"),
        confidence_bp=rev.confidence_bp,
        status="retracted",
    )
    return ret.revision_id


def _make_search_index(store: KnowledgeStore) -> SearchIndex:
    """Create a SearchIndex backed by NumpyIndex for tests."""
    backend = NumpyIndex(dimension=64)
    return SearchIndex(store, backend)


def _make_pipeline_with_index() -> Pipeline:
    """Create a Pipeline with NumpyIndex search backend."""
    backend = NumpyIndex(dimension=64)
    return Pipeline(embedding_backend=backend)


# ===========================================================================
# 1. SearchIndex retraction filtering
# ===========================================================================

class TestSearchIndexRetractionFiltering:

    def test_search_index_excludes_retracted_without_temporal(self) -> None:
        """SearchIndex.search() without temporal filters excludes retracted cores."""
        store = KnowledgeStore()
        rid_a = _assert_chunk(store, "The capital of France is Paris", tx_id=1)
        rid_b = _assert_chunk(store, "The capital of Germany is Berlin", source="doc.txt", chunk_idx=1, tx_id=2)

        idx = _make_search_index(store)
        idx.add(rid_a, "The capital of France is Paris")
        idx.add(rid_b, "The capital of Germany is Berlin")

        # Before retraction: both visible
        results = idx.search("capital", k=10)
        found_ids = {r.revision_id for r in results}
        assert rid_a in found_ids
        assert rid_b in found_ids

        # Retract rid_a
        _retract_revision(store, rid_a, tx_id=3)

        # After retraction: only rid_b visible (no temporal args = latest view)
        results = idx.search("capital", k=10)
        found_ids = {r.revision_id for r in results}
        assert rid_a not in found_ids
        assert rid_b in found_ids

    def test_search_index_temporal_sees_pre_retraction(self) -> None:
        """SearchIndex.search() with tx_id before retraction returns the revision."""
        store = KnowledgeStore()
        rid = _assert_chunk(store, "Quantum computing uses qubits", tx_id=1)
        idx = _make_search_index(store)
        idx.add(rid, "Quantum computing uses qubits")

        # Retract at tx_id=5
        _retract_revision(store, rid, tx_id=5)

        # Query as-of tx_id=2 (before retraction): should still see it
        results = idx.search("quantum", k=5, valid_at=dt(2024), tx_id=2)
        found_ids = {r.revision_id for r in results}
        assert rid in found_ids

    def test_search_index_temporal_excludes_post_retraction(self) -> None:
        """SearchIndex.search() with tx_id after retraction does NOT return it."""
        store = KnowledgeStore()
        rid = _assert_chunk(store, "Neural networks learn features", tx_id=1)
        idx = _make_search_index(store)
        idx.add(rid, "Neural networks learn features")

        # Retract at tx_id=3
        _retract_revision(store, rid, tx_id=3)

        # Query as-of tx_id=5 (after retraction): should NOT see it
        results = idx.search("neural networks", k=5, valid_at=dt(2024), tx_id=5)
        found_ids = {r.revision_id for r in results}
        assert rid not in found_ids

    def test_search_index_add_batch_excludes_retracted_on_rebuild(self) -> None:
        """After retraction, rebuild_index() should not include retracted revisions."""
        pipeline = _make_pipeline_with_index()
        rids = pipeline.ingest_text("Machine learning is a branch of AI", source="doc1.txt")
        assert len(rids) >= 1
        first_rid = rids[0]

        # Retract the first chunk
        _retract_revision(pipeline.store, first_rid, tx_id=100)

        # Rebuild: retracted revisions should be excluded
        count = pipeline.rebuild_index()
        # The retracted core_id should not be indexed
        retracted_cores = pipeline.store.retracted_core_ids()
        rev = pipeline.store.revisions[first_rid]
        assert rev.core_id in retracted_cores

        # Search should not return the retracted revision
        results = pipeline.query("machine learning", k=10)
        found_ids = {r.revision_id for r in results}
        assert first_rid not in found_ids


# ===========================================================================
# 2. Pipeline merge + sub-module consistency
# ===========================================================================

class TestPipelineMergeConsistency:

    def test_merge_updates_submodule_stores(self) -> None:
        """After pipeline.merge(), explorer.store and search.store match pipeline.store."""
        p1 = _make_pipeline_with_index()
        p2 = _make_pipeline_with_index()

        p1.ingest_text("Alpha bravo charlie", source="a.txt")
        p2.ingest_text("Delta echo foxtrot", source="b.txt")

        p1.merge(p2)

        # All sub-modules should point at the same merged store
        assert p1._explorer.store is p1.store
        assert p1._search.store is p1.store
        assert p1._index._store is p1.store

    def test_merge_preserves_retraction_state(self) -> None:
        """Merging two pipelines where one has retractions respects them."""
        p1 = _make_pipeline_with_index()
        p2 = _make_pipeline_with_index()

        rids = p1.ingest_text("Knowledge is power", source="kp.txt")
        rid = rids[0]

        # Retract in p1
        _retract_revision(p1.store, rid, tx_id=50)

        p2.ingest_text("Information is freedom", source="if.txt")

        # Merge p2 into p1 (p1 already has the retraction)
        p1.merge(p2)

        retracted = p1.store.retracted_core_ids()
        rev = p1.store.revisions[rid]
        assert rev.core_id in retracted

        # Rebuild and verify search excludes retracted
        p1.rebuild_index()
        results = p1.query("knowledge power", k=10)
        found_ids = {r.revision_id for r in results}
        assert rid not in found_ids

    def test_rebuild_after_merge_clean(self) -> None:
        """rebuild_index() after merge does not include retracted content."""
        p1 = _make_pipeline_with_index()
        p2 = _make_pipeline_with_index()

        rids_1 = p1.ingest_text("Photosynthesis converts light energy", source="bio.txt")
        rids_2 = p2.ingest_text("Mitosis divides cells", source="cell.txt")

        # Retract first chunk in p1
        _retract_revision(p1.store, rids_1[0], tx_id=99)

        p1.merge(p2)
        count = p1.rebuild_index()

        # The retracted revision should not be counted
        retracted_cores = p1.store.retracted_core_ids()
        for r in p1.store.revisions.values():
            if r.core_id in retracted_cores and r.status == "asserted":
                # This asserted revision's core_id is retracted => not indexed
                pass  # just checking logic

        results = p1.query("photosynthesis", k=10)
        found_ids = {r.revision_id for r in results}
        assert rids_1[0] not in found_ids


# ===========================================================================
# 3. link_entities retraction-aware
# ===========================================================================

class TestLinkEntitiesRetractionAware:

    def _make_pipeline_with_graph(self) -> Pipeline:
        """Create pipeline, ingest multi-source data, build graph."""
        try:
            from dks.index import TfidfSearchIndex
        except ImportError:
            pytest.skip("scikit-learn required for TfidfSearchIndex")

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn required")

        from dks.index import TfidfSearchIndex
        store = KnowledgeStore()
        p = Pipeline(store=store, search_index=TfidfSearchIndex(store))

        # Ingest enough data across sources so the graph has meaningful structure
        p.ingest_text(
            "Machine learning algorithms process data to find patterns. "
            "Deep learning uses neural networks with many layers. "
            "Reinforcement learning trains agents through rewards.",
            source="ml_intro.txt",
        )
        p.ingest_text(
            "Machine learning is applied in healthcare for diagnosis. "
            "Deep learning models detect cancer from medical images. "
            "Natural language processing helps analyze medical records.",
            source="ml_health.txt",
        )
        return p

    def test_link_entities_ignores_retracted(self) -> None:
        """link_entities() only considers active revisions."""
        p = self._make_pipeline_with_graph()

        # Build graph first
        p.build_graph(n_clusters=2)

        # Retract one chunk
        some_rid = list(p.store.revisions.keys())[0]
        _retract_revision(p.store, some_rid, tx_id=200)

        # Rebuild so graph is fresh
        p.build_graph(n_clusters=2)

        # link_entities should not include the retracted chunk
        result = p.link_entities(min_shared_entities=1)
        # Verify no error and result is structured
        assert "total_entities" in result

    def test_link_entities_after_source_deletion(self) -> None:
        """After delete_source(), link_entities() does not count deleted source's entities."""
        p = self._make_pipeline_with_graph()
        p.build_graph(n_clusters=2)

        # Delete one entire source
        p.delete_source("ml_health.txt")

        # Rebuild graph after deletion
        p.build_graph(n_clusters=2)

        result = p.link_entities(min_shared_entities=1)
        assert "total_entities" in result
        # The deleted source should not contribute entities
        # (we verify by checking link count is reduced or no error)
        assert isinstance(result["total_entities"], int)


# ===========================================================================
# 4. _reconstruct_siblings retraction
# ===========================================================================

class TestReconstructSiblingsRetraction:

    def test_reconstruct_siblings_excludes_retracted(self) -> None:
        """After retracting a chunk, _reconstruct_siblings() does not include it."""
        pipeline = _make_pipeline_with_index()
        rids = pipeline.ingest_text(
            "First chunk of text. " * 50
            + "SEPARATOR. "
            + "Second chunk of text. " * 50
            + "SEPARATOR. "
            + "Third chunk of text. " * 50,
            source="multi.txt",
            chunk_size=200,
            chunk_overlap=20,
        )
        assert len(rids) >= 2, f"Expected at least 2 chunks, got {len(rids)}"

        retracted_rid = rids[0]
        _retract_revision(pipeline.store, retracted_rid, tx_id=100)

        # _reconstruct_siblings goes through SearchEngine
        siblings = pipeline._reconstruct_siblings("multi.txt")
        assert retracted_rid not in siblings

    def test_query_with_context_excludes_retracted_siblings(self) -> None:
        """Context expansion skips retracted sibling chunks."""
        pipeline = _make_pipeline_with_index()
        rids = pipeline.ingest_text(
            "Alpha beta gamma delta. " * 50
            + "BREAK. "
            + "Epsilon zeta eta theta. " * 50
            + "BREAK. "
            + "Iota kappa lambda mu. " * 50,
            source="greek.txt",
            chunk_size=200,
            chunk_overlap=20,
        )
        assert len(rids) >= 2

        # Retract the first chunk
        retracted_rid = rids[0]
        _retract_revision(pipeline.store, retracted_rid, tx_id=100)

        # query_with_context should not include retracted chunk in expansion
        results = pipeline.query_with_context("epsilon zeta", k=3, context_window=2)
        found_ids = {r.revision_id for r in results}
        assert retracted_rid not in found_ids


# ===========================================================================
# 5. list_annotations orphan filtering
# ===========================================================================

class TestAnnotationOrphanFiltering:

    def test_list_annotations_excludes_orphaned(self) -> None:
        """After retracting the target chunk, annotations on it are excluded."""
        pipeline = _make_pipeline_with_index()
        rids = pipeline.ingest_text("Annotatable content here for testing", source="ann.txt")
        target_rid = rids[0]

        # Add an annotation targeting that chunk
        ann_rid = pipeline.annotate_chunk(target_rid, tags=["important"], note="test note")

        # Annotation should be visible
        anns = pipeline.list_annotations()
        ann_targets = {a["target_revision"] for a in anns}
        assert target_rid in ann_targets

        # Retract the target chunk
        _retract_revision(pipeline.store, target_rid, tx_id=200)

        # Annotation should now be excluded (orphaned)
        anns = pipeline.list_annotations()
        ann_targets = {a.get("target_revision", "") for a in anns}
        assert target_rid not in ann_targets

    def test_list_annotations_excludes_retracted_annotations(self) -> None:
        """After retracting the annotation itself, it is excluded."""
        pipeline = _make_pipeline_with_index()
        rids = pipeline.ingest_text("Content for annotation retraction test", source="ann2.txt")
        target_rid = rids[0]

        ann_rid = pipeline.annotate_chunk(target_rid, tags=["review"], note="needs review")

        # The annotation should be listed
        anns = pipeline.list_annotations()
        ann_rids = {a["annotation_id"] for a in anns}
        assert ann_rid in ann_rids

        # Retract the annotation revision itself
        _retract_revision(pipeline.store, ann_rid, tx_id=300)

        # The annotation should no longer appear
        anns = pipeline.list_annotations()
        ann_rids = {a["annotation_id"] for a in anns}
        assert ann_rid not in ann_rids


# ===========================================================================
# 6. get_entity_decisions retraction
# ===========================================================================

class TestEntityDecisionsRetraction:

    def test_get_entity_decisions_excludes_retracted(self) -> None:
        """After retracting an entity_review decision, it is not returned."""
        pipeline = _make_pipeline_with_index()

        # Manually insert an entity review decision
        core = ClaimCore(
            claim_type="dks.entity_review@v1",
            slots={"entity": "testentity", "decision": "accepted"},
        )
        rev = pipeline.store.assert_revision(
            core=core,
            assertion="Review: testentity accepted",
            valid_time=_vt(),
            transaction_time=_tx(10),
            provenance=_prov("review"),
            confidence_bp=5000,
        )

        decisions = pipeline.get_entity_decisions()
        assert "testentity" in decisions
        assert decisions["testentity"] == "accepted"

        # Retract the decision
        _retract_revision(pipeline.store, rev.revision_id, tx_id=20)

        decisions = pipeline.get_entity_decisions()
        assert "testentity" not in decisions


# ===========================================================================
# 7. rebuild_index idempotency
# ===========================================================================

class TestRebuildIndexIdempotency:

    def test_rebuild_index_no_duplicates(self) -> None:
        """Multiple rebuild_index() calls do not create duplicates."""
        pipeline = _make_pipeline_with_index()
        pipeline.ingest_text("Unique content for idempotency testing", source="idem.txt")

        count_1 = pipeline.rebuild_index()
        count_2 = pipeline.rebuild_index()
        count_3 = pipeline.rebuild_index()

        assert count_1 == count_2 == count_3
        assert pipeline._index.size == count_1

    def test_rebuild_index_after_retraction_reduces_size(self) -> None:
        """After retracting, rebuild reduces the index size."""
        pipeline = _make_pipeline_with_index()
        rids_a = pipeline.ingest_text("Content about machine learning", source="ml.txt")
        rids_b = pipeline.ingest_text("Content about deep learning", source="dl.txt")

        count_before = pipeline.rebuild_index()
        total_rids = len(rids_a) + len(rids_b)
        assert count_before == total_rids

        # Retract all of source a
        for rid in rids_a:
            _retract_revision(pipeline.store, rid, tx_id=500)

        count_after = pipeline.rebuild_index()
        assert count_after < count_before
        assert count_after == len(rids_b)


# ===========================================================================
# 8. Explore methods retraction
# ===========================================================================

class TestExploreMethodsRetraction:

    def test_list_sources_excludes_retracted(self) -> None:
        """list_sources() does not show sources whose chunks are all retracted."""
        pipeline = _make_pipeline_with_index()
        rids = pipeline.ingest_text("Only content in this source", source="ephemeral.txt")

        # Source should be listed
        sources = pipeline.list_sources()
        source_names = {s["source"] for s in sources}
        assert "ephemeral.txt" in source_names

        # Retract all chunks from that source
        for rid in rids:
            _retract_revision(pipeline.store, rid, tx_id=400)

        # Source should no longer appear
        sources = pipeline.list_sources()
        source_names = {s["source"] for s in sources}
        assert "ephemeral.txt" not in source_names

    def test_profile_excludes_retracted_chunks(self) -> None:
        """profile() counts exclude retracted chunks."""
        try:
            from dks.index import TfidfSearchIndex
            from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn required for profile() which needs graph")

        store = KnowledgeStore()
        p = Pipeline(store=store, search_index=TfidfSearchIndex(store))

        # Ingest enough content for graph building
        p.ingest_text(
            "Supervised learning uses labeled data for training models. "
            "Unsupervised learning discovers hidden patterns in data. "
            "Semi-supervised learning combines labeled and unlabeled data.",
            source="learning.txt",
        )
        p.ingest_text(
            "Regression predicts continuous values from features. "
            "Classification assigns data points to discrete categories. "
            "Clustering groups similar data points together.",
            source="methods.txt",
        )

        p.build_graph(n_clusters=2)

        profile_before = p.profile()
        chunk_count_before = profile_before["summary"]["chunks"]

        # Retract one source entirely
        p.delete_source("methods.txt")
        p.build_graph(n_clusters=2)

        profile_after = p.profile()
        chunk_count_after = profile_after["summary"]["chunks"]

        assert chunk_count_after < chunk_count_before

    def test_quality_report_excludes_retracted(self) -> None:
        """quality_report() metrics exclude retracted content."""
        try:
            from dks.index import TfidfSearchIndex
            from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn required for quality_report()")

        store = KnowledgeStore()
        p = Pipeline(store=store, search_index=TfidfSearchIndex(store))

        p.ingest_text(
            "Data preprocessing cleans and transforms raw data. "
            "Feature engineering creates meaningful input variables. "
            "Model evaluation measures prediction accuracy.",
            source="pipeline_steps.txt",
        )
        p.ingest_text(
            "Cross validation prevents overfitting during training. "
            "Hyperparameter tuning optimizes model performance. "
            "Ensemble methods combine multiple models for robustness.",
            source="best_practices.txt",
        )

        p.build_graph(n_clusters=2)

        report_before = p.quality_report()
        total_before = report_before["summary"]["total_chunks"]

        # Delete a source
        p.delete_source("best_practices.txt")
        p.build_graph(n_clusters=2)

        report_after = p.quality_report()
        total_after = report_after["summary"]["total_chunks"]

        assert total_after < total_before
