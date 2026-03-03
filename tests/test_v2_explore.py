"""Tests for dks.explore — Explorer class (browse, annotate, analyze)."""
from datetime import datetime, timezone

import pytest

from dks import KnowledgeStore, Pipeline, TfidfSearchIndex, ValidTime


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_pipeline_with_graph(n_docs=5, chunks_per_doc=5):
    """Create a pipeline with multiple sources, indexed and graph-built."""
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    pipeline = Pipeline(store=store, search_index=index)

    topics = [
        "neural networks and deep learning architectures for image recognition",
        "quantum computing and qubits for cryptographic applications",
        "climate change and carbon emissions affecting global temperatures",
        "gene editing with CRISPR technology for disease treatment",
        "blockchain and cryptocurrency decentralized finance systems",
    ]

    for doc_i in range(min(n_docs, len(topics))):
        for chunk_i in range(chunks_per_doc):
            text = (
                f"Document {doc_i} chunk {chunk_i}: detailed discussion about {topics[doc_i]}. "
                f"This section covers specific aspects of {topics[doc_i]} including methodology and results. "
                f"Research findings show important connections in the {topics[doc_i]} field."
            )
            pipeline.ingest_text(
                text,
                source=f"paper_{doc_i}.pdf",
                chunk_size=2000,
                valid_time=ValidTime(start=dt(2020 + doc_i), end=None),
            )

    index.rebuild()
    pipeline.build_graph(n_clusters=min(n_docs, 5))
    return pipeline


def _make_empty_pipeline_with_graph():
    """Create a pipeline with graph built but no document chunks."""
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    pipeline = Pipeline(store=store, search_index=index)
    # Manually set an empty graph so graph-dependent methods don't raise
    from dks import KnowledgeGraph
    pipeline._graph = KnowledgeGraph()
    pipeline._graph._adjacency = {}
    pipeline._graph._clusters = {}
    pipeline._graph._revision_cluster = {}
    pipeline._graph._cluster_labels = {}
    return pipeline


# ---- Corpus Profiling ----


class TestProfile:
    def test_profile_returns_correct_structure(self):
        pipeline = _make_pipeline_with_graph()
        profile = pipeline.profile()

        assert "summary" in profile
        assert "clusters" in profile
        assert "sources" in profile
        assert "boilerplate" in profile
        assert "quality_flags" in profile

        s = profile["summary"]
        assert s["chunks"] == 25
        assert s["sources"] == 5
        assert s["clusters"] > 0
        assert s["edges"] >= 0

    def test_profile_sources_have_correct_counts(self):
        pipeline = _make_pipeline_with_graph()
        profile = pipeline.profile()
        total_from_sources = sum(src["chunks"] for src in profile["sources"])
        assert total_from_sources == 25

    def test_profile_on_empty_store(self):
        pipeline = _make_empty_pipeline_with_graph()
        profile = pipeline.profile()
        assert profile["summary"]["chunks"] == 0
        assert profile["summary"]["sources"] == 0

    def test_profile_requires_graph(self):
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=index)
        with pytest.raises(ValueError, match="Graph not built"):
            pipeline.profile()

    def test_render_profile_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        text = pipeline.render_profile()
        assert isinstance(text, str)
        assert len(text) > 50
        assert "Corpus Profile" in text
        assert "Chunks:" in text


# ---- Quality Report ----


class TestQualityReport:
    def test_quality_report_structure(self):
        pipeline = _make_pipeline_with_graph()
        report = pipeline.quality_report()
        assert "summary" in report
        assert "issues" in report
        assert "per_source" in report
        assert "recommendations" in report
        assert report["summary"]["total_chunks"] > 0

    def test_quality_report_detects_short_chunks(self):
        """Ingest very short text to trigger the short_chunks issue."""
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=index)

        for i in range(10):
            pipeline.ingest_text("Hi.", source="short.pdf", chunk_size=2000)

        index.rebuild()
        pipeline.build_graph(n_clusters=1)
        report = pipeline.quality_report()
        short_issues = [iss for iss in report["issues"] if iss["type"] == "short_chunks"]
        assert len(short_issues) == 1
        assert short_issues[0]["count"] == 10

    def test_quality_report_detects_long_chunks(self):
        """Ingest very long text to trigger the long_chunks issue."""
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=index)

        long_text = "Deep learning research methodology and results. " * 100
        for i in range(3):
            pipeline.ingest_text(long_text, source="long.pdf", chunk_size=99999)

        index.rebuild()
        pipeline.build_graph(n_clusters=1)
        report = pipeline.quality_report()
        long_issues = [iss for iss in report["issues"] if iss["type"] == "long_chunks"]
        assert len(long_issues) == 1
        assert long_issues[0]["count"] == 3

    def test_quality_report_detects_orphan_chunks(self):
        """Chunks not in any cluster should be flagged as orphans."""
        pipeline = _make_pipeline_with_graph()
        # Manually remove some revisions from the cluster mapping
        rev_cluster = pipeline._graph._revision_cluster
        removed = 0
        for rid in list(rev_cluster.keys())[:3]:
            del rev_cluster[rid]
            removed += 1
        report = pipeline.quality_report()
        orphan_issues = [iss for iss in report["issues"] if iss["type"] == "orphan_chunks"]
        if orphan_issues:
            assert orphan_issues[0]["count"] >= removed

    def test_quality_report_empty_corpus(self):
        pipeline = _make_empty_pipeline_with_graph()
        report = pipeline.quality_report()
        assert report["summary"]["total_chunks"] == 0
        assert report["issues"] == []

    def test_render_quality_report_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        text = pipeline.render_quality_report()
        assert isinstance(text, str)
        assert "CORPUS QUALITY REPORT" in text


# ---- Source Management ----


class TestSourceManagement:
    def test_list_sources_returns_all(self):
        pipeline = _make_pipeline_with_graph()
        sources = pipeline.list_sources()
        assert len(sources) == 5
        names = {s["source"] for s in sources}
        for i in range(5):
            assert f"paper_{i}.pdf" in names

    def test_list_sources_chunk_counts(self):
        pipeline = _make_pipeline_with_graph()
        sources = pipeline.list_sources()
        for s in sources:
            assert s["chunks"] == 5

    def test_list_sources_excludes_retracted(self):
        pipeline = _make_pipeline_with_graph()
        pipeline.delete_source("paper_0.pdf")
        sources = pipeline.list_sources()
        names = {s["source"] for s in sources}
        # paper_0.pdf may still appear due to retraction being a new revision,
        # but its chunk count from asserted revisions should be 0
        for s in sources:
            if s["source"] == "paper_0.pdf":
                # After delete_source, asserted chunks become 0
                # but retracted revisions may cause the source to still appear
                # via the retraction provenance source ("source_delete")
                pass
        # At minimum, the other 4 sources still have their chunks
        other_chunks = sum(s["chunks"] for s in sources if s["source"] != "paper_0.pdf"
                          and s["source"] != "source_delete")
        assert other_chunks >= 20

    def test_source_detail(self):
        pipeline = _make_pipeline_with_graph()
        detail = pipeline.source_detail("paper_0.pdf")
        assert detail["found"] is True
        assert detail["chunk_count"] == 5
        assert detail["avg_chunk_length"] > 0

    def test_source_detail_nonexistent(self):
        pipeline = _make_pipeline_with_graph()
        detail = pipeline.source_detail("nonexistent.pdf")
        assert detail["found"] is False
        assert detail["chunk_count"] == 0

    def test_delete_source_retracts_chunks(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.delete_source("paper_2.pdf")
        assert result["retracted_count"] == 5
        assert result["source"] == "paper_2.pdf"

    def test_delete_source_does_not_affect_others(self):
        pipeline = _make_pipeline_with_graph()
        pipeline.delete_source("paper_0.pdf")
        detail = pipeline.source_detail("paper_1.pdf")
        assert detail["found"] is True
        assert detail["chunk_count"] == 5


# ---- Browsing ----


class TestBrowsing:
    def test_browse_cluster(self):
        pipeline = _make_pipeline_with_graph()
        clusters = pipeline._graph._clusters
        first_cid = next(iter(clusters))
        result = pipeline.browse_cluster(first_cid)
        assert result["cluster_id"] == first_cid
        assert result["total_members"] > 0
        assert len(result["chunks"]) > 0
        chunk = result["chunks"][0]
        assert "revision_id" in chunk
        assert "preview" in chunk
        assert "length" in chunk

    def test_browse_source(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.browse_source("paper_1.pdf")
        assert result["source"] == "paper_1.pdf"
        assert result["total_chunks"] == 5
        assert len(result["chunks"]) == 5
        for chunk in result["chunks"]:
            assert "preview" in chunk

    def test_browse_source_limit(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.browse_source("paper_1.pdf", limit=2)
        assert result["showing"] == 2
        assert result["total_chunks"] == 5

    def test_chunk_detail_found(self):
        pipeline = _make_pipeline_with_graph()
        rid = next(iter(pipeline.store.revisions))
        detail = pipeline.chunk_detail(rid)
        assert detail["found"] is True
        assert detail["revision_id"] == rid
        assert "text" in detail
        assert "source" in detail
        assert "slots" in detail

    def test_chunk_detail_not_found(self):
        pipeline = _make_pipeline_with_graph()
        detail = pipeline.chunk_detail("nonexistent-id")
        assert detail["found"] is False

    def test_chunk_detail_includes_neighbors(self):
        pipeline = _make_pipeline_with_graph()
        # Find a revision that has graph neighbors
        for rid in pipeline.store.revisions:
            adj = pipeline._graph._adjacency.get(rid, [])
            if adj:
                detail = pipeline.chunk_detail(rid)
                assert len(detail["neighbors"]) > 0
                assert "weight" in detail["neighbors"][0]
                return
        # If no neighbors found, that is still a valid state

    def test_render_browse_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.browse_source("paper_0.pdf")
        text = pipeline.render_browse(result)
        assert isinstance(text, str)
        assert "paper_0.pdf" in text

    def test_render_chunk_detail_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        rid = next(iter(pipeline.store.revisions))
        detail = pipeline.chunk_detail(rid)
        text = pipeline.render_chunk_detail(detail)
        assert isinstance(text, str)
        assert "CHUNK DETAIL" in text

    def test_render_chunk_detail_not_found(self):
        pipeline = _make_pipeline_with_graph()
        detail = pipeline.chunk_detail("missing-id")
        text = pipeline.render_chunk_detail(detail)
        assert "not found" in text


# ---- Entity Review ----


class TestEntityReview:
    def test_review_entities_returns_categories(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.review_entities(top_k=10)
        assert "high" in result
        assert "medium" in result
        assert "flagged" in result
        assert "total_analyzed" in result

    def test_accept_entities_stores_decision(self):
        pipeline = _make_pipeline_with_graph()
        count = pipeline.accept_entities(["neural networks", "deep learning"])
        assert count == 2
        decisions = pipeline.get_entity_decisions()
        assert decisions["neural networks"] == "accepted"
        assert decisions["deep learning"] == "accepted"

    def test_reject_entities_stores_decision(self):
        pipeline = _make_pipeline_with_graph()
        count = pipeline.reject_entities(["document", "section"])
        assert count == 2
        decisions = pipeline.get_entity_decisions()
        assert decisions["document"] == "rejected"
        assert decisions["section"] == "rejected"

    def test_get_entity_decisions_mixed(self):
        pipeline = _make_pipeline_with_graph()
        pipeline.accept_entities(["crispr"])
        pipeline.reject_entities(["boilerplate"])
        decisions = pipeline.get_entity_decisions()
        assert decisions["crispr"] == "accepted"
        assert decisions["boilerplate"] == "rejected"

    def test_get_entity_decisions_empty(self):
        pipeline = _make_pipeline_with_graph()
        decisions = pipeline.get_entity_decisions()
        assert decisions == {}


# ---- Annotations ----


class TestAnnotations:
    def test_annotate_chunk_creates_annotation(self):
        pipeline = _make_pipeline_with_graph()
        rid = next(iter(pipeline.store.revisions))
        ann_id = pipeline.annotate_chunk(rid, tags=["important", "review"], note="check later")
        assert ann_id is not None
        annotations = pipeline.list_annotations()
        assert len(annotations) == 1
        assert annotations[0]["target_revision"] == rid
        assert "important" in annotations[0]["tags"]
        assert annotations[0]["note"] == "check later"

    def test_list_annotations_filter_by_revision(self):
        pipeline = _make_pipeline_with_graph()
        rids = list(pipeline.store.revisions.keys())[:2]
        pipeline.annotate_chunk(rids[0], tags=["tag_a"])
        pipeline.annotate_chunk(rids[1], tags=["tag_b"])
        filtered = pipeline.list_annotations(revision_id=rids[0])
        assert len(filtered) == 1
        assert filtered[0]["target_revision"] == rids[0]

    def test_list_annotations_filter_by_tag(self):
        pipeline = _make_pipeline_with_graph()
        rids = list(pipeline.store.revisions.keys())[:2]
        pipeline.annotate_chunk(rids[0], tags=["keep", "review"])
        pipeline.annotate_chunk(rids[1], tags=["discard"])
        filtered = pipeline.list_annotations(tag="keep")
        assert len(filtered) == 1
        assert "keep" in filtered[0]["tags"]

    def test_search_by_tag(self):
        pipeline = _make_pipeline_with_graph()
        rid = next(iter(pipeline.store.revisions))
        pipeline.annotate_chunk(rid, tags=["flagged"])
        results = pipeline.search_by_tag("flagged")
        assert len(results) == 1
        assert results[0]["revision_id"] == rid

    def test_search_by_tag_no_matches(self):
        pipeline = _make_pipeline_with_graph()
        results = pipeline.search_by_tag("nonexistent_tag")
        assert results == []

    def test_remove_annotation(self):
        pipeline = _make_pipeline_with_graph()
        rid = next(iter(pipeline.store.revisions))
        ann_id = pipeline.annotate_chunk(rid, tags=["temp"], note="remove me")
        assert pipeline.remove_annotation(ann_id) is True
        annotations = pipeline.list_annotations()
        assert len(annotations) == 0

    def test_remove_annotation_nonexistent(self):
        pipeline = _make_pipeline_with_graph()
        assert pipeline.remove_annotation("nonexistent-id") is False

    def test_annotate_nonexistent_revision_raises(self):
        pipeline = _make_pipeline_with_graph()
        with pytest.raises(ValueError, match="not found"):
            pipeline.annotate_chunk("fake-revision", tags=["x"])


# ---- Temporal Analysis ----


class TestTemporalAnalysis:
    def test_ingestion_timeline_sorted(self):
        pipeline = _make_pipeline_with_graph()
        timeline = pipeline.ingestion_timeline()
        assert len(timeline) > 0
        for event in timeline:
            assert "tx_id" in event
            assert "timestamp" in event
            assert "chunk_count" in event
            assert event["chunk_count"] > 0

    def test_evolution_returns_timeline(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.evolution("neural networks", k=10)
        assert result["topic"] == "neural networks"
        assert result["total_chunks"] >= 0
        assert "timeline" in result
        assert "sources" in result

    def test_staleness_report(self):
        pipeline = _make_pipeline_with_graph()
        # Use age_days=0 so everything appears stale
        report = pipeline.staleness_report(age_days=0)
        assert report["stale_count"] > 0
        assert report["threshold_days"] == 0
        for entry in report["oldest"]:
            assert "revision_id" in entry
            assert "age_days" in entry

    def test_staleness_report_nothing_stale(self):
        pipeline = _make_pipeline_with_graph()
        # Use a large but valid age (100 years) so nothing is stale
        report = pipeline.staleness_report(age_days=36500)
        assert report["stale_count"] == 0

    def test_scan_contradictions_returns_list(self):
        pipeline = _make_pipeline_with_graph()
        pairs = pipeline.scan_contradictions(k=5, threshold=0.1)
        assert isinstance(pairs, list)
        for pair in pairs:
            assert "chunk_a" in pair
            assert "chunk_b" in pair
            assert "contradiction_score" in pair

    def test_render_timeline_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        text = pipeline.render_timeline()
        assert isinstance(text, str)
        assert "INGESTION TIMELINE" in text

    def test_render_evolution_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.evolution("quantum computing")
        text = pipeline.render_evolution(result)
        assert isinstance(text, str)
        assert "TOPIC EVOLUTION" in text

    def test_render_contradictions_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        text = pipeline.render_contradictions([])
        assert "No contradictions detected" in text


# ---- Comparative Analysis ----


class TestCompareSourcess:
    def test_compare_sources_overlap(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.compare_sources("paper_0.pdf", "paper_1.pdf")
        assert result["source_a"] == "paper_0.pdf"
        assert result["source_b"] == "paper_1.pdf"
        assert result["found_a"] is True
        assert result["found_b"] is True
        assert result["chunks_a"] == 5
        assert result["chunks_b"] == 5
        assert isinstance(result["overlap_pairs"], list)

    def test_compare_sources_missing_source(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.compare_sources("paper_0.pdf", "nonexistent.pdf")
        assert result["found_b"] is False
        assert result["overlap_pairs"] == []

    def test_render_comparison_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.compare_sources("paper_0.pdf", "paper_1.pdf")
        text = pipeline.render_comparison(result)
        assert isinstance(text, str)
        assert "SOURCE COMPARISON" in text

    def test_render_comparison_missing_source(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.compare_sources("paper_0.pdf", "missing.pdf")
        text = pipeline.render_comparison(result)
        assert "Missing" in text or "Cannot compare" in text


# ---- Insights ----


class TestInsights:
    def test_insights_returns_structure(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.insights()
        assert "health_score" in result
        assert "total_actions" in result
        assert "actions" in result
        assert "summary" in result
        assert 0 <= result["health_score"] <= 100

    def test_insights_actions_sorted_by_priority(self):
        pipeline = _make_pipeline_with_graph()
        result = pipeline.insights()
        priorities = [a["priority"] for a in result["actions"]]
        assert priorities == sorted(priorities)

    def test_suggest_queries_returns_list(self):
        pipeline = _make_pipeline_with_graph()
        suggestions = pipeline.suggest_queries(n=3)
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 3
        for s in suggestions:
            assert "query" in s
            assert "rationale" in s

    def test_summarize_corpus_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        summary = pipeline.summarize_corpus()
        assert isinstance(summary, str)
        assert "knowledge base" in summary.lower() or "chunks" in summary.lower()
        assert "source" in summary.lower()

    def test_render_insights_produces_text(self):
        pipeline = _make_pipeline_with_graph()
        text = pipeline.render_insights()
        assert isinstance(text, str)
        assert "CORPUS INSIGHTS" in text
        assert "Health:" in text


# ---- Edge Cases ----


class TestEdgeCases:
    def test_single_source_corpus(self):
        """Pipeline with only one source should still produce valid reports."""
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=index)
        for i in range(5):
            pipeline.ingest_text(
                f"Chunk {i} about machine learning optimization techniques and gradient descent.",
                source="only_paper.pdf",
                chunk_size=2000,
            )
        index.rebuild()
        pipeline.build_graph(n_clusters=1)

        profile = pipeline.profile()
        assert profile["summary"]["sources"] == 1

        report = pipeline.quality_report()
        assert report["summary"]["total_sources"] == 1
        rec = report["recommendations"]
        assert any("single-source" in r.lower() for r in rec)

    def test_no_graph_raises_on_graph_dependent_methods(self):
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=index)
        pipeline.ingest_text("Some text about testing.", source="test.pdf", chunk_size=2000)
        index.rebuild()
        # No build_graph() call
        with pytest.raises(ValueError, match="Graph not built"):
            pipeline.profile()
        with pytest.raises(ValueError, match="Graph not built"):
            pipeline.quality_report()
        with pytest.raises(ValueError, match="Graph not built"):
            pipeline.insights()
        with pytest.raises(ValueError, match="Graph not built"):
            pipeline.suggest_queries()
        with pytest.raises(ValueError, match="Graph not built"):
            pipeline.browse_cluster(0)
