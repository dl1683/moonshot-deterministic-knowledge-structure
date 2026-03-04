"""Tests for Pipeline save/load round-trip — critical data integrity path."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dks import KnowledgeStore, Pipeline, TfidfSearchIndex


def dt(year: int = 2024, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_pipeline() -> Pipeline:
    """Create a Pipeline with TF-IDF index and two ingested documents."""
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    pipeline = Pipeline(store=store, search_index=index)

    pipeline.ingest_text(
        "Neural networks process information through layers of interconnected nodes. "
        "Deep learning uses many layers to learn hierarchical representations. "
        "Backpropagation adjusts weights to minimize error.",
        source="ml_textbook.pdf",
    )
    pipeline.ingest_text(
        "Quantum computing uses qubits that can exist in superposition. "
        "Quantum entanglement allows correlated measurements across distance. "
        "Quantum algorithms can solve certain problems exponentially faster.",
        source="quantum_guide.pdf",
    )

    index.rebuild()
    return pipeline


# ---- Basic Round-Trip ----


class TestBasicRoundTrip:
    def test_store_contents_preserved(self) -> None:
        """Core count, revision count, and assertions survive save/load."""
        original = _make_pipeline()
        orig_cores = len(original.store.cores)
        orig_revs = len(original.store.revisions)

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        assert len(loaded.store.cores) == orig_cores
        assert len(loaded.store.revisions) == orig_revs

    def test_revision_assertions_match(self) -> None:
        """Every revision assertion text is identical after round-trip."""
        original = _make_pipeline()
        orig_assertions = {
            rid: rev.assertion for rid, rev in original.store.revisions.items()
        }

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        for rid, text in orig_assertions.items():
            assert rid in loaded.store.revisions
            assert loaded.store.revisions[rid].assertion == text

    def test_tx_counter_preserved(self) -> None:
        """tx_counter restores so new transactions don't collide."""
        original = _make_pipeline()
        orig_tx = original._tx_counter

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        assert loaded._tx_counter == orig_tx

    def test_loaded_pipeline_can_query(self) -> None:
        """Loaded pipeline returns search results for known content."""
        original = _make_pipeline()

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        results = loaded.query("neural networks deep learning")
        assert len(results) >= 1
        # The top result should mention neural/learning content
        assert any("neural" in r.text.lower() or "learning" in r.text.lower() for r in results)


# ---- TF-IDF Index Round-Trip ----


class TestTfidfRoundTrip:
    def test_search_results_equivalent(self) -> None:
        """Original and loaded pipelines return the same top result for a query."""
        original = _make_pipeline()
        orig_results = original.query("quantum computing qubits")

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        loaded_results = loaded.query("quantum computing qubits")
        assert len(loaded_results) == len(orig_results)

        # Same revision_ids in the same order
        orig_rids = [r.revision_id for r in orig_results]
        loaded_rids = [r.revision_id for r in loaded_results]
        assert orig_rids == loaded_rids

    def test_index_size_preserved(self) -> None:
        """TF-IDF index size matches after round-trip."""
        original = _make_pipeline()
        orig_size = original._index.size

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        assert loaded._index.size == orig_size

    def test_tfidf_files_written(self) -> None:
        """Save produces the expected TF-IDF artifact files."""
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as tmp:
            pipeline.save(tmp)
            d = Path(tmp)
            assert (d / "store.json").exists()
            assert (d / "meta.json").exists()
            assert (d / "tfidf_state.pkl").exists()
            assert (d / "tfidf_vectorizer.pkl").exists()
            assert (d / "tfidf_matrix.pkl").exists()


# ---- Knowledge Graph Round-Trip ----


class TestGraphRoundTrip:
    def test_graph_neighbors_survive(self) -> None:
        """Graph adjacency is restored so neighbors() works after load."""
        original = _make_pipeline()
        original.build_graph(n_clusters=2, similarity_threshold=0.05)

        # Pick a revision that has neighbors
        some_rid = list(original.store.revisions.keys())[0]
        orig_neighbors = original.neighbors(some_rid, k=3)

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        loaded_neighbors = loaded.neighbors(some_rid, k=3)
        orig_nids = [r.revision_id for r in orig_neighbors]
        loaded_nids = [r.revision_id for r in loaded_neighbors]
        assert orig_nids == loaded_nids

    def test_topics_survive(self) -> None:
        """Topic clusters are restored after load."""
        original = _make_pipeline()
        original.build_graph(n_clusters=2, similarity_threshold=0.05)
        orig_topics = original.topics()

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        loaded_topics = loaded.topics()
        assert len(loaded_topics) == len(orig_topics)
        for ot, lt in zip(orig_topics, loaded_topics):
            assert ot["cluster_id"] == lt["cluster_id"]
            assert ot["size"] == lt["size"]

    def test_graph_pkl_written(self) -> None:
        """Graph pickle file is created when graph exists."""
        pipeline = _make_pipeline()
        pipeline.build_graph(n_clusters=2)

        with tempfile.TemporaryDirectory() as tmp:
            pipeline.save(tmp)
            assert (Path(tmp) / "graph.pkl").exists()

    def test_no_graph_no_file(self) -> None:
        """No graph pickle is written when graph was never built."""
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as tmp:
            pipeline.save(tmp)
            assert not (Path(tmp) / "graph.pkl").exists()


# ---- Chunk Siblings Round-Trip (P1-5 fix) ----


class TestChunkSiblingsRoundTrip:
    def test_expand_context_after_load(self) -> None:
        """expand_context() works on loaded pipeline (chunk siblings propagated)."""
        original = _make_pipeline()
        results = original.query("neural networks")
        assert len(results) >= 1

        # expand_context should return the original plus siblings
        orig_expanded = original.expand_context(results[0], window=1)

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        loaded_results = loaded.query("neural networks")
        loaded_expanded = loaded.expand_context(loaded_results[0], window=1)

        # Same revision IDs in expanded context
        orig_exp_rids = [r.revision_id for r in orig_expanded]
        loaded_exp_rids = [r.revision_id for r in loaded_expanded]
        assert orig_exp_rids == loaded_exp_rids

    def test_chunk_siblings_dict_restored(self) -> None:
        """The _chunk_siblings dict is restored with correct source keys."""
        original = _make_pipeline()
        orig_siblings = dict(original._chunk_siblings)
        assert len(orig_siblings) > 0  # We ingested two sources

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        assert loaded._chunk_siblings == orig_siblings

    def test_siblings_propagated_to_submodules(self) -> None:
        """After load, _search and _ingester share the same siblings reference."""
        original = _make_pipeline()

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        assert loaded._search._chunk_siblings is loaded._chunk_siblings
        assert loaded._ingester._chunk_siblings is loaded._chunk_siblings

    def test_chunk_siblings_pkl_written(self) -> None:
        """Chunk siblings pickle is created when siblings exist."""
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as tmp:
            pipeline.save(tmp)
            assert (Path(tmp) / "chunk_siblings.pkl").exists()


# ---- Metadata Preservation ----


class TestMetadata:
    def test_metadata_fields(self) -> None:
        """Saved meta.json contains expected fields."""
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as tmp:
            pipeline.save(tmp)
            with open(Path(tmp) / "meta.json") as f:
                meta = json.load(f)

        import dks
        assert meta["version"] == dks.__version__
        assert meta["cores"] == len(pipeline.store.cores)
        assert meta["revisions"] == len(pipeline.store.revisions)
        assert meta["tx_counter"] == pipeline._tx_counter
        assert meta["index_type"] == "tfidf"
        assert meta["indexed"] == pipeline._index.size

    def test_graph_metadata_when_graph_built(self) -> None:
        """Meta.json includes graph stats when graph exists."""
        pipeline = _make_pipeline()
        graph = pipeline.build_graph(n_clusters=2)

        with tempfile.TemporaryDirectory() as tmp:
            pipeline.save(tmp)
            with open(Path(tmp) / "meta.json") as f:
                meta = json.load(f)

        assert "graph_nodes" in meta
        assert "graph_edges" in meta
        assert "graph_clusters" in meta
        assert meta["graph_clusters"] == graph.total_clusters


# ---- Edge Cases ----


class TestEdgeCases:
    def test_empty_store(self) -> None:
        """Save/load with an empty store succeeds."""
        store = KnowledgeStore()
        index = TfidfSearchIndex(store)
        pipeline = Pipeline(store=store, search_index=index)

        with tempfile.TemporaryDirectory() as tmp:
            pipeline.save(tmp)
            loaded = Pipeline.load(tmp)

        assert len(loaded.store.cores) == 0
        assert len(loaded.store.revisions) == 0
        assert loaded._tx_counter == 0

    def test_no_search_index(self) -> None:
        """Save/load with no search index configured."""
        store = KnowledgeStore()
        pipeline = Pipeline(store=store)

        with tempfile.TemporaryDirectory() as tmp:
            pipeline.save(tmp)
            loaded = Pipeline.load(tmp)

        assert len(loaded.store.cores) == 0
        assert loaded._index is None

    def test_save_creates_directory(self) -> None:
        """Save creates the target directory if it does not exist."""
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "deep" / "nested" / "dir"
            assert not nested.exists()
            pipeline.save(nested)
            assert nested.exists()
            assert (nested / "store.json").exists()

    def test_ingest_after_load(self) -> None:
        """A loaded pipeline can ingest new data without errors."""
        original = _make_pipeline()

        with tempfile.TemporaryDirectory() as tmp:
            original.save(tmp)
            loaded = Pipeline.load(tmp)

        new_ids = loaded.ingest_text(
            "Relativity describes gravity as curvature of spacetime.",
            source="physics.pdf",
        )
        assert len(new_ids) >= 1
        # tx_counter should have advanced
        assert loaded._tx_counter > original._tx_counter
