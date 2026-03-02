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


def _assert_relation_ids_sorted(*buckets: tuple) -> None:
    for bucket in buckets:
        relation_ids = tuple(relation.relation_id for relation in bucket)
        assert relation_ids == tuple(sorted(relation_ids))


def test_query_relation_lifecycle_transition_for_tx_window_tracks_entered_and_exited_buckets() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    core_enter_active = ClaimCore(claim_type="residence", slots={"subject": "enter-active"})
    core_exit_active = ClaimCore(claim_type="residence", slots={"subject": "exit-active"})
    linked_core = ClaimCore(claim_type="document", slots={"id": "lifecycle-linked"})

    enter_revision = store.assert_revision(
        core=core_enter_active,
        assertion="enter active relation",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_enter_revision"),
        confidence_bp=8300,
        status="asserted",
    )
    exit_revision = store.assert_revision(
        core=core_exit_active,
        assertion="exit active relation",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_exit_revision"),
        confidence_bp=8300,
        status="asserted",
    )
    linked_revision = store.assert_revision(
        core=linked_core,
        assertion="linked relation endpoint",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_linked_revision"),
        confidence_bp=9000,
        status="asserted",
    )

    exited_active = store.attach_relation(
        relation_type="derived_from",
        from_revision_id=exit_revision.revision_id,
        to_revision_id=linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    entered_active = store.attach_relation(
        relation_type="supports",
        from_revision_id=enter_revision.revision_id,
        to_revision_id=linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )
    store.assert_revision(
        core=core_exit_active,
        assertion="exit active relation",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_exit_retracted"),
        confidence_bp=8300,
        status="retracted",
    )

    orphan_replica = KnowledgeStore()
    stable_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=enter_revision.revision_id,
        to_revision_id="missing-stable-pending",
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    entered_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=enter_revision.revision_id,
        to_revision_id="missing-entered-pending",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    orphan_replica.relations[stable_pending.relation_id] = stable_pending
    orphan_replica.relations[entered_pending.relation_id] = entered_pending
    store = store.merge(orphan_replica).merged

    transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=3,
        tx_to=7,
        valid_at=dt(2024, 6, 1),
    )

    assert transition.tx_from == 3
    assert transition.tx_to == 7
    assert transition.entered_active == (entered_active,)
    assert transition.exited_active == (exited_active,)
    assert transition.entered_pending == (entered_pending,)
    assert transition.exited_pending == ()
    _assert_relation_ids_sorted(
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def test_query_relation_lifecycle_transition_for_tx_window_zero_delta_has_empty_buckets() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    relation_core = ClaimCore(claim_type="residence", slots={"subject": "zero-delta-a"})
    linked_core = ClaimCore(claim_type="document", slots={"id": "zero-delta-b"})

    relation_revision = store.assert_revision(
        core=relation_core,
        assertion="zero-delta relation",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_zero_delta_relation"),
        confidence_bp=8400,
        status="asserted",
    )
    linked_revision = store.assert_revision(
        core=linked_core,
        assertion="zero-delta linked",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_zero_delta_linked"),
        confidence_bp=9000,
        status="asserted",
    )

    store.attach_relation(
        relation_type="supports",
        from_revision_id=relation_revision.revision_id,
        to_revision_id=linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )

    orphan_replica = KnowledgeStore()
    pending_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=relation_revision.revision_id,
        to_revision_id="missing-zero-delta",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=5,
        tx_to=5,
        valid_at=dt(2024, 6, 1),
    )

    assert transition.entered_active == ()
    assert transition.exited_active == ()
    assert transition.entered_pending == ()
    assert transition.exited_pending == ()


def test_query_relation_lifecycle_transition_for_tx_window_supports_revision_filtering() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    focus_core = ClaimCore(claim_type="document", slots={"id": "focus-revision"})
    old_source_core = ClaimCore(claim_type="residence", slots={"subject": "focus-old-source"})
    new_source_core = ClaimCore(claim_type="residence", slots={"subject": "focus-new-source"})
    other_from_core = ClaimCore(claim_type="document", slots={"id": "other-from"})
    other_to_core = ClaimCore(claim_type="document", slots={"id": "other-to"})

    focus_revision = store.assert_revision(
        core=focus_core,
        assertion="focus endpoint",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_focus_revision"),
        confidence_bp=9000,
        status="asserted",
    )
    old_source_revision = store.assert_revision(
        core=old_source_core,
        assertion="focus old source",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_old_source"),
        confidence_bp=8400,
        status="asserted",
    )
    new_source_revision = store.assert_revision(
        core=new_source_core,
        assertion="focus new source",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_new_source"),
        confidence_bp=8400,
        status="asserted",
    )
    other_from_revision = store.assert_revision(
        core=other_from_core,
        assertion="other from",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_other_from"),
        confidence_bp=9000,
        status="asserted",
    )
    other_to_revision = store.assert_revision(
        core=other_to_core,
        assertion="other to",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_other_to"),
        confidence_bp=9000,
        status="asserted",
    )

    focus_exited_active = store.attach_relation(
        relation_type="derived_from",
        from_revision_id=old_source_revision.revision_id,
        to_revision_id=focus_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    focus_entered_active = store.attach_relation(
        relation_type="supports",
        from_revision_id=new_source_revision.revision_id,
        to_revision_id=focus_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    other_entered_active = store.attach_relation(
        relation_type="depends_on",
        from_revision_id=other_from_revision.revision_id,
        to_revision_id=other_to_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.assert_revision(
        core=old_source_core,
        assertion="focus old source",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_old_source_retracted"),
        confidence_bp=8400,
        status="retracted",
    )

    orphan_replica = KnowledgeStore()
    stable_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=focus_revision.revision_id,
        to_revision_id="missing-focus-stable",
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    focus_entered_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=focus_revision.revision_id,
        to_revision_id="missing-focus-entered",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    orphan_replica.relations[stable_pending.relation_id] = stable_pending
    orphan_replica.relations[focus_entered_pending.relation_id] = focus_entered_pending
    store = store.merge(orphan_replica).merged

    unfiltered_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=2,
        tx_to=5,
        valid_at=dt(2024, 6, 1),
    )
    filtered_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=2,
        tx_to=5,
        valid_at=dt(2024, 6, 1),
        revision_id=focus_revision.revision_id,
    )

    assert other_entered_active in unfiltered_transition.entered_active
    assert filtered_transition.entered_active == (focus_entered_active,)
    assert filtered_transition.exited_active == (focus_exited_active,)
    assert filtered_transition.entered_pending == (focus_entered_pending,)
    assert filtered_transition.exited_pending == ()
    _assert_relation_ids_sorted(
        filtered_transition.entered_active,
        filtered_transition.exited_active,
        filtered_transition.entered_pending,
        filtered_transition.exited_pending,
    )


def test_query_relation_lifecycle_transition_for_tx_window_matches_explicit_as_of_projection_diffs() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    core_a = ClaimCore(claim_type="residence", slots={"subject": "diff-core-a"})
    core_b = ClaimCore(claim_type="document", slots={"id": "diff-core-b"})
    core_c = ClaimCore(claim_type="document", slots={"id": "diff-core-c"})

    revision_a = store.assert_revision(
        core=core_a,
        assertion="diff relation a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_diff_a_asserted"),
        confidence_bp=8500,
        status="asserted",
    )
    revision_b = store.assert_revision(
        core=core_b,
        assertion="diff relation b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_diff_b_asserted"),
        confidence_bp=9000,
        status="asserted",
    )
    revision_c = store.assert_revision(
        core=core_c,
        assertion="diff relation c",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_diff_c_asserted"),
        confidence_bp=9000,
        status="asserted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=revision_a.revision_id,
        to_revision_id=revision_b.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    store.assert_revision(
        core=core_a,
        assertion="diff relation a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_diff_a_retracted"),
        confidence_bp=8500,
        status="retracted",
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=revision_b.revision_id,
        to_revision_id=revision_c.revision_id,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )

    orphan_replica = KnowledgeStore()
    stable_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=revision_b.revision_id,
        to_revision_id="missing-diff-stable",
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    entered_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=revision_c.revision_id,
        to_revision_id="missing-diff-entered",
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )
    orphan_replica.relations[stable_pending.relation_id] = stable_pending
    orphan_replica.relations[entered_pending.relation_id] = entered_pending
    store = store.merge(orphan_replica).merged

    tx_from = 3
    tx_to = 7
    from_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_from,
        valid_at=dt(2024, 6, 1),
    )
    to_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_to,
        valid_at=dt(2024, 6, 1),
    )
    transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=dt(2024, 6, 1),
    )

    from_active = {relation.relation_id: relation for relation in from_projection.active}
    to_active = {relation.relation_id: relation for relation in to_projection.active}
    from_pending = {relation.relation_id: relation for relation in from_projection.pending}
    to_pending = {relation.relation_id: relation for relation in to_projection.pending}

    assert transition.entered_active == tuple(
        to_active[relation_id] for relation_id in sorted(set(to_active) - set(from_active))
    )
    assert transition.exited_active == tuple(
        from_active[relation_id]
        for relation_id in sorted(set(from_active) - set(to_active))
    )
    assert transition.entered_pending == tuple(
        to_pending[relation_id]
        for relation_id in sorted(set(to_pending) - set(from_pending))
    )
    assert transition.exited_pending == tuple(
        from_pending[relation_id]
        for relation_id in sorted(set(from_pending) - set(to_pending))
    )
    _assert_relation_ids_sorted(
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def test_query_relation_lifecycle_transition_for_tx_window_rejects_inverted_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_to must be greater than or equal to tx_from",
    ):
        KnowledgeStore().query_relation_lifecycle_transition_for_tx_window(
            tx_from=9,
            tx_to=8,
            valid_at=dt(2024, 6, 1),
        )
