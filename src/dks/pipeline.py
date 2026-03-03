"""Pipeline orchestrator — the ONE canonical execution path for DKS.

Orchestrates: extract → resolve → commit → index for ingestion,
and embed → search → filter for queries.

The commitment boundary runs through this module: extraction and resolution
are non-deterministic, but once committed to the KnowledgeStore, everything
becomes deterministic data.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from .core import (
    ClaimCore,
    KnowledgeStore,
    MergeResult,
    Provenance,
    TransactionTime,
    ValidTime,
    canonicalize_text,
)
from .extract import ExtractionResult, Extractor, PDFExtractor, TextChunker
from .index import (
    CrossEncoderReranker,
    DenseSearchIndex,
    EmbeddingBackend,
    HybridSearchIndex,
    KnowledgeGraph,
    SearchIndex,
    SearchResult,
    TfidfSearchIndex,
)
from .resolve import CascadingResolver, ResolutionDecision, Resolver


class Pipeline:
    """End-to-end orchestrator for DKS operations.

    This is the canonical execution path. All operations flow through here:
    - ingest(): text → claims → committed revisions
    - ingest_pdf(): PDF → text → chunks → committed revisions
    - ingest_directory(): directory of PDFs → batch ingestion
    - query(): question → search → temporal-filtered results
    - query_multi(): question → multi-document retrieval
    - merge(): combine two pipelines deterministically
    """

    def __init__(
        self,
        store: KnowledgeStore | None = None,
        extractor: Extractor | None = None,
        resolver: Resolver | None = None,
        embedding_backend: EmbeddingBackend | None = None,
        *,
        search_index: TfidfSearchIndex | DenseSearchIndex | HybridSearchIndex | SearchIndex | None = None,
        reranker: CrossEncoderReranker | None = None,
    ) -> None:
        self.store = store or KnowledgeStore()
        self._extractor = extractor
        self._resolver = resolver
        self._index: TfidfSearchIndex | DenseSearchIndex | HybridSearchIndex | SearchIndex | None = search_index
        if self._index is None and embedding_backend is not None:
            self._index = SearchIndex(self.store, embedding_backend)
        self._reranker = reranker
        self._tx_counter = 0
        # Track chunk siblings: source -> [revision_ids in order]
        self._chunk_siblings: dict[str, list[str]] = {}

    def _next_tx(self) -> TransactionTime:
        """Auto-generate next transaction time."""
        self._tx_counter += 1
        return TransactionTime(
            tx_id=self._tx_counter,
            recorded_at=datetime.now(timezone.utc),
        )

    def ingest(
        self,
        text: str,
        *,
        valid_time: ValidTime,
        transaction_time: TransactionTime,
        provenance: Provenance | None = None,
        claim_types: list[str] | None = None,
        confidence_bp: int = 5000,
    ) -> list[str]:
        """Extract claims from text, resolve entities, commit to store, index.

        This is the main ingestion path. It crosses the commitment boundary:
        non-deterministic extraction → deterministic storage.

        Args:
            text: Unstructured input text.
            valid_time: When the facts in the text were true.
            transaction_time: When this ingestion is happening.
            provenance: Source provenance (auto-generated if None).
            claim_types: Optional filter for extraction.
            confidence_bp: Default confidence for extracted claims (0-10000).

        Returns:
            List of revision_ids for all committed revisions.
        """
        if self._extractor is None:
            raise ValueError("No extractor configured. Set extractor in Pipeline init.")

        # Phase 1: Extract (non-deterministic)
        extraction = self._extractor.extract(text, claim_types=claim_types)

        # Phase 2: Resolve entities (non-deterministic)
        resolved_claims = []
        for claim in extraction.claims:
            if self._resolver is not None:
                resolved_slots = {}
                for role, value in claim.slots.items():
                    decision = self._resolver.resolve(value)
                    if decision is not None:
                        resolved_slots[role] = decision.resolved_entity_id
                    else:
                        resolved_slots[role] = value
                resolved_claim = ClaimCore(
                    claim_type=claim.claim_type,
                    slots=resolved_slots,
                )
            else:
                resolved_claim = claim
            resolved_claims.append(resolved_claim)

        # Phase 3: Commit to store (COMMITMENT BOUNDARY — deterministic from here)
        revision_ids: list[str] = []
        prov = provenance or Provenance(source="pipeline:ingest")

        for i, claim in enumerate(resolved_claims):
            extraction_prov = extraction.provenance[i] if i < len(extraction.provenance) else prov

            # For document chunks, use full chunk text as assertion (from evidence_ref)
            if extraction_prov.evidence_ref and len(extraction_prov.evidence_ref) > 500:
                assertion = extraction_prov.evidence_ref
            else:
                assertion = text[:500]

            revision = self.store.assert_revision(
                core=claim,
                assertion=assertion,
                valid_time=valid_time,
                transaction_time=transaction_time,
                provenance=extraction_prov,
                confidence_bp=confidence_bp,
                status="asserted",
            )
            revision_ids.append(revision.revision_id)

            # Phase 4: Index for search (use full chunk text for better search)
            if self._index is not None:
                index_text = extraction_prov.evidence_ref or text[:500]
                self._index.add(revision.revision_id, index_text)

        return revision_ids

    def ingest_pdf(
        self,
        path: str | Path,
        *,
        valid_time: ValidTime | None = None,
        transaction_time: TransactionTime | None = None,
        confidence_bp: int = 5000,
        chunker: TextChunker | None = None,
    ) -> list[str]:
        """Ingest a single PDF file: extract text, chunk, commit, index.

        Args:
            path: Path to the PDF file.
            valid_time: When the facts are true (defaults to open-ended from now).
            transaction_time: When ingested (auto-generated if None).
            confidence_bp: Confidence for extracted claims.
            chunker: Optional custom chunker (uses default if None).

        Returns:
            List of revision_ids for all committed chunks.
        """
        pdf_extractor = PDFExtractor(chunker=chunker)
        extraction = pdf_extractor.extract_pdf(path)

        if not extraction.claims:
            return []

        vt = valid_time or ValidTime(
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=None,
        )
        tt = transaction_time or self._next_tx()

        revision_ids: list[str] = []

        for i, claim in enumerate(extraction.claims):
            prov = extraction.provenance[i] if i < len(extraction.provenance) else Provenance(
                source=f"pdf:{Path(path).name}",
            )

            # Use full chunk text as the assertion for search
            assertion = prov.evidence_ref or str(claim.slots)

            revision = self.store.assert_revision(
                core=claim,
                assertion=assertion,
                valid_time=vt,
                transaction_time=tt,
                provenance=prov,
                confidence_bp=confidence_bp,
                status="asserted",
            )
            revision_ids.append(revision.revision_id)

            # Index the chunk text for search
            if self._index is not None:
                self._index.add(revision.revision_id, assertion)

        # Track chunk siblings for context expansion
        source_name = Path(path).name
        self._chunk_siblings[source_name] = revision_ids

        return revision_ids

    def ingest_text(
        self,
        text: str,
        *,
        source: str = "text",
        valid_time: ValidTime | None = None,
        transaction_time: TransactionTime | None = None,
        confidence_bp: int = 5000,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
    ) -> list[str]:
        """Ingest raw text: chunk, commit, index. No PDF or extractor needed.

        This is the simplest ingestion path for plain text content.

        Args:
            text: Raw text to ingest.
            source: Source identifier for provenance.
            valid_time: When the facts are true.
            transaction_time: When ingested (auto-generated if None).
            confidence_bp: Confidence for chunks.
            chunk_size: Characters per chunk.
            chunk_overlap: Overlap between chunks.

        Returns:
            List of revision_ids for committed chunks.
        """
        chunker = TextChunker(chunk_size=chunk_size, overlap=chunk_overlap, min_chunk=10)
        chunks = chunker.chunk(text)

        if not chunks:
            # If chunker produces nothing (text too short), use raw text
            if text.strip():
                chunks = [text.strip()]
            else:
                return []

        vt = valid_time or ValidTime(start=datetime(2020, 1, 1, tzinfo=timezone.utc))
        tt = transaction_time or self._next_tx()

        revision_ids: list[str] = []
        for i, chunk_text in enumerate(chunks):
            core = ClaimCore(
                claim_type="document.chunk@v1",
                slots={
                    "source": canonicalize_text(source),
                    "chunk_idx": str(i),
                    "text": canonicalize_text(chunk_text[:200]),
                },
            )
            prov = Provenance(source=source, evidence_ref=chunk_text)

            revision = self.store.assert_revision(
                core=core,
                assertion=chunk_text,
                valid_time=vt,
                transaction_time=tt,
                provenance=prov,
                confidence_bp=confidence_bp,
                status="asserted",
            )
            revision_ids.append(revision.revision_id)

            if self._index is not None:
                self._index.add(revision.revision_id, chunk_text)

        # Track siblings for context expansion
        self._chunk_siblings[source] = revision_ids

        return revision_ids

    def ingest_directory(
        self,
        directory: str | Path,
        *,
        pattern: str = "*.pdf",
        valid_time: ValidTime | None = None,
        confidence_bp: int = 5000,
        chunker: TextChunker | None = None,
        progress: bool = True,
    ) -> dict[str, list[str]]:
        """Ingest all PDFs in a directory.

        Args:
            directory: Path to directory containing PDFs.
            pattern: Glob pattern for files (default: *.pdf).
            valid_time: When the facts are true.
            confidence_bp: Confidence for extracted claims.
            chunker: Optional custom chunker.
            progress: Print progress to stderr.

        Returns:
            Dict mapping filename → list of revision_ids.
        """
        directory = Path(directory)
        pdf_files = sorted(directory.glob(pattern))

        if not pdf_files:
            return {}

        results: dict[str, list[str]] = {}
        errors: dict[str, str] = {}

        for i, pdf_path in enumerate(pdf_files):
            if progress:
                print(
                    f"\r  [{i+1}/{len(pdf_files)}] {pdf_path.name[:60]}...",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )

            try:
                revision_ids = self.ingest_pdf(
                    pdf_path,
                    valid_time=valid_time,
                    confidence_bp=confidence_bp,
                    chunker=chunker,
                )
                results[pdf_path.name] = revision_ids
            except Exception as e:
                errors[pdf_path.name] = str(e)
                if progress:
                    print(
                        f"\n  ERROR: {pdf_path.name}: {e}",
                        file=sys.stderr,
                    )

        if progress:
            total_chunks = sum(len(v) for v in results.values())
            print(
                f"\n  Done: {len(results)} files, {total_chunks} chunks, {len(errors)} errors",
                file=sys.stderr,
            )

        # Rebuild search index after batch ingestion
        if hasattr(self._index, 'rebuild'):
            self._index.rebuild()

        return results

    def query(
        self,
        question: str,
        *,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
        k: int = 5,
    ) -> list[SearchResult]:
        """Search for relevant claims with temporal filtering.

        Args:
            question: Natural language query.
            valid_at: When the facts should be true (for temporal filter).
            tx_id: Transaction time cutoff (for temporal filter).
            k: Maximum number of results.

        Returns:
            List of SearchResult ordered by relevance.
        """
        if self._index is None:
            raise ValueError(
                "No search index configured. "
                "Set embedding_backend or search_index in Pipeline init."
            )

        # If re-ranker is configured, retrieve more candidates then re-rank
        if self._reranker is not None:
            candidates = self._index.search(
                question,
                k=k * 4,  # Over-retrieve for better re-ranking
                valid_at=valid_at,
                tx_id=tx_id,
            )
            return self._reranker.rerank(question, candidates, top_k=k)

        return self._index.search(
            question,
            k=k,
            valid_at=valid_at,
            tx_id=tx_id,
        )

    def query_multi(
        self,
        question: str,
        *,
        k: int = 10,
        group_by_source: bool = True,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> dict[str, list[SearchResult]]:
        """Multi-document retrieval: find relevant chunks across all sources.

        Returns results grouped by source document, enabling cross-document
        reasoning.

        Args:
            question: Natural language query.
            k: Total results to retrieve before grouping.
            group_by_source: If True, group results by source document.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            Dict mapping source filename → list of SearchResult.
        """
        results = self.query(
            question,
            k=k,
            valid_at=valid_at,
            tx_id=tx_id,
        )

        if not group_by_source:
            return {"all": results}

        grouped: dict[str, list[SearchResult]] = {}
        for result in results:
            # Get the source from the claim's slots
            core = self.store.cores.get(result.core_id)
            source = "unknown"
            if core and "source" in core.slots:
                source = core.slots["source"]
            grouped.setdefault(source, []).append(result)

        return grouped

    def query_exact(
        self,
        core_id: str,
        *,
        valid_at: datetime,
        tx_id: int,
    ):
        """Direct query by core_id with bitemporal coordinates.

        This bypasses search and goes straight to the deterministic core.
        """
        return self.store.query_as_of(
            core_id,
            valid_at=valid_at,
            tx_id=tx_id,
        )

    # ---- Context Expansion ----

    def expand_context(
        self,
        result: SearchResult,
        *,
        window: int = 2,
    ) -> list[SearchResult]:
        """Expand a search result to include surrounding chunks from the same document.

        When a relevant chunk is found, this retrieves the N chunks before
        and after it from the same source document, providing full context
        for reasoning.

        Args:
            result: A SearchResult to expand context around.
            window: Number of chunks before/after to include.

        Returns:
            Ordered list of SearchResults (including the original).
        """
        core = self.store.cores.get(result.core_id)
        if core is None:
            return [result]

        source = core.slots.get("source", "")
        if not source:
            return [result]

        # Find sibling chunks for this source
        siblings = self._chunk_siblings.get(source)

        # If siblings not tracked, try to reconstruct from store
        if siblings is None:
            siblings = self._reconstruct_siblings(source)

        if not siblings:
            return [result]

        # Find position of this result in the sibling list
        try:
            pos = siblings.index(result.revision_id)
        except ValueError:
            return [result]

        # Get window of surrounding chunks
        start = max(0, pos - window)
        end = min(len(siblings), pos + window + 1)

        expanded = []
        for rid in siblings[start:end]:
            rev = self.store.revisions.get(rid)
            if rev:
                expanded.append(SearchResult(
                    core_id=rev.core_id,
                    revision_id=rid,
                    score=result.score if rid == result.revision_id else result.score * 0.5,
                    text=rev.assertion,
                ))

        return expanded

    def _reconstruct_siblings(self, source: str) -> list[str]:
        """Reconstruct sibling chunk order from store data."""
        # Find all chunks from this source
        chunks: list[tuple[int, str]] = []  # (chunk_idx, revision_id)
        for rev_id, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            if core and core.slots.get("source") == source:
                try:
                    idx = int(core.slots.get("chunk_idx", "0"))
                except (ValueError, TypeError):
                    idx = 0
                chunks.append((idx, rev_id))

        if not chunks:
            return []

        chunks.sort()
        siblings = [rid for _, rid in chunks]
        self._chunk_siblings[source] = siblings
        return siblings

    def query_with_context(
        self,
        question: str,
        *,
        k: int = 5,
        context_window: int = 1,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Search with automatic context expansion.

        Like query(), but each result includes surrounding chunks from
        the same document for extended context.

        Args:
            question: Natural language query.
            k: Number of seed results.
            context_window: Chunks before/after each result to include.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of SearchResults including expanded context, ordered
            by seed result relevance with context chunks adjacent.
        """
        seeds = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        if context_window <= 0:
            return seeds

        seen: set[str] = set()
        expanded: list[SearchResult] = []

        for seed in seeds:
            context = self.expand_context(seed, window=context_window)
            for r in context:
                if r.revision_id not in seen:
                    seen.add(r.revision_id)
                    expanded.append(r)

        return expanded

    # ---- Persistence ----

    def save(self, directory: str | Path) -> None:
        """Save the entire pipeline state to disk.

        Saves:
        - KnowledgeStore → canonical JSON (deterministic, reproducible)
        - TF-IDF index → pickle (for fast reload)
        - Knowledge graph → pickle (for fast reload)
        - Pipeline metadata → JSON

        Args:
            directory: Directory to save into (created if needed).
        """
        import json
        import pickle

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        # 1. Save the deterministic store
        self.store.to_canonical_json_file(str(directory / "store.json"))

        # 2. Save TF-IDF index state
        tfidf_component = None
        dense_component = None

        if isinstance(self._index, HybridSearchIndex):
            tfidf_component = self._index._tfidf
            dense_component = self._index._dense
        elif isinstance(self._index, TfidfSearchIndex):
            tfidf_component = self._index._tfidf
        elif isinstance(self._index, DenseSearchIndex):
            dense_component = self._index._dense

        if tfidf_component is not None:
            tfidf_state = {
                "texts": tfidf_component._texts,
                "revision_ids": tfidf_component._revision_ids,
                "fitted": tfidf_component._fitted,
            }
            with open(directory / "tfidf_state.pkl", "wb") as f:
                pickle.dump(tfidf_state, f)
            if tfidf_component._fitted:
                with open(directory / "tfidf_vectorizer.pkl", "wb") as f:
                    pickle.dump(tfidf_component._vectorizer, f)
                with open(directory / "tfidf_matrix.pkl", "wb") as f:
                    pickle.dump(tfidf_component._matrix, f)

        # 2b. Save dense embeddings
        if dense_component is not None:
            dense_component.save_embeddings(directory / "dense_embeddings.pkl")

        # 3. Save knowledge graph
        if hasattr(self, "_graph") and self._graph is not None:
            graph_state = {
                "adjacency": self._graph._adjacency,
                "clusters": self._graph._clusters,
                "revision_cluster": self._graph._revision_cluster,
                "cluster_labels": self._graph._cluster_labels,
            }
            with open(directory / "graph.pkl", "wb") as f:
                pickle.dump(graph_state, f)

        # 4. Save chunk siblings map
        if self._chunk_siblings:
            with open(directory / "chunk_siblings.pkl", "wb") as f:
                pickle.dump(self._chunk_siblings, f)

        # 5. Save metadata
        meta: dict[str, Any] = {
            "version": "0.5.0",
            "cores": len(self.store.cores),
            "revisions": len(self.store.revisions),
            "tx_counter": self._tx_counter,
        }
        if isinstance(self._index, HybridSearchIndex):
            meta["index_type"] = "hybrid"
            meta["indexed"] = self._index._dense.size
        elif isinstance(self._index, DenseSearchIndex):
            meta["index_type"] = "dense"
            meta["indexed"] = self._index._dense.size
        elif isinstance(self._index, TfidfSearchIndex):
            meta["index_type"] = "tfidf"
            meta["indexed"] = self._index.size
        if hasattr(self, "_graph") and self._graph is not None:
            meta["graph_nodes"] = self._graph.total_nodes
            meta["graph_edges"] = self._graph.total_edges
            meta["graph_clusters"] = self._graph.total_clusters

        with open(directory / "meta.json", "w") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, directory: str | Path) -> "Pipeline":
        """Load a saved pipeline from disk.

        Args:
            directory: Directory containing saved pipeline state.

        Returns:
            Fully restored Pipeline with store, index, and graph.
        """
        import json
        import pickle

        directory = Path(directory)

        # 1. Load the deterministic store
        store = KnowledgeStore.from_canonical_json_file(
            str(directory / "store.json")
        )

        # 2. Load metadata
        with open(directory / "meta.json") as f:
            meta = json.load(f)

        # 3. Restore search index
        search_index = None
        index_type = meta.get("index_type", "tfidf")

        # 3a. Restore TF-IDF component (used by tfidf and hybrid)
        tfidf = None
        if (directory / "tfidf_state.pkl").exists():
            from .index import TfidfIndex

            with open(directory / "tfidf_state.pkl", "rb") as f:
                tfidf_state = pickle.load(f)

            tfidf = TfidfIndex.__new__(TfidfIndex)
            tfidf._texts = tfidf_state["texts"]
            tfidf._revision_ids = tfidf_state["revision_ids"]
            tfidf._fitted = tfidf_state["fitted"]

            if tfidf._fitted and (directory / "tfidf_vectorizer.pkl").exists():
                with open(directory / "tfidf_vectorizer.pkl", "rb") as f:
                    tfidf._vectorizer = pickle.load(f)
                with open(directory / "tfidf_matrix.pkl", "rb") as f:
                    tfidf._matrix = pickle.load(f)
            else:
                from sklearn.feature_extraction.text import TfidfVectorizer
                tfidf._vectorizer = TfidfVectorizer()
                tfidf._matrix = None

        # 3b. Restore dense component (used by dense and hybrid)
        dense = None
        if (directory / "dense_embeddings.pkl").exists():
            from .index import SentenceTransformerIndex
            dense = SentenceTransformerIndex.__new__(SentenceTransformerIndex)
            # Set defaults before loading
            dense._batch_size = 64
            dense._dirty = True
            try:
                from sentence_transformers import SentenceTransformer
                dense._model = SentenceTransformer("all-MiniLM-L6-v2")
                dense._dimension = dense._model.get_sentence_embedding_dimension()
            except ImportError:
                dense._model = None
                dense._dimension = 384
            dense.load_embeddings(directory / "dense_embeddings.pkl")

        # 3c. Assemble the correct index type
        if index_type == "hybrid" and tfidf is not None and dense is not None:
            from .index import HybridSearchIndex
            search_index = HybridSearchIndex.__new__(HybridSearchIndex)
            search_index._store = store
            search_index._tfidf = tfidf
            search_index._dense = dense
            search_index._alpha = 0.5
            search_index._rrf_k = 60
        elif index_type == "dense" and dense is not None:
            from .index import DenseSearchIndex
            search_index = DenseSearchIndex.__new__(DenseSearchIndex)
            search_index._store = store
            search_index._dense = dense
        elif tfidf is not None:
            search_index = TfidfSearchIndex.__new__(TfidfSearchIndex)
            search_index._store = store
            search_index._tfidf = tfidf

        # 4. Create pipeline
        pipeline = cls(store=store, search_index=search_index)
        pipeline._tx_counter = meta.get("tx_counter", 0)

        # 5. Restore knowledge graph
        if (directory / "graph.pkl").exists():
            from .index import KnowledgeGraph

            with open(directory / "graph.pkl", "rb") as f:
                graph_state = pickle.load(f)

            graph = KnowledgeGraph()
            graph._adjacency = graph_state["adjacency"]
            graph._clusters = graph_state["clusters"]
            graph._revision_cluster = graph_state["revision_cluster"]
            graph._cluster_labels = graph_state["cluster_labels"]
            pipeline._graph = graph

        # 6. Restore chunk siblings
        if (directory / "chunk_siblings.pkl").exists():
            with open(directory / "chunk_siblings.pkl", "rb") as f:
                pipeline._chunk_siblings = pickle.load(f)

        return pipeline

    def merge(self, other: "Pipeline") -> MergeResult:
        """Merge another pipeline's store into this one.

        Note: Only the KnowledgeStore data is merged. The search index
        is NOT automatically rebuilt — call rebuild_index() after merge
        if search is needed.

        Returns:
            MergeResult with merged store and any conflicts.
        """
        result = self.store.merge(other.store)
        self.store = result.merged
        if self._index is not None:
            self._index._store = self.store
        return result

    def rebuild_index(self) -> int:
        """Rebuild the search index from all revisions in the store.

        Returns:
            Number of revisions indexed.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        items = []
        for revision_id, revision in self.store.revisions.items():
            items.append((revision_id, revision.assertion))
        self._index.add_batch(items)

        # Rebuild index matrix
        if hasattr(self._index, 'rebuild'):
            self._index.rebuild()

        return len(items)

    def stats(self) -> dict[str, Any]:
        """Return store and index statistics."""
        s: dict[str, Any] = {
            "cores": len(self.store.cores),
            "revisions": len(self.store.revisions),
            "relations": len(self.store.relations),
        }
        if self._index is not None:
            s["indexed"] = self._index.size
        return s

    # ---- Knowledge Graph ----

    def build_graph(
        self,
        *,
        similarity_threshold: float = 0.15,
        max_neighbors: int = 10,
        n_clusters: int = 50,
    ) -> KnowledgeGraph:
        """Build a knowledge graph linking related chunks.

        Uses TF-IDF similarity to discover connections between chunks.
        Clusters chunks into topics for efficient navigation.

        Args:
            similarity_threshold: Minimum cosine similarity for a link.
            max_neighbors: Maximum neighbors per chunk.
            n_clusters: Number of topic clusters.

        Returns:
            KnowledgeGraph with adjacency lists and topic clusters.
        """
        # Get the TF-IDF component from whichever index type we have
        tfidf_component = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf_component = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf_component = self._index._tfidf

        if tfidf_component is None:
            raise ValueError("Graph building requires TfidfSearchIndex or HybridSearchIndex.")

        self._graph = KnowledgeGraph()
        self._graph.build_from_tfidf(
            tfidf_component,
            similarity_threshold=similarity_threshold,
            max_neighbors=max_neighbors,
            n_clusters=n_clusters,
        )
        return self._graph

    @property
    def graph(self) -> KnowledgeGraph | None:
        """Access the knowledge graph (None if not built)."""
        return getattr(self, "_graph", None)

    def neighbors(
        self,
        revision_id: str,
        *,
        k: int = 5,
    ) -> list[SearchResult]:
        """Find chunks related to a given chunk via the knowledge graph.

        Args:
            revision_id: The revision to find neighbors of.
            k: Maximum neighbors to return.

        Returns:
            List of SearchResult for neighboring chunks.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        neighbor_ids = self._graph.neighbors(revision_id, k=k)
        results = []
        for nid, score in neighbor_ids:
            rev = self.store.revisions.get(nid)
            if rev:
                results.append(SearchResult(
                    core_id=rev.core_id,
                    revision_id=nid,
                    score=score,
                    text=rev.assertion,
                ))
        return results

    def topics(self) -> list[dict[str, Any]]:
        """List all discovered topic clusters.

        Returns:
            List of dicts with cluster_id, size, and label terms.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")
        return self._graph.topics()

    def topic_chunks(
        self,
        cluster_id: int,
        *,
        k: int = 10,
    ) -> list[SearchResult]:
        """Get chunks belonging to a topic cluster.

        Args:
            cluster_id: The cluster to retrieve.
            k: Maximum chunks to return.

        Returns:
            List of SearchResult for chunks in the cluster.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        member_ids = self._graph.cluster_members(cluster_id)[:k]
        results = []
        for rid in member_ids:
            rev = self.store.revisions.get(rid)
            if rev:
                results.append(SearchResult(
                    core_id=rev.core_id,
                    revision_id=rid,
                    score=1.0,
                    text=rev.assertion,
                ))
        return results

    # ---- Reasoning Layer ----

    def reason(
        self,
        question: str,
        *,
        k: int = 5,
        hops: int = 2,
        expand_k: int = 3,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> ReasoningResult:
        """Multi-hop retrieval: iteratively expand context to answer complex questions.

        Unlike simple query(), reason() performs multiple retrieval rounds:
        1. Initial retrieval: get top-k chunks for the question
        2. Extract key terms from retrieved chunks
        3. Expand: query with extracted terms to find related context
        4. Repeat for `hops` iterations
        5. Deduplicate and rank all found chunks

        Args:
            question: Natural language question.
            k: Results per hop.
            hops: Number of expansion rounds.
            expand_k: Number of expansion queries per hop.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            ReasoningResult with all retrieved chunks, sources, and reasoning trace.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        all_results: dict[str, SearchResult] = {}  # revision_id -> result
        trace: list[dict[str, Any]] = []
        seen_queries: set[str] = set()

        # Hop 0: initial retrieval
        initial = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in initial:
            all_results[r.revision_id] = r
        trace.append({
            "hop": 0,
            "query": question,
            "results": len(initial),
            "new": len(initial),
        })
        seen_queries.add(question.lower().strip())

        # Expansion hops
        for hop in range(1, hops + 1):
            # Extract key terms from current results
            expansion_terms = self._extract_expansion_terms(
                list(all_results.values()),
                seen_queries,
                max_terms=expand_k,
            )

            new_this_hop = 0
            for term in expansion_terms:
                if term.lower().strip() in seen_queries:
                    continue
                seen_queries.add(term.lower().strip())

                hop_results = self.query(term, k=k, valid_at=valid_at, tx_id=tx_id)
                for r in hop_results:
                    if r.revision_id not in all_results:
                        all_results[r.revision_id] = r
                        new_this_hop += 1

            trace.append({
                "hop": hop,
                "expansion_terms": expansion_terms,
                "new": new_this_hop,
                "total": len(all_results),
            })

            if new_this_hop == 0:
                break  # No new information found

        # Rank all results by relevance to original question
        final_results = self._rerank_for_question(
            question, list(all_results.values())
        )

        # Group by source
        sources: dict[str, list[SearchResult]] = {}
        for r in final_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        return ReasoningResult(
            question=question,
            results=final_results,
            sources=sources,
            trace=trace,
            total_hops=len(trace) - 1,
        )

    def discover(
        self,
        seed_query: str,
        *,
        k: int = 5,
        depth: int = 2,
        similarity_threshold: float = 0.15,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Discover related knowledge by traversing the similarity graph.

        Starting from seed results, find progressively more distant but
        related chunks. Useful for exploratory analysis.

        Args:
            seed_query: Starting query.
            k: Results per expansion.
            depth: How many levels of expansion.
            similarity_threshold: Minimum score to follow.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            All discovered chunks, ordered by discovery path.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        discovered: dict[str, SearchResult] = {}
        frontier: list[str] = []  # queries to explore

        # Start with seed
        seed_results = self.query(seed_query, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in seed_results:
            if r.score >= similarity_threshold:
                discovered[r.revision_id] = r
                # Extract text snippets as new queries
                frontier.append(r.text[:200])

        for level in range(depth):
            new_frontier: list[str] = []
            for text in frontier[:k]:
                # Use first few significant words as expansion query
                words = text.split()[:10]
                expansion = " ".join(words)
                results = self.query(expansion, k=k, valid_at=valid_at, tx_id=tx_id)
                for r in results:
                    if r.revision_id not in discovered and r.score >= similarity_threshold:
                        discovered[r.revision_id] = r
                        new_frontier.append(r.text[:200])
            frontier = new_frontier
            if not frontier:
                break

        return list(discovered.values())

    def coverage(
        self,
        topic: str,
        *,
        k: int = 20,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> CoverageReport:
        """Analyze what the store knows about a topic.

        Returns a structured report of all related knowledge, grouped by
        source document and subtopic.

        Args:
            topic: Topic to analyze.
            k: Maximum chunks to analyze.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            CoverageReport with sources, subtopics, and gap analysis.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k, valid_at=valid_at, tx_id=tx_id)

        # Group by source
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Extract subtopics (key terms from results)
        all_text = " ".join(r.text for r in results)
        subtopics = self._extract_key_terms(all_text, max_terms=10)

        return CoverageReport(
            topic=topic,
            total_chunks=len(results),
            sources=by_source,
            subtopics=subtopics,
            source_count=len(by_source),
        )

    def evidence_chain(
        self,
        claim: str,
        *,
        k: int = 5,
        max_chain_length: int = 5,
        min_relevance: float = 0.05,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> "EvidenceChain":
        """Build an evidence chain supporting or refuting a claim.

        Given a claim like "transformers are better than RNNs for NLP",
        this method finds:
        1. Direct evidence (chunks that directly address the claim)
        2. Supporting evidence (chunks that support the direct evidence)
        3. Contradicting evidence (chunks that challenge the claim)
        4. Links between evidence chunks through the knowledge graph

        The chain traces how evidence connects across documents, enabling
        cross-document reasoning.

        Args:
            claim: A factual claim to investigate.
            k: Number of chunks to retrieve per search.
            max_chain_length: Maximum links in a single evidence chain.
            min_relevance: Minimum score threshold.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            EvidenceChain with supporting, contradicting, and linked evidence.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        # Step 1: Find direct evidence
        direct = self.query(claim, k=k, valid_at=valid_at, tx_id=tx_id)
        direct = [r for r in direct if r.score >= min_relevance]

        # Step 2: Extract the key aspects of the claim for targeted search
        key_terms = self._extract_key_terms(claim, max_terms=5)

        # Step 3: Search for supporting and contradicting evidence
        # Use negation terms to find counterarguments
        all_evidence: dict[str, SearchResult] = {}
        for r in direct:
            all_evidence[r.revision_id] = r

        # Expand via key terms
        for term in key_terms:
            expanded = self.query(term, k=k, valid_at=valid_at, tx_id=tx_id)
            for r in expanded:
                if r.revision_id not in all_evidence and r.score >= min_relevance:
                    all_evidence[r.revision_id] = r

        # Step 4: Build chains via graph traversal
        chains: list[list[SearchResult]] = []
        if hasattr(self, "_graph") and self._graph is not None:
            for seed_result in direct[:3]:
                chain = [seed_result]
                current_id = seed_result.revision_id
                visited = {current_id}

                for _ in range(max_chain_length - 1):
                    neighbors = self._graph.neighbors(current_id, k=3)
                    best_next = None
                    best_score = -1.0

                    for nid, nscore in neighbors:
                        if nid not in visited and nscore > min_relevance:
                            rev = self.store.revisions.get(nid)
                            if rev and nscore > best_score:
                                best_next = SearchResult(
                                    core_id=rev.core_id,
                                    revision_id=nid,
                                    score=nscore,
                                    text=rev.assertion,
                                )
                                best_score = nscore

                    if best_next is None:
                        break

                    chain.append(best_next)
                    visited.add(best_next.revision_id)
                    current_id = best_next.revision_id
                    all_evidence[best_next.revision_id] = best_next

                if len(chain) > 1:
                    chains.append(chain)

        # Step 5: Score each piece of evidence for/against the claim
        supporting: list[SearchResult] = []
        related: list[SearchResult] = []

        for r in sorted(all_evidence.values(), key=lambda x: -x.score):
            if r.revision_id in {d.revision_id for d in direct}:
                supporting.append(r)
            else:
                related.append(r)

        # Group by source
        sources: dict[str, list[SearchResult]] = {}
        for r in all_evidence.values():
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        return EvidenceChain(
            claim=claim,
            direct_evidence=direct,
            supporting_evidence=supporting,
            related_evidence=related,
            chains=chains,
            sources=sources,
            total_evidence=len(all_evidence),
        )

    def query_deep(
        self,
        question: str,
        *,
        k_per_subquery: int = 5,
        max_subqueries: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> DeepQueryResult:
        """Intelligent query decomposition and targeted retrieval.

        This is the "figure out what we need, then pull it out" capability.

        1. Decompose the question into sub-questions (facets)
        2. Identify which topic clusters are relevant
        3. Retrieve targeted chunks for each sub-question
        4. Follow graph connections to find additional context
        5. Assemble a comprehensive answer context

        Args:
            question: Complex natural language question.
            k_per_subquery: Results per sub-query.
            max_subqueries: Maximum number of sub-queries to generate.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            DeepQueryResult with organized context from across the store.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        # Step 1: Decompose question into sub-queries
        subqueries = self._decompose_question(question, max_subqueries)

        # Step 2: Identify relevant topic clusters
        relevant_clusters: dict[int, float] = {}
        if hasattr(self, "_graph") and self._graph is not None:
            for sq in subqueries:
                results = self.query(sq, k=3, valid_at=valid_at, tx_id=tx_id)
                for r in results:
                    cluster_id = self._graph.cluster_of(r.revision_id)
                    if cluster_id is not None:
                        current = relevant_clusters.get(cluster_id, 0)
                        relevant_clusters[cluster_id] = max(current, r.score)

        # Step 3: Targeted retrieval for each sub-query
        facets: list[QueryFacet] = []
        all_chunks: dict[str, SearchResult] = {}

        for sq in subqueries:
            results = self.query(sq, k=k_per_subquery, valid_at=valid_at, tx_id=tx_id)
            for r in results:
                all_chunks[r.revision_id] = r

            # Step 4: Follow graph connections for top results
            graph_results: list[SearchResult] = []
            if hasattr(self, "_graph") and self._graph is not None:
                for r in results[:2]:
                    for nid, nscore in self._graph.neighbors(r.revision_id, k=3):
                        if nid not in all_chunks:
                            rev = self.store.revisions.get(nid)
                            if rev:
                                sr = SearchResult(
                                    core_id=rev.core_id,
                                    revision_id=nid,
                                    score=nscore * 0.5,  # Discount graph-discovered results
                                    text=rev.assertion,
                                )
                                graph_results.append(sr)
                                all_chunks[nid] = sr

            facets.append(QueryFacet(
                subquery=sq,
                results=results,
                graph_results=graph_results,
            ))

        # Step 5: Re-rank all collected chunks
        final_results = self._rerank_for_question(
            question, list(all_chunks.values())
        )

        # Organize by source
        sources: dict[str, list[SearchResult]] = {}
        for r in final_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        # Build relevant topics info
        topic_info: list[dict[str, Any]] = []
        if hasattr(self, "_graph") and self._graph is not None:
            for cid, score in sorted(relevant_clusters.items(), key=lambda x: -x[1])[:5]:
                labels = self._graph.cluster_label(cid)
                size = len(self._graph.cluster_members(cid))
                topic_info.append({
                    "cluster_id": cid,
                    "relevance": score,
                    "labels": labels,
                    "size": size,
                })

        return DeepQueryResult(
            question=question,
            subqueries=subqueries,
            facets=facets,
            results=final_results,
            sources=sources,
            relevant_topics=topic_info,
        )

    # ---- Answer Synthesis ----

    def synthesize(
        self,
        question: str,
        *,
        k: int = 10,
        context_window: int = 1,
        hops: int = 2,
        max_context_chars: int = 30000,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> "SynthesisResult":
        """Full-stack retrieval and synthesis for answering complex questions.

        This is the highest-level reasoning method. It combines:
        1. Multi-hop retrieval (reason) for breadth
        2. Context expansion for depth within documents
        3. Source grouping for cross-document analysis
        4. Evidence chain construction for traceability
        5. Formatted output ready for LLM consumption

        Args:
            question: Complex natural language question.
            k: Number of seed results per retrieval step.
            context_window: Chunks before/after each seed to include.
            hops: Number of multi-hop expansion rounds.
            max_context_chars: Maximum characters in the output context.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            SynthesisResult with organized, source-attributed context.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        # Step 1: Multi-hop retrieval
        reasoning = self.reason(question, k=k, hops=hops, valid_at=valid_at, tx_id=tx_id)

        # Step 1b: Diversify seed results for cross-source coverage
        diversified = self._diversify_results(reasoning.results, max_per_source=3)

        # Step 2: Expand context for each seed, grouped by source
        seed_groups: dict[str, list[SearchResult]] = {}  # source -> expanded chunks
        seen: set[str] = set()

        for r in diversified:
            if r.revision_id in seen:
                continue

            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"

            if context_window > 0:
                context = self.expand_context(r, window=context_window)
                for cr in context:
                    if cr.revision_id not in seen:
                        seen.add(cr.revision_id)
                        seed_groups.setdefault(source, []).append(cr)
            else:
                seen.add(r.revision_id)
                seed_groups.setdefault(source, []).append(r)

        # Step 2b: Interleave sources for diversity in final result order
        # Round-robin across sources, sorted by best seed score
        for source in seed_groups:
            seed_groups[source].sort(key=lambda r: -r.score)

        sorted_group_keys = sorted(
            seed_groups.keys(),
            key=lambda s: -seed_groups[s][0].score if seed_groups[s] else 0,
        )

        expanded_results: list[SearchResult] = []
        round_idx = 0
        max_per_source = max(3, context_window * 2 + 1)  # seed + neighbors
        while True:
            added = False
            for source in sorted_group_keys:
                group = seed_groups[source]
                if round_idx < len(group) and round_idx < max_per_source:
                    expanded_results.append(group[round_idx])
                    added = True
            round_idx += 1
            if not added:
                break

        # Step 3: Group by source document
        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Sort chunks within each source by score (seeds before neighbors)
        for source in by_source:
            by_source[source].sort(key=lambda r: -r.score)

        # Sort sources by relevance (max seed score, not sum — avoids bulk-context bias)
        source_scores: dict[str, float] = {}
        for source, chunks in by_source.items():
            source_scores[source] = max(r.score for r in chunks) if chunks else 0.0
        sorted_sources = sorted(by_source.keys(), key=lambda s: -source_scores[s])

        # Step 4: Build structured context
        context_parts: list[str] = []
        context_parts.append(f"# Research Context: {question}\n")
        context_parts.append(
            f"Retrieved {len(expanded_results)} chunks from "
            f"{len(by_source)} sources via {reasoning.total_hops}-hop retrieval.\n"
        )

        total_chars = 0
        source_summaries: list[dict[str, Any]] = []

        for source in sorted_sources:
            chunks = by_source[source]
            if total_chars >= max_context_chars:
                break

            context_parts.append(f"\n## Source: {source}")
            context_parts.append(f"({len(chunks)} relevant chunks)\n")

            for chunk in chunks:
                remaining = max_context_chars - total_chars
                if remaining <= 0:
                    break
                text = chunk.text[:remaining]
                score_label = f" [relevance: {chunk.score:.3f}]" if chunk.score > 0 else ""
                context_parts.append(f"### Chunk{score_label}")
                context_parts.append(text)
                context_parts.append("")
                total_chars += len(text)

            source_summaries.append({
                "source": source,
                "chunks": len(chunks),
                "relevance": source_scores[source],
            })

        # Step 5: Extract key themes
        all_text = " ".join(r.text[:200] for r in expanded_results[:20])
        themes = self._extract_key_terms(all_text, max_terms=8)

        return SynthesisResult(
            question=question,
            results=expanded_results,
            sources=by_source,
            source_summaries=source_summaries,
            themes=themes,
            context="\n".join(context_parts),
            reasoning_trace=reasoning.trace,
            total_chunks=len(expanded_results),
        )

    # ---- Adaptive Retrieval ----

    def ask(
        self,
        question: str,
        *,
        k: int = 10,
        strategy: str = "auto",
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Intelligent adaptive retrieval — the single entry point for all queries.

        Automatically classifies the query and selects the best retrieval
        strategy:

        - "factual": Direct search + re-rank for specific fact lookup
        - "comparison": Search both terms, cross-document analysis
        - "exploratory": Multi-hop + graph traversal for open-ended questions
        - "multi-aspect": Decompose and search each aspect independently
        - "auto": Classify automatically (default)

        Args:
            question: Any natural language question.
            k: Maximum seed results.
            strategy: Override the automatic strategy selection.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            SynthesisResult with organized, source-attributed context.
        """
        if strategy == "auto":
            strategy = self._classify_query(question)

        if strategy == "factual":
            return self._retrieve_factual(question, k=k, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "comparison":
            return self._retrieve_comparison(question, k=k, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "exploratory":
            return self.synthesize(question, k=k, context_window=1, hops=3, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "multi-aspect":
            return self._retrieve_multi_aspect(question, k=k, valid_at=valid_at, tx_id=tx_id)
        else:
            return self.synthesize(question, k=k, context_window=1, hops=2, valid_at=valid_at, tx_id=tx_id)

    def _classify_query(self, question: str) -> str:
        """Classify a query into a retrieval strategy type.

        Uses heuristic patterns to determine query intent:
        - Comparison: "vs", "compare", "difference between", "better than"
        - Multi-aspect: conjunctions, multiple topics, "and", complex structure
        - Factual: "what is", "define", "how does", short and specific
        - Exploratory: "why", "explain", "how", open-ended
        """
        import re
        q = question.lower().strip()

        # Comparison patterns
        comparison_patterns = [
            r'\bvs\.?\b', r'\bversus\b', r'\bcompare\b', r'\bcompar',
            r'\bdifference\s+between\b', r'\bbetter\s+than\b',
            r'\badvantages?\s+(?:of|over)\b', r'\bpros?\s+and\s+cons?\b',
        ]
        for pat in comparison_patterns:
            if re.search(pat, q):
                return "comparison"

        # Multi-aspect: multiple conjunctions, long queries
        conjunctions = len(re.findall(r'\b(?:and|or|also|additionally)\b', q))
        if conjunctions >= 2 or len(q) > 150:
            return "multi-aspect"

        # Factual: short, specific, "what is"
        factual_patterns = [
            r'^what\s+is\b', r'^define\b', r'^who\s+(?:is|was|are)\b',
            r'^when\s+(?:did|was|is)\b', r'^where\s+(?:is|was|are)\b',
        ]
        for pat in factual_patterns:
            if re.search(pat, q):
                return "factual"

        # Exploratory: open-ended questions (check before short-query fallback)
        exploratory_patterns = [
            r'^why\b', r'^how\s+(?:do|does|can|could|should|have|has|did)\b',
            r'^explain\b', r'\bimpact\b', r'\bimplication',
            r'\bfuture\b', r'\btrend',
            r'^which\b.*\bmost\b', r'^what\b.*\bmost\b',  # superlative questions
            r'\bevolved?\b', r'\bchanged?\b', r'\bsuperseded\b',
            r'\blimitation', r'\bfundamental\b', r'\bpromising\b',
            r'\bconflict', r'\bcontradic',
        ]
        for pat in exploratory_patterns:
            if re.search(pat, q):
                return "exploratory"

        # Short queries are usually factual
        if len(q.split()) <= 4:
            return "factual"

        # Default to exploratory for longer questions
        if len(q.split()) > 8:
            return "exploratory"

        return "factual"

    def _retrieve_factual(
        self,
        question: str,
        *,
        k: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Factual retrieval: direct search, high precision."""
        results = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)

        # Expand top result for context
        expanded: list[SearchResult] = []
        seen: set[str] = set()

        if results:
            context = self.expand_context(results[0], window=1)
            for r in context:
                if r.revision_id not in seen:
                    seen.add(r.revision_id)
                    expanded.append(r)

        for r in results[1:]:
            if r.revision_id not in seen:
                seen.add(r.revision_id)
                expanded.append(r)

        # Build synthesis
        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Answer Context: {question}\n"]
        for r in expanded[:k]:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "?") if core else "?"
            context_parts.append(f"## From: {source}")
            context_parts.append(r.text[:1000])
            context_parts.append("")

        return SynthesisResult(
            question=question,
            results=expanded,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=self._extract_key_terms(" ".join(r.text[:200] for r in expanded[:5]), max_terms=5),
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(results), "new": len(results)}],
            total_chunks=len(expanded),
        )

    def _retrieve_comparison(
        self,
        question: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Comparison retrieval: search for both sides, cross-reference."""
        import re

        # Extract the two sides of the comparison
        sides = re.split(r'\s+(?:vs\.?|versus|compared?\s+to|or)\s+', question, flags=re.IGNORECASE)

        all_results: dict[str, SearchResult] = {}
        side_results: dict[str, list[SearchResult]] = {}

        for side in sides:
            side = side.strip().rstrip("?.,!")
            if len(side) < 3:
                continue
            results = self.query(side, k=k // 2, valid_at=valid_at, tx_id=tx_id)
            side_results[side] = results
            for r in results:
                all_results[r.revision_id] = r

        # Also search the full question
        full_results = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in full_results:
            all_results[r.revision_id] = r

        final = sorted(all_results.values(), key=lambda r: -r.score)

        # Build structured comparison context
        by_source: dict[str, list[SearchResult]] = {}
        for r in final:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Comparison: {question}\n"]
        for side, results in side_results.items():
            context_parts.append(f"## Perspective: {side}")
            for r in results[:k // 2]:
                context_parts.append(r.text[:800])
                context_parts.append("")

        return SynthesisResult(
            question=question,
            results=final,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=list(side_results.keys()),
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(full_results), "new": len(full_results)}],
            total_chunks=len(final),
        )

    def _retrieve_multi_aspect(
        self,
        question: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Multi-aspect retrieval: decompose and search each aspect."""
        # Use query_deep for decomposition
        deep = self.query_deep(question, k_per_subquery=k // 3, max_subqueries=4, valid_at=valid_at, tx_id=tx_id)

        # Expand top results with context
        expanded: list[SearchResult] = []
        seen: set[str] = set()
        for r in deep.results:
            if r.revision_id not in seen:
                context = self.expand_context(r, window=1)
                for cr in context:
                    if cr.revision_id not in seen:
                        seen.add(cr.revision_id)
                        expanded.append(cr)

        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Multi-Aspect Analysis: {question}\n"]
        for facet in deep.facets:
            context_parts.append(f"## Aspect: {facet.subquery}")
            for r in facet.results[:3]:
                context_parts.append(r.text[:600])
                context_parts.append("")

        return SynthesisResult(
            question=question,
            results=expanded,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=deep.subqueries,
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(deep.results), "new": len(deep.results)}],
            total_chunks=len(expanded),
        )

    # ---- Knowledge Timeline ----

    def timeline(
        self,
        topic: str,
        *,
        k: int = 20,
    ) -> list[dict[str, Any]]:
        """Show how knowledge about a topic evolved over time.

        Returns a chronological view of claims related to a topic, ordered
        by transaction time (when the knowledge was recorded). This enables
        questions like "how has our understanding of X changed?"

        Args:
            topic: Topic to trace through time.
            k: Maximum chunks to analyze.

        Returns:
            List of timeline entries, each with:
              - revision_id: str
              - text: str (chunk content)
              - source: str
              - recorded_at: str (ISO timestamp)
              - tx_id: int
              - valid_from: str (ISO timestamp)
              - valid_until: str | None
              - status: str ("asserted" or "retracted")
              - score: float (relevance to topic)
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k)

        entries: list[dict[str, Any]] = []
        for r in results:
            rev = self.store.revisions.get(r.revision_id)
            if rev is None:
                continue

            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"

            entries.append({
                "revision_id": r.revision_id,
                "text": r.text[:500],
                "source": source,
                "recorded_at": rev.transaction_time.recorded_at.isoformat(),
                "tx_id": rev.transaction_time.tx_id,
                "valid_from": rev.valid_time.start.isoformat(),
                "valid_until": rev.valid_time.end.isoformat() if rev.valid_time.end else None,
                "status": rev.status,
                "score": r.score,
            })

        # Sort chronologically by transaction time
        entries.sort(key=lambda e: e["recorded_at"])
        return entries

    def timeline_diff(
        self,
        topic: str,
        *,
        tx_id_a: int,
        tx_id_b: int,
        k: int = 20,
    ) -> dict[str, Any]:
        """Compare what was known about a topic at two different points in time.

        Returns chunks that appear in one time but not the other, enabling
        "what changed between version A and version B?" analysis.

        Args:
            topic: Topic to compare.
            tx_id_a: Earlier transaction time.
            tx_id_b: Later transaction time.
            k: Maximum chunks per query.

        Returns:
            Dict with:
              - only_in_a: chunks visible at tx_id_a but not tx_id_b
              - only_in_b: chunks visible at tx_id_b but not tx_id_a
              - in_both: chunks visible at both times
              - summary: human-readable diff summary
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)

        results_a = self.query(topic, k=k, valid_at=far_future, tx_id=tx_id_a)
        results_b = self.query(topic, k=k, valid_at=far_future, tx_id=tx_id_b)

        ids_a = {r.revision_id for r in results_a}
        ids_b = {r.revision_id for r in results_b}

        only_a = [r for r in results_a if r.revision_id not in ids_b]
        only_b = [r for r in results_b if r.revision_id not in ids_a]
        both = [r for r in results_b if r.revision_id in ids_a]

        summary_parts = [f"Topic: {topic}"]
        summary_parts.append(f"At tx_id={tx_id_a}: {len(results_a)} chunks")
        summary_parts.append(f"At tx_id={tx_id_b}: {len(results_b)} chunks")
        summary_parts.append(f"Added: {len(only_b)}, Removed: {len(only_a)}, Unchanged: {len(both)}")

        return {
            "only_in_a": only_a,
            "only_in_b": only_b,
            "in_both": both,
            "summary": " | ".join(summary_parts),
        }

    # ---- Provenance & Citation ----

    def provenance_of(self, result: SearchResult) -> dict[str, Any]:
        """Get full provenance for a search result.

        Returns structured provenance data including source document,
        page number, chunk position, ingestion time, and confidence.

        Args:
            result: A SearchResult from any query method.

        Returns:
            Dict with source, page, chunk_idx, ingested_at, valid_time,
            confidence_bp, and raw provenance.
        """
        rev = self.store.revisions.get(result.revision_id)
        if rev is None:
            return {"error": "revision not found", "revision_id": result.revision_id}

        core = self.store.cores.get(result.core_id)

        info: dict[str, Any] = {
            "revision_id": result.revision_id,
            "core_id": result.core_id,
            "source": rev.provenance.source if rev.provenance else "unknown",
            "evidence_ref_length": len(rev.provenance.evidence_ref) if rev.provenance and rev.provenance.evidence_ref else 0,
            "confidence_bp": rev.confidence_bp,
            "status": rev.status,
            "valid_time": {
                "start": rev.valid_time.start.isoformat(),
                "end": rev.valid_time.end.isoformat() if rev.valid_time.end else None,
            },
            "transaction_time": {
                "tx_id": rev.transaction_time.tx_id,
                "recorded_at": rev.transaction_time.recorded_at.isoformat(),
            },
        }

        # Extract structured fields from claim slots
        if core:
            info["claim_type"] = core.claim_type
            if "source" in core.slots:
                info["document"] = core.slots["source"]
            if "page_start" in core.slots:
                info["page"] = int(core.slots["page_start"])
            if "chunk_idx" in core.slots:
                info["chunk_index"] = int(core.slots["chunk_idx"])

        return info

    def cite(
        self,
        result: SearchResult,
        *,
        style: str = "inline",
    ) -> str:
        """Generate a formatted citation for a search result.

        Args:
            result: A SearchResult from any query method.
            style: Citation style — "inline", "full", or "markdown".

        Returns:
            Formatted citation string.
        """
        prov = self.provenance_of(result)
        if "error" in prov:
            return f"[unknown source]"

        source = prov.get("document", prov.get("source", "unknown"))
        page = prov.get("page")
        chunk_idx = prov.get("chunk_index")
        tx_time = prov.get("transaction_time", {}).get("recorded_at", "")

        if style == "inline":
            parts = [source]
            if page is not None:
                parts.append(f"p.{page}")
            return f"[{', '.join(parts)}]"

        elif style == "markdown":
            parts = [f"**{source}**"]
            if page is not None:
                parts.append(f"page {page}")
            if chunk_idx is not None:
                parts.append(f"chunk {chunk_idx}")
            return " | ".join(parts)

        else:  # full
            parts = [f"Source: {source}"]
            if page is not None:
                parts.append(f"Page: {page}")
            if chunk_idx is not None:
                parts.append(f"Chunk: {chunk_idx}")
            parts.append(f"Confidence: {prov.get('confidence_bp', 0)}/10000")
            if tx_time:
                parts.append(f"Ingested: {tx_time[:10]}")
            return " | ".join(parts)

    def cite_results(
        self,
        results: list[SearchResult],
        *,
        style: str = "inline",
        deduplicate: bool = True,
    ) -> list[str]:
        """Generate citations for a list of search results.

        Args:
            results: List of SearchResult from any query method.
            style: Citation style.
            deduplicate: If True, skip duplicate sources.

        Returns:
            List of formatted citation strings.
        """
        citations: list[str] = []
        seen_sources: set[str] = set()

        for r in results:
            citation = self.cite(r, style=style)
            if deduplicate:
                prov = self.provenance_of(r)
                source_key = prov.get("document", prov.get("source", r.revision_id))
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
            citations.append(citation)

        return citations

    def query_by_source(
        self,
        source: str,
        *,
        k: int = 50,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Retrieve all chunks from a specific source document.

        Args:
            source: Source document name (or partial match).
            k: Maximum results.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of SearchResult from the specified source.
        """
        results: list[SearchResult] = []
        source_lower = source.lower()

        for rid, rev in self.store.revisions.items():
            if len(results) >= k:
                break

            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue

            doc_source = core.slots.get("source", "")
            if source_lower not in doc_source.lower():
                continue

            # Apply temporal filter
            if valid_at is not None and tx_id is not None:
                winner = self.store.query_as_of(
                    rev.core_id, valid_at=valid_at, tx_id=tx_id,
                )
                if winner is None or winner.revision_id != rid:
                    continue

            results.append(SearchResult(
                core_id=rev.core_id,
                revision_id=rid,
                score=1.0,
                text=rev.assertion,
            ))

        return results

    def list_sources(self) -> list[dict[str, Any]]:
        """List all unique source documents in the store.

        Returns:
            List of dicts with source name, chunk count, and page range.
        """
        sources: dict[str, dict[str, Any]] = {}

        for rid, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue

            source = core.slots.get("source", "unknown")
            if source not in sources:
                sources[source] = {
                    "source": source,
                    "chunks": 0,
                    "pages": set(),
                    "first_ingested": rev.transaction_time.recorded_at,
                }

            sources[source]["chunks"] += 1
            page = core.slots.get("page_start")
            if page is not None:
                sources[source]["pages"].add(int(page))

            if rev.transaction_time.recorded_at < sources[source]["first_ingested"]:
                sources[source]["first_ingested"] = rev.transaction_time.recorded_at

        result = []
        for info in sorted(sources.values(), key=lambda x: -x["chunks"]):
            pages = sorted(info["pages"])
            result.append({
                "source": info["source"],
                "chunks": info["chunks"],
                "page_range": f"{min(pages)}-{max(pages)}" if pages else "unknown",
                "total_pages": len(pages),
                "first_ingested": info["first_ingested"].isoformat(),
            })

        return result

    # ---- Semantic Deduplication ----

    def deduplicate(
        self,
        *,
        threshold: float = 0.85,
        k: int = 100,
    ) -> list[list[SearchResult]]:
        """Find clusters of near-duplicate chunks across documents.

        Uses TF-IDF pairwise similarity to identify chunks that say
        essentially the same thing. Useful for corpus quality analysis.

        Args:
            threshold: Minimum similarity to consider as duplicate (0-1).
            k: Maximum chunks to analyze. Set high for full corpus scan.

        Returns:
            List of duplicate clusters (each cluster is a list of SearchResult).
            Only returns clusters with 2+ members.
        """
        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        if tfidf is None or not tfidf._fitted:
            return []

        try:
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            return []

        # Use the full TF-IDF matrix
        n = min(len(tfidf._texts), k)
        if n < 2:
            return []

        sim_matrix = cosine_similarity(tfidf._matrix[:n])

        # Union-find for clustering
        parent: dict[int, int] = {i: i for i in range(n)}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i in range(n):
            for j in range(i + 1, n):
                if float(sim_matrix[i][j]) >= threshold:
                    union(i, j)

        # Group by cluster
        clusters: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            clusters.setdefault(root, []).append(i)

        # Build results — only clusters with 2+ members
        result: list[list[SearchResult]] = []
        for members in clusters.values():
            if len(members) < 2:
                continue
            cluster_results = []
            for idx in members:
                rid = tfidf._revision_ids[idx]
                rev = self.store.revisions.get(rid)
                if rev:
                    cluster_results.append(SearchResult(
                        core_id=rev.core_id,
                        revision_id=rid,
                        score=1.0,
                        text=tfidf._texts[idx],
                    ))
            if len(cluster_results) >= 2:
                result.append(cluster_results)

        # Sort by cluster size (largest first)
        result.sort(key=lambda c: -len(c))
        return result

    # ---- Query Explanation ----

    def explain(
        self,
        question: str,
        result: SearchResult,
    ) -> dict[str, Any]:
        """Explain why a specific result was returned for a question.

        Provides feature attribution showing which terms matched,
        the similarity score breakdown, and contextual factors.

        Args:
            question: The original query.
            result: A SearchResult to explain.

        Returns:
            Dict with:
              - question: str
              - result_text: str (first 200 chars)
              - score: float
              - matching_terms: list[str] (shared terms)
              - question_unique_terms: list[str]
              - result_unique_terms: list[str]
              - term_overlap_ratio: float
              - source: str
              - provenance: dict
              - graph_distance: int | None (if graph exists)
        """
        import re

        # Extract terms
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "and", "or", "but", "not", "this", "that", "it", "its",
        }

        q_terms = set(re.findall(r'\b\w{3,}\b', question.lower())) - stop_words
        r_terms = set(re.findall(r'\b\w{3,}\b', result.text.lower())) - stop_words

        matching = q_terms & r_terms
        q_unique = q_terms - r_terms
        r_unique = r_terms - q_terms

        overlap_ratio = len(matching) / max(len(q_terms), 1)

        # Provenance
        prov = self.provenance_of(result)

        # Graph distance
        graph_distance = None
        if hasattr(self, "_graph") and self._graph is not None:
            # Try to find the shortest path from any query result to this result
            query_results = self.query(question, k=3)
            for qr in query_results:
                if qr.revision_id == result.revision_id:
                    graph_distance = 0
                    break
                path = self._graph.path(qr.revision_id, result.revision_id)
                if path is not None:
                    d = len(path) - 1
                    if graph_distance is None or d < graph_distance:
                        graph_distance = d

        return {
            "question": question,
            "result_text": result.text[:200],
            "score": result.score,
            "matching_terms": sorted(matching),
            "question_unique_terms": sorted(q_unique),
            "result_unique_terms": sorted(r_unique)[:20],
            "term_overlap_ratio": round(overlap_ratio, 3),
            "source": prov.get("document", prov.get("source", "unknown")),
            "provenance": prov,
            "graph_distance": graph_distance,
        }

    # ---- Contradiction Detection ----

    def contradictions(
        self,
        topic: str,
        *,
        k: int = 20,
        similarity_threshold: float = 0.15,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Find potential contradictions in the knowledge base about a topic.

        Searches for chunks that are topically similar but come from different
        sources, then applies negation and opposition detection to find conflicts.

        Args:
            topic: Topic to search for contradictions.
            k: Number of chunks to analyze.
            similarity_threshold: Minimum TF-IDF similarity between chunks.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of contradiction dicts, each with:
              - chunk_a: SearchResult
              - chunk_b: SearchResult
              - source_a: str
              - source_b: str
              - similarity: float (topical similarity)
              - conflict_signals: list[str] (what triggered the detection)
              - confidence_bp: int (0-10000, how likely this is a real contradiction)
        """
        import re

        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k, valid_at=valid_at, tx_id=tx_id)
        if len(results) < 2:
            return []

        # Get source for each result
        result_sources: dict[str, str] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            result_sources[r.revision_id] = (
                core.slots.get("source", "unknown") if core else "unknown"
            )

        # Compute pairwise similarity using TF-IDF
        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        pairs_with_similarity: list[tuple[int, int, float]] = []

        if tfidf is not None and tfidf._fitted:
            try:
                from sklearn.metrics.pairwise import cosine_similarity
                texts = [r.text for r in results]
                vecs = tfidf._vectorizer.transform(texts)
                sim_matrix = cosine_similarity(vecs)

                for i in range(len(results)):
                    for j in range(i + 1, len(results)):
                        sim = float(sim_matrix[i][j])
                        if sim >= similarity_threshold:
                            # Only consider cross-source pairs
                            if result_sources[results[i].revision_id] != result_sources[results[j].revision_id]:
                                pairs_with_similarity.append((i, j, sim))
            except Exception:
                pass

        if not pairs_with_similarity:
            # Fallback: compare all cross-source pairs
            for i in range(len(results)):
                for j in range(i + 1, len(results)):
                    if result_sources[results[i].revision_id] != result_sources[results[j].revision_id]:
                        pairs_with_similarity.append((i, j, 0.5))

        # Detect contradiction signals
        negation_words = {
            "not", "no", "never", "neither", "nor", "none", "nothing",
            "nowhere", "hardly", "scarcely", "barely", "doesn't", "don't",
            "didn't", "won't", "wouldn't", "couldn't", "shouldn't",
            "isn't", "aren't", "wasn't", "weren't", "cannot", "can't",
        }
        opposition_pairs = [
            ("increase", "decrease"), ("improve", "worsen"), ("better", "worse"),
            ("higher", "lower"), ("more", "less"), ("faster", "slower"),
            ("larger", "smaller"), ("stronger", "weaker"), ("efficient", "inefficient"),
            ("effective", "ineffective"), ("successful", "unsuccessful"),
            ("advantage", "disadvantage"), ("benefit", "drawback"),
            ("outperform", "underperform"), ("superior", "inferior"),
            ("significant", "insignificant"), ("positive", "negative"),
            ("optimal", "suboptimal"), ("accurate", "inaccurate"),
        ]

        contradictions: list[dict[str, Any]] = []

        for i, j, sim in pairs_with_similarity:
            a, b = results[i], results[j]
            a_words = set(re.findall(r'\b\w+\b', a.text.lower()))
            b_words = set(re.findall(r'\b\w+\b', b.text.lower()))

            signals: list[str] = []
            confidence = 0

            # Signal 1: One has negation of shared concept
            a_negations = a_words & negation_words
            b_negations = b_words & negation_words
            if a_negations and not b_negations:
                signals.append(f"negation in A: {', '.join(a_negations)}")
                confidence += 2000
            elif b_negations and not a_negations:
                signals.append(f"negation in B: {', '.join(b_negations)}")
                confidence += 2000

            # Signal 2: Opposition word pairs
            for pos, neg in opposition_pairs:
                if pos in a_words and neg in b_words:
                    signals.append(f"opposition: A='{pos}' vs B='{neg}'")
                    confidence += 3000
                elif neg in a_words and pos in b_words:
                    signals.append(f"opposition: A='{neg}' vs B='{pos}'")
                    confidence += 3000

            # Signal 3: Numerical disagreement on same topic
            a_nums = set(re.findall(r'\b\d+(?:\.\d+)?%?\b', a.text))
            b_nums = set(re.findall(r'\b\d+(?:\.\d+)?%?\b', b.text))
            shared_context = a_words & b_words - negation_words
            if a_nums and b_nums and a_nums != b_nums and len(shared_context) > 5:
                signals.append(f"different numbers: A={a_nums} vs B={b_nums}")
                confidence += 1500

            # Signal 4: High topical similarity + different sources = potential conflict
            if sim > 0.4:
                signals.append(f"high similarity ({sim:.2f}) across sources")
                confidence += 1000

            if signals:
                confidence = min(confidence, 10000)
                contradictions.append({
                    "chunk_a": a,
                    "chunk_b": b,
                    "source_a": result_sources[a.revision_id],
                    "source_b": result_sources[b.revision_id],
                    "similarity": sim,
                    "conflict_signals": signals,
                    "confidence_bp": confidence,
                })

        # Sort by confidence
        contradictions.sort(key=lambda c: -c["confidence_bp"])
        return contradictions

    def confidence(
        self,
        claim: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Assess confidence in a claim based on evidence in the store.

        Scores a claim based on:
        1. Source diversity (more independent sources = higher confidence)
        2. Internal consistency (do sources agree?)
        3. Recency (newer evidence weighted higher)
        4. Evidence density (how many relevant chunks found)

        Args:
            claim: Factual claim to evaluate.
            k: Number of chunks to analyze.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            Dict with:
              - confidence_bp: int (0-10000)
              - evidence_count: int
              - source_count: int
              - supporting: int (chunks that support)
              - contradicting: int (chunks with contradiction signals)
              - recency_score: float (0-1, how recent the evidence is)
              - assessment: str ("high", "medium", "low", "insufficient")
        """
        import re

        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(claim, k=k, valid_at=valid_at, tx_id=tx_id)
        if not results:
            return {
                "confidence_bp": 0,
                "evidence_count": 0,
                "source_count": 0,
                "supporting": 0,
                "contradicting": 0,
                "recency_score": 0.0,
                "assessment": "insufficient",
            }

        # Count unique sources
        sources: set[str] = set()
        for r in results:
            core = self.store.cores.get(r.core_id)
            if core:
                sources.add(core.slots.get("source", "unknown"))

        # Check for negation/contradiction signals vs the claim
        claim_words = set(re.findall(r'\b\w+\b', claim.lower()))
        negation_words = {
            "not", "no", "never", "neither", "nor", "none",
            "doesn't", "don't", "didn't", "won't", "cannot", "can't",
        }
        claim_has_negation = bool(claim_words & negation_words)

        supporting = 0
        contradicting = 0
        for r in results:
            r_words = set(re.findall(r'\b\w+\b', r.text.lower()))
            r_has_negation = bool(r_words & negation_words)

            # If claim is positive and evidence is negative (or vice versa)
            if claim_has_negation != r_has_negation:
                contradicting += 1
            else:
                supporting += 1

        # Recency score: based on transaction times of evidence
        recency_scores = []
        for r in results:
            rev = self.store.revisions.get(r.revision_id)
            if rev:
                tx_recorded = rev.transaction_time.recorded_at
                # Score based on how recent (within last 5 years)
                now = datetime.now(timezone.utc)
                age_days = (now - tx_recorded).days
                recency = max(0.0, 1.0 - age_days / (365 * 5))
                recency_scores.append(recency)
        recency_score = sum(recency_scores) / len(recency_scores) if recency_scores else 0.0

        # Compute overall confidence
        confidence = 0

        # Source diversity (0-3000)
        source_score = min(len(sources) * 1000, 3000)
        confidence += source_score

        # Evidence density (0-2000)
        density_score = min(len(results) * 400, 2000)
        confidence += density_score

        # Consistency (0-3000)
        if supporting > 0:
            consistency = supporting / (supporting + contradicting)
            confidence += int(consistency * 3000)

        # Recency boost (0-2000)
        confidence += int(recency_score * 2000)

        confidence = min(confidence, 10000)

        # Assessment
        if len(results) < 2:
            assessment = "insufficient"
        elif confidence >= 7000:
            assessment = "high"
        elif confidence >= 4000:
            assessment = "medium"
        else:
            assessment = "low"

        return {
            "confidence_bp": confidence,
            "evidence_count": len(results),
            "source_count": len(sources),
            "supporting": supporting,
            "contradicting": contradicting,
            "recency_score": round(recency_score, 3),
            "assessment": assessment,
        }

    def _decompose_question(
        self,
        question: str,
        max_parts: int = 5,
    ) -> list[str]:
        """Decompose a complex question into simpler sub-questions.

        Uses heuristic decomposition:
        - Split on conjunctions (and, or, but)
        - Extract distinct concepts
        - Generate aspect-specific queries
        """
        import re

        subqueries = [question]  # Always include the original

        # Split on logical conjunctions
        parts = re.split(r'\b(?:and|or|but|also|additionally|furthermore|moreover)\b', question, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip().rstrip("?.,!")
            if len(part) > 15 and part.lower() != question.lower():
                subqueries.append(part)

        # Extract key noun phrases as additional queries
        terms = self._extract_key_terms(question, max_terms=3)
        for term in terms:
            if len(term) > 5 and term.lower() not in question.lower()[:30].lower():
                subqueries.append(term)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for sq in subqueries:
            normalized = sq.lower().strip()
            if normalized not in seen and len(normalized) > 5:
                seen.add(normalized)
                unique.append(sq)

        return unique[:max_parts]

    def _extract_expansion_terms(
        self,
        results: list[SearchResult],
        seen: set[str],
        max_terms: int = 3,
    ) -> list[str]:
        """Extract key terms from results for query expansion."""
        all_text = " ".join(r.text for r in results)
        terms = self._extract_key_terms(all_text, max_terms=max_terms * 2)
        # Filter already seen
        novel = [t for t in terms if t.lower().strip() not in seen]
        return novel[:max_terms]

    def _extract_key_terms(
        self,
        text: str,
        max_terms: int = 10,
    ) -> list[str]:
        """Extract key terms from text using TF-IDF or simple frequency."""
        import re
        from collections import Counter

        # Common English stop words + newsletter/boilerplate terms
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "dare", "ought",
            "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "above",
            "below", "between", "out", "off", "over", "under", "again",
            "further", "then", "once", "here", "there", "when", "where", "why",
            "how", "all", "each", "every", "both", "few", "more", "most",
            "other", "some", "such", "no", "nor", "not", "only", "own", "same",
            "so", "than", "too", "very", "just", "because", "but", "and", "or",
            "if", "while", "about", "up", "this", "that", "these", "those",
            "it", "its", "they", "them", "their", "we", "our", "you", "your",
            "he", "him", "his", "she", "her", "i", "me", "my", "what", "which",
            "who", "whom", "also", "many", "much", "any", "well", "like",
            "new", "one", "two", "first", "even", "back", "get", "make",
            "know", "take", "come", "see", "think", "look", "want", "give",
            "use", "find", "tell", "work", "way", "let", "still", "going",
            "don", "didn", "doesn", "won", "ll", "ve", "re", "things",
            # Newsletter/boilerplate terms
            "hey", "subscribe", "newsletter", "email", "post", "writeup",
            "write", "series", "breakdowns", "breakdown", "found", "value",
            "sharing", "share", "appreciate", "link", "links", "click",
            "follow", "join", "sign", "free", "update", "content", "read",
            "reading", "check", "drop", "playlist", "search", "important",
            "always", "people", "time", "really", "great", "amazing",
            "incredible", "interesting", "awesome", "love", "thanks",
            # Generic filler words
            "huge", "believe", "becoming", "become", "thing", "things",
            "look", "looking", "lot", "lots", "make", "making", "made",
            "like", "keep", "still", "well", "much", "many", "also",
            "way", "ways", "new", "use", "using", "used", "need",
            "want", "say", "said", "means", "mean", "take", "step",
            "move", "going", "come", "think", "know", "see", "get",
            "let", "put", "run", "try", "give", "work", "call",
            "long", "able", "different", "good", "best", "even",
            "every", "first", "last", "next", "part", "point",
            "right", "actually", "basically", "simply", "just",
            "world", "today", "google", "source", "image",
        }

        # Extract words (2+ chars, alphabetic)
        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        filtered = [w for w in words if w not in stop_words and len(w) > 3]

        # Count bigrams too for better terms
        bigrams = []
        for i in range(len(words) - 1):
            if words[i] not in stop_words and words[i+1] not in stop_words:
                bigrams.append(f"{words[i]} {words[i+1]}")

        # Combine unigram and bigram counts
        counter = Counter(filtered)
        bigram_counter = Counter(bigrams)

        # Prefer bigrams (more specific)
        terms: list[str] = []
        for term, count in bigram_counter.most_common(max_terms):
            if count >= 2:
                terms.append(term)
        for term, count in counter.most_common(max_terms * 2):
            if len(terms) >= max_terms:
                break
            if term not in " ".join(terms):
                terms.append(term)

        return terms[:max_terms]

    def _diversify_results(
        self,
        results: list[SearchResult],
        *,
        max_per_source: int = 3,
    ) -> list[SearchResult]:
        """Re-order results to maximize source diversity.

        Uses a round-robin approach: take the best result from each source,
        then the second-best from each, etc. This ensures the top results
        come from diverse documents.

        Args:
            results: Results sorted by score.
            max_per_source: Maximum results from any single source.

        Returns:
            Results re-ordered for diversity.
        """
        # Group by source, preserving order within each source
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Round-robin selection: best from each source, then second-best, etc.
        diversified: list[SearchResult] = []
        seen: set[str] = set()
        round_num = 0

        while len(diversified) < len(results):
            added_this_round = False
            # Sort sources by their best remaining score
            sorted_sources = sorted(
                by_source.items(),
                key=lambda x: -x[1][0].score if x[1] else 0,
            )
            for source, chunks in sorted_sources:
                if round_num < len(chunks) and round_num < max_per_source:
                    r = chunks[round_num]
                    if r.revision_id not in seen:
                        seen.add(r.revision_id)
                        diversified.append(r)
                        added_this_round = True
            round_num += 1
            if not added_this_round:
                break

        return diversified

    def _rerank_for_question(
        self,
        question: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Re-rank results by relevance to the original question."""
        # Get TF-IDF component for re-ranking
        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        if tfidf is None:
            return sorted(results, key=lambda r: -r.score)

        # Re-score against original question using TF-IDF
        if not tfidf._fitted:
            tfidf.rebuild()

        try:
            from sklearn.metrics.pairwise import cosine_similarity
            vectorizer = tfidf._vectorizer
            q_vec = vectorizer.transform([question])
            text_vecs = vectorizer.transform([r.text for r in results])
            scores = cosine_similarity(q_vec, text_vecs)[0]

            rescored = []
            for r, score in zip(results, scores):
                rescored.append(SearchResult(
                    core_id=r.core_id,
                    revision_id=r.revision_id,
                    score=float(score),
                    text=r.text,
                ))
            rescored.sort(key=lambda r: -r.score)
            return rescored
        except Exception:
            return sorted(results, key=lambda r: -r.score)


@dataclass
class ReasoningResult:
    """Result of multi-hop reasoning over the knowledge store."""
    question: str
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    trace: list[dict[str, Any]]
    total_hops: int

    @property
    def total_chunks(self) -> int:
        return len(self.results)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def summary(self) -> str:
        """Human-readable summary of reasoning results."""
        lines = [f'Question: "{self.question}"']
        lines.append(f"Found {self.total_chunks} relevant chunks across {self.source_count} documents")
        lines.append(f"Reasoning: {self.total_hops} expansion hops")
        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1])):
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")
        lines.append("")
        lines.append("Top results:")
        for r in self.results[:5]:
            text_preview = r.text[:120].replace("\n", " ")
            lines.append(f"  [{r.score:.3f}] {text_preview}...")
        return "\n".join(lines)


@dataclass
class QueryFacet:
    """A single facet (sub-question) of a deep query."""
    subquery: str
    results: list[SearchResult]
    graph_results: list[SearchResult]

    @property
    def total_chunks(self) -> int:
        return len(self.results) + len(self.graph_results)


@dataclass
class DeepQueryResult:
    """Result of intelligent query decomposition and targeted retrieval."""
    question: str
    subqueries: list[str]
    facets: list[QueryFacet]
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    relevant_topics: list[dict[str, Any]]

    @property
    def total_chunks(self) -> int:
        return len(self.results)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [f'Deep Query: "{self.question}"']
        lines.append(f"Decomposed into {len(self.subqueries)} sub-queries:")
        for sq in self.subqueries:
            lines.append(f"  - {sq}")
        lines.append(f"\nFound {self.total_chunks} chunks across {self.source_count} documents")

        if self.relevant_topics:
            lines.append("\nRelevant topics:")
            for t in self.relevant_topics:
                labels = ", ".join(t["labels"][:3])
                lines.append(f"  [{t['size']} chunks, relevance={t['relevance']:.3f}] {labels}")

        lines.append("\nTop results:")
        for r in self.results[:5]:
            text_preview = r.text[:120].replace("\n", " ")
            lines.append(f"  [{r.score:.3f}] {text_preview}...")

        lines.append(f"\nSource breakdown:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1]))[:8]:
            lines.append(f"  [{len(chunks)} chunks] {source[:55]}")

        return "\n".join(lines)

    def context_for_llm(self, max_chunks: int = 10) -> str:
        """Format results as context suitable for feeding to an LLM.

        Returns a structured text block with source attribution that
        can be used as context for LLM-based reasoning.
        """
        lines = [f"# Context for: {self.question}\n"]

        for i, r in enumerate(self.results[:max_chunks]):
            core_lookup = None
            # We can't access store from here, so use what we have
            lines.append(f"## Chunk {i+1} (relevance: {r.score:.3f})")
            lines.append(r.text[:1000])
            lines.append("")

        return "\n".join(lines)


@dataclass
class EvidenceChain:
    """Cross-document evidence chain supporting or refuting a claim."""
    claim: str
    direct_evidence: list[SearchResult]
    supporting_evidence: list[SearchResult]
    related_evidence: list[SearchResult]
    chains: list[list[SearchResult]]
    sources: dict[str, list[SearchResult]]
    total_evidence: int

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def chain_count(self) -> int:
        return len(self.chains)

    def summary(self) -> str:
        """Human-readable evidence chain summary."""
        lines = [f'Evidence for: "{self.claim}"']
        lines.append(f"Total evidence: {self.total_evidence} chunks from {self.source_count} sources")
        lines.append(f"Direct evidence: {len(self.direct_evidence)} chunks")
        lines.append(f"Evidence chains: {self.chain_count}")
        lines.append("")

        if self.direct_evidence:
            lines.append("Direct evidence:")
            for r in self.direct_evidence[:5]:
                text_preview = r.text[:120].replace("\n", " ")
                lines.append(f"  [{r.score:.3f}] {text_preview}...")

        if self.chains:
            lines.append("")
            lines.append("Evidence chains:")
            for i, chain in enumerate(self.chains[:3]):
                lines.append(f"  Chain {i+1} ({len(chain)} links):")
                for j, link in enumerate(chain):
                    text_preview = link.text[:80].replace("\n", " ")
                    lines.append(f"    {j+1}. [{link.score:.3f}] {text_preview}...")

        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1]))[:8]:
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")

        return "\n".join(lines)

    def context_for_llm(self, max_chunks: int = 15) -> str:
        """Format evidence as LLM-ready context with source attribution."""
        lines = [f"# Evidence Analysis: {self.claim}\n"]

        lines.append("## Direct Evidence\n")
        for i, r in enumerate(self.direct_evidence[:max_chunks // 2]):
            lines.append(f"### Evidence {i+1} (relevance: {r.score:.3f})")
            lines.append(r.text[:1000])
            lines.append("")

        if self.chains:
            lines.append("## Evidence Chains\n")
            for i, chain in enumerate(self.chains[:3]):
                lines.append(f"### Chain {i+1}")
                for j, link in enumerate(chain):
                    lines.append(f"Link {j+1}: {link.text[:500]}")
                    lines.append("")

        if self.related_evidence:
            lines.append("## Related Context\n")
            remaining = max_chunks - len(self.direct_evidence[:max_chunks // 2])
            for i, r in enumerate(self.related_evidence[:remaining]):
                lines.append(f"### Related {i+1} (relevance: {r.score:.3f})")
                lines.append(r.text[:500])
                lines.append("")

        return "\n".join(lines)


@dataclass
class SynthesisResult:
    """Full-stack retrieval and synthesis result.

    Contains organized, source-attributed context ready for LLM consumption
    or human review.
    """
    question: str
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    source_summaries: list[dict[str, Any]]
    themes: list[str]
    context: str
    reasoning_trace: list[dict[str, Any]]
    total_chunks: int

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def context_length(self) -> int:
        return len(self.context)

    def summary(self) -> str:
        """Human-readable summary of the synthesis."""
        lines = [f'Synthesis: "{self.question}"']
        lines.append(
            f"Retrieved {self.total_chunks} chunks from "
            f"{self.source_count} sources"
        )
        lines.append(f"Context: {self.context_length:,} characters")
        lines.append("")

        if self.themes:
            lines.append("Key themes: " + ", ".join(self.themes))
            lines.append("")

        lines.append("Sources (by relevance):")
        for ss in self.source_summaries[:10]:
            lines.append(
                f"  [{ss['chunks']} chunks, rel={ss['relevance']:.3f}] "
                f"{ss['source'][:55]}"
            )

        lines.append("")
        lines.append("Reasoning trace:")
        for t in self.reasoning_trace:
            if t["hop"] == 0:
                lines.append(f"  Hop 0: {t['results']} initial results")
            else:
                terms = t.get("expansion_terms", [])
                lines.append(
                    f"  Hop {t['hop']}: +{t['new']} new "
                    f"(expanded: {', '.join(terms[:3])})"
                )

        return "\n".join(lines)


@dataclass
class CoverageReport:
    """Analysis of store coverage for a topic."""
    topic: str
    total_chunks: int
    sources: dict[str, list[SearchResult]]
    subtopics: list[str]
    source_count: int

    def summary(self) -> str:
        """Human-readable coverage report."""
        lines = [f'Coverage: "{self.topic}"']
        lines.append(f"Found {self.total_chunks} chunks across {self.source_count} documents")
        lines.append("")
        lines.append("Subtopics discovered:")
        for st in self.subtopics:
            lines.append(f"  - {st}")
        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1])):
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")
        return "\n".join(lines)
