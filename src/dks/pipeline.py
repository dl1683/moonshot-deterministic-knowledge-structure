"""Pipeline orchestrator — the ONE canonical execution path for DKS.

Orchestrates: extract → resolve → commit → index for ingestion,
and embed → search → filter for queries.

The commitment boundary runs through this module: extraction and resolution
are non-deterministic, but once committed to the KnowledgeStore, everything
becomes deterministic data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import AuditManager, AuditTrace
from .explore import Explorer
from .ingest import Ingester
from .search import SearchEngine
from .core import (
    KnowledgeStore,
    MergeResult,
    TransactionTime,
)
from .extract import Extractor
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
from .resolve import Resolver


def _get_version() -> str:
    """Get DKS version without circular import."""
    from . import __version__
    return __version__


def _safe_pickle_load(path: str | Path) -> Any:
    """Load a pickle file with a restricted unpickler for safety.

    Only allows types that DKS actually serializes: builtins (dict, list,
    tuple, set, str, int, float, bool, bytes), numpy arrays, scipy sparse
    matrices, and sklearn TfidfVectorizer.

    Raises pickle.UnpicklingError if the file contains unexpected types.
    """
    import io
    import pickle

    # Explicit allowlist of (module, qualname) pairs that DKS actually serializes.
    # No blanket prefixes — every allowed type is enumerated.
    _ALLOWED_TYPES: set[tuple[str, str]] = {
        # numpy: array reconstruction
        ("numpy", "ndarray"),
        ("numpy", "dtype"),
        ("numpy.core.multiarray", "_reconstruct"),
        ("numpy.core.multiarray", "scalar"),
        ("numpy", "core.multiarray._reconstruct"),
        ("numpy", "core.multiarray.scalar"),
        ("numpy", "int64"),
        ("numpy", "float64"),
        ("numpy", "float32"),
        ("numpy", "bool_"),
        # scipy sparse (TF-IDF matrices)
        ("scipy.sparse._csr", "csr_matrix"),
        ("scipy.sparse.csr", "csr_matrix"),
        ("scipy.sparse._csc", "csc_matrix"),
        ("scipy.sparse.csc", "csc_matrix"),
        ("scipy.sparse", "_csr.csr_matrix"),
        ("scipy.sparse", "_csc.csc_matrix"),
        # sklearn TF-IDF (the only sklearn classes DKS serializes)
        ("sklearn.feature_extraction.text", "TfidfVectorizer"),
        ("sklearn.feature_extraction.text", "TfidfTransformer"),
        ("sklearn.feature_extraction.text", "CountVectorizer"),
        # sklearn internals used during TfidfVectorizer unpickling
        ("sklearn.feature_extraction._stop_words", "ENGLISH_STOP_WORDS"),
        ("sklearn.utils._tags", "Tags"),
        # collections
        ("collections", "OrderedDict"),
        ("collections", "defaultdict"),
        # copy/reconstruction
        ("copyreg", "_reconstructor"),
    }

    class _RestrictedUnpickler(pickle.Unpickler):
        def find_class(self, module: str, name: str) -> Any:
            if (module, name) in _ALLOWED_TYPES:
                return super().find_class(module, name)
            if module == "builtins" and name in (
                "set", "frozenset", "dict", "list", "tuple",
                "bytes", "bytearray", "True", "False", "None",
                "int", "float", "complex", "str", "bool",
                "slice", "range",
            ):
                return super().find_class(module, name)
            raise pickle.UnpicklingError(
                f"DKS: Blocked unsafe pickle class: {module}.{name}. "
                f"Only whitelisted types are allowed during Pipeline.load()."
            )

    with open(path, "rb") as f:
        return _RestrictedUnpickler(f).load()


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
        # Dirty flag: set True after retraction ops, triggers auto-rebuild on next search
        self._index_dirty = False
        # Knowledge graph (built lazily via build_graph())
        self._graph: KnowledgeGraph | None = None
        # Audit trail
        self._audit = AuditManager()
        # Ingester (delegates ingest operations)
        self._ingester = Ingester(
            store=self.store,
            extractor=self._extractor,
            resolver=self._resolver,
            index=self._index,
            tx_factory=self.next_tx,
            chunk_siblings=self._chunk_siblings,
        )
        # SearchEngine (delegates search/reasoning operations)
        self._search = SearchEngine(
            store=self.store,
            index=self._index,
            reranker=self._reranker,
            graph_fn=lambda: self._graph,
            audit=self._audit,
            chunk_siblings=self._chunk_siblings,
            entity_decisions_fn=lambda: self._explorer.get_entity_decisions(),
        )
        # Explorer (delegates browse/profile/annotation/entity/insights operations)
        self._explorer = Explorer(
            store=self.store,
            graph_fn=lambda: self._graph,
            tx_factory=self.next_tx,
            query_fn=self._search.query,
            stats_fn=self.stats,
            topics_fn=self.topics,
            link_entities_fn=self._search.link_entities,
        )

    # ---- Audit Trail ----

    def enable_audit(self, enabled: bool = True) -> None:
        """Enable or disable audit trail recording."""
        self._audit.enabled = enabled

    def last_audit(self) -> AuditTrace | None:
        """Return the audit trace from the last audited operation."""
        return self._audit.last_trace

    def _begin_audit(self, operation: str, question: str) -> AuditTrace | None:
        return self._audit.begin(operation, question)

    def _finish_audit(self, trace: AuditTrace | None, t0: float) -> None:
        self._audit.finish(trace, t0)

    def render_audit(self, trace: AuditTrace | None = None) -> str:
        """Render an audit trace as a human-readable markdown report."""
        if trace is None:
            trace = self._audit.last_trace
        return AuditManager.render(trace)

    def next_tx(self) -> TransactionTime:
        """Auto-generate next transaction time."""
        self._tx_counter += 1
        return TransactionTime(
            tx_id=self._tx_counter,
            recorded_at=datetime.now(timezone.utc),
        )

    @property
    def tx_counter(self) -> int:
        """Current transaction counter value."""
        return self._tx_counter

    def ingest(self, text: str, **kwargs) -> list[str]:
        """Extract claims from text, resolve entities, commit to store, index."""
        return self._ingester.ingest(text, **kwargs)

    def ingest_pdf(self, path: str | Path, **kwargs) -> list[str]:
        """Ingest a single PDF file: extract text, chunk, commit, index."""
        return self._ingester.ingest_pdf(path, **kwargs)

    def ingest_text(self, text: str, **kwargs) -> list[str]:
        """Ingest raw text: chunk, commit, index."""
        return self._ingester.ingest_text(text, **kwargs)

    def ingest_directory(self, directory: str | Path, **kwargs) -> dict[str, list[str]]:
        """Ingest all PDFs in a directory."""
        return self._ingester.ingest_directory(directory, **kwargs)

    # ---- Search (delegated to SearchEngine) ----

    def _ensure_index_fresh(self) -> None:
        """Auto-rebuild search index if dirty (e.g., after retraction)."""
        if self._index_dirty and self._index is not None:
            self.rebuild_index()
            self._index_dirty = False

    def query(self, question: str, **kwargs) -> list[SearchResult]:
        """Search for relevant claims with temporal filtering."""
        self._ensure_index_fresh()
        return self._search.query(question, **kwargs)

    def query_multi(self, question: str, **kwargs) -> dict[str, list[SearchResult]]:
        """Multi-document retrieval: find relevant chunks across all sources."""
        self._ensure_index_fresh()
        return self._search.query_multi(question, **kwargs)

    def query_exact(self, core_id: str, *, valid_at, tx_id):
        """Direct query by core_id with bitemporal coordinates."""
        return self._search.query_exact(core_id, valid_at=valid_at, tx_id=tx_id)

    def expand_context(self, result: SearchResult, *, window: int = 2) -> list[SearchResult]:
        """Expand a search result to include surrounding chunks."""
        return self._search.expand_context(result, window=window)

    def query_with_context(self, question: str, **kwargs) -> list[SearchResult]:
        """Search with automatic context expansion."""
        self._ensure_index_fresh()
        return self._search.query_with_context(question, **kwargs)

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

        # 2. Save index state via serialization interfaces
        tfidf_component = None
        dense_component = None

        if isinstance(self._index, HybridSearchIndex):
            tfidf_component = self._index.tfidf
            dense_component = self._index.dense
        elif isinstance(self._index, TfidfSearchIndex):
            tfidf_component = self._index.tfidf
        elif isinstance(self._index, DenseSearchIndex):
            dense_component = self._index.dense

        if tfidf_component is not None:
            tfidf_state = tfidf_component.get_state()
            # Save lightweight state separately from heavy objects
            with open(directory / "tfidf_state.pkl", "wb") as f:
                pickle.dump({
                    "texts": tfidf_state["texts"],
                    "revision_ids": tfidf_state["revision_ids"],
                    "fitted": tfidf_state["fitted"],
                }, f)
            if tfidf_state["fitted"]:
                with open(directory / "tfidf_vectorizer.pkl", "wb") as f:
                    pickle.dump(tfidf_state["vectorizer"], f)
                with open(directory / "tfidf_matrix.pkl", "wb") as f:
                    pickle.dump(tfidf_state["matrix"], f)

        # 2b. Save dense embeddings
        if dense_component is not None:
            dense_state = dense_component.get_state()
            with open(directory / "dense_embeddings.pkl", "wb") as f:
                pickle.dump(dense_state, f)

        # 3. Save knowledge graph via serialization interface
        if self._graph is not None:
            with open(directory / "graph.pkl", "wb") as f:
                pickle.dump(self._graph.get_state(), f)

        # 4. Save chunk siblings map
        if self._chunk_siblings:
            with open(directory / "chunk_siblings.pkl", "wb") as f:
                pickle.dump(self._chunk_siblings, f)

        # 5. Save metadata
        meta: dict[str, Any] = {
            "version": _get_version(),
            "cores": len(self.store.cores),
            "revisions": len(self.store.revisions),
            "tx_counter": self._tx_counter,
            "index_dirty": self._index_dirty,
        }
        if isinstance(self._index, HybridSearchIndex):
            meta["index_type"] = "hybrid"
            meta["indexed"] = self._index.size
            meta["hybrid_alpha"] = self._index.alpha
            meta["hybrid_rrf_k"] = self._index.rrf_k
        elif isinstance(self._index, DenseSearchIndex):
            meta["index_type"] = "dense"
            meta["indexed"] = self._index.size
        elif isinstance(self._index, TfidfSearchIndex):
            meta["index_type"] = "tfidf"
            meta["indexed"] = self._index.size
        if self._graph is not None:
            meta["graph_nodes"] = self._graph.total_nodes
            meta["graph_edges"] = self._graph.total_edges
            meta["graph_clusters"] = self._graph.total_clusters

        # Save dense model name for restoration
        if dense_component is not None:
            meta["dense_model_name"] = dense_component.model_name

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

        directory = Path(directory)

        # 1. Load the deterministic store
        store = KnowledgeStore.from_canonical_json_file(
            str(directory / "store.json")
        )

        # 2. Load metadata
        with open(directory / "meta.json") as f:
            meta = json.load(f)

        # 3. Restore search index via from_state interfaces
        search_index = None
        index_type = meta.get("index_type", "tfidf")

        # 3a. Restore TF-IDF component
        tfidf = None
        if (directory / "tfidf_state.pkl").exists():
            from .index import TfidfIndex
            tfidf_state = _safe_pickle_load(directory / "tfidf_state.pkl")
            if tfidf_state["fitted"] and (directory / "tfidf_vectorizer.pkl").exists():
                tfidf_state["vectorizer"] = _safe_pickle_load(directory / "tfidf_vectorizer.pkl")
                tfidf_state["matrix"] = _safe_pickle_load(directory / "tfidf_matrix.pkl")
            tfidf = TfidfIndex.from_state(tfidf_state)

        # 3b. Restore dense component
        dense = None
        if (directory / "dense_embeddings.pkl").exists():
            from .index import SentenceTransformerIndex
            dense_state = _safe_pickle_load(directory / "dense_embeddings.pkl")
            model_name = meta.get("dense_model_name", "all-MiniLM-L6-v2")
            dense = SentenceTransformerIndex.from_state(dense_state, model_name=model_name)

        # 3c. Assemble the correct index type via from_state
        if index_type == "hybrid" and tfidf is not None and dense is not None:
            from .index import HybridSearchIndex
            search_index = HybridSearchIndex.from_state(
                store, tfidf, dense,
                alpha=meta.get("hybrid_alpha", 0.5),
                rrf_k=meta.get("hybrid_rrf_k", 60),
            )
        elif index_type == "dense" and dense is not None:
            from .index import DenseSearchIndex
            search_index = DenseSearchIndex.from_state(store, dense)
        elif tfidf is not None:
            search_index = TfidfSearchIndex.from_state(store, tfidf)

        # 4. Create pipeline
        pipeline = cls(store=store, search_index=search_index)
        pipeline._tx_counter = meta.get("tx_counter", 0)
        pipeline._index_dirty = meta.get("index_dirty", False)

        # 5. Restore knowledge graph via from_state
        if (directory / "graph.pkl").exists():
            from .index import KnowledgeGraph
            graph_state = _safe_pickle_load(directory / "graph.pkl")
            pipeline._graph = KnowledgeGraph.from_state(graph_state)

        # 6. Restore chunk siblings
        if (directory / "chunk_siblings.pkl").exists():
            pipeline._chunk_siblings = _safe_pickle_load(directory / "chunk_siblings.pkl")
            # Update references in sub-modules (they hold refs to the old empty dict)
            pipeline._ingester._chunk_siblings = pipeline._chunk_siblings
            pipeline._search._chunk_siblings = pipeline._chunk_siblings

        return pipeline

    def merge(self, other: "Pipeline") -> MergeResult:
        """Merge another pipeline's store into this one.

        Note: Only the KnowledgeStore data is merged. The search index
        and knowledge graph are NOT automatically rebuilt. Call
        rebuild_index() and build_graph() after merge.

        Returns:
            MergeResult with merged store and any conflicts.
        """
        result = self.store.merge(other.store)
        self.store = result.merged
        # Update store references in all sub-modules
        if self._index is not None:
            self._index.store = self.store
        self._ingester.store = self.store
        self._search.store = self.store
        self._explorer.store = self.store
        # Merge chunk siblings from other pipeline
        for source, rids in other._chunk_siblings.items():
            if source not in self._chunk_siblings:
                self._chunk_siblings[source] = rids
            else:
                # Merge revision lists, avoiding duplicates
                existing = set(self._chunk_siblings[source])
                self._chunk_siblings[source].extend(
                    rid for rid in rids if rid not in existing
                )
        # Invalidate stale graph — must rebuild after merge
        # Explorer._graph is a property that reads pipeline._graph via _graph_fn
        self._graph = None
        # Mark index as dirty — merged store has new revisions not yet indexed
        self._index_dirty = True
        return result

    def rebuild_index(self) -> int:
        """Rebuild the search index from all revisions in the store.

        Skips revisions whose core_id has been retracted.

        Returns:
            Number of revisions indexed.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        retracted_cores = self.store.retracted_core_ids()

        items = []
        for revision_id, revision in self.store.revisions.items():
            if revision.status != "asserted":
                continue
            if revision.core_id in retracted_cores:
                continue
            items.append((revision_id, revision.assertion))

        # Clear existing index data before rebuilding to prevent duplicates
        tfidf = getattr(self._index, 'tfidf', None)
        if tfidf is not None:
            tfidf.clear()
        dense = getattr(self._index, 'dense', None)
        if dense is not None:
            dense.clear()
        self._index.add_batch(items)

        # Rebuild index matrix
        if hasattr(self._index, 'rebuild'):
            self._index.rebuild()

        self._index_dirty = False
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
            tfidf_component = self._index.tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf_component = self._index.tfidf

        if tfidf_component is None:
            raise ValueError("Graph building requires TfidfSearchIndex or HybridSearchIndex.")

        # Rebuild index to ensure retracted content is excluded from graph
        self.rebuild_index()

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
        return self._graph

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
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        neighbor_ids = self._graph.neighbors(revision_id, k=k)
        retracted = self.store.retracted_core_ids()
        results = []
        for nid, score in neighbor_ids:
            rev = self.store.revisions.get(nid)
            if rev and rev.status == "asserted" and rev.core_id not in retracted:
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
        if self._graph is None:
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
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        member_ids = self._graph.cluster_members(cluster_id)[:k]
        retracted = self.store.retracted_core_ids()
        results = []
        for rid in member_ids:
            rev = self.store.revisions.get(rid)
            if rev and rev.status == "asserted" and rev.core_id not in retracted:
                results.append(SearchResult(
                    core_id=rev.core_id,
                    revision_id=rid,
                    score=1.0,
                    text=rev.assertion,
                ))
        return results

    # ---- Data Exploration (delegated to Explorer) ----

    def profile(self) -> dict[str, Any]:
        """Generate a comprehensive corpus profile."""
        return self._explorer.profile()

    def render_profile(self, profile=None) -> str:
        """Render a corpus profile as readable text."""
        return self._explorer.render_profile(profile)

    def delete_cluster(self, cluster_id: int, *, reason: str = 'User deleted cluster via interactive review') -> dict[str, Any]:
        """Delete all chunks in a cluster by retracting their revisions."""
        result = self._explorer.delete_cluster(cluster_id, reason=reason)
        if result.get("retracted_count", 0) > 0:
            self._index_dirty = True
        return result

    def review_entities(self, *, top_k: int = 50) -> dict[str, Any]:
        """Analyze entities for interactive review."""
        return self._explorer.review_entities(top_k=top_k)

    def accept_entities(self, entities: list[str], *, reason: str = 'User accepted via interactive review') -> int:
        """Accept entities as valid domain terms."""
        return self._explorer.accept_entities(entities, reason=reason)

    def reject_entities(self, entities: list[str], *, reason: str = 'User rejected via interactive review') -> int:
        """Reject entities as noise/boilerplate."""
        return self._explorer.reject_entities(entities, reason=reason)

    def get_entity_decisions(self) -> dict[str, str]:
        """Retrieve all entity review decisions."""
        return self._explorer.get_entity_decisions()

    def source_detail(self, source: str) -> dict[str, Any]:
        """Get detailed statistics for a specific source document."""
        return self._explorer.source_detail(source)

    def delete_source(self, source: str, *, reason: str = 'User deleted source via interactive review') -> dict[str, Any]:
        """Delete all chunks from a source by retracting."""
        result = self._explorer.delete_source(source, reason=reason)
        if result.get("retracted_count", 0) > 0:
            self._index_dirty = True
        return result

    def browse_cluster(self, cluster_id: int, *, limit: int = 20, preview_length: int = 200) -> dict[str, Any]:
        """Browse chunks within a specific cluster."""
        return self._explorer.browse_cluster(cluster_id, limit=limit, preview_length=preview_length)

    def browse_source(self, source: str, *, limit: int = 20, preview_length: int = 200) -> dict[str, Any]:
        """Browse chunks from a specific source document."""
        return self._explorer.browse_source(source, limit=limit, preview_length=preview_length)

    def chunk_detail(self, revision_id: str) -> dict[str, Any]:
        """Get full details of a single chunk."""
        return self._explorer.chunk_detail(revision_id)

    def quality_report(self) -> dict[str, Any]:
        """Generate a comprehensive corpus quality report."""
        return self._explorer.quality_report()

    def render_quality_report(self, report=None) -> str:
        """Render a quality report as human-readable text."""
        return self._explorer.render_quality_report(report)

    def render_browse(self, result: dict[str, Any]) -> str:
        """Render browse result as human-readable text."""
        return self._explorer.render_browse(result)

    def render_chunk_detail(self, detail: dict[str, Any]) -> str:
        """Render chunk detail as human-readable text."""
        return self._explorer.render_chunk_detail(detail)

    def ingestion_timeline(self) -> list[dict[str, Any]]:
        """Show when knowledge was added over time."""
        return self._explorer.ingestion_timeline()

    def scan_contradictions(self, *, k: int = 10, threshold: float = 0.15) -> list[dict[str, Any]]:
        """Scan corpus for potentially contradictory claims."""
        self._ensure_index_fresh()
        return self._explorer.scan_contradictions(k=k, threshold=threshold)

    def evolution(self, topic: str, *, k: int = 20) -> dict[str, Any]:
        """Show how understanding of a topic changed across documents."""
        return self._explorer.evolution(topic, k=k)

    def staleness_report(self, *, age_days: int = 365) -> dict[str, Any]:
        """Identify old claims that may need updating."""
        return self._explorer.staleness_report(age_days=age_days)

    def render_timeline(self, timeline=None) -> str:
        """Render ingestion timeline as human-readable text."""
        return self._explorer.render_timeline(timeline)

    def render_evolution(self, result: dict[str, Any]) -> str:
        """Render evolution output as human-readable text."""
        return self._explorer.render_evolution(result)

    def render_contradictions(self, pairs: list[dict[str, Any]]) -> str:
        """Render contradictions as human-readable text."""
        return self._explorer.render_contradictions(pairs)

    def compare_sources(self, source_a: str, source_b: str, *, similarity_threshold: float = 0.5) -> dict[str, Any]:
        """Compare two source documents for overlap and divergence."""
        return self._explorer.compare_sources(source_a, source_b, similarity_threshold=similarity_threshold)

    def render_comparison(self, result: dict[str, Any]) -> str:
        """Render source comparison as human-readable text."""
        return self._explorer.render_comparison(result)

    def insights(self) -> dict[str, Any]:
        """Generate proactive insights and recommendations."""
        return self._explorer.insights()

    def suggest_queries(self, *, n: int = 5) -> list[dict[str, str]]:
        """Suggest interesting queries to explore."""
        return self._explorer.suggest_queries(n=n)

    def render_insights(self, result=None) -> str:
        """Render insights as human-readable text."""
        return self._explorer.render_insights(result)

    def annotate_chunk(self, revision_id: str, *, tags=None, note: str = '') -> str:
        """Add user-defined tags and notes to a chunk."""
        return self._explorer.annotate_chunk(revision_id, tags=tags, note=note)

    def list_annotations(self, *, revision_id=None, tag=None) -> list[dict[str, Any]]:
        """List annotations, optionally filtered."""
        return self._explorer.list_annotations(revision_id=revision_id, tag=tag)

    def search_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """Find all chunks annotated with a specific tag."""
        return self._explorer.search_by_tag(tag)

    def remove_annotation(self, annotation_id: str) -> bool:
        """Remove an annotation by retracting it."""
        return self._explorer.remove_annotation(annotation_id)

    def summarize_corpus(self) -> str:
        """Generate a text summary of corpus contents."""
        return self._explorer.summarize_corpus()

    def list_sources(self):
        """List all unique source documents in the store."""
        return self._explorer.list_sources()

    # ---- Entity Linking & Reasoning (delegated to SearchEngine) ----

    def link_entities(self, **kwargs):
        """Create entity-based cross-references between chunks."""
        return self._search.link_entities(**kwargs)

    def reason(self, question, **kwargs):
        """Multi-hop reasoning over the knowledge store."""
        self._ensure_index_fresh()
        return self._search.reason(question, **kwargs)

    def discover(self, seed_query, **kwargs):
        """Discover related chunks through graph traversal."""
        self._ensure_index_fresh()
        return self._search.discover(seed_query, **kwargs)

    def coverage(self, topic, **kwargs):
        """Analyze store coverage for a topic."""
        self._ensure_index_fresh()
        return self._search.coverage(topic, **kwargs)

    def evidence_chain(self, claim, **kwargs):
        """Build cross-document evidence chain."""
        self._ensure_index_fresh()
        return self._search.evidence_chain(claim, **kwargs)

    def query_deep(self, question, **kwargs):
        """Intelligent query decomposition and targeted retrieval."""
        self._ensure_index_fresh()
        return self._search.query_deep(question, **kwargs)

    def synthesize(self, question, **kwargs):
        """Full-stack retrieval and synthesis."""
        self._ensure_index_fresh()
        return self._search.synthesize(question, **kwargs)

    def ask(self, question, **kwargs):
        """Intelligent query routing and answer."""
        self._ensure_index_fresh()
        return self._search.ask(question, **kwargs)

    def timeline(self, topic, **kwargs):
        """Build knowledge timeline for a topic."""
        self._ensure_index_fresh()
        return self._search.timeline(topic, **kwargs)

    def timeline_diff(self, topic, **kwargs):
        """Show how a topic changed between time periods."""
        self._ensure_index_fresh()
        return self._search.timeline_diff(topic, **kwargs)

    def provenance_of(self, result):
        """Get full provenance for a search result."""
        return self._search.provenance_of(result)

    def cite(self, result, **kwargs):
        """Get citation for a search result."""
        return self._search.cite(result, **kwargs)

    def cite_results(self, results, **kwargs):
        """Add citation info to existing results."""
        return self._search.cite_results(results, **kwargs)

    def query_by_source(self, source, **kwargs):
        """Get all chunks from a specific source document."""
        return self._search.query_by_source(source, **kwargs)

    def deduplicate(self, **kwargs):
        """Find clusters of near-duplicate chunks."""
        self._ensure_index_fresh()
        return self._search.deduplicate(**kwargs)

    def explain(self, question, result=None, **kwargs):
        """Explain what the search pipeline does for a query."""
        self._ensure_index_fresh()
        if result is not None:
            return self._search.explain(question, result, **kwargs)
        return self._search.explain(question, **kwargs)

    def extract_answer(self, question, results=None, **kwargs):
        """Extract a direct answer from retrieved chunks."""
        self._ensure_index_fresh()
        return self._search.extract_answer(question, results, **kwargs)

    def answer(self, question, **kwargs):
        """Complete answer pipeline: search + extract."""
        self._ensure_index_fresh()
        return self._search.answer(question, **kwargs)

    def contradictions(self, topic, **kwargs):
        """Find contradictory claims in the store."""
        self._ensure_index_fresh()
        return self._search.contradictions(topic, **kwargs)

    def confidence(self, claim, **kwargs):
        """Assess confidence in answers to a question."""
        self._ensure_index_fresh()
        return self._search.confidence(claim, **kwargs)

    # Private method pass-throughs (for test compatibility)
    def _reconstruct_siblings(self, source):
        return self._search._reconstruct_siblings(source)

    def _classify_query(self, question):
        return self._search._classify_query(question)

    def _decompose_question(self, question, **kwargs):
        return self._search._decompose_question(question, **kwargs)
