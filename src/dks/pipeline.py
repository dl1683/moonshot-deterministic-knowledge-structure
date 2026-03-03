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
)
from .extract import ExtractionResult, Extractor, PDFExtractor, TextChunker
from .index import (
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
    ) -> None:
        self.store = store or KnowledgeStore()
        self._extractor = extractor
        self._resolver = resolver
        self._index: TfidfSearchIndex | DenseSearchIndex | HybridSearchIndex | SearchIndex | None = search_index
        if self._index is None and embedding_backend is not None:
            self._index = SearchIndex(self.store, embedding_backend)
        self._tx_counter = 0

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
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
            tfidf_state = {
                "texts": tfidf._texts,
                "revision_ids": tfidf._revision_ids,
                "fitted": tfidf._fitted,
            }
            with open(directory / "tfidf_state.pkl", "wb") as f:
                pickle.dump(tfidf_state, f)
            # Save the fitted vectorizer separately
            if tfidf._fitted:
                with open(directory / "tfidf_vectorizer.pkl", "wb") as f:
                    pickle.dump(tfidf._vectorizer, f)
                # Save the matrix
                with open(directory / "tfidf_matrix.pkl", "wb") as f:
                    pickle.dump(tfidf._matrix, f)

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

        # 4. Save metadata
        meta = {
            "version": "0.3.0",
            "cores": len(self.store.cores),
            "revisions": len(self.store.revisions),
            "tx_counter": self._tx_counter,
        }
        if isinstance(self._index, TfidfSearchIndex):
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

        # 3. Restore TF-IDF index
        search_index = None
        if meta.get("index_type") == "tfidf" and (directory / "tfidf_state.pkl").exists():
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
    ) -> list[SearchResult]:
        """Discover related knowledge by traversing the similarity graph.

        Starting from seed results, find progressively more distant but
        related chunks. Useful for exploratory analysis.

        Args:
            seed_query: Starting query.
            k: Results per expansion.
            depth: How many levels of expansion.
            similarity_threshold: Minimum score to follow.

        Returns:
            All discovered chunks, ordered by discovery path.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        discovered: dict[str, SearchResult] = {}
        frontier: list[str] = []  # queries to explore

        # Start with seed
        seed_results = self.query(seed_query, k=k)
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
                results = self.query(expansion, k=k)
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
    ) -> CoverageReport:
        """Analyze what the store knows about a topic.

        Returns a structured report of all related knowledge, grouped by
        source document and subtopic.

        Args:
            topic: Topic to analyze.
            k: Maximum chunks to analyze.

        Returns:
            CoverageReport with sources, subtopics, and gap analysis.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k)

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

    def query_deep(
        self,
        question: str,
        *,
        k_per_subquery: int = 5,
        max_subqueries: int = 5,
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
                results = self.query(sq, k=3)
                for r in results:
                    cluster_id = self._graph.cluster_of(r.revision_id)
                    if cluster_id is not None:
                        current = relevant_clusters.get(cluster_id, 0)
                        relevant_clusters[cluster_id] = max(current, r.score)

        # Step 3: Targeted retrieval for each sub-query
        facets: list[QueryFacet] = []
        all_chunks: dict[str, SearchResult] = {}

        for sq in subqueries:
            results = self.query(sq, k=k_per_subquery)
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

        # Common English stop words
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
