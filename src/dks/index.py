"""Semantic search with temporal awareness.

Multiple backends:
- NumpyIndex: Bag-of-characters toy (for testing only)
- TfidfIndex: scikit-learn TF-IDF (real keyword search, no model download)
- SentenceTransformerIndex: Dense embeddings (highest quality, requires model)

Results are filtered through KnowledgeStore.query_as_of() to respect
bitemporal visibility. This ensures search results honor the same
temporal guarantees as direct queries.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable, Optional, Any

from collections import deque

from .core import KnowledgeStore


@dataclass(frozen=True)
class SearchResult:
    """A single search result with score and temporal context."""
    core_id: str
    revision_id: str
    score: float
    text: str


def _apply_temporal_filter(
    store: KnowledgeStore,
    candidates: list[tuple[str, float, str]],
    k: int,
    valid_at: datetime | None,
    tx_id: int | None,
) -> list[SearchResult]:
    """Apply retraction/temporal filtering to search candidates.

    Shared by all search index types to eliminate duplication.

    Args:
        store: KnowledgeStore for temporal queries.
        candidates: List of (revision_id, score, text) tuples, pre-sorted by relevance.
        k: Maximum results to return.
        valid_at: Temporal filter (requires tx_id too).
        tx_id: Transaction time cutoff (requires valid_at too).

    Returns:
        Filtered list of SearchResult.
    """
    has_temporal = valid_at is not None and tx_id is not None
    retracted = store.retracted_core_ids() if not has_temporal else set()

    results: list[SearchResult] = []
    for revision_id, score, text in candidates:
        if len(results) >= k:
            break

        revision = store.revisions.get(revision_id)
        if revision is None:
            continue

        if has_temporal:
            winner = store.query_as_of(
                revision.core_id,
                valid_at=valid_at,
                tx_id=tx_id,
            )
            if winner is None or winner.revision_id != revision_id:
                continue
        else:
            if revision.status != "asserted" or revision.core_id in retracted:
                continue

        results.append(SearchResult(
            core_id=revision.core_id,
            revision_id=revision_id,
            score=score,
            text=text,
        ))

    return results


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Protocol for embedding computation backends.

    Default recommendation: Qwen3-Embedding-0.6B (from model registry)
    for fast iteration. 600M params, 32-1024 dims, 100+ languages.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (same length as texts).
        """
        ...

    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        ...


class SearchIndex:
    """Temporal-aware semantic search over a KnowledgeStore.

    Combines embedding similarity with bitemporal filtering to return
    only results that are visible at the queried point in time.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        backend: EmbeddingBackend,
    ) -> None:
        self._store = store
        self._backend = backend
        self._vectors: dict[str, list[float]] = {}  # revision_id -> vector
        self._texts: dict[str, str] = {}  # revision_id -> text

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @store.setter
    def store(self, value: KnowledgeStore) -> None:
        self._store = value

    def add(self, revision_id: str, text: str) -> None:
        """Index a revision's text for search.

        Args:
            revision_id: The revision to index.
            text: The text content to embed and index.
        """
        vectors = self._backend.embed([text])
        self._vectors[revision_id] = vectors[0]
        self._texts[revision_id] = text

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        """Index multiple revisions at once.

        Args:
            items: List of (revision_id, text) pairs.
        """
        if not items:
            return
        revision_ids, texts = zip(*items)
        vectors = self._backend.embed(list(texts))
        for rid, vec, txt in zip(revision_ids, vectors, texts):
            self._vectors[rid] = vec
            self._texts[rid] = txt

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Search for similar content with optional temporal filtering.

        Args:
            query: Query text to search for.
            k: Maximum number of results to return.
            valid_at: If provided with tx_id, filter by bitemporal visibility.
            tx_id: If provided with valid_at, filter by bitemporal visibility.

        Returns:
            List of SearchResult ordered by descending score.
        """
        if not self._vectors:
            return []

        query_vec = self._backend.embed([query])[0]

        # Score all indexed revisions
        scored: list[tuple[float, str]] = []
        for revision_id, vec in self._vectors.items():
            score = _cosine_similarity(query_vec, vec)
            scored.append((score, revision_id))

        # Sort by score descending
        scored.sort(key=lambda x: (-x[0], x[1]))

        # Convert to (revision_id, score, text) for shared filter
        candidates = [
            (rid, sc, self._texts.get(rid, ""))
            for sc, rid in scored
        ]
        return _apply_temporal_filter(self._store, candidates, k, valid_at, tx_id)

    @property
    def size(self) -> int:
        """Number of indexed vectors."""
        return len(self._vectors)


class NumpyIndex:
    """Zero-dependency brute-force cosine similarity index.

    Good for small stores (< 100K vectors). For larger stores,
    swap in a FAISS or Annoy backend implementing EmbeddingBackend.
    """

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension
        self._vectors: dict[str, list[float]] = {}
        self._texts: dict[str, str] = {}

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Simple bag-of-characters embedding (for testing only).

        For real use, replace with a proper embedding model backend.
        """
        vectors = []
        for text in texts:
            vec = [0.0] * self._dimension
            for i, ch in enumerate(text.lower()):
                vec[ord(ch) % self._dimension] += 1.0
            # L2 normalize
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vec = [x / norm for x in vec]
            vectors.append(vec)
        return vectors

    def search_vectors(
        self,
        query: list[float],
        vectors: dict[str, list[float]],
        k: int,
    ) -> list[tuple[str, float]]:
        """Brute-force cosine similarity search."""
        scored = []
        for key, vec in vectors.items():
            score = _cosine_similarity(query, vec)
            scored.append((key, score))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]


class TfidfIndex:
    """TF-IDF based search index using scikit-learn.

    Real keyword-based semantic search. No model download required.
    Rebuilds the TF-IDF matrix incrementally as documents are added.
    Good for up to ~500K documents.

    Requires: pip install scikit-learn
    """

    def __init__(self, **vectorizer_kwargs: Any) -> None:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            raise ImportError("scikit-learn required: pip install scikit-learn")

        defaults = {
            "max_features": 50000,
            "ngram_range": (1, 2),
            "sublinear_tf": True,
            "stop_words": "english",
        }
        defaults.update(vectorizer_kwargs)
        self._vectorizer = TfidfVectorizer(**defaults)
        self._texts: list[str] = []
        self._revision_ids: list[str] = []
        self._matrix = None
        self._fitted = False

    @property
    def dimension(self) -> int:
        if self._fitted:
            return len(self._vectorizer.vocabulary_)
        return 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using TF-IDF. Fits vectorizer if needed."""
        if not texts:
            return []
        if not self._fitted:
            # Can't transform without fitting
            # Return zero vectors as placeholder
            return [[0.0] * 100 for _ in texts]
        matrix = self._vectorizer.transform(texts)
        return [row.toarray()[0].tolist() for row in matrix]

    def add(self, revision_id: str, text: str) -> None:
        """Add a document to the index."""
        self._texts.append(text)
        self._revision_ids.append(revision_id)
        self._fitted = False  # Mark for rebuild

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        """Add multiple documents at once."""
        for rid, text in items:
            self._texts.append(text)
            self._revision_ids.append(rid)
        self._fitted = False

    def rebuild(self) -> None:
        """Rebuild the TF-IDF matrix from all stored texts."""
        if not self._texts:
            self._matrix = None
            self._fitted = True
            return
        self._matrix = self._vectorizer.fit_transform(self._texts)
        self._fitted = True

    def search(
        self,
        query: str,
        *,
        k: int = 5,
    ) -> list[tuple[str, float, str]]:
        """Search for similar documents.

        Returns list of (revision_id, score, text) tuples.
        """
        if not self._fitted:
            self.rebuild()
        if self._matrix is None or self._matrix.shape[0] == 0:
            return []

        from sklearn.metrics.pairwise import cosine_similarity

        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._matrix)[0]

        # Get top-k indices
        top_indices = scores.argsort()[::-1][:k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score > 0:
                results.append((
                    self._revision_ids[idx],
                    score,
                    self._texts[idx],
                ))

        return results

    @property
    def size(self) -> int:
        return len(self._texts)

    def get_state(self) -> dict:
        """Return serializable state for persistence."""
        return {
            "texts": self._texts,
            "revision_ids": self._revision_ids,
            "fitted": self._fitted,
            "vectorizer": self._vectorizer if self._fitted else None,
            "matrix": self._matrix,
        }

    @classmethod
    def from_state(cls, state: dict) -> "TfidfIndex":
        """Restore from saved state without re-importing sklearn."""
        obj = cls.__new__(cls)
        obj._texts = state["texts"]
        obj._revision_ids = state["revision_ids"]
        obj._fitted = state["fitted"]
        obj._vectorizer = state.get("vectorizer")
        obj._matrix = state.get("matrix")
        if obj._vectorizer is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            obj._vectorizer = TfidfVectorizer()
        return obj


class TfidfSearchIndex:
    """Full search index combining TF-IDF with temporal awareness.

    Drop-in replacement for SearchIndex when using TF-IDF instead of
    embedding vectors. Integrates directly with KnowledgeStore for
    bitemporal filtering.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        **vectorizer_kwargs: Any,
    ) -> None:
        self._store = store
        self._tfidf = TfidfIndex(**vectorizer_kwargs)

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @store.setter
    def store(self, value: KnowledgeStore) -> None:
        self._store = value

    def add(self, revision_id: str, text: str) -> None:
        self._tfidf.add(revision_id, text)

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        self._tfidf.add_batch(items)

    def rebuild(self) -> None:
        self._tfidf.rebuild()

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Search with temporal filtering."""
        if not self._tfidf._fitted:
            self._tfidf.rebuild()

        # Get more candidates than needed to account for temporal filtering
        raw_results = self._tfidf.search(query, k=k * 3)
        return _apply_temporal_filter(self._store, raw_results, k, valid_at, tx_id)

    @property
    def size(self) -> int:
        return self._tfidf.size

    @property
    def tfidf(self) -> TfidfIndex:
        """Public access to the underlying TfidfIndex component."""
        return self._tfidf

    @classmethod
    def from_state(cls, store: KnowledgeStore, tfidf: TfidfIndex) -> "TfidfSearchIndex":
        """Restore from a pre-built TfidfIndex component."""
        obj = cls.__new__(cls)
        obj._store = store
        obj._tfidf = tfidf
        return obj


class KnowledgeGraph:
    """Derived graph structure linking related chunks by TF-IDF similarity.

    This is NOT stored in the deterministic KnowledgeStore. It's a derived
    index — rebuilt from the data, like the TF-IDF index itself.

    Enables:
    - Graph traversal: given a chunk, find related chunks
    - Topic clustering: group chunks by semantic similarity
    - Path finding: discover multi-hop connections between concepts
    """

    def __init__(self) -> None:
        self._adjacency: dict[str, list[tuple[str, float]]] = {}
        self._clusters: dict[int, list[str]] = {}  # cluster_id -> revision_ids
        self._revision_cluster: dict[str, int] = {}  # revision_id -> cluster_id
        self._cluster_labels: dict[int, list[str]] = {}  # cluster_id -> top terms

    def build_from_tfidf(
        self,
        tfidf_index: TfidfIndex,
        *,
        similarity_threshold: float = 0.15,
        max_neighbors: int = 10,
        n_clusters: int = 50,
    ) -> None:
        """Build the knowledge graph from a fitted TF-IDF index.

        1. Cluster all chunks into topics using k-means
        2. Within each cluster, compute pairwise similarity
        3. Store adjacency lists for navigation

        Args:
            tfidf_index: Fitted TF-IDF index with stored texts.
            similarity_threshold: Minimum cosine similarity to create a link.
            max_neighbors: Maximum neighbors per node.
            n_clusters: Number of topic clusters.
        """
        if not tfidf_index._fitted:
            tfidf_index.rebuild()
        if tfidf_index._matrix is None:
            return

        try:
            from sklearn.cluster import MiniBatchKMeans
            from sklearn.metrics.pairwise import cosine_similarity
            import numpy as np
        except ImportError:
            raise ImportError("scikit-learn + numpy required for graph building")

        matrix = tfidf_index._matrix
        revision_ids = tfidf_index._revision_ids
        n_docs = len(revision_ids)

        if n_docs == 0:
            return

        # Adjust clusters to not exceed doc count
        actual_clusters = min(n_clusters, n_docs)

        # Step 1: Cluster
        if actual_clusters > 1:
            kmeans = MiniBatchKMeans(
                n_clusters=actual_clusters,
                random_state=42,
                batch_size=min(1000, n_docs),
                n_init=3,
            )
            labels = kmeans.fit_predict(matrix)
        else:
            labels = np.zeros(n_docs, dtype=int)

        # Store cluster assignments
        self._clusters = {}
        self._revision_cluster = {}
        for idx, label in enumerate(labels):
            cluster_id = int(label)
            self._clusters.setdefault(cluster_id, []).append(revision_ids[idx])
            self._revision_cluster[revision_ids[idx]] = cluster_id

        # Extract cluster labels (top terms per cluster)
        if hasattr(tfidf_index._vectorizer, 'get_feature_names_out'):
            feature_names = tfidf_index._vectorizer.get_feature_names_out()
            if actual_clusters > 1:
                for cluster_id in range(actual_clusters):
                    cluster_mask = labels == cluster_id
                    if cluster_mask.sum() > 0:
                        cluster_matrix = matrix[cluster_mask]
                        mean_tfidf = np.asarray(cluster_matrix.mean(axis=0)).flatten()
                        top_indices = mean_tfidf.argsort()[::-1][:5]
                        self._cluster_labels[cluster_id] = [
                            feature_names[i] for i in top_indices
                        ]

        # Step 2: Within-cluster pairwise similarity
        rid_to_idx = {rid: i for i, rid in enumerate(revision_ids)}
        self._adjacency = {}
        for cluster_id, members in self._clusters.items():
            if len(members) <= 1:
                continue

            member_indices = [rid_to_idx[rid] for rid in members]
            cluster_matrix = matrix[member_indices]
            sim_matrix = cosine_similarity(cluster_matrix)

            for i, rid_i in enumerate(members):
                neighbors = []
                for j, rid_j in enumerate(members):
                    if i == j:
                        continue
                    score = float(sim_matrix[i, j])
                    if score >= similarity_threshold:
                        neighbors.append((rid_j, score))

                # Sort by score, keep top max_neighbors
                neighbors.sort(key=lambda x: -x[1])
                if neighbors:
                    self._adjacency[rid_i] = neighbors[:max_neighbors]

    def neighbors(
        self,
        revision_id: str,
        *,
        k: int = 5,
    ) -> list[tuple[str, float]]:
        """Get the nearest neighbors of a chunk.

        Returns list of (revision_id, similarity_score).
        """
        adj = self._adjacency.get(revision_id, [])
        return adj[:k]

    def add_edge(self, from_id: str, to_id: str, score: float) -> bool:
        """Add a directed edge between two revisions.

        Returns True if the edge was added, False if it already existed.
        """
        if from_id not in self._adjacency:
            self._adjacency[from_id] = []
        existing = {nid for nid, _ in self._adjacency[from_id]}
        if to_id not in existing:
            self._adjacency[from_id].append((to_id, score))
            return True
        return False

    def cluster_of(self, revision_id: str) -> int | None:
        """Get the cluster ID of a revision."""
        return self._revision_cluster.get(revision_id)

    def cluster_members(self, cluster_id: int) -> list[str]:
        """Get all revision_ids in a cluster."""
        return self._clusters.get(cluster_id, [])

    def cluster_label(self, cluster_id: int) -> list[str]:
        """Get the top terms describing a cluster."""
        return self._cluster_labels.get(cluster_id, [])

    def topics(self) -> list[dict[str, Any]]:
        """Get all topic clusters with labels and sizes."""
        result = []
        for cid in sorted(self._clusters.keys()):
            result.append({
                "cluster_id": cid,
                "size": len(self._clusters[cid]),
                "labels": self._cluster_labels.get(cid, []),
            })
        return result

    def remove_revision(self, revision_id: str) -> None:
        """Remove a revision from the graph (adjacency + cluster membership)."""
        self._adjacency.pop(revision_id, None)
        # Remove from neighbor lists
        for rid, adj in list(self._adjacency.items()):
            self._adjacency[rid] = [(n, s) for n, s in adj if n != revision_id]
        # Remove from cluster
        cid = self._revision_cluster.pop(revision_id, None)
        if cid is not None and cid in self._clusters:
            members = self._clusters[cid]
            if revision_id in members:
                members.remove(revision_id)
            if not members:
                self._clusters.pop(cid, None)
                self._cluster_labels.pop(cid, None)

    def remove_cluster(self, cluster_id: int) -> list[str]:
        """Remove an entire cluster and return the member revision_ids."""
        members = self._clusters.pop(cluster_id, [])
        self._cluster_labels.pop(cluster_id, None)
        for rid in members:
            self._adjacency.pop(rid, None)
            self._revision_cluster.pop(rid, None)
        # Remove from neighbor lists of other nodes
        for rid, adj in list(self._adjacency.items()):
            self._adjacency[rid] = [(n, s) for n, s in adj if n not in members]
        return members

    def path_between(
        self,
        start_revision_id: str,
        end_revision_id: str,
        *,
        max_depth: int = 4,
    ) -> list[str] | None:
        """Find a path between two chunks through the graph.

        Uses BFS. Returns list of revision_ids forming the path,
        or None if no path exists within max_depth.
        """
        if start_revision_id == end_revision_id:
            return [start_revision_id]

        visited = {start_revision_id}
        queue: deque[list[str]] = deque([[start_revision_id]])

        while queue:
            path = queue.popleft()
            if len(path) > max_depth:
                break

            current = path[-1]
            for neighbor_id, _ in self._adjacency.get(current, []):
                if neighbor_id == end_revision_id:
                    return path + [neighbor_id]
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append(path + [neighbor_id])

        return None

    @property
    def total_edges(self) -> int:
        return sum(len(v) for v in self._adjacency.values())

    @property
    def total_nodes(self) -> int:
        return len(self._adjacency)

    @property
    def total_clusters(self) -> int:
        return len(self._clusters)

    @property
    def clusters(self) -> dict[int, list[str]]:
        """Read-only access to cluster_id -> revision_ids mapping."""
        return self._clusters

    @property
    def revision_cluster(self) -> dict[str, int]:
        """Read-only access to revision_id -> cluster_id mapping."""
        return self._revision_cluster

    @property
    def cluster_labels_map(self) -> dict[int, list[str]]:
        """Read-only access to cluster_id -> top terms mapping."""
        return self._cluster_labels

    def get_state(self) -> dict:
        """Return serializable state for persistence."""
        return {
            "adjacency": self._adjacency,
            "clusters": self._clusters,
            "revision_cluster": self._revision_cluster,
            "cluster_labels": self._cluster_labels,
        }

    @classmethod
    def from_state(cls, state: dict) -> "KnowledgeGraph":
        """Restore from saved state."""
        obj = cls()
        obj._adjacency = state["adjacency"]
        obj._clusters = state["clusters"]
        obj._revision_cluster = state["revision_cluster"]
        obj._cluster_labels = state["cluster_labels"]
        return obj


class SentenceTransformerIndex:
    """Dense embedding search using sentence-transformers.

    High-quality semantic search using pre-trained transformer models.
    Much better than TF-IDF for meaning-based queries like:
    - "what causes AI hallucinations" (vs keyword "hallucination")
    - "how to make models faster" (vs keyword "optimization")

    Requires: pip install sentence-transformers

    Default model: all-MiniLM-L6-v2 (384 dims, fast, good quality)
    For higher quality: all-mpnet-base-v2 (768 dims, slower)
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        *,
        batch_size: int = 64,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("sentence-transformers required: pip install sentence-transformers")

        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        self._batch_size = batch_size
        self._dimension = self._model.get_sentence_embedding_dimension()
        self._texts: list[str] = []
        self._revision_ids: list[str] = []
        self._embeddings: Any = None  # numpy array
        self._dirty = False

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the sentence-transformer model."""
        if not texts:
            return []
        embeddings = self._model.encode(
            texts,
            batch_size=self._batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def add(self, revision_id: str, text: str) -> None:
        """Add a document to the index. Incrementally embeds if index exists."""
        self._texts.append(text)
        self._revision_ids.append(revision_id)

        # If we already have embeddings, incrementally add the new one
        if self._embeddings is not None and not self._dirty:
            import numpy as np
            new_emb = self._model.encode(
                [text], normalize_embeddings=True,
            )
            self._embeddings = np.vstack([self._embeddings, new_emb])
        else:
            self._dirty = True

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        """Add multiple documents. Incrementally embeds if index exists."""
        new_texts = []
        for rid, text in items:
            self._texts.append(text)
            self._revision_ids.append(rid)
            new_texts.append(text)

        # If we already have embeddings, incrementally add the new batch
        if self._embeddings is not None and not self._dirty and new_texts:
            import numpy as np
            new_embs = self._model.encode(
                new_texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
            )
            self._embeddings = np.vstack([self._embeddings, new_embs])
        else:
            self._dirty = True

    def rebuild(self) -> None:
        """Rebuild the embedding matrix from all stored texts."""
        if not self._texts:
            return
        import numpy as np
        self._embeddings = np.array(self._model.encode(
            self._texts,
            batch_size=self._batch_size,
            show_progress_bar=len(self._texts) > 1000,
            normalize_embeddings=True,
        ))
        self._dirty = False

    def search(
        self,
        query: str,
        *,
        k: int = 5,
    ) -> list[tuple[str, float, str]]:
        """Search for similar documents."""
        if self._dirty or self._embeddings is None:
            self.rebuild()
        if self._embeddings is None or len(self._embeddings) == 0:
            return []

        import numpy as np
        query_emb = self._model.encode(
            [query],
            normalize_embeddings=True,
        )
        scores = np.dot(self._embeddings, query_emb.T).flatten()
        top_indices = scores.argsort()[::-1][:k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score > 0:
                results.append((
                    self._revision_ids[idx],
                    score,
                    self._texts[idx],
                ))
        return results

    def save_embeddings(self, path: str | Path) -> None:
        """Save embeddings, texts, and revision IDs to disk.

        Saves the precomputed embeddings so they don't need to be
        recomputed on reload. Much faster than re-encoding all texts.
        """
        import pickle
        if self._dirty or self._embeddings is None:
            self.rebuild()
        state = {
            "texts": self._texts,
            "revision_ids": self._revision_ids,
            "embeddings": self._embeddings,
            "model_name": self._model_name,
            "dimension": self._dimension,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f)

    def load_embeddings(self, path: str | Path) -> None:
        """Load saved embeddings from disk.

        Restores precomputed embeddings, skipping the expensive encoding step.
        Uses RestrictedUnpickler for safety (blocks arbitrary code execution).
        """
        from .pipeline import _safe_pickle_load
        state = _safe_pickle_load(path)
        self._texts = state["texts"]
        self._revision_ids = state["revision_ids"]
        self._embeddings = state["embeddings"]
        self._dirty = False

    @property
    def size(self) -> int:
        return len(self._texts)

    @property
    def model_name(self) -> str:
        """Name of the sentence-transformer model."""
        return self._model_name

    def get_state(self) -> dict:
        """Return serializable state for persistence."""
        if self._dirty or self._embeddings is None:
            if self._texts:
                self.rebuild()
        return {
            "texts": self._texts,
            "revision_ids": self._revision_ids,
            "embeddings": self._embeddings,
            "dimension": self._dimension,
        }

    @classmethod
    def from_state(cls, state: dict, model_name: str = "all-MiniLM-L6-v2") -> "SentenceTransformerIndex":
        """Restore from saved state."""
        obj = cls.__new__(cls)
        obj._batch_size = 64
        obj._model_name = model_name
        obj._texts = state["texts"]
        obj._revision_ids = state["revision_ids"]
        obj._embeddings = state["embeddings"]
        obj._dimension = state.get("dimension", 384)
        obj._dirty = False
        try:
            from sentence_transformers import SentenceTransformer
            obj._model = SentenceTransformer(model_name)
            obj._dimension = obj._model.get_sentence_embedding_dimension()
        except ImportError:
            raise ImportError(
                "sentence-transformers required to load dense embeddings: "
                "pip install sentence-transformers"
            )
        return obj


class DenseSearchIndex:
    """Full search index using sentence-transformer embeddings with temporal awareness.

    Drop-in replacement for TfidfSearchIndex with semantic understanding.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        model_name: str = "all-MiniLM-L6-v2",
        **kwargs: Any,
    ) -> None:
        self._store = store
        self._dense = SentenceTransformerIndex(model_name, **kwargs)

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @store.setter
    def store(self, value: KnowledgeStore) -> None:
        self._store = value

    def add(self, revision_id: str, text: str) -> None:
        self._dense.add(revision_id, text)

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        self._dense.add_batch(items)

    def rebuild(self) -> None:
        self._dense.rebuild()

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Search with temporal filtering."""
        if self._dense._dirty or self._dense._embeddings is None:
            self._dense.rebuild()

        raw_results = self._dense.search(query, k=k * 3)
        return _apply_temporal_filter(self._store, raw_results, k, valid_at, tx_id)

    @property
    def size(self) -> int:
        return self._dense.size

    @property
    def dense(self) -> SentenceTransformerIndex:
        """Public access to the underlying SentenceTransformerIndex component."""
        return self._dense

    @classmethod
    def from_state(cls, store: KnowledgeStore, dense: SentenceTransformerIndex) -> "DenseSearchIndex":
        """Restore from a pre-built SentenceTransformerIndex component."""
        obj = cls.__new__(cls)
        obj._store = store
        obj._dense = dense
        return obj


class HybridSearchIndex:
    """Hybrid search fusing TF-IDF keyword scores + dense semantic scores.

    Uses reciprocal rank fusion (RRF) to combine:
    - TF-IDF: Great for exact keyword matching, rare terms, specific entities
    - Dense: Great for semantic meaning, paraphrasing, conceptual similarity

    The combination is strictly better than either alone.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        model_name: str = "all-MiniLM-L6-v2",
        *,
        alpha: float = 0.5,
        rrf_k: int = 60,
        **tfidf_kwargs: Any,
    ) -> None:
        """
        Args:
            store: KnowledgeStore for temporal filtering.
            model_name: Sentence-transformer model name.
            alpha: Weight for dense scores (1-alpha for TF-IDF). Default 0.5.
            rrf_k: RRF constant (higher = smoother fusion). Default 60.
        """
        self._store = store
        self._tfidf = TfidfIndex(**tfidf_kwargs)
        self._dense = SentenceTransformerIndex(model_name)
        self._alpha = alpha
        self._rrf_k = rrf_k

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @store.setter
    def store(self, value: KnowledgeStore) -> None:
        self._store = value

    def add(self, revision_id: str, text: str) -> None:
        self._tfidf.add(revision_id, text)
        self._dense.add(revision_id, text)

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        self._tfidf.add_batch(items)
        self._dense.add_batch(items)

    def rebuild(self) -> None:
        self._tfidf.rebuild()
        self._dense.rebuild()

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Hybrid search with reciprocal rank fusion."""
        # Get candidates from both systems
        n_candidates = k * 5
        tfidf_results = self._tfidf.search(query, k=n_candidates)
        dense_results = self._dense.search(query, k=n_candidates)

        # Build rank maps
        tfidf_ranks: dict[str, int] = {}
        for rank, (rid, score, text) in enumerate(tfidf_results):
            tfidf_ranks[rid] = rank

        dense_ranks: dict[str, int] = {}
        for rank, (rid, score, text) in enumerate(dense_results):
            dense_ranks[rid] = rank

        # Collect all candidate revision_ids
        all_candidates = set(tfidf_ranks.keys()) | set(dense_ranks.keys())

        # Compute RRF scores
        rrf_scores: list[tuple[str, float]] = []
        for rid in all_candidates:
            tfidf_rank = tfidf_ranks.get(rid, n_candidates)
            dense_rank = dense_ranks.get(rid, n_candidates)

            tfidf_rrf = 1.0 / (self._rrf_k + tfidf_rank)
            dense_rrf = 1.0 / (self._rrf_k + dense_rank)

            fused = (1 - self._alpha) * tfidf_rrf + self._alpha * dense_rrf
            rrf_scores.append((rid, fused))

        rrf_scores.sort(key=lambda x: -x[1])

        # Build text lookup
        text_lookup: dict[str, str] = {}
        for rid, score, text in tfidf_results:
            text_lookup[rid] = text
        for rid, score, text in dense_results:
            text_lookup.setdefault(rid, text)

        # Apply temporal filtering
        candidates = [(rid, score, text_lookup.get(rid, "")) for rid, score in rrf_scores]
        return _apply_temporal_filter(self._store, candidates, k, valid_at, tx_id)

    @property
    def size(self) -> int:
        return self._tfidf.size

    @property
    def tfidf(self) -> TfidfIndex:
        """Public access to the underlying TfidfIndex component."""
        return self._tfidf

    @property
    def dense(self) -> SentenceTransformerIndex:
        """Public access to the underlying SentenceTransformerIndex component."""
        return self._dense

    @property
    def alpha(self) -> float:
        """Dense/TF-IDF fusion weight."""
        return self._alpha

    @property
    def rrf_k(self) -> int:
        """Reciprocal rank fusion constant."""
        return self._rrf_k

    @classmethod
    def from_state(
        cls,
        store: KnowledgeStore,
        tfidf: TfidfIndex,
        dense: SentenceTransformerIndex,
        *,
        alpha: float = 0.5,
        rrf_k: int = 60,
    ) -> "HybridSearchIndex":
        """Restore from pre-built TF-IDF and dense components."""
        obj = cls.__new__(cls)
        obj._store = store
        obj._tfidf = tfidf
        obj._dense = dense
        obj._alpha = alpha
        obj._rrf_k = rrf_k
        return obj


class CrossEncoderReranker:
    """Cross-encoder re-ranker for high-precision result ordering.

    Bi-encoders (SentenceTransformer, TF-IDF) retrieve candidates fast but
    sacrifice precision. Cross-encoders process query+document TOGETHER
    through the full transformer, giving much better relevance scores.

    Standard retrieve-then-rerank pattern:
    1. Bi-encoder retrieves top-N candidates (fast, approximate)
    2. Cross-encoder re-ranks those N candidates (slow, precise)

    Default model: cross-encoder/ms-marco-MiniLM-L-6-v2 (trained on MS MARCO)
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise ImportError(
                "sentence-transformers required: pip install sentence-transformers"
            )
        self._model = CrossEncoder(model_name)

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        *,
        top_k: int | None = None,
    ) -> list[SearchResult]:
        """Re-rank search results using cross-encoder scoring.

        Args:
            query: The original query string.
            results: Candidate SearchResults from a bi-encoder/TF-IDF stage.
            top_k: If provided, return only the top-k re-ranked results.

        Returns:
            Re-ranked list of SearchResult with updated scores.
        """
        if not results:
            return []

        # Build query-document pairs
        pairs = [[query, r.text] for r in results]

        # Score with cross-encoder
        scores = self._model.predict(pairs)

        # Build re-ranked results
        reranked = []
        for r, score in zip(results, scores):
            reranked.append(SearchResult(
                core_id=r.core_id,
                revision_id=r.revision_id,
                score=float(score),
                text=r.text,
            ))

        reranked.sort(key=lambda r: -r.score)

        if top_k is not None:
            return reranked[:top_k]
        return reranked


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
