from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_query_revision_lifecycle_as_of_buckets_active_and_retracted_winners() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    core_active = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": "Grace Hopper"},
    )
    core_future = ClaimCore(claim_type="residence", slots={"subject": "Katherine Johnson"})

    active_revision = store.assert_revision(
        core=core_active,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_active"),
        confidence_bp=8000,
        status="asserted",
    )
    prior_asserted = store.assert_revision(
        core=core_retracted,
        assertion="Grace lives in New York",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_prior_asserted"),
        confidence_bp=8000,
        status="asserted",
    )
    retracted_winner = store.assert_revision(
        core=core_retracted,
        assertion="Grace lives in New York",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_retracted"),
        confidence_bp=8000,
        status="retracted",
    )
    store.assert_revision(
        core=core_future,
        assertion="Katherine lives in Virginia",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_future"),
        confidence_bp=8000,
        status="asserted",
    )

    projection_tx1 = store.query_revision_lifecycle_as_of(
        tx_id=1,
        valid_at=dt(2024, 6, 1),
    )
    assert projection_tx1.active == (prior_asserted,)
    assert projection_tx1.retracted == ()

    projection_tx2 = store.query_revision_lifecycle_as_of(
        tx_id=2,
        valid_at=dt(2024, 6, 1),
    )
    assert projection_tx2.active == (active_revision,)
    assert projection_tx2.retracted == (retracted_winner,)


def test_query_revision_lifecycle_as_of_is_deterministically_ordered() -> None:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    specs = (
        (
            ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"}),
            "Ada lives in London",
            "asserted",
            "source_a",
        ),
        (
            ClaimCore(claim_type="residence", slots={"subject": "Grace Hopper"}),
            "Grace lives in New York",
            "asserted",
            "source_b",
        ),
        (
            ClaimCore(claim_type="residence", slots={"subject": "Katherine Johnson"}),
            "Katherine lives in Virginia",
            "retracted",
            "source_c",
        ),
        (
            ClaimCore(claim_type="residence", slots={"subject": "Dorothy Vaughan"}),
            "Dorothy lives in Cleveland",
            "retracted",
            "source_d",
        ),
    )

    def build_store(order: tuple[int, ...]) -> KnowledgeStore:
        store = KnowledgeStore()
        for index in order:
            core, assertion, status, source = specs[index]
            store.assert_revision(
                core=core,
                assertion=assertion,
                valid_time=valid_time,
                transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
                provenance=Provenance(source=source),
                confidence_bp=7600,
                status=status,
            )
        return store

    forward_store = build_store((0, 1, 2, 3))
    reverse_store = build_store((3, 2, 1, 0))

    forward_projection = forward_store.query_revision_lifecycle_as_of(
        tx_id=7,
        valid_at=dt(2024, 6, 1),
    )
    reverse_projection = reverse_store.query_revision_lifecycle_as_of(
        tx_id=7,
        valid_at=dt(2024, 6, 1),
    )

    assert forward_projection == reverse_projection
    assert tuple(
        revision.revision_id for revision in forward_projection.active
    ) == tuple(sorted(revision.revision_id for revision in forward_projection.active))
    assert tuple(
        revision.revision_id for revision in forward_projection.retracted
    ) == tuple(sorted(revision.revision_id for revision in forward_projection.retracted))


def test_query_revision_lifecycle_as_of_supports_core_filtering() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    active_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    retracted_core = ClaimCore(claim_type="residence", slots={"subject": "Grace Hopper"})

    active_revision = store.assert_revision(
        core=active_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_active"),
        confidence_bp=8100,
        status="asserted",
    )
    store.assert_revision(
        core=retracted_core,
        assertion="Grace lives in New York",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_prior"),
        confidence_bp=8100,
        status="asserted",
    )
    retracted_revision = store.assert_revision(
        core=retracted_core,
        assertion="Grace lives in New York",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_retracted"),
        confidence_bp=8100,
        status="retracted",
    )

    active_projection = store.query_revision_lifecycle_as_of(
        tx_id=3,
        valid_at=dt(2024, 6, 1),
        core_id=active_core.core_id,
    )
    assert active_projection.active == (active_revision,)
    assert active_projection.retracted == ()

    retracted_projection = store.query_revision_lifecycle_as_of(
        tx_id=3,
        valid_at=dt(2024, 6, 1),
        core_id=retracted_core.core_id,
    )
    assert retracted_projection.active == ()
    assert retracted_projection.retracted == (retracted_revision,)

    missing_projection = store.query_revision_lifecycle_as_of(
        tx_id=3,
        valid_at=dt(2024, 6, 1),
        core_id="missing-core",
    )
    assert missing_projection.active == ()
    assert missing_projection.retracted == ()


def test_query_revision_lifecycle_as_of_active_bucket_matches_query_as_of() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    core_active_a = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    core_active_b = ClaimCore(
        claim_type="residence",
        slots={"subject": "Katherine Johnson"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": "Grace Hopper"},
    )

    store.assert_revision(
        core=core_active_a,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_a"),
        confidence_bp=8200,
        status="asserted",
    )
    store.assert_revision(
        core=core_active_b,
        assertion="Katherine lives in Virginia",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_b"),
        confidence_bp=8200,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="Grace lives in New York",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_prior"),
        confidence_bp=8200,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="Grace lives in New York",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_retracted"),
        confidence_bp=8200,
        status="retracted",
    )

    tx_cutoff = 4
    valid_at = dt(2024, 6, 1)
    projection = store.query_revision_lifecycle_as_of(tx_id=tx_cutoff, valid_at=valid_at)

    expected_active = []
    for core_id in sorted((core_active_a.core_id, core_active_b.core_id, core_retracted.core_id)):
        winner = store.query_as_of(core_id, valid_at=valid_at, tx_id=tx_cutoff)
        if winner is not None:
            expected_active.append(winner)
    expected_active.sort(key=lambda revision: revision.revision_id)

    assert projection.active == tuple(expected_active)


def test_query_revision_lifecycle_for_tx_window_matches_as_of_filtered_projection() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    core_before = ClaimCore(claim_type="residence", slots={"subject": "before window"})
    core_start = ClaimCore(claim_type="residence", slots={"subject": "start boundary"})
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": "retracted winner"},
    )
    core_end = ClaimCore(claim_type="residence", slots={"subject": "end boundary"})

    store.assert_revision(
        core=core_before,
        assertion="before-window winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_before"),
        confidence_bp=8300,
        status="asserted",
    )
    start_winner = store.assert_revision(
        core=core_start,
        assertion="start-boundary winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_start"),
        confidence_bp=8300,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="retracted winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_prior"),
        confidence_bp=8300,
        status="asserted",
    )
    retracted_winner = store.assert_revision(
        core=core_retracted,
        assertion="retracted winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_retracted"),
        confidence_bp=8300,
        status="retracted",
    )
    end_winner = store.assert_revision(
        core=core_end,
        assertion="end-boundary winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_end"),
        confidence_bp=8300,
        status="asserted",
    )

    tx_windows = (
        (4, 4),
        (5, 5),
        (5, 6),
        (6, 7),
        (4, 7),
    )
    for tx_start, tx_end in tx_windows:
        projection = store.query_revision_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=dt(2024, 6, 1),
        )
        as_of_projection = store.query_revision_lifecycle_as_of(
            tx_id=tx_end,
            valid_at=dt(2024, 6, 1),
        )
        assert projection.active == tuple(
            revision
            for revision in as_of_projection.active
            if tx_start <= revision.transaction_time.tx_id <= tx_end
        )
        assert projection.retracted == tuple(
            revision
            for revision in as_of_projection.retracted
            if tx_start <= revision.transaction_time.tx_id <= tx_end
        )

    full_window = store.query_revision_lifecycle_for_tx_window(
        tx_start=5,
        tx_end=7,
        valid_at=dt(2024, 6, 1),
    )
    assert full_window.active == tuple(
        sorted((start_winner, end_winner), key=lambda revision: revision.revision_id)
    )
    assert full_window.retracted == (retracted_winner,)


def test_query_revision_lifecycle_for_tx_window_includes_start_and_end_boundaries() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    core_before = ClaimCore(claim_type="residence", slots={"subject": "outside"})
    core_start = ClaimCore(claim_type="residence", slots={"subject": "start"})
    core_end = ClaimCore(claim_type="residence", slots={"subject": "end"})

    store.assert_revision(
        core=core_before,
        assertion="outside",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=9, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_before"),
        confidence_bp=8400,
        status="asserted",
    )
    start_winner = store.assert_revision(
        core=core_start,
        assertion="start",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
        provenance=Provenance(source="source_start"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_end,
        assertion="end",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=11, recorded_at=dt(2024, 1, 12)),
        provenance=Provenance(source="source_prior"),
        confidence_bp=8400,
        status="asserted",
    )
    end_winner = store.assert_revision(
        core=core_end,
        assertion="end",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=12, recorded_at=dt(2024, 1, 13)),
        provenance=Provenance(source="source_end"),
        confidence_bp=8400,
        status="retracted",
    )

    projection = store.query_revision_lifecycle_for_tx_window(
        tx_start=10,
        tx_end=12,
        valid_at=dt(2024, 6, 1),
    )
    assert projection.active == (start_winner,)
    assert projection.retracted == (end_winner,)


def test_query_revision_lifecycle_for_tx_window_rejects_inverted_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore().query_revision_lifecycle_for_tx_window(
            tx_start=8,
            tx_end=7,
            valid_at=dt(2024, 6, 1),
        )
