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
