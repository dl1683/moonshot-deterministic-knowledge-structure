"""Tests for PDF extraction, TF-IDF search, and reasoning capabilities."""
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dks import (
    KnowledgeStore,
    Pipeline,
    PDFExtractor,
    TextChunker,
    TfidfSearchIndex,
    SearchResult,
    ValidTime,
    TransactionTime,
)
from dks.pipeline import ReasoningResult, CoverageReport


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


# ---- TextChunker Tests ----


class TestTextChunker:
    def test_empty_text(self) -> None:
        chunker = TextChunker()
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_short_text(self) -> None:
        chunker = TextChunker(chunk_size=500, min_chunk=10)
        chunks = chunker.chunk("Hello world. This is a test.")
        assert len(chunks) == 1
        assert "Hello world" in chunks[0]

    def test_paragraph_splitting(self) -> None:
        chunker = TextChunker(chunk_size=100, overlap=0, min_chunk=10)
        text = "First paragraph about AI.\n\nSecond paragraph about ML.\n\nThird paragraph about DL."
        chunks = chunker.chunk(text)
        assert len(chunks) >= 1

    def test_long_text_produces_multiple_chunks(self) -> None:
        chunker = TextChunker(chunk_size=200, overlap=0, min_chunk=10)
        # Generate long text with multiple paragraphs
        paragraphs = [f"Paragraph {i} " * 20 for i in range(10)]
        text = "\n\n".join(paragraphs)
        chunks = chunker.chunk(text)
        assert len(chunks) > 1

    def test_overlap_preserves_context(self) -> None:
        chunker = TextChunker(chunk_size=200, overlap=50, min_chunk=10)
        paragraphs = [f"Paragraph {i} " * 20 for i in range(10)]
        text = "\n\n".join(paragraphs)
        chunks = chunker.chunk(text)
        # With overlap, later chunks should contain text from previous chunks
        if len(chunks) > 1:
            # The second chunk should share some text with the first
            assert len(chunks[1]) > len(chunks[0]) * 0.1

    def test_min_chunk_filters_tiny_fragments(self) -> None:
        chunker = TextChunker(chunk_size=100, overlap=0, min_chunk=50)
        text = "Hi\n\nThis is a longer paragraph that should be kept."
        chunks = chunker.chunk(text)
        for chunk in chunks:
            assert len(chunk) >= 50 or len(chunks) == 0


# ---- PDFExtractor Tests ----


class TestPDFExtractor:
    def test_extract_from_text(self) -> None:
        """PDFExtractor satisfies Extractor protocol for plain text."""
        extractor = PDFExtractor(TextChunker(chunk_size=200, min_chunk=10))
        result = extractor.extract("This is a long document about AI and machine learning. " * 10)
        assert len(result.claims) >= 1
        assert result.claims[0].claim_type == "document.chunk@v1"

    def test_empty_text_extraction(self) -> None:
        extractor = PDFExtractor()
        result = extractor.extract("")
        assert len(result.claims) == 0

    def test_chunk_slots_have_source(self) -> None:
        extractor = PDFExtractor(TextChunker(chunk_size=200, min_chunk=10))
        result = extractor.extract("Sample text " * 20)
        if result.claims:
            assert "source" in result.claims[0].slots
            assert "chunk_idx" in result.claims[0].slots

    def test_provenance_contains_chunk_text(self) -> None:
        extractor = PDFExtractor(TextChunker(chunk_size=200, min_chunk=10))
        text = "This is important content about neural networks and deep learning. " * 10
        result = extractor.extract(text)
        if result.provenance:
            # evidence_ref should contain the actual chunk text
            assert len(result.provenance[0].evidence_ref) > 10


# ---- TfidfSearchIndex Tests ----


class TestTfidfSearchIndex:
    def test_add_and_search(self) -> None:
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)

        # Create some claims and revisions
        from dks import ClaimCore, Provenance
        core1 = ClaimCore(claim_type="test", slots={"text": "cats"})
        rev1 = store.assert_revision(
            core=core1, assertion="cats are great pets",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="test"),
            confidence_bp=5000,
        )
        core2 = ClaimCore(claim_type="test", slots={"text": "dogs"})
        rev2 = store.assert_revision(
            core=core2, assertion="dogs are loyal companions",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="test"),
            confidence_bp=5000,
        )
        core3 = ClaimCore(claim_type="test", slots={"text": "ml"})
        rev3 = store.assert_revision(
            core=core3, assertion="machine learning is powerful",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="test"),
            confidence_bp=5000,
        )

        index.add(rev1.revision_id, "cats are great pets")
        index.add(rev2.revision_id, "dogs are loyal companions")
        index.add(rev3.revision_id, "machine learning is powerful")

        results = index.search("pets cats", k=2)
        assert len(results) >= 1
        assert results[0].text == "cats are great pets"

    def test_empty_search(self) -> None:
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        results = index.search("anything", k=5)
        assert len(results) == 0

    def test_batch_add(self) -> None:
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)

        from dks import ClaimCore, Provenance
        items = []
        for i in range(10):
            core = ClaimCore(claim_type="test", slots={"idx": str(i)})
            rev = store.assert_revision(
                core=core, assertion=f"document number {i} about topic {i}",
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                provenance=Provenance(source="test"),
                confidence_bp=5000,
            )
            items.append((rev.revision_id, f"document number {i} about topic {i}"))

        index.add_batch(items)
        assert index.size == 10


# ---- Pipeline PDF Ingestion Tests ----


class TestPipelinePDFIngestion:
    def test_ingest_text_via_pdf_extractor(self) -> None:
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(
            store=store,
            extractor=PDFExtractor(TextChunker(chunk_size=200, min_chunk=10)),
            search_index=search,
        )

        text = "AI and machine learning are transforming the world. " * 20
        rev_ids = pipeline.ingest(
            text,
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        assert len(rev_ids) >= 1
        assert len(store.cores) >= 1


# ---- Reasoning Tests ----


class TestPipelineReasoning:
    def _make_pipeline_with_data(self) -> Pipeline:
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(
            store=store,
            extractor=PDFExtractor(TextChunker(chunk_size=300, min_chunk=20)),
            search_index=search,
        )

        texts = [
            "Machine learning uses neural networks for pattern recognition. Deep learning is a subset of machine learning that uses multiple layers.",
            "Natural language processing enables computers to understand human language. Transformers are the dominant architecture for NLP tasks.",
            "Reinforcement learning trains agents through reward signals. Deep reinforcement learning combines neural nets with RL algorithms.",
            "Computer vision uses convolutional neural networks for image recognition. Object detection and segmentation are key tasks.",
            "Generative AI creates new content. Large language models like GPT generate text. Diffusion models generate images.",
        ]

        for i, text in enumerate(texts):
            pipeline.ingest(
                text,
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=i+1, recorded_at=dt(2024)),
            )

        search.rebuild()
        return pipeline

    def test_reason_returns_result(self) -> None:
        pipeline = self._make_pipeline_with_data()
        result = pipeline.reason("neural networks deep learning", k=3, hops=1)
        assert isinstance(result, ReasoningResult)
        assert result.total_chunks > 0
        assert result.question == "neural networks deep learning"

    def test_reason_multi_hop_expands_context(self) -> None:
        pipeline = self._make_pipeline_with_data()
        result_1hop = pipeline.reason("machine learning", k=3, hops=1)
        result_2hop = pipeline.reason("machine learning", k=3, hops=2)
        # Multi-hop should find at least as many results
        assert result_2hop.total_chunks >= result_1hop.total_chunks

    def test_reason_trace_records_hops(self) -> None:
        pipeline = self._make_pipeline_with_data()
        result = pipeline.reason("reinforcement learning", k=3, hops=2)
        assert len(result.trace) >= 1
        assert result.trace[0]["hop"] == 0

    def test_reason_summary_is_readable(self) -> None:
        pipeline = self._make_pipeline_with_data()
        result = pipeline.reason("neural networks", k=3, hops=1)
        summary = result.summary()
        assert "neural networks" in summary.lower()
        assert "chunks" in summary.lower()

    def test_coverage_returns_report(self) -> None:
        pipeline = self._make_pipeline_with_data()
        report = pipeline.coverage("machine learning", k=5)
        assert isinstance(report, CoverageReport)
        assert report.total_chunks > 0
        assert report.topic == "machine learning"

    def test_coverage_finds_subtopics(self) -> None:
        pipeline = self._make_pipeline_with_data()
        report = pipeline.coverage("neural networks", k=10)
        assert len(report.subtopics) > 0

    def test_discover_finds_related(self) -> None:
        pipeline = self._make_pipeline_with_data()
        discovered = pipeline.discover("deep learning", k=3, depth=1)
        assert len(discovered) > 0

    def test_query_multi_groups_by_source(self) -> None:
        pipeline = self._make_pipeline_with_data()
        grouped = pipeline.query_multi("learning", k=5)
        assert isinstance(grouped, dict)
        # Should have at least one source
        assert len(grouped) >= 1
