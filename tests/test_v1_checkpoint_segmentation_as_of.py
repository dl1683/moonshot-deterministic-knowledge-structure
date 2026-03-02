from datetime import datetime, timezone

import itertools
from typing import Callable

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    RelationLifecycleProjection,
    RelationResolutionProjection,
    RevisionLifecycleProjection,
    TransactionTime,
    ValidTime,
)

EXPECTED_CONFLICT_CODE_COUNTS = (
    (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
    (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 2),
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


def replay_with_checkpoint_segments(
    replicas: list[KnowledgeStore],
    *,
    boundaries: tuple[int, ...],
) -> tuple[KnowledgeStore, tuple]:
    merged = KnowledgeStore()
    conflicts = []
    start_index = 0

    for boundary in boundaries + (len(replicas),):
        segment = replicas[start_index:boundary]
        segment_start = merged if start_index == 0 else merged.checkpoint()
        merged, segment_conflicts = merge_replicas(segment, start=segment_start)
        conflicts.extend(segment_conflicts)
        start_index = boundary

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


def _revision_projection_signatures(
    projection: RevisionLifecycleProjection,
) -> tuple[
    tuple[tuple[str, str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, str, int, str], ...],
]:
    return (
        tuple(_revision_signature(revision) for revision in projection.active),
        tuple(_revision_signature(revision) for revision in projection.retracted),
    )


def _relation_projection_signatures(
    projection: RelationResolutionProjection | RelationLifecycleProjection,
) -> tuple[
    tuple[tuple[str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, int, str], ...],
]:
    return (
        tuple(_relation_signature(relation) for relation in projection.active),
        tuple(_relation_signature(relation) for relation in projection.pending),
    )


def _assert_revision_projection_ordering(projection: RevisionLifecycleProjection) -> None:
    active_ids = tuple(revision.revision_id for revision in projection.active)
    retracted_ids = tuple(revision.revision_id for revision in projection.retracted)
    assert active_ids == tuple(sorted(active_ids))
    assert retracted_ids == tuple(sorted(retracted_ids))


def _assert_relation_projection_ordering(
    projection: RelationResolutionProjection | RelationLifecycleProjection,
) -> None:
    active_ids = tuple(relation.relation_id for relation in projection.active)
    pending_ids = tuple(relation.relation_id for relation in projection.pending)
    assert active_ids == tuple(sorted(active_ids))
    assert pending_ids == tuple(sorted(pending_ids))


def _assert_checkpoint_segmentation_invariance(
    replicas: list[KnowledgeStore],
    *,
    query_signature: Callable[[KnowledgeStore], tuple],
    assert_unsplit_behavior: Callable[[tuple], None],
) -> None:
    unsplit_merged, unsplit_conflicts = merge_replicas(replicas)
    unsplit_signature = query_signature(unsplit_merged)
    unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

    assert KnowledgeStore.conflict_code_counts(unsplit_conflicts) == EXPECTED_CONFLICT_CODE_COUNTS
    assert_unsplit_behavior(unsplit_signature)

    two_way_boundaries = [(split_index,) for split_index in range(1, len(replicas))]
    three_way_boundaries = list(itertools.combinations(range(1, len(replicas)), 2))
    assert three_way_boundaries

    for boundaries in two_way_boundaries + three_way_boundaries:
        segmented_merged, segmented_conflicts = replay_with_checkpoint_segments(
            replicas,
            boundaries=boundaries,
        )
        segmented_signature = query_signature(segmented_merged)

        assert segmented_signature == unsplit_signature
        assert (
            KnowledgeStore.conflict_signatures(segmented_conflicts)
            == unsplit_conflict_signatures
        )
        assert (
            segmented_merged.revision_state_signatures()
            == unsplit_merged.revision_state_signatures()
        )
        assert (
            segmented_merged.relation_state_signatures()
            == unsplit_merged.relation_state_signatures()
        )
        assert segmented_merged.pending_relation_ids() == unsplit_merged.pending_relation_ids()


def _as_of_checkpoint_segmentation_scenario() -> tuple[
    list[KnowledgeStore],
    datetime,
    int,
    str,
    str,
    tuple[str, str],
    str,
    str,
]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_as_of = 7

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
    competing_revision_a = replica_base.assert_revision(
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
    competing_revision_b = replica_competing.assert_revision(
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
        tx_as_of,
        core_competing.core_id,
        core_exit_active.core_id,
        (competing_revision_a.revision_id, competing_revision_b.revision_id),
        core_relation_anchor.core_id,
        relation_anchor_revision.revision_id,
    )


def test_query_as_of_two_and_three_way_checkpoint_segmentation_matches_unsplit() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        competing_core_id,
        retracted_core_id,
        competing_revision_ids,
        _anchor_core_id,
        _anchor_revision_id,
    ) = _as_of_checkpoint_segmentation_scenario()

    def query_signature(store: KnowledgeStore) -> tuple:
        competing_winner = store.query_as_of(
            competing_core_id,
            valid_at=valid_at,
            tx_id=tx_as_of,
        )
        retracted_winner = store.query_as_of(
            retracted_core_id,
            valid_at=valid_at,
            tx_id=tx_as_of,
        )
        return (
            _revision_signature(competing_winner) if competing_winner is not None else None,
            _revision_signature(retracted_winner) if retracted_winner is not None else None,
        )

    def assert_unsplit_behavior(signature: tuple) -> None:
        competing_winner_signature, retracted_winner_signature = signature
        assert competing_winner_signature is not None
        assert competing_winner_signature[0] == min(competing_revision_ids)
        assert competing_winner_signature[2] == "asserted"
        assert retracted_winner_signature is None

    _assert_checkpoint_segmentation_invariance(
        replicas,
        query_signature=query_signature,
        assert_unsplit_behavior=assert_unsplit_behavior,
    )


def test_query_revision_lifecycle_as_of_two_and_three_way_checkpoint_segmentation_matches_unsplit() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        _competing_core_id,
        _retracted_core_id,
        _competing_revision_ids,
        _anchor_core_id,
        _anchor_revision_id,
    ) = _as_of_checkpoint_segmentation_scenario()

    def query_signature(store: KnowledgeStore) -> tuple:
        projection = store.query_revision_lifecycle_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
        )
        _assert_revision_projection_ordering(projection)
        return _revision_projection_signatures(projection)

    def assert_unsplit_behavior(signature: tuple) -> None:
        active, retracted = signature
        assert active
        assert retracted
        assert all(revision_signature[2] == "asserted" for revision_signature in active)
        assert all(revision_signature[2] == "retracted" for revision_signature in retracted)

    _assert_checkpoint_segmentation_invariance(
        replicas,
        query_signature=query_signature,
        assert_unsplit_behavior=assert_unsplit_behavior,
    )


def test_query_relation_resolution_as_of_two_and_three_way_checkpoint_segmentation_matches_unsplit() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        _competing_core_id,
        _retracted_core_id,
        _competing_revision_ids,
        anchor_core_id,
        _anchor_revision_id,
    ) = _as_of_checkpoint_segmentation_scenario()

    def query_signature(store: KnowledgeStore) -> tuple:
        projection = store.query_relation_resolution_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
            core_id=anchor_core_id,
        )
        _assert_relation_projection_ordering(projection)
        return _relation_projection_signatures(projection)

    def assert_unsplit_behavior(signature: tuple) -> None:
        active, pending = signature
        assert active
        assert pending

    _assert_checkpoint_segmentation_invariance(
        replicas,
        query_signature=query_signature,
        assert_unsplit_behavior=assert_unsplit_behavior,
    )


def test_query_relation_lifecycle_as_of_two_and_three_way_checkpoint_segmentation_matches_unsplit() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        _competing_core_id,
        _retracted_core_id,
        _competing_revision_ids,
        _anchor_core_id,
        anchor_revision_id,
    ) = _as_of_checkpoint_segmentation_scenario()

    def query_signature(store: KnowledgeStore) -> tuple:
        projection = store.query_relation_lifecycle_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
            revision_id=anchor_revision_id,
        )
        _assert_relation_projection_ordering(projection)
        return _relation_projection_signatures(projection)

    def assert_unsplit_behavior(signature: tuple) -> None:
        active, pending = signature
        assert active
        assert pending

    _assert_checkpoint_segmentation_invariance(
        replicas,
        query_signature=query_signature,
        assert_unsplit_behavior=assert_unsplit_behavior,
    )
