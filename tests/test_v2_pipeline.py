"""Tests for dks.pipeline — end-to-end orchestration."""
from datetime import datetime, timezone

from dks import (
    ClaimCore,
    KnowledgeStore,
    NumpyIndex,
    Pipeline,
    Provenance,
    RegexExtractor,
    ExactResolver,
    CascadingResolver,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_pipeline() -> Pipeline:
    """Create a fully-configured Pipeline for testing."""
    extractor = RegexExtractor()
    extractor.register_pattern(
        "residence",
        r"(?P<subject>\w+) lives in (?P<city>\w+)",
        ["subject", "city"],
    )
    extractor.register_pattern(
        "role",
        r"(?P<subject>\w+) is a (?P<title>\w+)",
        ["subject", "title"],
    )

    resolver = ExactResolver()
    resolver.register("alice", "entity:alice")
    resolver.register("bob", "entity:bob")
    resolver.register("london", "entity:london")
    resolver.register("paris", "entity:paris")

    cascade = CascadingResolver([resolver])

    backend = NumpyIndex(dimension=64)

    return Pipeline(
        extractor=extractor,
        resolver=cascade,
        embedding_backend=backend,
    )


class TestPipelineIngest:
    def test_basic_ingest(self) -> None:
        pipeline = _make_pipeline()

        revision_ids = pipeline.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        assert len(revision_ids) == 1
        assert len(pipeline.store.cores) == 1
        assert len(pipeline.store.revisions) == 1

    def test_ingest_with_resolution(self) -> None:
        """Ingest should resolve entities through the resolver."""
        pipeline = _make_pipeline()

        pipeline.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        # The core should have resolved entity IDs in slots
        core = list(pipeline.store.cores.values())[0]
        # "alice" resolved to "entity:alice", "london" resolved to "entity:london"
        assert core.slots.get("subject") == "entity:alice"
        assert core.slots.get("city") == "entity:london"

    def test_ingest_multiple_claims(self) -> None:
        pipeline = _make_pipeline()

        revision_ids = pipeline.ingest(
            "Alice lives in London. Bob is a CEO.",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        assert len(revision_ids) == 2
        assert len(pipeline.store.cores) == 2

    def test_ingest_indexes_for_search(self) -> None:
        """Ingested claims should be searchable."""
        pipeline = _make_pipeline()

        pipeline.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        results = pipeline.query("lives in city", k=5)
        assert len(results) >= 1

    def test_ingest_without_extractor_raises(self) -> None:
        pipeline = Pipeline()
        try:
            pipeline.ingest(
                "text",
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            )
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_ingest_without_resolver_uses_raw_slots(self) -> None:
        """Without a resolver, slot values pass through unchanged."""
        extractor = RegexExtractor()
        extractor.register_pattern("fact", r"(?P<subject>\w+) exists", ["subject"])

        pipeline = Pipeline(extractor=extractor, embedding_backend=NumpyIndex(dimension=32))

        pipeline.ingest(
            "Alpha exists",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        core = list(pipeline.store.cores.values())[0]
        assert core.slots["subject"] == "alpha"  # canonicalized but not resolved


class TestPipelineQuery:
    def test_query_returns_results(self) -> None:
        pipeline = _make_pipeline()

        pipeline.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        results = pipeline.query("where does someone live")
        assert len(results) >= 1
        assert results[0].score > 0

    def test_query_with_temporal_filter(self) -> None:
        pipeline = _make_pipeline()

        pipeline.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        # Should find it at tx_id=1
        results = pipeline.query(
            "Alice London",
            valid_at=dt(2024, 6, 1),
            tx_id=1,
        )
        assert len(results) >= 1

        # Should NOT find it before tx_id=1
        results = pipeline.query(
            "Alice London",
            valid_at=dt(2024, 6, 1),
            tx_id=0,
        )
        assert len(results) == 0

    def test_query_without_backend_raises(self) -> None:
        pipeline = Pipeline()
        try:
            pipeline.query("test")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestPipelineQueryExact:
    def test_exact_query(self) -> None:
        pipeline = _make_pipeline()

        pipeline.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        core = list(pipeline.store.cores.values())[0]
        result = pipeline.query_exact(
            core.core_id,
            valid_at=dt(2024, 6, 1),
            tx_id=1,
        )
        assert result is not None

    def test_exact_query_not_found(self) -> None:
        pipeline = _make_pipeline()
        result = pipeline.query_exact(
            "nonexistent_core_id",
            valid_at=dt(2024, 6, 1),
            tx_id=1,
        )
        assert result is None


class TestPipelineMerge:
    def test_merge_two_pipelines(self) -> None:
        pipeline_a = _make_pipeline()
        pipeline_b = _make_pipeline()

        pipeline_a.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )
        pipeline_b.ingest(
            "Bob lives in Paris",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024)),
        )

        result = pipeline_a.merge(pipeline_b)

        # Merged store has both claims
        assert len(pipeline_a.store.cores) == 2
        assert len(pipeline_a.store.revisions) == 2

    def test_merge_and_rebuild_index(self) -> None:
        pipeline_a = _make_pipeline()
        pipeline_b = _make_pipeline()

        pipeline_a.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )
        pipeline_b.ingest(
            "Bob lives in Paris",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024)),
        )

        pipeline_a.merge(pipeline_b)
        count = pipeline_a.rebuild_index()
        assert count == 2

        # Search should find both
        results = pipeline_a.query("lives in")
        assert len(results) == 2


class TestPipelineRebuildIndex:
    def test_rebuild_index(self) -> None:
        pipeline = _make_pipeline()

        pipeline.ingest(
            "Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
        )

        count = pipeline.rebuild_index()
        assert count == 1

    def test_rebuild_without_backend_raises(self) -> None:
        pipeline = Pipeline()
        try:
            pipeline.rebuild_index()
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
