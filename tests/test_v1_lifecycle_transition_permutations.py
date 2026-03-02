from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    RelationResolutionTransition,
    RevisionLifecycleTransition,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def merge_replicas(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple]:
    merged = start if start is not None else KnowledgeStore()
    conflicts = []
    for replica in replicas:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        conflicts.extend(merge_result.conflicts)
    return merged, tuple(conflicts)


def _revision_signature(revision) -> tuple[str, str, str, str, str, int, str]:
    return (
        revision.revision_id,
        revision.core_id,
        revision.status,
        revision.valid_time.start.isoformat(),
        revision.valid_time.end.isoformat() if revision.valid_time.end is not None else "",
        revision.transaction_time.tx_id,
        revision.transaction_time.recorded_at.isoformat(),
    )


def _relation_signature(relation) -> tuple[str, str, str, str, int, str]:
    return (
        relation.relation_id,
        relation.relation_type,
        relation.from_revision_id,
        relation.to_revision_id,
        relation.transaction_time.tx_id,
        relation.transaction_time.recorded_at.isoformat(),
    )


def _revision_transition_signatures(
    transition: RevisionLifecycleTransition,
) -> tuple[
    tuple[tuple[str, str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, str, int, str], ...],
]:
    return (
        tuple(_revision_signature(revision) for revision in transition.entered_active),
        tuple(_revision_signature(revision) for revision in transition.exited_active),
        tuple(_revision_signature(revision) for revision in transition.entered_retracted),
        tuple(_revision_signature(revision) for revision in transition.exited_retracted),
    )


def _relation_transition_signatures(
    transition: RelationResolutionTransition,
) -> tuple[
    tuple[tuple[str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, int, str], ...],
]:
    return (
        tuple(_relation_signature(relation) for relation in transition.entered_active),
        tuple(_relation_signature(relation) for relation in transition.exited_active),
        tuple(_relation_signature(relation) for relation in transition.entered_pending),
        tuple(_relation_signature(relation) for relation in transition.exited_pending),
    )


def _assert_revision_transition_bucket_order(
    transition: RevisionLifecycleTransition,
) -> None:
    for bucket in (
        transition.entered_active,
        transition.exited_active,
        transition.entered_retracted,
        transition.exited_retracted,
    ):
        revision_ids = tuple(revision.revision_id for revision in bucket)
        assert revision_ids == tuple(sorted(revision_ids))


def _assert_relation_transition_bucket_order(
    transition: RelationResolutionTransition,
) -> None:
    for bucket in (
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    ):
        relation_ids = tuple(relation.relation_id for relation in bucket)
        assert relation_ids == tuple(sorted(relation_ids))


def _expected_revision_transition_signatures_from_as_of(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
) -> tuple[
    tuple[tuple[str, str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, str, int, str], ...],
]:
    from_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
    )
    to_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )
    from_active = {revision.revision_id: revision for revision in from_projection.active}
    to_active = {revision.revision_id: revision for revision in to_projection.active}
    from_retracted = {
        revision.revision_id: revision for revision in from_projection.retracted
    }
    to_retracted = {revision.revision_id: revision for revision in to_projection.retracted}

    return (
        tuple(
            _revision_signature(to_active[revision_id])
            for revision_id in sorted(set(to_active) - set(from_active))
        ),
        tuple(
            _revision_signature(from_active[revision_id])
            for revision_id in sorted(set(from_active) - set(to_active))
        ),
        tuple(
            _revision_signature(to_retracted[revision_id])
            for revision_id in sorted(set(to_retracted) - set(from_retracted))
        ),
        tuple(
            _revision_signature(from_retracted[revision_id])
            for revision_id in sorted(set(from_retracted) - set(to_retracted))
        ),
    )


def _expected_relation_transition_signatures_from_as_of(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
) -> tuple[
    tuple[tuple[str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, int, str], ...],
]:
    from_projection = store.query_relation_resolution_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
    )
    to_projection = store.query_relation_resolution_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )
    from_active = {relation.relation_id: relation for relation in from_projection.active}
    to_active = {relation.relation_id: relation for relation in to_projection.active}
    from_pending = {
        relation.relation_id: relation for relation in from_projection.pending
    }
    to_pending = {relation.relation_id: relation for relation in to_projection.pending}

    return (
        tuple(
            _relation_signature(to_active[relation_id])
            for relation_id in sorted(set(to_active) - set(from_active))
        ),
        tuple(
            _relation_signature(from_active[relation_id])
            for relation_id in sorted(set(from_active) - set(to_active))
        ),
        tuple(
            _relation_signature(to_pending[relation_id])
            for relation_id in sorted(set(to_pending) - set(from_pending))
        ),
        tuple(
            _relation_signature(from_pending[relation_id])
            for relation_id in sorted(set(from_pending) - set(to_pending))
        ),
    )


def _lifecycle_transition_checkpoint_scenario() -> tuple[list[KnowledgeStore], datetime, int, int]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 3
    tx_to = 7

    core_enter_active = ClaimCore(claim_type="residence", slots={"subject": "enter-active"})
    core_exit_active = ClaimCore(claim_type="residence", slots={"subject": "exit-active"})
    core_exit_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": "exit-retracted"},
    )
    core_relation_anchor = ClaimCore(
        claim_type="document",
        slots={"id": "relation-anchor"},
    )
    core_relation_linked = ClaimCore(
        claim_type="document",
        slots={"id": "relation-linked"},
    )
    core_relation_future = ClaimCore(
        claim_type="document",
        slots={"id": "relation-future"},
    )
    core_competing = ClaimCore(claim_type="residence", slots={"subject": "competing"})

    replica_base = KnowledgeStore()
    relation_anchor_revision = replica_base.assert_revision(
        core=core_relation_anchor,
        assertion="relation anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_relation_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    relation_linked_revision = replica_base.assert_revision(
        core=core_relation_linked,
        assertion="relation linked",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_relation_linked"),
        confidence_bp=9000,
        status="asserted",
    )
    exited_active_revision = replica_base.assert_revision(
        core=core_exit_active,
        assertion="exit active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_exit_active_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_exit_retracted,
        assertion="exit retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_exit_retracted_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="competing-a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_competing_a"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=exited_active_revision.revision_id,
        to_revision_id=relation_linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=relation_anchor_revision.revision_id,
        to_revision_id=relation_linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
    )

    replica_updates = KnowledgeStore()
    entered_active_revision = replica_updates.assert_revision(
        core=core_enter_active,
        assertion="enter active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_enter_active"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_updates.assert_revision(
        core=core_exit_active,
        assertion="exit active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_exit_active_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    replica_updates.assert_revision(
        core=core_exit_retracted,
        assertion="exit retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_exit_retracted_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    relation_future_revision = replica_updates.assert_revision(
        core=core_relation_future,
        assertion="relation future",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_relation_future"),
        confidence_bp=9000,
        status="asserted",
    )
    relation_linked_revision_copy = replica_updates.assert_revision(
        core=core_relation_linked,
        assertion="relation linked",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_relation_linked"),
        confidence_bp=9000,
        status="asserted",
    )
    replica_updates.attach_relation(
        relation_type="supports",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id=relation_linked_revision_copy.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )

    replica_orphans = KnowledgeStore()
    pending_to_become_active = RelationEdge(
        relation_type="depends_on",
        from_revision_id=relation_anchor_revision.revision_id,
        to_revision_id=relation_future_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    entered_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=relation_anchor_revision.revision_id,
        to_revision_id="missing-transition-permanent-endpoint",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    replica_orphans.relations[pending_to_become_active.relation_id] = pending_to_become_active
    replica_orphans.relations[entered_pending.relation_id] = entered_pending

    replica_competing = KnowledgeStore()
    replica_competing.assert_revision(
        core=core_competing,
        assertion="competing-b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_competing_b"),
        confidence_bp=8400,
        status="asserted",
    )

    return (
        [replica_base, replica_updates, replica_orphans, replica_competing],
        valid_at,
        tx_from,
        tx_to,
    )


def test_query_revision_lifecycle_transition_for_tx_window_checkpoint_resumed_permutation_replay_matches_unsplit() -> None:
    replicas, valid_at, tx_from, tx_to = _lifecycle_transition_checkpoint_scenario()
    baseline_transition_signatures = None
    baseline_conflict_signatures = None

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = merge_replicas(ordered_replicas)

        unsplit_transition = unsplit_merged.query_revision_lifecycle_transition_for_tx_window(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
        unsplit_transition_signatures = _revision_transition_signatures(unsplit_transition)
        expected_signatures = _expected_revision_transition_signatures_from_as_of(
            unsplit_merged,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        assert KnowledgeStore.conflict_code_counts(unsplit_conflicts) == (
            (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
            (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 2),
        )
        assert unsplit_transition_signatures == expected_signatures
        assert unsplit_transition_signatures[0]
        assert unsplit_transition_signatures[1]
        assert unsplit_transition_signatures[2]
        assert unsplit_transition_signatures[3]
        _assert_revision_transition_bucket_order(unsplit_transition)

        if baseline_transition_signatures is None:
            baseline_transition_signatures = unsplit_transition_signatures
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_transition_signatures == baseline_transition_signatures
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_conflicts = merge_replicas(ordered_replicas[:split_index])
            resumed_merged, resumed_suffix_conflicts = merge_replicas(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_transition = resumed_merged.query_revision_lifecycle_transition_for_tx_window(
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
            )
            resumed_transition_signatures = _revision_transition_signatures(resumed_transition)
            resumed_expected_signatures = _expected_revision_transition_signatures_from_as_of(
                resumed_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
            )
            resumed_conflict_signatures = KnowledgeStore.conflict_signatures(
                prefix_conflicts + resumed_suffix_conflicts
            )

            assert resumed_transition == unsplit_transition
            assert resumed_transition_signatures == unsplit_transition_signatures
            assert resumed_transition_signatures == resumed_expected_signatures
            assert resumed_conflict_signatures == unsplit_conflict_signatures
            _assert_revision_transition_bucket_order(resumed_transition)


def test_query_relation_resolution_transition_for_tx_window_checkpoint_resumed_permutation_replay_matches_unsplit() -> None:
    replicas, valid_at, tx_from, tx_to = _lifecycle_transition_checkpoint_scenario()
    baseline_transition_signatures = None
    baseline_conflict_signatures = None

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = merge_replicas(ordered_replicas)

        unsplit_transition = (
            unsplit_merged.query_relation_resolution_transition_for_tx_window(
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
            )
        )
        unsplit_transition_signatures = _relation_transition_signatures(unsplit_transition)
        expected_signatures = _expected_relation_transition_signatures_from_as_of(
            unsplit_merged,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        assert KnowledgeStore.conflict_code_counts(unsplit_conflicts) == (
            (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
            (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 2),
        )
        assert unsplit_transition_signatures == expected_signatures
        assert unsplit_transition_signatures[0]
        assert unsplit_transition_signatures[1]
        assert unsplit_transition_signatures[2]
        _assert_relation_transition_bucket_order(unsplit_transition)

        if baseline_transition_signatures is None:
            baseline_transition_signatures = unsplit_transition_signatures
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_transition_signatures == baseline_transition_signatures
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_conflicts = merge_replicas(ordered_replicas[:split_index])
            resumed_merged, resumed_suffix_conflicts = merge_replicas(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_transition = (
                resumed_merged.query_relation_resolution_transition_for_tx_window(
                    tx_from=tx_from,
                    tx_to=tx_to,
                    valid_at=valid_at,
                )
            )
            resumed_transition_signatures = _relation_transition_signatures(resumed_transition)
            resumed_expected_signatures = _expected_relation_transition_signatures_from_as_of(
                resumed_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
            )
            resumed_conflict_signatures = KnowledgeStore.conflict_signatures(
                prefix_conflicts + resumed_suffix_conflicts
            )

            assert resumed_transition == unsplit_transition
            assert resumed_transition_signatures == unsplit_transition_signatures
            assert resumed_transition_signatures == resumed_expected_signatures
            assert resumed_conflict_signatures == unsplit_conflict_signatures
            _assert_relation_transition_bucket_order(resumed_transition)
