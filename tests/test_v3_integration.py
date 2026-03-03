"""Integration tests: end-to-end lifecycle and cross-module verification."""

import os
import shutil
import tempfile
from datetime import datetime, timezone

import pytest

from dks import (
    KnowledgeStore, Pipeline, TransactionTime, ValidTime,
    TfidfSearchIndex, RegexExtractor, ExactResolver,
    CascadingResolver, NormalizedResolver, SearchResult,
)
from dks.mcp import MCPToolHandler
from dks.audit import AuditTrace
from dks.results import ReasoningResult, SynthesisResult, EvidenceChain


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_pipeline():
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


def _make_corpus_pipeline():
    """Create a pipeline with a realistic multi-source corpus."""
    pipeline = _make_pipeline()

    # Science corpus
    pipeline.ingest_text(
        "Photosynthesis is the process by which plants convert sunlight, water, "
        "and carbon dioxide into glucose and oxygen. Chlorophyll in chloroplasts "
        "absorbs light energy to drive these chemical reactions.",
        source="biology_textbook.pdf",
    )
    pipeline.ingest_text(
        "Cellular respiration breaks down glucose to release energy in the form "
        "of ATP. This process occurs in the mitochondria and requires oxygen. "
        "The waste products are carbon dioxide and water.",
        source="biology_textbook.pdf",
    )
    pipeline.ingest_text(
        "DNA replication is the process by which a cell copies its DNA before "
        "division. The enzyme helicase unwinds the double helix while DNA "
        "polymerase synthesizes new complementary strands.",
        source="genetics_guide.pdf",
    )

    # History corpus
    pipeline.ingest_text(
        "The Industrial Revolution began in Britain in the late 18th century. "
        "Steam engines powered factories and transformed manufacturing from "
        "hand production to machine-based processes.",
        source="history_overview.pdf",
    )
    pipeline.ingest_text(
        "The French Revolution of 1789 overthrew the monarchy and established "
        "a republic based on principles of liberty, equality, and fraternity. "
        "It fundamentally changed European political systems.",
        source="history_overview.pdf",
    )

    # Technology corpus
    pipeline.ingest_text(
        "Machine learning algorithms learn patterns from data without being "
        "explicitly programmed. Neural networks, inspired by biological neurons, "
        "are a key architecture for deep learning tasks.",
        source="ml_handbook.pdf",
    )
    pipeline.ingest_text(
        "Quantum computing uses qubits that can exist in superposition states. "
        "This enables quantum computers to solve certain problems exponentially "
        "faster than classical computers.",
        source="quantum_primer.pdf",
    )

    pipeline.rebuild_index()
    pipeline.build_graph(n_clusters=3)
    return pipeline


# =============================================================================
# Full Lifecycle Tests
# =============================================================================

class TestFullLifecycle:
    """End-to-end: ingest -> search -> browse -> annotate -> analyze -> save/load."""

    def test_complete_lifecycle(self):
        pipeline = _make_corpus_pipeline()

        # 1. Query
        results = pipeline.query("photosynthesis chloroplasts", k=3)
        assert len(results) > 0
        assert "photosynth" in results[0].text.lower() or "chloroplast" in results[0].text.lower()

        # 2. Browse the top result
        detail = pipeline.chunk_detail(results[0].revision_id)
        assert detail["text"] == results[0].text
        assert detail["source"] is not None

        # 3. Annotate it
        ann_id = pipeline.annotate_chunk(
            results[0].revision_id, tags=["important", "biology"], note="Key concept"
        )
        assert ann_id is not None

        # 4. Search by tag
        tagged = pipeline.search_by_tag("biology")
        assert len(tagged) >= 1

        # 5. List annotations
        anns = pipeline.list_annotations(revision_id=results[0].revision_id)
        assert len(anns) >= 1
        assert "biology" in anns[0]["tags"]

        # 6. Profile
        profile = pipeline.profile()
        assert profile["summary"]["chunks"] >= 7
        assert profile["summary"]["sources"] >= 4

        # 7. Quality report
        report = pipeline.quality_report()
        assert "summary" in report

        # 8. Save and reload
        tmpdir = tempfile.mkdtemp()
        try:
            pipeline.save(tmpdir)
            loaded = Pipeline.load(tmpdir)

            # Query should still work
            loaded_results = loaded.query("photosynthesis", k=3)
            assert len(loaded_results) > 0
            assert loaded_results[0].revision_id == results[0].revision_id
        finally:
            shutil.rmtree(tmpdir)

    def test_ingest_query_retract_lifecycle(self):
        """Ingest -> query -> retract -> verify invisible."""
        pipeline = _make_pipeline()

        pipeline.ingest_text("Alpha particles are helium nuclei.", source="physics.pdf")
        pipeline.ingest_text("Beta decay emits electrons.", source="physics.pdf")
        pipeline.ingest_text("Gamma rays are electromagnetic radiation.", source="radiation.pdf")
        pipeline.rebuild_index()

        # All results found
        results = pipeline.query("radiation particles", k=5)
        assert len(results) >= 2

        # Retract one source
        pipeline.delete_source("radiation.pdf", reason="outdated")
        pipeline.rebuild_index()

        # Source no longer listed
        sources = pipeline.list_sources()
        source_names = [s["source"] for s in sources]
        assert "radiation.pdf" not in source_names
        assert "physics.pdf" in source_names

    def test_multi_source_comparison(self):
        """Ingest overlapping sources -> compare."""
        pipeline = _make_pipeline()

        pipeline.ingest_text(
            "The speed of light is approximately 300000 kilometers per second.",
            source="physics_a.pdf",
        )
        pipeline.ingest_text(
            "Light travels at roughly 300000 km/s in a vacuum.",
            source="physics_b.pdf",
        )
        pipeline.ingest_text(
            "Sound travels at about 343 meters per second in air.",
            source="physics_a.pdf",
        )
        pipeline.rebuild_index()
        pipeline.build_graph(n_clusters=2)

        comparison = pipeline.compare_sources("physics_a.pdf", "physics_b.pdf")
        assert "source_a" in comparison
        assert "source_b" in comparison


# =============================================================================
# Merge Integration
# =============================================================================

class TestMergeIntegration:
    """Merging two pipelines with overlapping and disjoint data."""

    def test_merge_preserves_all_data(self):
        pipeline_a = _make_pipeline()
        pipeline_a.ingest_text("Earth orbits the Sun.", source="astronomy.pdf")
        pipeline_a.ingest_text("Mars has two moons.", source="astronomy.pdf")

        pipeline_b = _make_pipeline()
        pipeline_b.ingest_text("Jupiter is a gas giant.", source="planets.pdf")
        pipeline_b.ingest_text("Saturn has rings.", source="planets.pdf")

        merge_result = pipeline_a.merge(pipeline_b)
        pipeline_a.rebuild_index()

        # All data accessible (merge mutates pipeline_a.store)
        assert pipeline_a.stats()["revisions"] >= 4

        earth = pipeline_a.query("Earth Sun orbit", k=3)
        assert len(earth) > 0

        jupiter = pipeline_a.query("Jupiter gas giant", k=3)
        assert len(jupiter) > 0

    def test_merge_overlapping_sources(self):
        """Merge pipelines that share a source name."""
        pipeline_a = _make_pipeline()
        pipeline_a.ingest_text("Water boils at 100 degrees Celsius.", source="facts.pdf")

        pipeline_b = _make_pipeline()
        pipeline_b.ingest_text("Water freezes at 0 degrees Celsius.", source="facts.pdf")

        pipeline_a.merge(pipeline_b)
        pipeline_a.rebuild_index()

        results = pipeline_a.query("water temperature", k=5)
        assert len(results) >= 2


# =============================================================================
# Retraction Propagation
# =============================================================================

class TestRetractionPropagation:
    """Retractions must propagate through all subsystems."""

    def test_retraction_clears_from_search_browse_profile(self):
        pipeline = _make_corpus_pipeline()

        # Count sources before
        sources_before = pipeline.list_sources()
        n_before = len(sources_before)

        # Delete one source
        pipeline.delete_source("quantum_primer.pdf", reason="retraction test")
        pipeline.rebuild_index()

        # Fewer sources
        sources_after = pipeline.list_sources()
        assert len(sources_after) < n_before

        # Profile reflects change
        profile = pipeline.profile()
        assert profile["summary"]["sources"] < n_before

        # Query doesn't return retracted content
        results = pipeline.query("quantum qubits superposition", k=10)
        for r in results:
            core = pipeline.store.cores.get(r.core_id)
            if core:
                assert core.slots.get("source") != "quantum_primer.pdf"


# =============================================================================
# MCP Tool Coverage
# =============================================================================

class TestMCPIntegration:
    """MCP tools work end-to-end through the handler."""

    def test_mcp_ingest_and_query(self):
        # MCP dks_ingest uses Pipeline.ingest() which needs an extractor,
        # so we use ingest_text via pipeline first, then query via MCP
        pipeline = _make_pipeline()
        pipeline.ingest_text(
            "The Eiffel Tower is in Paris, France. It was built in 1889.",
            source="paris.pdf",
        )
        pipeline.rebuild_index()

        handler = MCPToolHandler(pipeline)

        # Query via MCP
        result = handler.handle_tool_call("dks_query", {
            "question": "Eiffel Tower Paris",
            "k": 3,
        })
        assert isinstance(result, dict)

    def test_mcp_profile_and_sources(self):
        pipeline = _make_corpus_pipeline()
        handler = MCPToolHandler(pipeline)

        # Profile
        profile = handler.handle_tool_call("dks_profile", {})
        assert "error" not in profile or not profile.get("error")

        # Sources
        sources = handler.handle_tool_call("dks_sources", {})
        assert "error" not in sources or not sources.get("error")

    def test_mcp_stats(self):
        pipeline = _make_corpus_pipeline()
        handler = MCPToolHandler(pipeline)

        result = handler.handle_tool_call("dks_stats", {})
        assert "error" not in result or not result.get("error")

    def test_mcp_all_tools_listed(self):
        pipeline = _make_pipeline()
        handler = MCPToolHandler(pipeline)

        tools = handler.list_tools()
        tool_names = {t["name"] for t in tools}

        # Key tools must exist
        assert "dks_ingest" in tool_names
        assert "dks_query" in tool_names
        assert "dks_profile" in tool_names
        assert "dks_stats" in tool_names
        assert "dks_sources" in tool_names


# =============================================================================
# Audit Trail Capture
# =============================================================================

class TestAuditTrailIntegration:
    """Audit trail captures operations accurately."""

    def test_audit_captures_answer(self):
        pipeline = _make_corpus_pipeline()
        pipeline.enable_audit(True)

        pipeline.answer("What is photosynthesis?")

        trace = pipeline.last_audit()
        assert trace is not None
        assert trace.operation == "answer"

    def test_audit_captures_synthesize(self):
        pipeline = _make_corpus_pipeline()
        pipeline.enable_audit(True)

        pipeline.synthesize("biology overview")

        trace = pipeline.last_audit()
        assert trace is not None
        assert trace.operation == "synthesize"

    def test_audit_render_does_not_crash(self):
        pipeline = _make_corpus_pipeline()
        pipeline.enable_audit(True)

        pipeline.answer("What is photosynthesis?")

        trace = pipeline.last_audit()
        assert trace is not None
        rendered = pipeline.render_audit(trace)
        assert isinstance(rendered, str)
        assert len(rendered) > 0


# =============================================================================
# Extraction + Resolution Integration
# =============================================================================

class TestExtractionResolutionIntegration:
    """End-to-end extraction + resolution pipeline."""

    def test_regex_extraction_and_query(self):
        extractor = RegexExtractor()
        extractor.register_pattern(
            "residence",
            r"(?P<subject>\w+) lives in (?P<city>\w+)",
            ["subject", "city"],
        )

        resolver = CascadingResolver([NormalizedResolver()])

        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(
            store=store,
            search_index=index,
            extractor=extractor,
            resolver=resolver,
        )

        pipeline.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )
        pipeline.rebuild_index()

        # Should find the extracted claim
        assert len(pipeline.store.cores) >= 1

    def test_extraction_with_multiple_patterns(self):
        extractor = RegexExtractor()
        extractor.register_pattern(
            "residence",
            r"(?P<subject>\w+) lives in (?P<city>\w+)",
            ["subject", "city"],
        )
        extractor.register_pattern(
            "employment",
            r"(?P<subject>\w+) works at (?P<company>\w+)",
            ["subject", "company"],
        )

        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(
            store=store,
            search_index=index,
            extractor=extractor,
        )

        pipeline.ingest(
            "Bob lives in Paris. Bob works at Google.",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        # Should have extracted both claims
        assert len(pipeline.store.cores) >= 2


# =============================================================================
# Graph-Based Reasoning
# =============================================================================

class TestGraphReasoning:
    """Multi-hop reasoning and graph traversal."""

    def test_reason_returns_results(self):
        pipeline = _make_corpus_pipeline()

        result = pipeline.reason("How does photosynthesis relate to respiration?", k=3)
        assert result is not None
        # ReasoningResult has .results and .reasoning_path
        assert hasattr(result, "results") or isinstance(result, dict)

    def test_discover_finds_related(self):
        pipeline = _make_corpus_pipeline()

        results = pipeline.discover("photosynthesis", k=5)
        assert results is not None

    def test_evidence_chain_builds(self):
        pipeline = _make_corpus_pipeline()

        chain = pipeline.evidence_chain("Plants produce oxygen")
        assert chain is not None

    def test_coverage_report(self):
        pipeline = _make_corpus_pipeline()

        report = pipeline.coverage("biology")
        assert report is not None


# =============================================================================
# Timeline and Temporal
# =============================================================================

class TestTemporalIntegration:
    """Timeline and temporal query features."""

    def test_timeline_tracks_ingestion_order(self):
        pipeline = _make_pipeline()

        pipeline.ingest_text("First document about cats.", source="doc1.pdf")
        pipeline.ingest_text("Second document about dogs.", source="doc2.pdf")
        pipeline.ingest_text("Third document about birds.", source="doc3.pdf")
        pipeline.rebuild_index()

        timeline = pipeline.ingestion_timeline()
        assert len(timeline) >= 3

    def test_staleness_report(self):
        pipeline = _make_corpus_pipeline()

        report = pipeline.staleness_report(age_days=0)
        # With age_days=0, everything should be flagged
        assert len(report) > 0

    def test_evolution_tracks_topic(self):
        pipeline = _make_corpus_pipeline()

        result = pipeline.evolution("biology", k=5)
        assert result is not None
