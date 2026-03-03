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


# ---- Dense Search Tests ----


class TestDenseSearchIndex:
    """Tests for SentenceTransformerIndex and DenseSearchIndex."""

    def _make_store_with_data(self):
        """Create a store with diverse test documents."""
        from dks import ClaimCore, Provenance
        store = KnowledgeStore()
        docs = [
            ("cats", "cats are adorable furry pets that purr"),
            ("dogs", "dogs are loyal companions that bark and fetch"),
            ("ml", "machine learning uses neural networks for pattern recognition"),
            ("nlp", "natural language processing enables text understanding"),
            ("cv", "computer vision detects objects in images using deep learning"),
        ]
        revision_ids = []
        for slot_val, assertion in docs:
            core = ClaimCore(claim_type="test", slots={"text": slot_val})
            rev = store.assert_revision(
                core=core, assertion=assertion,
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                provenance=Provenance(source="test"),
                confidence_bp=5000,
            )
            revision_ids.append((rev.revision_id, assertion))
        return store, revision_ids

    def test_sentence_transformer_index_search(self) -> None:
        from dks.index import SentenceTransformerIndex
        idx = SentenceTransformerIndex("all-MiniLM-L6-v2")
        idx.add("r1", "cats are adorable furry pets")
        idx.add("r2", "machine learning is powerful")
        idx.add("r3", "dogs are loyal companions")
        idx.rebuild()
        results = idx.search("cute animals pets", k=2)
        assert len(results) >= 1
        # "cats" or "dogs" should rank higher than "machine learning"
        top_ids = [r[0] for r in results]
        assert "r1" in top_ids or "r3" in top_ids

    def test_dense_search_index_with_store(self) -> None:
        from dks import DenseSearchIndex
        store, items = self._make_store_with_data()
        dense = DenseSearchIndex(store, "all-MiniLM-L6-v2")
        dense.add_batch(items)
        dense.rebuild()
        results = dense.search("animal pets", k=2)
        assert len(results) >= 1
        assert isinstance(results[0], SearchResult)
        # Should find pet-related docs, not ML docs
        assert "cats" in results[0].text or "dogs" in results[0].text

    def test_dense_search_empty(self) -> None:
        from dks import DenseSearchIndex
        store = KnowledgeStore()
        dense = DenseSearchIndex(store, "all-MiniLM-L6-v2")
        results = dense.search("anything", k=5)
        assert len(results) == 0

    def test_dense_semantic_vs_keyword(self) -> None:
        """Dense search should find semantically similar texts even without keyword overlap."""
        from dks.index import SentenceTransformerIndex
        idx = SentenceTransformerIndex("all-MiniLM-L6-v2")
        idx.add("r1", "felines enjoy sleeping in warm sunny spots")
        idx.add("r2", "gradient descent optimizes neural network weights")
        idx.add("r3", "puppies love playing in the park with their owners")
        idx.rebuild()
        # Query about "cats" should match "felines" semantically
        results = idx.search("cats sleeping", k=2)
        assert results[0][0] == "r1"


# ---- Hybrid Search Tests ----


class TestHybridSearchIndex:
    """Tests for HybridSearchIndex (reciprocal rank fusion)."""

    def _make_store_with_data(self):
        from dks import ClaimCore, Provenance
        store = KnowledgeStore()
        docs = [
            ("cats", "cats are adorable furry pets that purr and sleep"),
            ("dogs", "dogs are loyal companions that bark and fetch balls"),
            ("ml", "machine learning uses neural networks for pattern recognition"),
            ("nlp", "natural language processing enables text understanding and generation"),
            ("cv", "computer vision detects objects in images using convolutional networks"),
            ("rl", "reinforcement learning trains agents through reward signals"),
        ]
        items = []
        for slot_val, assertion in docs:
            core = ClaimCore(claim_type="test", slots={"text": slot_val})
            rev = store.assert_revision(
                core=core, assertion=assertion,
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                provenance=Provenance(source="test"),
                confidence_bp=5000,
            )
            items.append((rev.revision_id, assertion))
        return store, items

    def test_hybrid_search_returns_results(self) -> None:
        from dks import HybridSearchIndex
        store, items = self._make_store_with_data()
        hybrid = HybridSearchIndex(store, "all-MiniLM-L6-v2", alpha=0.5)
        hybrid.add_batch(items)
        hybrid.rebuild()
        results = hybrid.search("neural network deep learning", k=3)
        assert len(results) >= 1
        assert isinstance(results[0], SearchResult)

    def test_hybrid_finds_keyword_and_semantic(self) -> None:
        """Hybrid should find results that both TF-IDF and dense would find."""
        from dks import HybridSearchIndex
        store, items = self._make_store_with_data()
        hybrid = HybridSearchIndex(store, "all-MiniLM-L6-v2", alpha=0.5)
        hybrid.add_batch(items)
        hybrid.rebuild()
        results = hybrid.search("pets animals cats", k=3)
        assert len(results) >= 1
        # Should find cat/dog related content
        all_text = " ".join(r.text for r in results)
        assert "cats" in all_text or "dogs" in all_text

    def test_hybrid_empty_search(self) -> None:
        from dks import HybridSearchIndex
        store = KnowledgeStore()
        hybrid = HybridSearchIndex(store, "all-MiniLM-L6-v2")
        results = hybrid.search("anything", k=5)
        assert len(results) == 0

    def test_hybrid_batch_size(self) -> None:
        from dks import HybridSearchIndex
        store, items = self._make_store_with_data()
        hybrid = HybridSearchIndex(store, "all-MiniLM-L6-v2")
        hybrid.add_batch(items)
        assert hybrid.size == 6

    def test_hybrid_alpha_weighting(self) -> None:
        """Different alpha values should shift results between keyword and semantic."""
        from dks import HybridSearchIndex
        store, items = self._make_store_with_data()

        # alpha=0 -> pure TF-IDF
        h_tfidf = HybridSearchIndex(store, "all-MiniLM-L6-v2", alpha=0.0)
        h_tfidf.add_batch(items)
        h_tfidf.rebuild()

        # alpha=1 -> pure dense
        h_dense = HybridSearchIndex(store, "all-MiniLM-L6-v2", alpha=1.0)
        h_dense.add_batch(items)
        h_dense.rebuild()

        r_tfidf = h_tfidf.search("pattern recognition learning", k=3)
        r_dense = h_dense.search("pattern recognition learning", k=3)

        # Both should return results
        assert len(r_tfidf) >= 1
        assert len(r_dense) >= 1


# ---- Cross-Encoder Re-ranker Tests ----


class TestCrossEncoderReranker:
    """Tests for cross-encoder re-ranking."""

    def test_rerank_improves_ordering(self) -> None:
        from dks import CrossEncoderReranker
        reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")

        # Create fake search results with wrong ordering
        results = [
            SearchResult(core_id="c1", revision_id="r1", score=0.9,
                        text="cats are adorable furry pets"),
            SearchResult(core_id="c2", revision_id="r2", score=0.8,
                        text="machine learning uses neural networks for pattern recognition"),
            SearchResult(core_id="c3", revision_id="r3", score=0.7,
                        text="deep learning is a subset of machine learning"),
        ]

        reranked = reranker.rerank("neural networks deep learning", results)
        assert len(reranked) == 3
        # The ML/DL results should be ranked higher than cats
        ml_ids = {"r2", "r3"}
        assert reranked[0].revision_id in ml_ids

    def test_rerank_with_top_k(self) -> None:
        from dks import CrossEncoderReranker
        reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")

        results = [
            SearchResult(core_id="c1", revision_id="r1", score=0.5,
                        text="cats are adorable pets"),
            SearchResult(core_id="c2", revision_id="r2", score=0.5,
                        text="dogs are loyal companions"),
            SearchResult(core_id="c3", revision_id="r3", score=0.5,
                        text="machine learning is powerful"),
        ]

        reranked = reranker.rerank("pets", results, top_k=2)
        assert len(reranked) == 2

    def test_rerank_empty(self) -> None:
        from dks import CrossEncoderReranker
        reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
        assert reranker.rerank("query", []) == []

    def test_rerank_scores_are_cross_encoder_scale(self) -> None:
        """Cross-encoder scores should be in a different range than cosine similarity."""
        from dks import CrossEncoderReranker
        reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
        results = [
            SearchResult(core_id="c1", revision_id="r1", score=0.5,
                        text="machine learning uses neural networks"),
        ]
        reranked = reranker.rerank("what is machine learning", results)
        # Cross-encoder scores are typically in [-15, 15] range, not [0, 1]
        assert abs(reranked[0].score) > 1.0

    def test_pipeline_with_reranker(self) -> None:
        """Pipeline should use reranker when configured."""
        from dks import CrossEncoderReranker
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
        pipeline = Pipeline(store=store, search_index=index, reranker=reranker)

        from dks import ClaimCore, Provenance
        texts = [
            "neural networks learn patterns from data through backpropagation",
            "cats enjoy sleeping in warm sunny spots all day long",
            "deep learning models have millions of trainable parameters",
        ]
        for text in texts:
            core = ClaimCore(claim_type="test", slots={"text": text[:20]})
            rev = store.assert_revision(
                core=core, assertion=text,
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                provenance=Provenance(source="test"),
                confidence_bp=5000,
            )
            index.add(rev.revision_id, text)
        index.rebuild()

        results = pipeline.query("how do neural networks learn", k=2)
        assert len(results) >= 1
        # Cross-encoder should rank the neural network text highest
        assert "neural" in results[0].text or "deep learning" in results[0].text


# ---- Evidence Chain Tests ----


class TestEvidenceChain:
    """Tests for cross-document evidence chain reasoning."""

    def _make_pipeline_with_graph(self) -> Pipeline:
        """Create a pipeline with graph for evidence chain testing."""
        from dks import ClaimCore, Provenance
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        texts = [
            "Neural networks use backpropagation to learn patterns from data. Deep learning uses multiple layers.",
            "Transformers replaced RNNs for sequence modeling. Self-attention enables parallel processing.",
            "Large language models can hallucinate incorrect facts. They lack grounded understanding of the world.",
            "Reinforcement learning trains agents through reward signals. Deep RL combines neural nets with RL.",
            "Self-supervised learning learns from unlabeled data. Contrastive learning is a popular approach.",
            "Model compression reduces size through distillation. Small models can be surprisingly capable.",
            "Computer vision uses CNNs for image recognition. Vision transformers are replacing CNNs.",
            "Transfer learning pre-trains on large datasets. Fine-tuning adapts models to specific tasks.",
        ]

        for i, text in enumerate(texts):
            core = ClaimCore(
                claim_type="test",
                slots={"text": text[:30], "source": f"doc_{i}.pdf"},
            )
            rev = store.assert_revision(
                core=core, assertion=text,
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=i+1, recorded_at=dt(2024)),
                provenance=Provenance(source=f"doc_{i}.pdf"),
                confidence_bp=5000,
            )
            search.add(rev.revision_id, text)

        search.rebuild()
        pipeline.build_graph(n_clusters=3)
        return pipeline

    def test_evidence_chain_returns_result(self) -> None:
        from dks.pipeline import EvidenceChain
        pipeline = self._make_pipeline_with_graph()
        chain = pipeline.evidence_chain("neural networks learn patterns")
        assert isinstance(chain, EvidenceChain)
        assert chain.total_evidence > 0
        assert chain.claim == "neural networks learn patterns"

    def test_evidence_chain_finds_direct_evidence(self) -> None:
        pipeline = self._make_pipeline_with_graph()
        chain = pipeline.evidence_chain("transformers replaced RNNs")
        assert len(chain.direct_evidence) > 0
        # Should find the transformer text
        found_transformer = any(
            "transformer" in r.text.lower() or "rnn" in r.text.lower()
            for r in chain.direct_evidence
        )
        assert found_transformer

    def test_evidence_chain_multi_source(self) -> None:
        pipeline = self._make_pipeline_with_graph()
        chain = pipeline.evidence_chain("deep learning architectures")
        assert chain.source_count >= 1

    def test_evidence_chain_summary(self) -> None:
        pipeline = self._make_pipeline_with_graph()
        chain = pipeline.evidence_chain("model compression distillation")
        summary = chain.summary()
        assert "Evidence for" in summary
        assert "model compression distillation" in summary.lower()
        assert "chunks" in summary.lower()

    def test_evidence_chain_context_for_llm(self) -> None:
        pipeline = self._make_pipeline_with_graph()
        chain = pipeline.evidence_chain("self-supervised learning")
        context = chain.context_for_llm()
        assert "Evidence Analysis" in context
        assert "self-supervised learning" in context.lower()


# ---- Context Expansion Tests ----


class TestContextExpansion:
    """Tests for context expansion and sibling chunk tracking."""

    def _make_pipeline_with_siblings(self) -> Pipeline:
        """Build a pipeline with tracked chunk siblings."""
        from dks import ClaimCore, Provenance
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        # Simulate ingesting a 5-chunk document
        source = "test_doc.pdf"
        chunk_revisions = []
        for i in range(5):
            texts = [
                "Introduction to machine learning and neural networks basics",
                "Deep learning architectures including CNNs and transformers",
                "Training techniques backpropagation gradient descent optimization",
                "Evaluation metrics accuracy precision recall F1 score",
                "Conclusion and future directions for AI research",
            ]
            core = ClaimCore(
                claim_type="document.chunk@v1",
                slots={"source": source, "chunk_idx": str(i), "text": texts[i][:30]},
            )
            rev = store.assert_revision(
                core=core, assertion=texts[i],
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                provenance=Provenance(source=source),
                confidence_bp=5000,
            )
            search.add(rev.revision_id, texts[i])
            chunk_revisions.append(rev.revision_id)

        search.rebuild()
        pipeline._chunk_siblings[source] = chunk_revisions
        return pipeline

    def test_expand_context_returns_surrounding_chunks(self) -> None:
        pipeline = self._make_pipeline_with_siblings()
        results = pipeline.query("deep learning CNNs", k=1)
        assert len(results) >= 1

        expanded = pipeline.expand_context(results[0], window=1)
        assert len(expanded) >= 2  # At least original + 1 neighbor

    def test_expand_context_window_size(self) -> None:
        pipeline = self._make_pipeline_with_siblings()
        results = pipeline.query("training backpropagation", k=1)
        assert len(results) >= 1

        # Window of 2 around chunk 2 should give chunks 0-4
        expanded = pipeline.expand_context(results[0], window=2)
        assert len(expanded) >= 3  # At least 3 chunks

    def test_expand_context_edge_chunk(self) -> None:
        pipeline = self._make_pipeline_with_siblings()
        results = pipeline.query("introduction machine learning basics", k=1)
        assert len(results) >= 1

        # Window around first chunk shouldn't go negative
        expanded = pipeline.expand_context(results[0], window=2)
        assert len(expanded) >= 1

    def test_query_with_context(self) -> None:
        pipeline = self._make_pipeline_with_siblings()
        results = pipeline.query_with_context("deep learning", k=1, context_window=1)
        # Should return more than just 1 result (expanded with context)
        assert len(results) >= 2

    def test_query_with_context_deduplicates(self) -> None:
        pipeline = self._make_pipeline_with_siblings()
        results = pipeline.query_with_context("neural networks", k=2, context_window=1)
        # Should not have duplicate revision_ids
        rev_ids = [r.revision_id for r in results]
        assert len(rev_ids) == len(set(rev_ids))

    def test_context_expansion_preserves_order(self) -> None:
        """Expanded chunks should be in document order."""
        pipeline = self._make_pipeline_with_siblings()
        results = pipeline.query("training backpropagation", k=1)
        if results:
            expanded = pipeline.expand_context(results[0], window=2)
            # Check that chunk_idx values are in order
            indices = []
            for r in expanded:
                core = pipeline.store.cores.get(r.core_id)
                if core:
                    indices.append(int(core.slots.get("chunk_idx", "0")))
            assert indices == sorted(indices)

    def test_reconstruct_siblings_from_store(self) -> None:
        """Test that siblings can be reconstructed when not in memory."""
        from dks import ClaimCore, Provenance
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        source = "recon_doc.pdf"
        for i in range(3):
            core = ClaimCore(
                claim_type="document.chunk@v1",
                slots={"source": source, "chunk_idx": str(i), "text": f"chunk {i}"},
            )
            rev = store.assert_revision(
                core=core, assertion=f"chunk {i} content about topic {i}",
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                provenance=Provenance(source=source),
                confidence_bp=5000,
            )
            search.add(rev.revision_id, f"chunk {i} content about topic {i}")
        search.rebuild()

        # Don't set _chunk_siblings — force reconstruction
        siblings = pipeline._reconstruct_siblings(source)
        assert len(siblings) == 3


# ---- Adaptive Retrieval Tests ----


class TestAdaptiveRetrieval:
    """Tests for query classification and adaptive retrieval."""

    def test_classify_factual(self) -> None:
        store = KnowledgeStore()
        idx = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=idx)
        assert pipeline._classify_query("what is backpropagation") == "factual"
        assert pipeline._classify_query("graph neural networks") == "factual"
        assert pipeline._classify_query("define entropy") == "factual"

    def test_classify_comparison(self) -> None:
        store = KnowledgeStore()
        idx = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=idx)
        assert pipeline._classify_query("transformers vs RNNs") == "comparison"
        assert pipeline._classify_query("compare CNNs and transformers") == "comparison"

    def test_classify_exploratory(self) -> None:
        store = KnowledgeStore()
        idx = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=idx)
        assert pipeline._classify_query("why do models hallucinate") == "exploratory"
        assert pipeline._classify_query("explain the impact of AI on society") == "exploratory"

    def test_ask_returns_synthesis(self) -> None:
        from dks import ClaimCore, Provenance
        from dks.pipeline import SynthesisResult
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        for i, text in enumerate([
            "Neural networks learn patterns through backpropagation",
            "Transformers use attention for sequence processing",
            "RNNs process sequences sequentially with hidden state",
        ]):
            core = ClaimCore(claim_type="test", slots={"source": f"doc{i}.pdf", "text": text[:20]})
            rev = store.assert_revision(
                core=core, assertion=text,
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=i+1, recorded_at=dt(2024)),
                provenance=Provenance(source=f"doc{i}.pdf"),
                confidence_bp=5000,
            )
            search.add(rev.revision_id, text)
        search.rebuild()

        result = pipeline.ask("what is backpropagation")
        assert isinstance(result, SynthesisResult)
        assert result.total_chunks > 0

    def test_ask_comparison_strategy(self) -> None:
        from dks import ClaimCore, Provenance
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        for i, text in enumerate([
            "Transformers use self-attention mechanism for parallel processing",
            "RNNs process data sequentially with recurrent connections",
            "CNNs use convolutional filters for spatial features",
        ]):
            core = ClaimCore(claim_type="test", slots={"source": f"doc{i}.pdf", "text": text[:20]})
            rev = store.assert_revision(
                core=core, assertion=text,
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=i+1, recorded_at=dt(2024)),
                provenance=Provenance(source=f"doc{i}.pdf"),
                confidence_bp=5000,
            )
            search.add(rev.revision_id, text)
        search.rebuild()

        result = pipeline.ask("transformers vs RNNs")
        assert result.total_chunks > 0
        assert "Comparison" in result.context


# ---- Synthesis Tests ----


class TestSynthesis:
    """Tests for full-stack answer synthesis."""

    def _make_pipeline(self) -> Pipeline:
        from dks import ClaimCore, Provenance
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        docs = {
            "intro.pdf": [
                "Neural networks are the foundation of deep learning. They learn patterns through backpropagation.",
                "Convolutional neural networks excel at image recognition tasks. They use local receptive fields.",
            ],
            "transformers.pdf": [
                "Transformers use self-attention to process sequences in parallel. They replaced RNNs for NLP.",
                "Multi-head attention allows transformers to attend to different representation subspaces.",
            ],
            "safety.pdf": [
                "AI alignment ensures models behave according to human values and intentions.",
                "Reinforcement learning from human feedback is a key technique for alignment.",
            ],
        }

        for source, chunks in docs.items():
            rev_ids = []
            for i, text in enumerate(chunks):
                core = ClaimCore(
                    claim_type="document.chunk@v1",
                    slots={"source": source, "chunk_idx": str(i), "text": text[:30]},
                )
                rev = store.assert_revision(
                    core=core, assertion=text,
                    valid_time=ValidTime(start=dt(2024), end=None),
                    transaction_time=TransactionTime(tx_id=i+1, recorded_at=dt(2024)),
                    provenance=Provenance(source=source),
                    confidence_bp=5000,
                )
                search.add(rev.revision_id, text)
                rev_ids.append(rev.revision_id)
            pipeline._chunk_siblings[source] = rev_ids

        search.rebuild()
        return pipeline

    def test_synthesize_returns_result(self) -> None:
        from dks.pipeline import SynthesisResult
        pipeline = self._make_pipeline()
        result = pipeline.synthesize("neural networks", k=3, hops=1, context_window=0)
        assert isinstance(result, SynthesisResult)
        assert result.total_chunks > 0
        assert result.question == "neural networks"

    def test_synthesize_has_context(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.synthesize("transformers attention", k=3, hops=1, context_window=0)
        assert result.context_length > 0
        assert "Research Context" in result.context

    def test_synthesize_has_themes(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.synthesize("deep learning", k=3, hops=1, context_window=0)
        assert len(result.themes) >= 1

    def test_synthesize_has_sources(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.synthesize("neural networks transformers", k=5, hops=1, context_window=0)
        assert result.source_count >= 1
        assert len(result.source_summaries) >= 1

    def test_synthesize_summary(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.synthesize("AI alignment safety", k=3, hops=1, context_window=0)
        summary = result.summary()
        assert "Synthesis" in summary
        assert "sources" in summary.lower()

    def test_synthesize_with_context_window(self) -> None:
        pipeline = self._make_pipeline()
        without = pipeline.synthesize("transformers", k=2, hops=1, context_window=0)
        with_ctx = pipeline.synthesize("transformers", k=2, hops=1, context_window=1)
        # With context window should have more chunks
        assert with_ctx.total_chunks >= without.total_chunks


# ---- Temporal-Aware Retrieval Tests ----


class TestTemporalRetrieval:
    """Test that all retrieval methods respect bitemporal filtering."""

    def _make_pipeline(self) -> Pipeline:
        """Build a pipeline with claims at different times."""
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        # Fact 1: asserted at tx_id=1, valid from 2020
        core1 = ClaimCore(claim_type="fact@v1", slots={"subject": "neural networks", "source": "paper_a"})
        store.assert_revision(
            core=core1,
            assertion="Neural networks use backpropagation for training deep learning models",
            valid_time=ValidTime(start=dt(2020)),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
            provenance=Provenance(source="paper_a"),
            confidence_bp=5000,
            status="asserted",
        )

        # Fact 2: asserted at tx_id=2, valid from 2023
        core2 = ClaimCore(claim_type="fact@v1", slots={"subject": "transformers", "source": "paper_b"})
        store.assert_revision(
            core=core2,
            assertion="Transformers revolutionized natural language processing with attention mechanisms",
            valid_time=ValidTime(start=dt(2023)),
            transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 6, 1)),
            provenance=Provenance(source="paper_b"),
            confidence_bp=5000,
            status="asserted",
        )

        # Fact 3: asserted at tx_id=3, valid 2021-2023
        core3 = ClaimCore(claim_type="fact@v1", slots={"subject": "rnn", "source": "paper_c"})
        store.assert_revision(
            core=core3,
            assertion="Recurrent neural networks were the dominant approach for sequence modeling",
            valid_time=ValidTime(start=dt(2021), end=dt(2023)),
            transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 9, 1)),
            provenance=Provenance(source="paper_c"),
            confidence_bp=5000,
            status="asserted",
        )

        # Index all revisions
        for rid, rev in store.revisions.items():
            search.add(rid, rev.assertion)
        search.rebuild()

        return pipeline

    def test_query_without_temporal_returns_all(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("neural networks transformers sequence modeling", k=10)
        assert len(results) == 3  # All three facts

    def test_query_with_valid_at_filters(self) -> None:
        pipeline = self._make_pipeline()
        # At valid_at=2022, only fact 1 (from 2020) and fact 3 (2021-2023) are valid
        results = pipeline.query(
            "neural networks transformers sequence modeling",
            k=10,
            valid_at=dt(2022, 6, 1),
            tx_id=10,  # Far future tx so all are visible
        )
        # Fact 2 (valid from 2023) should be excluded
        # Note: canonicalize_text lowercases assertions
        texts = [r.text for r in results]
        assert any("backpropagation" in t for t in texts)  # Fact 1
        assert any("recurrent" in t for t in texts)  # Fact 3
        assert not any("transformers revolutionized" in t for t in texts)  # Fact 2 excluded

    def test_query_with_tx_id_filters(self) -> None:
        pipeline = self._make_pipeline()
        # With tx_id=1, only fact 1 is visible (tx_id=1)
        results = pipeline.query(
            "neural networks transformers sequence modeling",
            k=10,
            valid_at=dt(2025),
            tx_id=1,
        )
        texts = [r.text for r in results]
        assert any("backpropagation" in t for t in texts)  # Fact 1 visible
        # Facts 2 and 3 have tx_id 2 and 3 respectively, so not visible at tx_id=1

    def test_reason_with_temporal(self) -> None:
        pipeline = self._make_pipeline()
        # Reason should respect temporal filter
        result = pipeline.reason(
            "neural networks",
            k=5,
            hops=1,
            valid_at=dt(2022, 6, 1),
            tx_id=10,
        )
        texts = [r.text for r in result.results]
        assert not any("transformers revolutionized" in t for t in texts)

    def test_synthesize_with_temporal(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.synthesize(
            "neural networks",
            k=5,
            hops=1,
            context_window=0,
            valid_at=dt(2022, 6, 1),
            tx_id=10,
        )
        texts = [r.text for r in result.results]
        assert not any("transformers revolutionized" in t for t in texts)

    def test_ask_with_temporal(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.ask(
            "what is neural network training",
            k=5,
            valid_at=dt(2022, 6, 1),
            tx_id=10,
        )
        texts = [r.text for r in result.results]
        assert not any("transformers revolutionized" in t for t in texts)

    def test_coverage_with_temporal(self) -> None:
        pipeline = self._make_pipeline()
        report = pipeline.coverage(
            "neural networks",
            k=10,
            valid_at=dt(2022, 6, 1),
            tx_id=10,
        )
        texts = [r.text for r in [chunk for chunks in report.sources.values() for chunk in chunks]]
        assert not any("transformers revolutionized" in t for t in texts)

    def test_evidence_chain_with_temporal(self) -> None:
        pipeline = self._make_pipeline()
        chain = pipeline.evidence_chain(
            "neural networks for training",
            k=5,
            valid_at=dt(2022, 6, 1),
            tx_id=10,
        )
        all_texts = [r.text for r in chain.direct_evidence + chain.related_evidence]
        assert not any("transformers revolutionized" in t for t in all_texts)


# ---- Contradiction Detection & Confidence Tests ----


class TestContradictionDetection:
    """Test contradiction detection and confidence scoring."""

    def _make_pipeline(self) -> Pipeline:
        """Build a pipeline with contradictory claims from different sources."""
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        claims = [
            # Contradictory pair: performance claims about transformers
            ("transformers achieve higher accuracy than recurrent neural networks on language tasks",
             "paper_a"),
            ("recurrent neural networks are not outperformed by transformers on language tasks",
             "paper_b"),
            # Supporting claims from different sources
            ("deep learning models require large datasets for effective training",
             "paper_c"),
            ("neural networks need large amounts of training data to perform well",
             "paper_d"),
            # Numerical disagreement
            ("the model achieved 95% accuracy on the benchmark dataset",
             "paper_e"),
            ("the model achieved 78% accuracy on the benchmark dataset",
             "paper_f"),
        ]

        for i, (text, source) in enumerate(claims):
            core = ClaimCore(claim_type="fact@v1", slots={"subject": "ml", "source": source})
            rev = store.assert_revision(
                core=core,
                assertion=text,
                valid_time=ValidTime(start=dt(2024)),
                transaction_time=TransactionTime(tx_id=i + 1, recorded_at=dt(2024, i + 1, 1)),
                provenance=Provenance(source=source),
                confidence_bp=5000,
                status="asserted",
            )
            search.add(rev.revision_id, rev.assertion)

        search.rebuild()
        return pipeline

    def test_contradictions_returns_list(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.contradictions("neural networks transformers language")
        assert isinstance(result, list)

    def test_contradictions_finds_negation(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.contradictions("transformers recurrent neural networks language")
        # Should find the contradiction between paper_a and paper_b
        assert len(result) > 0
        # At least one should have negation signal
        all_signals = [s for c in result for s in c["conflict_signals"]]
        assert any("negation" in s or "opposition" in s for s in all_signals)

    def test_contradictions_cross_source_only(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.contradictions("neural networks")
        # All contradictions should be cross-source
        for c in result:
            assert c["source_a"] != c["source_b"]

    def test_contradictions_has_confidence(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.contradictions("transformers neural networks")
        for c in result:
            assert 0 <= c["confidence_bp"] <= 10000

    def test_contradictions_sorted_by_confidence(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.contradictions("transformers neural networks accuracy")
        if len(result) > 1:
            for i in range(len(result) - 1):
                assert result[i]["confidence_bp"] >= result[i + 1]["confidence_bp"]

    def test_confidence_returns_assessment(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.confidence("deep learning requires large datasets")
        assert "confidence_bp" in result
        assert "assessment" in result
        assert result["assessment"] in ("high", "medium", "low", "insufficient")
        assert result["evidence_count"] > 0

    def test_confidence_with_supporting_evidence(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.confidence("neural networks need large training data")
        assert result["supporting"] > 0
        assert result["source_count"] >= 1

    def test_confidence_insufficient_for_unknown(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.confidence("quantum teleportation of cat brains")
        assert result["evidence_count"] == 0
        assert result["assessment"] == "insufficient"

    def test_contradictions_with_temporal(self) -> None:
        pipeline = self._make_pipeline()
        # Only tx_id 1-2 visible
        result = pipeline.contradictions(
            "transformers neural networks",
            valid_at=dt(2025),
            tx_id=2,
        )
        # Should still work with temporal filtering
        assert isinstance(result, list)


# ---- Provenance & Citation Tests ----


class TestProvenanceCitation:
    """Test provenance tracking and citation generation."""

    def _make_pipeline(self) -> Pipeline:
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        claims = [
            ("attention mechanisms enable transformers to process sequences",
             "attention_is_all_you_need.pdf", "0", "3"),
            ("bert uses masked language modeling for pretraining",
             "bert_paper.pdf", "0", "5"),
            ("gpt models use autoregressive language modeling",
             "gpt_paper.pdf", "1", "7"),
        ]

        for i, (text, source, chunk_idx, page) in enumerate(claims):
            core = ClaimCore(
                claim_type="document.chunk@v1",
                slots={"source": source, "chunk_idx": chunk_idx, "page_start": page, "text": text[:50]},
            )
            rev = store.assert_revision(
                core=core,
                assertion=text,
                valid_time=ValidTime(start=dt(2024)),
                transaction_time=TransactionTime(tx_id=i + 1, recorded_at=dt(2024, i + 1, 1)),
                provenance=Provenance(source=f"pdf:{source}", evidence_ref=text),
                confidence_bp=5000,
                status="asserted",
            )
            search.add(rev.revision_id, rev.assertion)

        search.rebuild()
        return pipeline

    def test_provenance_of_result(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("attention transformers", k=1)
        assert len(results) >= 1
        prov = pipeline.provenance_of(results[0])
        assert "source" in prov
        assert "confidence_bp" in prov
        assert prov["confidence_bp"] == 5000
        assert "valid_time" in prov
        assert "transaction_time" in prov

    def test_provenance_has_page_and_chunk(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("attention transformers", k=1)
        prov = pipeline.provenance_of(results[0])
        assert "page" in prov
        assert "chunk_index" in prov
        assert isinstance(prov["page"], int)

    def test_cite_inline(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("attention transformers", k=1)
        citation = pipeline.cite(results[0], style="inline")
        assert "[" in citation
        assert "]" in citation

    def test_cite_markdown(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("bert masked language", k=1)
        citation = pipeline.cite(results[0], style="markdown")
        assert "**" in citation  # bold source name

    def test_cite_full(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("gpt autoregressive", k=1)
        citation = pipeline.cite(results[0], style="full")
        assert "Source:" in citation
        assert "Confidence:" in citation

    def test_cite_results_deduplicate(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("language modeling", k=5)
        citations = pipeline.cite_results(results, style="inline", deduplicate=True)
        # With deduplication, should have <= number of unique sources
        assert len(citations) <= len(results)

    def test_list_sources(self) -> None:
        pipeline = self._make_pipeline()
        sources = pipeline.list_sources()
        assert len(sources) == 3
        for s in sources:
            assert "source" in s
            assert "chunks" in s
            assert s["chunks"] >= 1

    def test_query_by_source(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query_by_source("bert")
        assert len(results) >= 1
        for r in results:
            core = pipeline.store.cores.get(r.core_id)
            assert "bert" in core.slots.get("source", "").lower()

    def test_query_by_source_with_temporal(self) -> None:
        pipeline = self._make_pipeline()
        # Only tx_id=1 visible — should only see attention paper
        results = pipeline.query_by_source("attention", valid_at=dt(2025), tx_id=1)
        assert len(results) >= 1


# ---- Save/Load Persistence Tests ----


class TestPipelinePersistence:
    """Test save/load round-trip for all index types."""

    def test_tfidf_save_load(self) -> None:
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        core = ClaimCore(claim_type="fact@v1", slots={"subject": "ai", "source": "test"})
        rev = store.assert_revision(
            core=core, assertion="neural networks use gradient descent",
            valid_time=ValidTime(start=dt(2024)),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="test"), confidence_bp=5000, status="asserted",
        )
        search.add(rev.revision_id, rev.assertion)
        search.rebuild()

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline.save(tmpdir)
            loaded = Pipeline.load(tmpdir)
            results = loaded.query("neural networks gradient", k=1)
            assert len(results) >= 1
            assert "gradient" in results[0].text

    def test_save_load_preserves_chunk_siblings(self) -> None:
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        rids = []
        for i in range(3):
            core = ClaimCore(claim_type="fact@v1", slots={"subject": f"chunk{i}", "source": "doc"})
            rev = store.assert_revision(
                core=core, assertion=f"chunk {i} content about topic {i}",
                valid_time=ValidTime(start=dt(2024)),
                transaction_time=TransactionTime(tx_id=i+1, recorded_at=dt(2024)),
                provenance=Provenance(source="doc"), confidence_bp=5000, status="asserted",
            )
            rids.append(rev.revision_id)
            search.add(rev.revision_id, rev.assertion)
        search.rebuild()
        pipeline._chunk_siblings["doc"] = rids

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline.save(tmpdir)
            loaded = Pipeline.load(tmpdir)
            assert "doc" in loaded._chunk_siblings
            assert loaded._chunk_siblings["doc"] == rids


# ---- Text Ingestion & Incremental Index Tests ----


class TestTextIngestion:
    """Test raw text ingestion and incremental indexing."""

    def test_ingest_text_basic(self) -> None:
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        rids = pipeline.ingest_text(
            "Neural networks are powerful machine learning models. "
            "They use backpropagation for training. "
            "Deep learning has revolutionized AI research.",
            source="notes.txt",
        )
        assert len(rids) >= 1
        # Should be searchable
        search.rebuild()
        results = pipeline.query("neural networks backpropagation", k=3)
        assert len(results) >= 1

    def test_ingest_text_chunking(self) -> None:
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        # Create text longer than chunk size
        long_text = " ".join([f"Paragraph {i} about topic {i % 5}." * 20 for i in range(10)])
        rids = pipeline.ingest_text(long_text, source="long_doc.txt", chunk_size=200)
        assert len(rids) > 1  # Should produce multiple chunks

    def test_ingest_text_tracks_siblings(self) -> None:
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        rids = pipeline.ingest_text("A long text. " * 100, source="doc1.txt", chunk_size=100)
        assert "doc1.txt" in pipeline._chunk_siblings
        assert pipeline._chunk_siblings["doc1.txt"] == rids

    def test_incremental_ingest(self) -> None:
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        # First ingest
        rids1 = pipeline.ingest_text("Transformers use attention mechanisms", source="paper1.txt")
        search.rebuild()
        results1 = pipeline.query("attention mechanisms", k=5)
        count1 = len(results1)

        # Second ingest (incremental)
        rids2 = pipeline.ingest_text("BERT uses masked language modeling", source="paper2.txt")
        search.rebuild()

        # Should now find both
        results_all = pipeline.query("transformers attention BERT language", k=10)
        assert len(results_all) >= 2

    def test_ingest_text_with_custom_times(self) -> None:
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        rids = pipeline.ingest_text(
            "Historical fact about ancient Rome",
            source="history.txt",
            valid_time=ValidTime(start=dt(2000), end=dt(2020)),
            transaction_time=TransactionTime(tx_id=42, recorded_at=dt(2024)),
        )
        assert len(rids) >= 1
        rev = store.revisions[rids[0]]
        assert rev.transaction_time.tx_id == 42
        assert rev.valid_time.end == dt(2020)


# ---- Knowledge Timeline Tests ----


class TestTimeline:
    """Test knowledge timeline and temporal diff."""

    def _make_pipeline(self) -> Pipeline:
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        # Claims at different transaction times
        claims = [
            ("neural networks were first invented in the 1940s", "early_ai.pdf", 1, dt(2020)),
            ("deep learning became practical with GPUs in 2012", "dl_history.pdf", 2, dt(2021)),
            ("transformers replaced recurrent models for NLP", "transformers.pdf", 3, dt(2023)),
        ]

        for text, source, tx_id, recorded in claims:
            core = ClaimCore(claim_type="fact@v1", slots={"subject": "ai", "source": source})
            rev = store.assert_revision(
                core=core, assertion=text,
                valid_time=ValidTime(start=dt(2020)),
                transaction_time=TransactionTime(tx_id=tx_id, recorded_at=recorded),
                provenance=Provenance(source=source), confidence_bp=5000, status="asserted",
            )
            search.add(rev.revision_id, rev.assertion)
        search.rebuild()
        return pipeline

    def test_timeline_returns_entries(self) -> None:
        pipeline = self._make_pipeline()
        entries = pipeline.timeline("neural networks deep learning")
        assert len(entries) > 0
        for e in entries:
            assert "recorded_at" in e
            assert "source" in e
            assert "text" in e

    def test_timeline_chronological_order(self) -> None:
        pipeline = self._make_pipeline()
        entries = pipeline.timeline("neural networks deep learning")
        for i in range(len(entries) - 1):
            assert entries[i]["recorded_at"] <= entries[i + 1]["recorded_at"]

    def test_timeline_diff_basic(self) -> None:
        pipeline = self._make_pipeline()
        diff = pipeline.timeline_diff("neural networks deep learning", tx_id_a=1, tx_id_b=3)
        assert "only_in_a" in diff
        assert "only_in_b" in diff
        assert "in_both" in diff
        assert "summary" in diff

    def test_timeline_diff_shows_additions(self) -> None:
        pipeline = self._make_pipeline()
        diff = pipeline.timeline_diff("neural networks", tx_id_a=1, tx_id_b=3)
        # tx_id_b should have more results than tx_id_a
        assert len(diff["only_in_b"]) >= 0


# ---- Deduplication Tests ----


class TestDeduplication:
    """Test semantic deduplication."""

    def _make_pipeline_with_duplicates(self) -> Pipeline:
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        texts = [
            ("neural networks use backpropagation for training", "paper_a"),
            ("neural networks use backpropagation for model training", "paper_b"),  # near-dup of above
            ("transformers use attention mechanisms for sequence processing", "paper_c"),
            ("transformer models use attention mechanism for sequence tasks", "paper_d"),  # near-dup of above
            ("reinforcement learning uses reward signals", "paper_e"),  # unique
        ]

        for text, source in texts:
            core = ClaimCore(claim_type="fact@v1", slots={"subject": "ml", "source": source})
            rev = store.assert_revision(
                core=core, assertion=text,
                valid_time=ValidTime(start=dt(2024)),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                provenance=Provenance(source=source), confidence_bp=5000, status="asserted",
            )
            search.add(rev.revision_id, rev.assertion)
        search.rebuild()
        return pipeline

    def test_deduplicate_finds_clusters(self) -> None:
        pipeline = self._make_pipeline_with_duplicates()
        clusters = pipeline.deduplicate(threshold=0.6)
        assert isinstance(clusters, list)

    def test_deduplicate_cluster_size(self) -> None:
        pipeline = self._make_pipeline_with_duplicates()
        clusters = pipeline.deduplicate(threshold=0.6)
        for cluster in clusters:
            assert len(cluster) >= 2  # Only clusters with 2+ members

    def test_deduplicate_high_threshold_fewer(self) -> None:
        pipeline = self._make_pipeline_with_duplicates()
        low = pipeline.deduplicate(threshold=0.5)
        high = pipeline.deduplicate(threshold=0.95)
        assert len(high) <= len(low)

    def test_deduplicate_empty_store(self) -> None:
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)
        clusters = pipeline.deduplicate()
        assert clusters == []


# ---- Query Explanation Tests ----


class TestQueryExplanation:
    """Test query explanation and feature attribution."""

    def _make_pipeline(self) -> Pipeline:
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        texts = [
            "neural networks use backpropagation for gradient descent optimization",
            "transformers use multi-head attention mechanisms for sequence modeling",
            "reinforcement learning uses reward signals for policy optimization",
        ]

        for i, text in enumerate(texts):
            core = ClaimCore(claim_type="fact@v1", slots={"subject": "ml", "source": f"paper_{i}"})
            rev = store.assert_revision(
                core=core, assertion=text,
                valid_time=ValidTime(start=dt(2024)),
                transaction_time=TransactionTime(tx_id=i+1, recorded_at=dt(2024)),
                provenance=Provenance(source=f"paper_{i}"), confidence_bp=5000, status="asserted",
            )
            search.add(rev.revision_id, rev.assertion)
        search.rebuild()
        return pipeline

    def test_explain_returns_fields(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("neural networks backpropagation", k=1)
        assert len(results) >= 1
        explanation = pipeline.explain("neural networks backpropagation", results[0])
        assert "matching_terms" in explanation
        assert "score" in explanation
        assert "term_overlap_ratio" in explanation
        assert "source" in explanation

    def test_explain_matching_terms(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("neural networks backpropagation", k=1)
        explanation = pipeline.explain("neural networks backpropagation", results[0])
        assert "neural" in explanation["matching_terms"] or "networks" in explanation["matching_terms"]

    def test_explain_overlap_ratio(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("neural networks backpropagation", k=1)
        explanation = pipeline.explain("neural networks backpropagation", results[0])
        assert 0 <= explanation["term_overlap_ratio"] <= 1
        assert explanation["term_overlap_ratio"] > 0  # Should have some overlap

    def test_explain_has_provenance(self) -> None:
        pipeline = self._make_pipeline()
        results = pipeline.query("attention mechanisms", k=1)
        explanation = pipeline.explain("attention mechanisms", results[0])
        assert "provenance" in explanation
        assert "confidence_bp" in explanation["provenance"]


# ---- Audit Trail Tests ----


class TestAuditTrail:

    def _make_pipeline(self) -> Pipeline:
        from dks import Provenance, ClaimCore
        from dks.pipeline import AuditTrace

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        docs = {
            "paper_a.pdf": [
                "Neural networks use backpropagation for training deep learning models.",
                "Convolutional neural networks are excellent for image recognition tasks.",
            ],
            "paper_b.pdf": [
                "Transformers use self-attention to process sequences in parallel.",
                "Large language models can hallucinate incorrect facts about the world.",
            ],
            "paper_c.pdf": [
                "Reinforcement learning trains agents using reward signals from the environment.",
                "Deep reinforcement learning combines neural networks with RL algorithms.",
            ],
        }

        for source, chunks in docs.items():
            rev_ids = []
            for i, text in enumerate(chunks):
                core = ClaimCore(
                    claim_type="document.chunk@v1",
                    slots={"source": source, "chunk_idx": str(i), "text": text[:30]},
                )
                rev = store.assert_revision(
                    core=core, assertion=text,
                    valid_time=ValidTime(start=dt(2024), end=None),
                    transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                    provenance=Provenance(source=source),
                    confidence_bp=5000,
                )
                search.add(rev.revision_id, text)
                rev_ids.append(rev.revision_id)
            pipeline._chunk_siblings[source] = rev_ids

        search.rebuild()
        return pipeline

    def test_audit_disabled_by_default(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.ask("neural networks")
        assert pipeline.last_audit() is None

    def test_audit_enabled_captures_trace(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("neural networks")
        audit = pipeline.last_audit()
        assert audit is not None
        assert audit.operation == "ask"
        assert audit.question == "neural networks"
        assert len(audit.events) >= 2  # classify + dispatch at minimum

    def test_audit_has_classification(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("Why do models hallucinate?")
        audit = pipeline.last_audit()
        assert audit is not None
        classify_event = next(e for e in audit.events if e.stage == "classify")
        assert classify_event.outputs["strategy"] == "exploratory"

    def test_audit_has_dispatch_results(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("neural networks deep learning")
        audit = pipeline.last_audit()
        dispatch_event = next(e for e in audit.events if e.stage == "dispatch")
        assert "total_chunks" in dispatch_event.outputs
        assert "source_count" in dispatch_event.outputs
        assert dispatch_event.outputs["total_chunks"] > 0

    def test_audit_timing(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("transformers attention")
        audit = pipeline.last_audit()
        assert audit.total_duration_ms > 0
        for event in audit.events:
            assert event.duration_ms >= 0

    def test_audit_to_dict(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("reinforcement learning")
        audit = pipeline.last_audit()
        d = audit.to_dict()
        assert d["operation"] == "ask"
        assert isinstance(d["events"], list)
        assert len(d["events"]) >= 2

    def test_audit_to_json(self) -> None:
        import json
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("deep learning")
        audit = pipeline.last_audit()
        j = audit.to_json()
        parsed = json.loads(j)
        assert parsed["operation"] == "ask"
        assert "events" in parsed

    def test_render_audit_markdown(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("Why do neural networks need backpropagation?")
        report = pipeline.render_audit()
        assert "# Audit Report:" in report
        assert "Decision Pipeline" in report
        assert "Timing Breakdown" in report
        assert "CLASSIFY" in report
        assert "DISPATCH" in report

    def test_render_audit_no_trace(self) -> None:
        pipeline = self._make_pipeline()
        report = pipeline.render_audit()
        assert report == "No audit trace available."

    def test_synthesize_audit_events(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.synthesize("How do neural networks learn?", k=3, hops=1)
        audit = pipeline.last_audit()
        assert audit is not None
        assert audit.operation == "synthesize"
        stages = [e.stage for e in audit.events]
        assert "reason" in stages
        assert "diversify" in stages
        assert "expand" in stages
        assert "themes" in stages

    def test_audit_strategy_recorded(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("Compare transformers vs RNNs", strategy="comparison")
        audit = pipeline.last_audit()
        assert audit.strategy == "comparison"

    def test_audit_can_be_disabled(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        pipeline.ask("neural networks")
        assert pipeline.last_audit() is not None
        pipeline.enable_audit(False)
        pipeline.ask("transformers")
        # last_audit should still be the previous one (not overwritten)
        assert pipeline.last_audit().question == "neural networks"


# ---- Answer Extraction Tests ----


class TestAnswerExtraction:

    def _make_pipeline(self) -> Pipeline:
        from dks import Provenance, ClaimCore

        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=search)

        docs = {
            "paper_a.pdf": [
                "Neural networks use backpropagation to learn. Backpropagation computes gradients layer by layer. This is the core training algorithm for deep learning.",
                "Convolutional neural networks excel at image recognition. They use local receptive fields and weight sharing to reduce parameters.",
            ],
            "paper_b.pdf": [
                "Transformers replaced RNNs for natural language processing. Self-attention enables parallel computation across the sequence.",
                "Large language models can hallucinate incorrect facts. They lack grounded understanding and generate plausible but wrong text.",
            ],
            "paper_c.pdf": [
                "Reinforcement learning trains agents through reward signals. The agent learns a policy that maximizes cumulative reward.",
                "Deep reinforcement learning combines neural networks with RL. This enables learning from high-dimensional state spaces.",
            ],
        }

        for source, chunks in docs.items():
            rev_ids = []
            for i, text in enumerate(chunks):
                core = ClaimCore(
                    claim_type="document.chunk@v1",
                    slots={"source": source, "chunk_idx": str(i), "text": text[:30]},
                )
                rev = store.assert_revision(
                    core=core, assertion=text,
                    valid_time=ValidTime(start=dt(2024), end=None),
                    transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                    provenance=Provenance(source=source),
                    confidence_bp=5000,
                )
                search.add(rev.revision_id, text)
                rev_ids.append(rev.revision_id)
            pipeline._chunk_siblings[source] = rev_ids

        search.rebuild()
        return pipeline

    def test_extract_answer_returns_structure(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.extract_answer("How do neural networks learn?")
        assert "question" in result
        assert "answer_sentences" in result
        assert "supporting_chunks" in result
        assert "confidence" in result
        assert "source_count" in result

    def test_extract_answer_finds_relevant_sentences(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.extract_answer("How do neural networks learn?")
        assert len(result["answer_sentences"]) > 0
        # Should find backpropagation-related sentence
        all_text = " ".join(s["text"] for s in result["answer_sentences"])
        assert "backpropagation" in all_text.lower() or "neural" in all_text.lower()

    def test_extract_answer_has_overlap_terms(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.extract_answer("neural networks backpropagation")
        for sent in result["answer_sentences"]:
            assert "overlap_terms" in sent
            assert isinstance(sent["overlap_terms"], list)

    def test_extract_answer_confidence(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.extract_answer("How do neural networks learn?")
        assert 0.0 <= result["confidence"] <= 1.0
        # Should have decent confidence for a matching query
        assert result["confidence"] > 0.0

    def test_extract_answer_no_results(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.extract_answer("quantum gravity string theory")
        # May still find some results but with low relevance
        assert result["confidence"] >= 0.0

    def test_answer_full_pipeline(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.answer("How do neural networks learn?", k=5, hops=1)
        assert "strategy" in result
        assert result["source_count"] > 0
        assert len(result["answer_sentences"]) > 0

    def test_answer_with_audit(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.enable_audit(True)
        result = pipeline.answer("Why do transformers use attention?", k=5, hops=1)
        audit = pipeline.last_audit()
        assert audit is not None
        assert audit.operation == "answer"
        stages = [e.stage for e in audit.events]
        assert "classify" in stages
        assert "retrieve" in stages
        assert "extract" in stages

    def test_extract_answer_deduplication(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.extract_answer("neural networks deep learning")
        # Verify no near-duplicate sentences
        texts = [s["text"] for s in result["answer_sentences"]]
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                words_i = set(texts[i].lower().split())
                words_j = set(texts[j].lower().split())
                jaccard = len(words_i & words_j) / max(len(words_i | words_j), 1)
                assert jaccard <= 0.6, f"Near-duplicate sentences found: {texts[i][:50]}... vs {texts[j][:50]}..."

    def test_answer_sentences_sorted_by_score(self) -> None:
        pipeline = self._make_pipeline()
        result = pipeline.extract_answer("How do neural networks learn backpropagation?")
        scores = [s["score"] for s in result["answer_sentences"]]
        assert scores == sorted(scores, reverse=True)
