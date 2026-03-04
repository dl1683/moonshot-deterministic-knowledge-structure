"""Stress tests: property-based invariant verification using Hypothesis."""

import os
import shutil
import tempfile
from datetime import datetime, timezone
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from dks import (
    KnowledgeStore, Pipeline, TransactionTime, ValidTime,
    SearchResult, TfidfSearchIndex,
)


# --- Strategies ---

_text_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=10,
    max_size=200,
)

_source_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=3,
    max_size=20,
).map(lambda s: s.strip() or "default_source")


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_pipeline():
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


# --- Test Classes ---

class TestScoreInvariants:
    """Query scores must be in [0, 1] and sorted descending."""

    @given(
        texts=st.lists(_text_strategy, min_size=3, max_size=10),
        query=_text_strategy,
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_scores_bounded_and_sorted(self, texts, query):
        assume(len(query.strip()) > 2)
        assume(all(len(t.strip()) > 5 for t in texts))

        pipeline = _make_pipeline()
        for i, text in enumerate(texts):
            pipeline.ingest_text(text, source=f"doc{i}.txt")
        pipeline.rebuild_index()

        results = pipeline.query(query, k=5)
        for r in results:
            assert -1e-9 <= r.score <= 1.0 + 1e-9, f"Score {r.score} out of bounds"

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True), "Scores not sorted descending"


class TestValidObjectReferences:
    """Every revision_id in search results must exist in the store."""

    @given(
        texts=st.lists(_text_strategy, min_size=2, max_size=8),
        query=_text_strategy,
    )
    @settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow])
    def test_result_revision_ids_exist_in_store(self, texts, query):
        assume(len(query.strip()) > 2)
        assume(all(len(t.strip()) > 5 for t in texts))

        pipeline = _make_pipeline()
        for i, text in enumerate(texts):
            pipeline.ingest_text(text, source=f"doc{i}.txt")
        pipeline.rebuild_index()

        results = pipeline.query(query, k=10)
        for r in results:
            assert r.revision_id in pipeline.store.revisions, (
                f"revision_id {r.revision_id} not in store"
            )
            assert r.core_id in pipeline.store.cores, (
                f"core_id {r.core_id} not in store"
            )


class TestRetractionInvisibility:
    """Retracted sources should not appear in query results."""

    @given(
        texts=st.lists(_text_strategy, min_size=3, max_size=6),
        delete_idx=st.integers(min_value=0),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_deleted_source_invisible(self, texts, delete_idx):
        assume(all(len(t.strip()) > 5 for t in texts))

        pipeline = _make_pipeline()
        sources = []
        for i, text in enumerate(texts):
            src = f"doc{i}.txt"
            sources.append(src)
            pipeline.ingest_text(text, source=src)
        pipeline.rebuild_index()

        # Delete one source
        target = sources[delete_idx % len(sources)]
        pipeline.delete_source(target, reason="test retraction")
        pipeline.rebuild_index()

        # Query for anything — deleted source should not appear
        for text in texts:
            results = pipeline.query(text, k=20)
            for r in results:
                core = pipeline.store.cores.get(r.core_id)
                if core:
                    doc_source = core.slots.get("source", "")
                    assert doc_source != target, (
                        f"Retracted source {target} appeared in results"
                    )


class TestSaveLoadEquivalence:
    """Save → load round-trip must preserve query results exactly."""

    @given(
        texts=st.lists(_text_strategy, min_size=2, max_size=6),
        query=_text_strategy,
    )
    @settings(max_examples=15, suppress_health_check=[HealthCheck.too_slow])
    def test_save_load_preserves_results(self, texts, query):
        assume(len(query.strip()) > 2)
        assume(all(len(t.strip()) > 5 for t in texts))

        pipeline = _make_pipeline()
        for i, text in enumerate(texts):
            pipeline.ingest_text(text, source=f"doc{i}.txt")
        pipeline.rebuild_index()

        original_results = pipeline.query(query, k=5)

        tmpdir = tempfile.mkdtemp()
        try:
            pipeline.save(tmpdir)
            loaded = Pipeline.load(tmpdir)
            loaded_results = loaded.query(query, k=5)

            assert len(original_results) == len(loaded_results)
            for orig, load in zip(original_results, loaded_results):
                assert orig.revision_id == load.revision_id
                assert orig.core_id == load.core_id
                assert abs(orig.score - load.score) < 1e-6
        finally:
            shutil.rmtree(tmpdir)


class TestMergeSuperset:
    """Merging two stores must produce a superset of both."""

    @given(
        texts_a=st.lists(_text_strategy, min_size=1, max_size=5),
        texts_b=st.lists(_text_strategy, min_size=1, max_size=5),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_merge_is_superset(self, texts_a, texts_b):
        assume(all(len(t.strip()) > 5 for t in texts_a))
        assume(all(len(t.strip()) > 5 for t in texts_b))

        pipeline_a = _make_pipeline()
        for i, text in enumerate(texts_a):
            pipeline_a.ingest_text(text, source=f"a_doc{i}.txt")

        pipeline_b = _make_pipeline()
        for i, text in enumerate(texts_b):
            pipeline_b.ingest_text(text, source=f"b_doc{i}.txt")

        merged = pipeline_a.merge(pipeline_b)

        # merge() returns MergeResult; .merged is the KnowledgeStore
        cores_a = set(pipeline_a.store.cores.keys())
        cores_b = set(pipeline_b.store.cores.keys())
        cores_merged = set(merged.merged.cores.keys())

        assert cores_a.issubset(cores_merged), "cores from A missing after merge"
        assert cores_b.issubset(cores_merged), "cores from B missing after merge"


class TestHighVolumeIngestion:
    """System handles many documents without crashing or losing data."""

    @given(
        n_docs=st.integers(min_value=20, max_value=50),
    )
    @settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_high_volume_no_data_loss(self, n_docs):
        pipeline = _make_pipeline()
        expected_ids = []
        for i in range(n_docs):
            text = f"Document number {i} contains unique information about topic_{i} and details_{i}."
            ids = pipeline.ingest_text(text, source=f"bulk_{i}.txt")
            expected_ids.extend(ids)

        pipeline.rebuild_index()

        # Every ingested revision must be in store
        for rid in expected_ids:
            assert rid in pipeline.store.revisions, f"Missing revision {rid}"

        # Stats should reflect the count
        stats = pipeline.stats()
        assert stats["revisions"] >= n_docs


class TestTxCounterMonotonicity:
    """Transaction counter must strictly increase across operations."""

    @given(
        n_ops=st.integers(min_value=3, max_value=15),
    )
    @settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_tx_counter_increases(self, n_ops):
        pipeline = _make_pipeline()
        counters = []
        for i in range(n_ops):
            text = f"Operation {i} with content about item_{i}."
            pipeline.ingest_text(text, source=f"op_{i}.txt")
            counters.append(pipeline.tx_counter)

        # Must be strictly increasing
        for i in range(1, len(counters)):
            assert counters[i] > counters[i - 1], (
                f"tx_counter not monotonic: {counters}"
            )


class TestDeleteSourceExclusion:
    """After deleting a source, list_sources must not include it."""

    @given(
        n_sources=st.integers(min_value=2, max_value=6),
        delete_idx=st.integers(min_value=0),
    )
    @settings(max_examples=15, suppress_health_check=[HealthCheck.too_slow])
    def test_deleted_source_not_listed(self, n_sources, delete_idx):
        pipeline = _make_pipeline()
        sources = []
        for i in range(n_sources):
            src = f"source_{i}.txt"
            sources.append(src)
            pipeline.ingest_text(
                f"Content for source {i} about topic_{i}.",
                source=src,
            )

        target = sources[delete_idx % len(sources)]
        pipeline.delete_source(target, reason="test")

        listed = pipeline.list_sources()
        listed_names = [s["source"] for s in listed]
        assert target not in listed_names, (
            f"Deleted source {target} still listed"
        )
