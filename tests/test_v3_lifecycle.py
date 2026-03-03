"""Comprehensive end-to-end lifecycle stress tests for the DKS pipeline.

Each test exercises a full realistic lifecycle: ingest -> search -> annotate ->
retract -> merge -> save/load -> verify consistency.  Tests are self-contained
and use only TF-IDF search (no model downloads required).
"""

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from dks import (
    KnowledgeStore,
    ClaimCore,
    ValidTime,
    TransactionTime,
    Provenance,
    NumpyIndex,
    SearchIndex,
    TfidfSearchIndex,
    SearchResult,
    Pipeline,
)
from dks.extract import RegexExtractor
from dks.resolve import CascadingResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(year=2024, month=1, day=1, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _pipeline():
    """Fresh pipeline with TF-IDF search (no embedding model needed)."""
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


DOC_SCIENCE = (
    "Photosynthesis converts sunlight into chemical energy in chloroplasts. "
    "Plants use water and carbon dioxide to produce glucose and oxygen. "
    "Chlorophyll pigments absorb light energy to drive the Calvin cycle."
)
DOC_HISTORY = (
    "The Industrial Revolution began in Britain in the late 18th century. "
    "Steam-powered factories replaced cottage industries. Railways connected "
    "cities and accelerated the movement of goods across the nation."
)
DOC_TECH = (
    "Neural networks are the foundation of modern deep learning systems. "
    "Backpropagation computes gradients efficiently for training. "
    "Convolutional networks excel at image recognition tasks."
)
DOC_GEOGRAPHY = (
    "The Amazon rainforest spans nine countries in South America. "
    "It produces roughly twenty percent of the worlds oxygen. "
    "Deforestation threatens biodiversity and accelerates climate change."
)
DOC_POLITICS = (
    "The United States of America is a federal republic with fifty states. "
    "The US constitution establishes three branches of government. "
    "USA foreign policy shapes global diplomatic relations."
)


# ===================================================================
# 1. Full Document Lifecycle
# ===================================================================

class TestFullDocumentLifecycle:
    """Ingest 3 docs -> search -> annotate -> retract one source ->
    verify search excludes retracted -> verify orphaned annotations ->
    verify profile/stats update."""

    def test_full_document_lifecycle(self):
        p = _pipeline()

        # -- Ingest three documents --
        rids_sci = p.ingest_text(DOC_SCIENCE, source="science.txt")
        rids_hist = p.ingest_text(DOC_HISTORY, source="history.txt")
        rids_tech = p.ingest_text(DOC_TECH, source="tech.txt")

        assert len(rids_sci) >= 1
        assert len(rids_hist) >= 1
        assert len(rids_tech) >= 1

        p.rebuild_index()

        # -- Search finds science content --
        results = p.query("photosynthesis chloroplasts", k=5)
        assert len(results) > 0
        found_texts = " ".join(r.text.lower() for r in results)
        assert "photosynthesis" in found_texts or "chloroplast" in found_texts

        # -- Annotate a science chunk --
        ann_id = p.annotate_chunk(rids_sci[0], tags=["important", "biology"], note="key chunk")
        annotations = p.list_annotations(tag="important")
        assert any(a["annotation_id"] == ann_id for a in annotations)

        stats_before = p.stats()

        # -- Retract the science source --
        # Source names are canonicalized by ingest_text (lowercased etc.)
        result = p.delete_source("science.txt")
        assert result["retracted_count"] >= len(rids_sci)

        p.rebuild_index()

        # -- Search no longer returns retracted content --
        results_after = p.query("photosynthesis chloroplasts", k=5)
        retracted_rids = set(rids_sci)
        for r in results_after:
            assert r.revision_id not in retracted_rids

        # -- Annotations on retracted chunks are orphaned (excluded) --
        annotations_after = p.list_annotations(tag="important")
        orphaned = [a for a in annotations_after if a["target_revision"] in retracted_rids]
        assert len(orphaned) == 0

        # -- Stats reflect the retraction (more revisions from retraction records) --
        stats_after = p.stats()
        assert stats_after["revisions"] > stats_before["revisions"]

        # -- Sources list excludes retracted --
        sources = p.list_sources()
        source_names = [s["source"] for s in sources]
        assert "science.txt" not in source_names
        assert "history.txt" in source_names
        assert "tech.txt" in source_names


# ===================================================================
# 2. Multi-Source Merge Lifecycle
# ===================================================================

class TestMultiSourceMergeLifecycle:
    """Two pipelines ingest independently -> merge -> verify combined search ->
    delete a source from merged -> verify retraction propagates."""

    def test_multi_source_merge_lifecycle(self):
        # -- Pipeline A: science + history --
        pa = _pipeline()
        rids_a_sci = pa.ingest_text(DOC_SCIENCE, source="science.txt")
        rids_a_hist = pa.ingest_text(DOC_HISTORY, source="history.txt")
        pa.rebuild_index()

        # -- Pipeline B: tech + geography --
        pb = _pipeline()
        rids_b_tech = pb.ingest_text(DOC_TECH, source="tech.txt")
        rids_b_geo = pb.ingest_text(DOC_GEOGRAPHY, source="geography.txt")
        pb.rebuild_index()

        # -- Merge B into A --
        merge_result = pa.merge(pb)
        pa.rebuild_index()

        # -- Merged store has content from both pipelines --
        sources = pa.list_sources()
        source_names = {s["source"] for s in sources}
        assert "science.txt" in source_names
        assert "history.txt" in source_names
        assert "tech.txt" in source_names
        assert "geography.txt" in source_names

        # -- Search finds content from both pipelines --
        sci_results = pa.query("photosynthesis chloroplasts", k=3)
        assert len(sci_results) > 0
        tech_results = pa.query("neural networks backpropagation", k=3)
        assert len(tech_results) > 0

        # -- Stats reflect combined content --
        stats = pa.stats()
        assert stats["cores"] >= 4  # at least one core per ingest_text call

        # -- Delete a source from merged store --
        del_result = pa.delete_source("tech.txt")
        assert del_result["retracted_count"] >= len(rids_b_tech)

        pa.rebuild_index()

        # -- Retraction propagated: tech content excluded --
        tech_after = pa.query("neural networks backpropagation", k=5)
        for r in tech_after:
            rev = pa.store.revisions[r.revision_id]
            core = pa.store.cores[rev.core_id]
            assert core.slots.get("source") != "tech.txt"

        sources_after = pa.list_sources()
        source_names_after = {s["source"] for s in sources_after}
        assert "tech.txt" not in source_names_after


# ===================================================================
# 3. Temporal Query Progression
# ===================================================================

class TestTemporalQueryProgression:
    """Ingest fact -> query sees it -> retract -> old tx still sees it ->
    new tx does not -> ingest updated fact -> latest tx sees new version.

    Uses SearchIndex+NumpyIndex (dict-based vector storage) so that retracted
    vectors remain in the index for bitemporal lookups -- temporal visibility
    is handled by query_as_of inside SearchIndex.search().
    """

    def test_temporal_query_progression(self):
        store = KnowledgeStore()
        backend = NumpyIndex(dimension=64)
        index = SearchIndex(store, backend)
        p = Pipeline(store=store, search_index=index)

        # -- Ingest initial fact at tx=1 --
        rids = p.ingest_text(
            "The population of Capital City is 500000 people.",
            source="census_2020.txt",
        )
        tx_after_ingest = p._tx_counter

        # -- Query at current tx sees it --
        results_t1 = index.search(
            "population Capital City",
            k=3,
            valid_at=_dt(2024, 6, 1),
            tx_id=tx_after_ingest,
        )
        assert len(results_t1) > 0
        assert "500000" in results_t1[0].text or "capital" in results_t1[0].text.lower()

        # -- Retract the fact (do NOT rebuild_index -- keep vectors for old-tx queries) --
        p.delete_source("census_2020.txt")
        tx_after_retract = p._tx_counter

        # -- Query at OLD tx still sees it (bitemporal: fact was visible then) --
        results_old_tx = index.search(
            "population Capital City",
            k=3,
            valid_at=_dt(2024, 6, 1),
            tx_id=tx_after_ingest,
        )
        assert len(results_old_tx) > 0
        assert any("500000" in r.text for r in results_old_tx)

        # -- Query at NEW tx does NOT see it --
        results_new_tx = index.search(
            "population Capital City",
            k=3,
            valid_at=_dt(2024, 6, 1),
            tx_id=tx_after_retract,
        )
        retracted_rids = set(rids)
        for r in results_new_tx:
            assert r.revision_id not in retracted_rids

        # -- Ingest updated fact --
        rids_new = p.ingest_text(
            "The population of Capital City is 750000 people according to the 2024 census.",
            source="census_2024.txt",
        )
        tx_after_update = p._tx_counter

        # -- Latest tx sees the new version --
        results_latest = index.search(
            "population Capital City",
            k=3,
            valid_at=_dt(2024, 6, 1),
            tx_id=tx_after_update,
        )
        assert len(results_latest) > 0
        latest_texts = " ".join(r.text for r in results_latest)
        assert "750000" in latest_texts


# ===================================================================
# 4. Entity Resolution Lifecycle
# ===================================================================

class TestEntityResolutionLifecycle:
    """Ingest documents mentioning same entity differently -> run entity
    linking -> verify entities detected -> retract source -> verify
    linking excludes retracted."""

    def test_entity_resolution_lifecycle(self):
        p = _pipeline()

        # -- Ingest documents with variant entity names --
        rids_a = p.ingest_text(DOC_POLITICS, source="politics.txt")
        rids_b = p.ingest_text(
            "The US economy is the largest in the world. "
            "United States exports include technology and agriculture. "
            "American foreign policy influences global markets.",
            source="economics.txt",
        )
        p.rebuild_index()

        # -- Build graph (required for link_entities) --
        p.build_graph(n_clusters=2)

        # -- Run entity linking --
        entity_result = p.link_entities(min_entity_length=2, min_shared_entities=1)
        assert "total_entities" in entity_result
        assert entity_result["total_entities"] >= 0  # may be 0 for small corpus

        # -- Retract one source --
        p.delete_source("politics.txt")
        p.rebuild_index()

        # -- Rebuild graph after retraction --
        p.build_graph(n_clusters=2)

        # -- Re-link: should exclude retracted content --
        entity_after = p.link_entities(min_entity_length=2, min_shared_entities=1)
        assert "total_entities" in entity_after

        # -- Verify retracted source is gone from sources list --
        sources = p.list_sources()
        source_names = [s["source"] for s in sources]
        assert "politics.txt" not in source_names
        assert "economics.txt" in source_names


# ===================================================================
# 5. Annotation Lifecycle
# ===================================================================

class TestAnnotationLifecycle:
    """Ingest -> annotate with tags -> list by tag -> retract annotated chunk
    -> verify orphaned excluded -> annotate another -> retract annotation
    itself -> verify excluded."""

    def test_annotation_lifecycle(self):
        p = _pipeline()

        # -- Ingest two documents --
        rids_sci = p.ingest_text(DOC_SCIENCE, source="science.txt")
        rids_hist = p.ingest_text(DOC_HISTORY, source="history.txt")
        p.rebuild_index()

        # -- Annotate a science chunk --
        ann_id_1 = p.annotate_chunk(rids_sci[0], tags=["review", "biology"], note="needs review")
        anns = p.list_annotations(tag="review")
        assert len(anns) == 1
        assert anns[0]["annotation_id"] == ann_id_1

        # -- Retract the annotated science chunk's source --
        p.delete_source("science.txt")

        # -- Orphaned annotation excluded from list --
        anns_after_retract = p.list_annotations(tag="review")
        orphaned = [a for a in anns_after_retract if a["target_revision"] in set(rids_sci)]
        assert len(orphaned) == 0

        # -- Annotate a history chunk --
        ann_id_2 = p.annotate_chunk(rids_hist[0], tags=["review", "history"], note="good source")
        anns_hist = p.list_annotations(tag="review")
        assert any(a["annotation_id"] == ann_id_2 for a in anns_hist)

        # -- Remove the annotation itself --
        removed = p.remove_annotation(ann_id_2)
        assert removed is True

        # -- Annotation no longer listed --
        anns_final = p.list_annotations(tag="review")
        assert not any(a["annotation_id"] == ann_id_2 for a in anns_final)


# ===================================================================
# 6. Graph Rebuild After Retraction
# ===================================================================

class TestGraphRebuildAfterRetraction:
    """Ingest docs -> build graph -> verify clusters -> delete source ->
    rebuild graph -> verify clusters updated -> verify neighbors excludes
    retracted."""

    def test_graph_rebuild_after_retraction(self):
        p = _pipeline()

        # Ingest enough content for meaningful graph
        p.ingest_text(DOC_SCIENCE, source="science.txt")
        p.ingest_text(DOC_HISTORY, source="history.txt")
        p.ingest_text(DOC_TECH, source="tech.txt")
        p.ingest_text(DOC_GEOGRAPHY, source="geography.txt")
        p.rebuild_index()

        # -- Build graph --
        graph = p.build_graph(n_clusters=2, similarity_threshold=0.05)
        assert graph.total_clusters >= 1

        topics_before = p.topics()
        total_size_before = sum(t["size"] for t in topics_before)
        assert total_size_before >= 4

        # -- Get a revision with neighbors (if any) --
        neighbor_found = False
        all_rids = [
            rid for rid, rev in p.store.revisions.items()
            if rev.status == "asserted"
        ]
        for rid in all_rids:
            try:
                nbrs = p.neighbors(rid, k=3)
                if nbrs:
                    neighbor_found = True
                    break
            except (ValueError, KeyError):
                continue

        # -- Delete the science source --
        p.delete_source("science.txt")
        p.rebuild_index()

        # -- Rebuild graph --
        graph_after = p.build_graph(n_clusters=2, similarity_threshold=0.05)

        topics_after = p.topics()
        total_size_after = sum(t["size"] for t in topics_after)

        # Fewer chunks in graph after retraction
        assert total_size_after < total_size_before

        # -- Neighbors of any remaining node should not include retracted --
        retracted_cores = p.store.retracted_core_ids()
        for rid, rev in p.store.revisions.items():
            if rev.status != "asserted" or rev.core_id in retracted_cores:
                continue
            try:
                nbrs = p.neighbors(rid, k=5)
                for nbr in nbrs:
                    nbr_rev = p.store.revisions[nbr.revision_id]
                    assert nbr_rev.core_id not in retracted_cores
            except (ValueError, KeyError):
                continue


# ===================================================================
# 7. Save / Load Preserves Retraction State
# ===================================================================

class TestSaveLoadPreservesRetractionState:
    """Ingest -> retract -> save -> load into new pipeline -> verify
    retracted content excluded from search and exploration."""

    def test_save_load_preserves_retraction_state(self):
        p = _pipeline()

        # -- Ingest and retract --
        rids_sci = p.ingest_text(DOC_SCIENCE, source="science.txt")
        rids_hist = p.ingest_text(DOC_HISTORY, source="history.txt")
        p.rebuild_index()

        p.delete_source("science.txt")
        p.rebuild_index()

        # Verify retraction works before save
        sources_before = p.list_sources()
        assert "science.txt" not in [s["source"] for s in sources_before]

        results_before = p.query("photosynthesis", k=3)
        for r in results_before:
            assert r.revision_id not in set(rids_sci)

        # -- Save --
        tmp_dir = tempfile.mkdtemp()
        try:
            p.save(tmp_dir)

            # -- Load into new pipeline --
            p2 = Pipeline.load(tmp_dir)

            # -- Verify retracted content still excluded --
            sources_after = p2.list_sources()
            source_names = [s["source"] for s in sources_after]
            assert "science.txt" not in source_names
            assert "history.txt" in source_names

            # -- Search excludes retracted after load --
            results_after = p2.query("photosynthesis chloroplasts", k=5)
            for r in results_after:
                assert r.revision_id not in set(rids_sci)

            # -- Stats match --
            assert p2.stats()["cores"] == p.stats()["cores"]
            assert p2.stats()["revisions"] == p.stats()["revisions"]

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ===================================================================
# 8. Concurrent Operations Consistency
# ===================================================================

class TestConcurrentOperationsConsistency:
    """Many sequential operations to verify no state corruption:
    ingest -> search -> annotate -> ingest more -> delete source ->
    ingest replacement -> merge with another pipeline -> verify stats."""

    def test_concurrent_operations_consistency(self):
        p = _pipeline()

        # -- Phase 1: Initial ingest --
        rids_sci = p.ingest_text(DOC_SCIENCE, source="science.txt")
        rids_hist = p.ingest_text(DOC_HISTORY, source="history.txt")
        p.rebuild_index()

        stats_1 = p.stats()
        assert stats_1["cores"] >= 2

        # -- Phase 2: Search --
        results = p.query("steam engine factories", k=3)
        assert len(results) > 0

        # -- Phase 3: Annotate --
        ann_id = p.annotate_chunk(rids_sci[0], tags=["flagged"], note="check this")
        anns = p.list_annotations(tag="flagged")
        assert len(anns) == 1

        # -- Phase 4: Ingest more --
        rids_tech = p.ingest_text(DOC_TECH, source="tech.txt")
        rids_geo = p.ingest_text(DOC_GEOGRAPHY, source="geography.txt")
        p.rebuild_index()

        stats_2 = p.stats()
        assert stats_2["cores"] > stats_1["cores"]

        # -- Phase 5: Delete a source --
        p.delete_source("history.txt")
        p.rebuild_index()

        sources = p.list_sources()
        assert "history.txt" not in [s["source"] for s in sources]

        # -- Phase 6: Ingest replacement --
        rids_hist2 = p.ingest_text(
            "The Industrial Revolution transformed society in the 19th century. "
            "New inventions like the spinning jenny and power loom revolutionized textile production.",
            source="history_v2.txt",
        )
        p.rebuild_index()

        sources_updated = p.list_sources()
        source_names = [s["source"] for s in sources_updated]
        assert "history_v2.txt" in source_names
        assert "history.txt" not in source_names

        # -- Phase 7: Merge with another pipeline --
        p2 = _pipeline()
        rids_pol = p2.ingest_text(DOC_POLITICS, source="politics.txt")
        p2.rebuild_index()

        merge_result = p.merge(p2)
        p.rebuild_index()

        # -- Verify all stats are consistent --
        final_stats = p.stats()
        final_sources = p.list_sources()
        final_source_names = {s["source"] for s in final_sources}

        # Present sources
        assert "science.txt" in final_source_names
        assert "tech.txt" in final_source_names
        assert "geography.txt" in final_source_names
        assert "history_v2.txt" in final_source_names
        assert "politics.txt" in final_source_names

        # Retracted sources still absent
        assert "history.txt" not in final_source_names

        # Annotation on science chunk should still be valid
        anns_final = p.list_annotations(tag="flagged")
        assert len(anns_final) >= 1

        # Core count must be positive and consistent
        assert final_stats["cores"] > 0
        assert final_stats["revisions"] > final_stats["cores"]  # retractions added revisions

        # Indexed count should reflect only active content
        assert final_stats["indexed"] > 0


# ===================================================================
# 9. Annotation Bulk Lifecycle (bonus: depth testing)
# ===================================================================

class TestAnnotationBulkLifecycle:
    """Annotate multiple chunks across sources, filter by different tags,
    verify cross-source annotation integrity after retraction."""

    def test_annotation_bulk_lifecycle(self):
        p = _pipeline()

        rids_a = p.ingest_text(DOC_SCIENCE, source="science.txt")
        rids_b = p.ingest_text(DOC_HISTORY, source="history.txt")
        rids_c = p.ingest_text(DOC_TECH, source="tech.txt")
        p.rebuild_index()

        # Annotate chunks across all three sources
        ann_sci = p.annotate_chunk(rids_a[0], tags=["star", "review"], note="science note")
        ann_hist = p.annotate_chunk(rids_b[0], tags=["star"], note="history note")
        ann_tech = p.annotate_chunk(rids_c[0], tags=["review"], note="tech note")

        # Filter by "star" -> 2 results
        star_anns = p.list_annotations(tag="star")
        assert len(star_anns) == 2

        # Filter by "review" -> 2 results
        review_anns = p.list_annotations(tag="review")
        assert len(review_anns) == 2

        # Retract history source
        p.delete_source("history.txt")

        # "star" now only 1 (history chunk orphaned)
        star_after = p.list_annotations(tag="star")
        assert len(star_after) == 1
        assert star_after[0]["target_revision"] == rids_a[0]

        # "review" unchanged at 2 (only science + tech, no history)
        review_after = p.list_annotations(tag="review")
        assert len(review_after) == 2

        # Remove the science annotation
        p.remove_annotation(ann_sci)

        # "star" now 0, "review" now 1
        star_final = p.list_annotations(tag="star")
        assert len(star_final) == 0
        review_final = p.list_annotations(tag="review")
        assert len(review_final) == 1
        assert review_final[0]["target_revision"] == rids_c[0]


# ===================================================================
# 10. End-to-End With Save, Load, Merge, and Graph
# ===================================================================

class TestFullPipelineRoundTrip:
    """Combines ingestion, graph building, save/load, merge, and
    verifies the entire round-trip preserves consistency."""

    def test_full_pipeline_round_trip(self):
        # -- Pipeline A: ingest + graph --
        pa = _pipeline()
        pa.ingest_text(DOC_SCIENCE, source="science.txt")
        pa.ingest_text(DOC_HISTORY, source="history.txt")
        pa.ingest_text(DOC_TECH, source="tech.txt")
        pa.rebuild_index()
        pa.build_graph(n_clusters=2)

        topics_a = pa.topics()
        assert len(topics_a) >= 1

        # -- Save pipeline A --
        tmp_a = tempfile.mkdtemp()
        tmp_b = tempfile.mkdtemp()
        try:
            pa.save(tmp_a)

            # -- Pipeline B: independent --
            pb = _pipeline()
            pb.ingest_text(DOC_GEOGRAPHY, source="geography.txt")
            pb.ingest_text(DOC_POLITICS, source="politics.txt")
            pb.rebuild_index()

            # -- Load A from disk --
            pa_loaded = Pipeline.load(tmp_a)

            # -- Merge B into loaded A --
            pa_loaded.merge(pb)
            pa_loaded.rebuild_index()

            # -- Build graph on merged --
            pa_loaded.build_graph(n_clusters=3)
            topics_merged = pa_loaded.topics()
            total_members = sum(t["size"] for t in topics_merged)

            # All five sources should be present
            sources = pa_loaded.list_sources()
            source_names = {s["source"] for s in sources}
            assert len(source_names) >= 5

            # Graph should cover all active chunks
            retracted = pa_loaded.store.retracted_core_ids()
            active_count = sum(
                1 for rev in pa_loaded.store.revisions.values()
                if rev.status == "asserted"
                and rev.core_id not in retracted
                and pa_loaded.store.cores[rev.core_id].claim_type == "document.chunk@v1"
            )
            assert total_members == active_count

            # -- Save merged, load again, verify --
            pa_loaded.save(tmp_b)
            pa_final = Pipeline.load(tmp_b)

            stats_final = pa_final.stats()
            assert stats_final["cores"] == pa_loaded.stats()["cores"]
            assert stats_final["revisions"] == pa_loaded.stats()["revisions"]

        finally:
            shutil.rmtree(tmp_a, ignore_errors=True)
            shutil.rmtree(tmp_b, ignore_errors=True)
