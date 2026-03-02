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


def _assert_revision_ids_sorted(*buckets: tuple) -> None:
    for bucket in buckets:
        revision_ids = tuple(revision.revision_id for revision in bucket)
        assert revision_ids == tuple(sorted(revision_ids))


def test_query_revision_lifecycle_transition_for_tx_window_tracks_entered_and_exited_buckets() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    core_enter_active = ClaimCore(claim_type="residence", slots={"subject": "enter-active"})
    core_exit_active = ClaimCore(claim_type="residence", slots={"subject": "exit-active"})
    core_exit_retracted = ClaimCore(claim_type="residence", slots={"subject": "exit-retracted"})
    core_stable_active = ClaimCore(claim_type="residence", slots={"subject": "stable-active"})
    core_stable_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": "stable-retracted"},
    )

    entered_active = store.assert_revision(
        core=core_enter_active,
        assertion="entered active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_enter_active"),
        confidence_bp=8300,
        status="asserted",
    )
    exited_active = store.assert_revision(
        core=core_exit_active,
        assertion="exited active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_exit_active_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    entered_retracted = store.assert_revision(
        core=core_exit_active,
        assertion="exited active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_exit_active_retracted"),
        confidence_bp=8300,
        status="retracted",
    )
    exited_retracted = store.assert_revision(
        core=core_exit_retracted,
        assertion="exited retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_exit_retracted_retracted"),
        confidence_bp=8300,
        status="retracted",
    )
    entered_active_from_retracted = store.assert_revision(
        core=core_exit_retracted,
        assertion="exited retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_exit_retracted_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    store.assert_revision(
        core=core_stable_active,
        assertion="stable active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_stable_active"),
        confidence_bp=8300,
        status="asserted",
    )
    store.assert_revision(
        core=core_stable_retracted,
        assertion="stable retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_stable_retracted_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    store.assert_revision(
        core=core_stable_retracted,
        assertion="stable retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_stable_retracted_retracted"),
        confidence_bp=8300,
        status="retracted",
    )

    transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=3,
        tx_to=6,
        valid_at=dt(2024, 6, 1),
    )

    assert transition.tx_from == 3
    assert transition.tx_to == 6
    assert transition.entered_active == tuple(
        sorted(
            (entered_active, entered_active_from_retracted),
            key=lambda revision: revision.revision_id,
        )
    )
    assert transition.exited_active == (exited_active,)
    assert transition.entered_retracted == (entered_retracted,)
    assert transition.exited_retracted == (exited_retracted,)
    _assert_revision_ids_sorted(
        transition.entered_active,
        transition.exited_active,
        transition.entered_retracted,
        transition.exited_retracted,
    )


def test_query_revision_lifecycle_transition_for_tx_window_zero_delta_has_empty_buckets() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    core_active = ClaimCore(claim_type="residence", slots={"subject": "zero-delta-active"})
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": "zero-delta-retracted"},
    )

    store.assert_revision(
        core=core_active,
        assertion="zero-delta active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_zero_delta_active"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="zero-delta retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_zero_delta_retracted_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="zero-delta retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_zero_delta_retracted"),
        confidence_bp=8400,
        status="retracted",
    )

    transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=5,
        tx_to=5,
        valid_at=dt(2024, 6, 1),
    )

    assert transition.entered_active == ()
    assert transition.exited_active == ()
    assert transition.entered_retracted == ()
    assert transition.exited_retracted == ()


def test_query_revision_lifecycle_transition_for_tx_window_supports_core_filtering() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    target_core = ClaimCore(claim_type="residence", slots={"subject": "target-core"})
    other_core = ClaimCore(claim_type="residence", slots={"subject": "other-core"})

    target_exited_active = store.assert_revision(
        core=target_core,
        assertion="target lifecycle",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_target_asserted"),
        confidence_bp=8500,
        status="asserted",
    )
    target_entered_retracted = store.assert_revision(
        core=target_core,
        assertion="target lifecycle",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_target_retracted"),
        confidence_bp=8500,
        status="retracted",
    )
    other_entered_active = store.assert_revision(
        core=other_core,
        assertion="other lifecycle",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_other_asserted"),
        confidence_bp=8500,
        status="asserted",
    )

    unfiltered_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=2,
        tx_to=4,
        valid_at=dt(2024, 6, 1),
    )
    filtered_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=2,
        tx_to=4,
        valid_at=dt(2024, 6, 1),
        core_id=target_core.core_id,
    )

    assert other_entered_active in unfiltered_transition.entered_active
    assert filtered_transition.entered_active == ()
    assert filtered_transition.exited_active == (target_exited_active,)
    assert filtered_transition.entered_retracted == (target_entered_retracted,)
    assert filtered_transition.exited_retracted == ()


def test_query_revision_lifecycle_transition_for_tx_window_matches_explicit_as_of_set_diffs() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    core_a = ClaimCore(claim_type="residence", slots={"subject": "diff-core-a"})
    core_b = ClaimCore(claim_type="residence", slots={"subject": "diff-core-b"})
    core_c = ClaimCore(claim_type="residence", slots={"subject": "diff-core-c"})

    store.assert_revision(
        core=core_a,
        assertion="diff core a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_diff_a_asserted"),
        confidence_bp=8600,
        status="asserted",
    )
    store.assert_revision(
        core=core_a,
        assertion="diff core a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_diff_a_retracted"),
        confidence_bp=8600,
        status="retracted",
    )
    store.assert_revision(
        core=core_b,
        assertion="diff core b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_diff_b_retracted"),
        confidence_bp=8600,
        status="retracted",
    )
    store.assert_revision(
        core=core_b,
        assertion="diff core b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_diff_b_asserted"),
        confidence_bp=8600,
        status="asserted",
    )
    store.assert_revision(
        core=core_c,
        assertion="diff core c",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_diff_c_asserted"),
        confidence_bp=8600,
        status="asserted",
    )

    tx_from = 3
    tx_to = 7
    from_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_from,
        valid_at=dt(2024, 6, 1),
    )
    to_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_to,
        valid_at=dt(2024, 6, 1),
    )
    transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=dt(2024, 6, 1),
    )

    from_active = {revision.revision_id: revision for revision in from_projection.active}
    to_active = {revision.revision_id: revision for revision in to_projection.active}
    from_retracted = {
        revision.revision_id: revision for revision in from_projection.retracted
    }
    to_retracted = {revision.revision_id: revision for revision in to_projection.retracted}

    assert transition.entered_active == tuple(
        to_active[revision_id] for revision_id in sorted(set(to_active) - set(from_active))
    )
    assert transition.exited_active == tuple(
        from_active[revision_id]
        for revision_id in sorted(set(from_active) - set(to_active))
    )
    assert transition.entered_retracted == tuple(
        to_retracted[revision_id]
        for revision_id in sorted(set(to_retracted) - set(from_retracted))
    )
    assert transition.exited_retracted == tuple(
        from_retracted[revision_id]
        for revision_id in sorted(set(from_retracted) - set(to_retracted))
    )
    _assert_revision_ids_sorted(
        transition.entered_active,
        transition.exited_active,
        transition.entered_retracted,
        transition.exited_retracted,
    )


def test_query_revision_lifecycle_transition_for_tx_window_rejects_inverted_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_to must be greater than or equal to tx_from",
    ):
        KnowledgeStore().query_revision_lifecycle_transition_for_tx_window(
            tx_from=9,
            tx_to=8,
            valid_at=dt(2024, 6, 1),
        )
