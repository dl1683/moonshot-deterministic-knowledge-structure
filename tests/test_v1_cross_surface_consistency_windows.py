from datetime import datetime, timezone

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


def _assert_revision_ordering(revisions: tuple) -> None:
    revision_ids = tuple(revision.revision_id for revision in revisions)
    assert revision_ids == tuple(sorted(revision_ids))


def _assert_relation_ordering(relations: tuple) -> None:
    relation_ids = tuple(relation.relation_id for relation in relations)
    assert relation_ids == tuple(sorted(relation_ids))


def _assert_revision_transition_ordering(transition) -> None:
    for bucket in (
        transition.entered_active,
        transition.exited_active,
        transition.entered_retracted,
        transition.exited_retracted,
    ):
        _assert_revision_ordering(bucket)


def _assert_relation_transition_ordering(transition) -> None:
    for bucket in (
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    ):
        _assert_relation_ordering(bucket)


def _revision_transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_active,
        transition.exited_active,
        transition.entered_retracted,
        transition.exited_retracted,
    )


def _relation_transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def _expected_revision_transition_from_as_of(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    core_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=core_id,
    )
    to_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    from_active = {revision.revision_id: revision for revision in from_projection.active}
    to_active = {revision.revision_id: revision for revision in to_projection.active}
    from_retracted = {
        revision.revision_id: revision for revision in from_projection.retracted
    }
    to_retracted = {revision.revision_id: revision for revision in to_projection.retracted}
    return (
        tuple(to_active[revision_id] for revision_id in sorted(set(to_active) - set(from_active))),
        tuple(
            from_active[revision_id] for revision_id in sorted(set(from_active) - set(to_active))
        ),
        tuple(
            to_retracted[revision_id]
            for revision_id in sorted(set(to_retracted) - set(from_retracted))
        ),
        tuple(
            from_retracted[revision_id]
            for revision_id in sorted(set(from_retracted) - set(to_retracted))
        ),
    )


def _expected_relation_resolution_transition_from_as_of(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    core_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = store.query_relation_resolution_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=core_id,
    )
    to_projection = store.query_relation_resolution_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    from_active = {relation.relation_id: relation for relation in from_projection.active}
    to_active = {relation.relation_id: relation for relation in to_projection.active}
    from_pending = {relation.relation_id: relation for relation in from_projection.pending}
    to_pending = {relation.relation_id: relation for relation in to_projection.pending}
    return (
        tuple(to_active[relation_id] for relation_id in sorted(set(to_active) - set(from_active))),
        tuple(
            from_active[relation_id] for relation_id in sorted(set(from_active) - set(to_active))
        ),
        tuple(
            to_pending[relation_id] for relation_id in sorted(set(to_pending) - set(from_pending))
        ),
        tuple(
            from_pending[relation_id]
            for relation_id in sorted(set(from_pending) - set(to_pending))
        ),
    )


def _expected_relation_lifecycle_transition_from_as_of(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    revision_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        revision_id=revision_id,
    )
    to_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        revision_id=revision_id,
    )
    from_active = {relation.relation_id: relation for relation in from_projection.active}
    to_active = {relation.relation_id: relation for relation in to_projection.active}
    from_pending = {relation.relation_id: relation for relation in from_projection.pending}
    to_pending = {relation.relation_id: relation for relation in to_projection.pending}
    return (
        tuple(to_active[relation_id] for relation_id in sorted(set(to_active) - set(from_active))),
        tuple(
            from_active[relation_id] for relation_id in sorted(set(from_active) - set(to_active))
        ),
        tuple(
            to_pending[relation_id] for relation_id in sorted(set(to_pending) - set(from_pending))
        ),
        tuple(
            from_pending[relation_id]
            for relation_id in sorted(set(from_pending) - set(to_pending))
        ),
    )


def _cross_surface_window_transition_scenario() -> tuple[
    KnowledgeStore,
    datetime,
    int,
    int,
    int,
    int,
    str,
    str,
    str,
    str,
]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_start = 5
    tx_end = 7
    tx_from = 5
    tx_to = 7

    core_anchor = ClaimCore(claim_type="document", slots={"id": "window-anchor"})
    core_enter_active = ClaimCore(claim_type="residence", slots={"subject": "window-enter"})
    core_exit_active = ClaimCore(claim_type="residence", slots={"subject": "window-exit"})
    core_reactivate = ClaimCore(claim_type="residence", slots={"subject": "window-reactivate"})
    core_future = ClaimCore(claim_type="document", slots={"id": "window-future"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="window anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_window_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    exited_active_revision = store.assert_revision(
        core=core_exit_active,
        assertion="window exited active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_window_exit_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_reactivate,
        assertion="window reactivate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_window_reactivate_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    entered_active_revision = store.assert_revision(
        core=core_enter_active,
        assertion="window entered active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_window_enter"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_exit_active,
        assertion="window exited active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_window_exit_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    reactivated_revision = store.assert_revision(
        core=core_reactivate,
        assertion="window reactivate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_window_reactivate_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    future_revision = store.assert_revision(
        core=core_future,
        assertion="window future",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_window_future"),
        confidence_bp=9000,
        status="asserted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=exited_active_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=future_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=reactivated_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )

    orphan_replica = KnowledgeStore()
    stable_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id="missing-window-stable",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    entered_pending = RelationEdge(
        relation_type="supports",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id="missing-window-entered",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    orphan_replica.relations[stable_pending.relation_id] = stable_pending
    orphan_replica.relations[entered_pending.relation_id] = entered_pending
    store = store.merge(orphan_replica).merged

    return (
        store,
        valid_at,
        tx_start,
        tx_end,
        tx_from,
        tx_to,
        core_reactivate.core_id,
        core_exit_active.core_id,
        core_anchor.core_id,
        anchor_revision.revision_id,
    )


def test_tx_window_surfaces_match_as_of_filtered_projections_at_tx_end() -> None:
    (
        store,
        valid_at,
        tx_start,
        tx_end,
        _tx_from,
        _tx_to,
        reactivated_core_id,
        _exiting_core_id,
        anchor_core_id,
        anchor_revision_id,
    ) = _cross_surface_window_transition_scenario()

    revision_window = store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    revision_as_of = store.query_revision_lifecycle_as_of(tx_id=tx_end, valid_at=valid_at)
    expected_revision_active = tuple(
        revision
        for revision in revision_as_of.active
        if tx_start <= revision.transaction_time.tx_id <= tx_end
    )
    expected_revision_retracted = tuple(
        revision
        for revision in revision_as_of.retracted
        if tx_start <= revision.transaction_time.tx_id <= tx_end
    )
    _assert_revision_ordering(revision_window.active)
    _assert_revision_ordering(revision_window.retracted)
    assert revision_window.active == expected_revision_active
    assert revision_window.retracted == expected_revision_retracted

    revision_window_txs = tuple(
        revision.transaction_time.tx_id
        for revision in revision_window.active + revision_window.retracted
    )
    assert tx_start in revision_window_txs
    assert tx_end in revision_window_txs
    assert all(tx_start <= tx_id <= tx_end for tx_id in revision_window_txs)

    relation_resolution_window = store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    relation_resolution_as_of = store.query_relation_resolution_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )
    expected_resolution_active = tuple(
        relation
        for relation in relation_resolution_as_of.active
        if tx_start <= relation.transaction_time.tx_id <= tx_end
    )
    expected_resolution_pending = tuple(
        relation
        for relation in relation_resolution_as_of.pending
        if tx_start <= relation.transaction_time.tx_id <= tx_end
    )
    _assert_relation_ordering(relation_resolution_window.active)
    _assert_relation_ordering(relation_resolution_window.pending)
    assert relation_resolution_window.active == expected_resolution_active
    assert relation_resolution_window.pending == expected_resolution_pending

    relation_lifecycle_window = store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    relation_lifecycle_as_of = store.query_relation_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )
    expected_lifecycle_active = tuple(
        relation
        for relation in relation_lifecycle_as_of.active
        if tx_start <= relation.transaction_time.tx_id <= tx_end
    )
    expected_lifecycle_pending = tuple(
        relation
        for relation in relation_lifecycle_as_of.pending
        if tx_start <= relation.transaction_time.tx_id <= tx_end
    )
    _assert_relation_ordering(relation_lifecycle_window.active)
    _assert_relation_ordering(relation_lifecycle_window.pending)
    assert relation_lifecycle_window.active == expected_lifecycle_active
    assert relation_lifecycle_window.pending == expected_lifecycle_pending

    relation_window_txs = tuple(
        relation.transaction_time.tx_id
        for relation in relation_resolution_window.active
        + relation_resolution_window.pending
        + relation_lifecycle_window.active
        + relation_lifecycle_window.pending
    )
    assert tx_start in relation_window_txs
    assert tx_end in relation_window_txs
    assert all(tx_start <= tx_id <= tx_end for tx_id in relation_window_txs)

    filtered_revision_window = store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=reactivated_core_id,
    )
    filtered_revision_as_of = store.query_revision_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=reactivated_core_id,
    )
    assert filtered_revision_window.active == tuple(
        revision
        for revision in filtered_revision_as_of.active
        if tx_start <= revision.transaction_time.tx_id <= tx_end
    )
    assert filtered_revision_window.retracted == tuple(
        revision
        for revision in filtered_revision_as_of.retracted
        if tx_start <= revision.transaction_time.tx_id <= tx_end
    )

    filtered_resolution_window = store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=anchor_core_id,
    )
    filtered_resolution_as_of = store.query_relation_resolution_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=anchor_core_id,
    )
    assert filtered_resolution_window.active == tuple(
        relation
        for relation in filtered_resolution_as_of.active
        if tx_start <= relation.transaction_time.tx_id <= tx_end
    )
    assert filtered_resolution_window.pending == tuple(
        relation
        for relation in filtered_resolution_as_of.pending
        if tx_start <= relation.transaction_time.tx_id <= tx_end
    )

    filtered_lifecycle_window = store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )
    filtered_lifecycle_as_of = store.query_relation_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )
    assert filtered_lifecycle_window.active == tuple(
        relation
        for relation in filtered_lifecycle_as_of.active
        if tx_start <= relation.transaction_time.tx_id <= tx_end
    )
    assert filtered_lifecycle_window.pending == tuple(
        relation
        for relation in filtered_lifecycle_as_of.pending
        if tx_start <= relation.transaction_time.tx_id <= tx_end
    )


def test_transition_surfaces_match_explicit_as_of_set_diffs() -> None:
    (
        store,
        valid_at,
        _tx_start,
        _tx_end,
        tx_from,
        tx_to,
        _reactivated_core_id,
        exiting_core_id,
        anchor_core_id,
        anchor_revision_id,
    ) = _cross_surface_window_transition_scenario()

    revision_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert revision_transition.tx_from == tx_from
    assert revision_transition.tx_to == tx_to
    _assert_revision_transition_ordering(revision_transition)
    assert _revision_transition_buckets(revision_transition) == _expected_revision_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )

    relation_resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert relation_resolution_transition.tx_from == tx_from
    assert relation_resolution_transition.tx_to == tx_to
    _assert_relation_transition_ordering(relation_resolution_transition)
    assert _relation_transition_buckets(
        relation_resolution_transition
    ) == _expected_relation_resolution_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )

    relation_lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert relation_lifecycle_transition.tx_from == tx_from
    assert relation_lifecycle_transition.tx_to == tx_to
    _assert_relation_transition_ordering(relation_lifecycle_transition)
    assert _relation_transition_buckets(
        relation_lifecycle_transition
    ) == _expected_relation_lifecycle_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )

    filtered_revision_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=exiting_core_id,
    )
    _assert_revision_transition_ordering(filtered_revision_transition)
    assert _revision_transition_buckets(
        filtered_revision_transition
    ) == _expected_revision_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=exiting_core_id,
    )

    filtered_resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=anchor_core_id,
    )
    _assert_relation_transition_ordering(filtered_resolution_transition)
    assert _relation_transition_buckets(
        filtered_resolution_transition
    ) == _expected_relation_resolution_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=anchor_core_id,
    )

    filtered_lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )
    _assert_relation_transition_ordering(filtered_lifecycle_transition)
    assert _relation_transition_buckets(
        filtered_lifecycle_transition
    ) == _expected_relation_lifecycle_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )

    zero_delta_revision_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_to,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    zero_delta_resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_to,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    zero_delta_lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_to,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert _revision_transition_buckets(zero_delta_revision_transition) == ((), (), (), ())
    assert _relation_transition_buckets(zero_delta_resolution_transition) == ((), (), (), ())
    assert _relation_transition_buckets(zero_delta_lifecycle_transition) == ((), (), (), ())
