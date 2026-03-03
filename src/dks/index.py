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
from dataclasses import dataclass, field
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

        # Filter by temporal visibility if requested
        results: list[SearchResult] = []
        for score, revision_id in scored:
            if len(results) >= k:
                break

            revision = self._store.revisions.get(revision_id)
            if revision is None:
                continue

            # Temporal filter: check if this revision is the winner at the query point
            if valid_at is not None and tx_id is not None:
                winner = self._store.query_as_of(
                    revision.core_id,
                    valid_at=valid_at,
                    tx_id=tx_id,
                )
                if winner is None or winner.revision_id != revision_id:
                    continue

            results.append(SearchResult(
                core_id=revision.core_id,
                revision_id=revision_id,
                score=score,
                text=self._texts.get(revision_id, ""),
            ))

        return results

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

        results: list[SearchResult] = []
        for revision_id, score, text in raw_results:
            if len(results) >= k:
                break

            revision = self._store.revisions.get(revision_id)
            if revision is None:
                continue

            if valid_at is not None and tx_id is not None:
                winner = self._store.query_as_of(
                    revision.core_id,
                    valid_at=valid_at,
                    tx_id=tx_id,
                )
                if winner is None or winner.revision_id != revision_id:
                    continue

            results.append(SearchResult(
                core_id=revision.core_id,
                revision_id=revision_id,
                score=score,
                text=text,
            ))

        return results

    @property
    def size(self) -> int:
        return self._tfidf.size


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
        self._adjacency = {}
        for cluster_id, members in self._clusters.items():
            if len(members) <= 1:
                continue

            member_indices = [
                revision_ids.index(rid) for rid in members
            ]
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
