from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def replay_stream(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple]:
    merged = start if start is not None else KnowledgeStore()
    observed_conflicts = []
    for replica in replicas:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        observed_conflicts.extend(merge_result.conflicts)
    return merged, tuple(observed_conflicts)


def relation_state_signature(
    bucket: str,
    relation: RelationEdge,
) -> tuple[str, str, str, str, str, int, str]:
    return (
        bucket,
        relation.relation_id,
        relation.relation_type,
        relation.from_revision_id,
        relation.to_revision_id,
        relation.transaction_time.tx_id,
        relation.transaction_time.recorded_at.isoformat(),
    )


def _assert_projection_ordering(projection) -> None:
    assert projection.active == tuple(sorted(projection.active))
    assert projection.pending == tuple(sorted(projection.pending))


def _assert_transition_ordering(transition) -> None:
    assert transition.entered_active == tuple(sorted(transition.entered_active))
    assert transition.exited_active == tuple(sorted(transition.exited_active))
    assert transition.entered_pending == tuple(sorted(transition.entered_pending))
    assert transition.exited_pending == tuple(sorted(transition.exited_pending))


def _transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def _build_relation_lifecycle_signature_cross_surface_store(
    *,
    tx_base: int,
) -> tuple[KnowledgeStore, RelationEdge, RelationEdge, RelationEdge]:
    residence_core = ClaimCore(
        claim_type="residence",
        slots={"subject": "Ada Lovelace"},
    )
    evidence_core = ClaimCore(
        claim_type="document",
        slots={"id": f"archive-lifecycle-cross-surface-signature-{tx_base}"},
    )

    seed = KnowledgeStore()
    residence_early_revision = seed.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=dt(2024, 4, 1)),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence_early"),
        confidence_bp=7100,
    )
    evidence_revision = seed.assert_revision(
        core=evidence_core,
        assertion="Archive timeline records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_evidence"),
        confidence_bp=9200,
    )
    residence_late_revision = seed.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 4, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 4, 2)),
        provenance=Provenance(source="source_residence_late"),
        confidence_bp=7300,
    )

    active_early_relation = RelationEdge(
        relation_type="derived_from",
        from_revision_id=residence_early_revision.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 5, recorded_at=dt(2024, 2, 1)),
    )
    active_late_relation = RelationEdge(
        relation_type="derived_from",
        from_revision_id=residence_late_revision.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 5, 1)),
    )
    pending_unresolved_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=residence_late_revision.revision_id,
        to_revision_id=f"missing-cross-surface-signature-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 4, 15)),
    )

    replica_orphan_early = KnowledgeStore()
    replica_orphan_early.relations[active_early_relation.relation_id] = active_early_relation

    replica_orphan_late = KnowledgeStore()
    replica_orphan_late.relations[active_late_relation.relation_id] = active_late_relation

    replica_pending_unresolved = KnowledgeStore()
    replica_pending_unresolved.relations[
        pending_unresolved_relation.relation_id
    ] = pending_unresolved_relation

    replica_endpoints_early = KnowledgeStore()
    replica_endpoints_early.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=dt(2024, 4, 1)),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence_early"),
        confidence_bp=7100,
    )
    replica_endpoints_early.assert_revision(
        core=evidence_core,
        assertion="Archive timeline records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_evidence"),
        confidence_bp=9200,
    )

    replica_endpoint_late = KnowledgeStore()
    replica_endpoint_late.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 4, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 4, 2)),
        provenance=Provenance(source="source_residence_late"),
        confidence_bp=7300,
    )

    replay_sequence = [
        replica_orphan_early,
        replica_orphan_late,
        replica_pending_unresolved,
        replica_endpoints_early,
        replica_endpoint_late,
    ]
    merged, _conflicts = replay_stream(replay_sequence)
    return (
        merged,
        active_early_relation,
        active_late_relation,
        pending_unresolved_relation,
    )


def _filter_signatures_for_tx_window(
    signatures: tuple[tuple[str, str, str, str, str, int, str], ...],
    *,
    tx_start: int,
    tx_end: int,
) -> tuple[tuple[str, str, str, str, str, int, str], ...]:
    return tuple(
        signature
        for signature in signatures
        if tx_start <= signature[5] <= tx_end
    )


def _expected_window_projection_from_as_of_filtering(
    store: KnowledgeStore,
    *,
    tx_start: int,
    tx_end: int,
    valid_at: datetime,
    revision_id: str | None = None,
):
    as_of_projection = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        revision_id=revision_id,
    )
    return (
        _filter_signatures_for_tx_window(
            as_of_projection.active,
            tx_start=tx_start,
            tx_end=tx_end,
        ),
        _filter_signatures_for_tx_window(
            as_of_projection.pending,
            tx_start=tx_start,
            tx_end=tx_end,
        ),
    )


def _expected_transition_from_as_of_window_diffs(
    store: KnowledgeStore,
    *,
    tx_start: int,
    tx_end: int,
    valid_from: datetime,
    valid_to: datetime,
    revision_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_active, from_pending = _expected_window_projection_from_as_of_filtering(
        store,
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_from,
        revision_id=revision_id,
    )
    to_active, to_pending = _expected_window_projection_from_as_of_filtering(
        store,
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_to,
        revision_id=revision_id,
    )
    return (
        tuple(sorted(set(to_active) - set(from_active))),
        tuple(sorted(set(from_active) - set(to_active))),
        tuple(sorted(set(to_pending) - set(from_pending))),
        tuple(sorted(set(from_pending) - set(to_pending))),
    )


def test_relation_lifecycle_signature_tx_window_cross_surface_matches_as_of_filtering_and_boundaries() -> None:
    tx_base = 5640
    (
        store,
        _active_early_relation,
        active_late_relation,
        pending_unresolved_relation,
    ) = _build_relation_lifecycle_signature_cross_surface_store(tx_base=tx_base)

    tx_windows = (
        (tx_base + 4, tx_base + 4, dt(2024, 3, 1)),
        (tx_base + 5, tx_base + 5, dt(2024, 3, 1)),
        (tx_base + 5, tx_base + 6, dt(2024, 3, 1)),
        (tx_base + 6, tx_base + 7, dt(2024, 6, 1)),
        (tx_base + 7, tx_base + 7, dt(2024, 6, 1)),
        (tx_base + 8, tx_base + 9, dt(2024, 6, 1)),
        (tx_base + 5, tx_base + 7, dt(2024, 6, 1)),
    )
    for tx_start, tx_end, valid_at in tx_windows:
        window_projection = store.query_relation_lifecycle_signatures_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
        )
        expected_active, expected_pending = _expected_window_projection_from_as_of_filtering(
            store,
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
        )
        assert window_projection.active == expected_active
        assert window_projection.pending == expected_pending
        _assert_projection_ordering(window_projection)

    boundary_start_inclusive = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 6,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 6, 1),
    )
    boundary_start_exclusive = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 7,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 6, 1),
    )
    assert boundary_start_inclusive.pending == (
        relation_state_signature("pending", pending_unresolved_relation),
    )
    assert boundary_start_exclusive.pending == ()

    boundary_end_inclusive = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 6,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 6, 1),
    )
    boundary_end_exclusive = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 6,
        tx_end=tx_base + 6,
        valid_at=dt(2024, 6, 1),
    )
    assert boundary_end_inclusive.active == (
        relation_state_signature("active", active_late_relation),
    )
    assert boundary_end_exclusive.active == ()


def test_relation_lifecycle_signature_transition_cross_surface_matches_as_of_set_diffs_and_boundaries() -> None:
    tx_base = 5720
    (
        store,
        active_early_relation,
        active_late_relation,
        _pending_unresolved_relation,
    ) = _build_relation_lifecycle_signature_cross_surface_store(tx_base=tx_base)

    tx_windows = (
        (tx_base + 5, tx_base + 7, dt(2024, 3, 1), dt(2024, 6, 1)),
        (tx_base + 5, tx_base + 5, dt(2024, 3, 1), dt(2024, 6, 1)),
        (tx_base + 6, tx_base + 7, dt(2024, 3, 1), dt(2024, 6, 1)),
    )
    for tx_start, tx_end, valid_from, valid_to in tx_windows:
        transition = store.query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        expected_buckets = _expected_transition_from_as_of_window_diffs(
            store,
            tx_start=tx_start,
            tx_end=tx_end,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        assert transition.valid_from == valid_from
        assert transition.valid_to == valid_to
        assert _transition_buckets(transition) == expected_buckets
        _assert_transition_ordering(transition)

    boundary_start_inclusive = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_from=dt(2024, 3, 1),
        valid_to=dt(2024, 6, 1),
    )
    boundary_start_exclusive = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 6,
        tx_end=tx_base + 7,
        valid_from=dt(2024, 3, 1),
        valid_to=dt(2024, 6, 1),
    )
    assert boundary_start_inclusive.exited_active == (
        relation_state_signature("active", active_early_relation),
    )
    assert boundary_start_exclusive.exited_active == ()

    boundary_end_inclusive = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 6,
        tx_end=tx_base + 7,
        valid_from=dt(2024, 3, 1),
        valid_to=dt(2024, 6, 1),
    )
    boundary_end_exclusive = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 6,
        tx_end=tx_base + 6,
        valid_from=dt(2024, 3, 1),
        valid_to=dt(2024, 6, 1),
    )
    assert boundary_end_inclusive.entered_active == (
        relation_state_signature("active", active_late_relation),
    )
    assert boundary_end_exclusive.entered_active == ()


def test_relation_lifecycle_signature_transition_zero_delta_identity_matches_as_of_diff_identity() -> None:
    tx_base = 5800
    (
        store,
        _active_early_relation,
        _active_late_relation,
        _pending_unresolved_relation,
    ) = _build_relation_lifecycle_signature_cross_surface_store(tx_base=tx_base)
    transition = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_from=dt(2024, 6, 1),
        valid_to=dt(2024, 6, 1),
    )

    assert _transition_buckets(transition) == ((), (), (), ())
    assert _transition_buckets(transition) == _expected_transition_from_as_of_window_diffs(
        store,
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_from=dt(2024, 6, 1),
        valid_to=dt(2024, 6, 1),
    )
    _assert_transition_ordering(transition)


def test_relation_lifecycle_signature_cross_surface_inverted_windows_raise_value_error() -> None:
    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore().query_relation_lifecycle_signatures_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=dt(2024, 6, 1),
        )

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore().query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=12,
            tx_end=11,
            valid_from=dt(2024, 3, 1),
            valid_to=dt(2024, 6, 1),
        )

    with pytest.raises(
        ValueError,
        match="valid_to must be greater than or equal to valid_from",
    ):
        KnowledgeStore().query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=12,
            tx_end=12,
            valid_from=dt(2024, 6, 1),
            valid_to=dt(2024, 3, 1),
        )
