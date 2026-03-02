from datetime import datetime, timezone
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


def _assert_duplicate_replay_idempotence(
    replicas: list[KnowledgeStore],
    *,
    query_signature: Callable[[KnowledgeStore], tuple],
    assert_single_shot_behavior: Callable[[tuple], None],
) -> None:
    single_shot_merged, single_shot_conflicts = merge_replicas(replicas)
    single_shot_signature = query_signature(single_shot_merged)
    single_shot_conflict_signatures = KnowledgeStore.conflict_signatures(single_shot_conflicts)

    assert KnowledgeStore.conflict_code_counts(single_shot_conflicts) == EXPECTED_CONFLICT_CODE_COUNTS
    assert_single_shot_behavior(single_shot_signature)

    replay_merged, replay_conflicts = merge_replicas(
        replicas,
        start=single_shot_merged,
    )
    replay_signature = query_signature(replay_merged)
    assert replay_signature == single_shot_signature
    assert replay_conflicts == ()
    assert (
        KnowledgeStore.conflict_signatures(single_shot_conflicts + replay_conflicts)
        == single_shot_conflict_signatures
    )
    assert replay_merged.revision_state_signatures() == single_shot_merged.revision_state_signatures()
    assert replay_merged.relation_state_signatures() == single_shot_merged.relation_state_signatures()
    assert replay_merged.pending_relation_ids() == single_shot_merged.pending_relation_ids()

    resumed_merged, resumed_conflicts = merge_replicas(
        replicas,
        start=single_shot_merged.checkpoint(),
    )
    resumed_signature = query_signature(resumed_merged)
    assert resumed_signature == single_shot_signature
    assert resumed_conflicts == ()
    assert (
        KnowledgeStore.conflict_signatures(single_shot_conflicts + resumed_conflicts)
        == single_shot_conflict_signatures
    )
    assert resumed_merged.revision_state_signatures() == single_shot_merged.revision_state_signatures()
    assert resumed_merged.relation_state_signatures() == single_shot_merged.relation_state_signatures()
    assert resumed_merged.pending_relation_ids() == single_shot_merged.pending_relation_ids()


def _as_of_duplicate_replay_scenario() -> tuple[
    list[KnowledgeStore],
    datetime,
    int,
    str,
    str,
    tuple[str, str],
    str,
    str,
    str,
    tuple[str, str],
    tuple[str, str],
]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_as_of = 6

    core_competing = ClaimCore(claim_type="residence", slots={"subject": "competing"})
    core_retracted = ClaimCore(claim_type="residence", slots={"subject": "retracted"})
    core_relation_anchor = ClaimCore(claim_type="document", slots={"id": "anchor"})
    core_relation_linked_a = ClaimCore(claim_type="document", slots={"id": "linked-a"})
    core_relation_linked_b = ClaimCore(claim_type="document", slots={"id": "linked-b"})

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_relation_anchor,
        assertion="anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    linked_a_revision = replica_base.assert_revision(
        core=core_relation_linked_a,
        assertion="linked-a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_linked_a"),
        confidence_bp=9000,
        status="asserted",
    )
    linked_b_revision = replica_base.assert_revision(
        core=core_relation_linked_b,
        assertion="linked-b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_linked_b"),
        confidence_bp=9000,
        status="asserted",
    )
    competing_revision_a = replica_base.assert_revision(
        core=core_competing,
        assertion="competing-a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_competing_a"),
        confidence_bp=8300,
        status="asserted",
    )
    retracted_revision = replica_base.assert_revision(
        core=core_retracted,
        assertion="retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_retracted"),
        confidence_bp=8300,
        status="retracted",
    )
    active_relation_a = replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=linked_a_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    active_relation_b = replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=linked_b_revision.revision_id,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )

    replica_competing = KnowledgeStore()
    competing_revision_b = replica_competing.assert_revision(
        core=core_competing,
        assertion="competing-b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_competing_b"),
        confidence_bp=8300,
        status="asserted",
    )

    replica_orphans = KnowledgeStore()
    pending_relation_a = RelationEdge(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id="missing-duplicate-replay-endpoint-a",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    pending_relation_b = RelationEdge(
        relation_type="contradicts",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id="missing-duplicate-replay-endpoint-b",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    replica_orphans.relations[pending_relation_a.relation_id] = pending_relation_a
    replica_orphans.relations[pending_relation_b.relation_id] = pending_relation_b

    return (
        [replica_base, replica_competing, replica_orphans],
        valid_at,
        tx_as_of,
        core_competing.core_id,
        core_retracted.core_id,
        (competing_revision_a.revision_id, competing_revision_b.revision_id),
        retracted_revision.revision_id,
        core_relation_anchor.core_id,
        anchor_revision.revision_id,
        (active_relation_a.relation_id, active_relation_b.relation_id),
        (pending_relation_a.relation_id, pending_relation_b.relation_id),
    )


def test_query_as_of_duplicate_replay_idempotence_matches_single_shot() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        competing_core_id,
        retracted_core_id,
        competing_revision_ids,
        _retracted_revision_id,
        _anchor_core_id,
        _anchor_revision_id,
        _active_relation_ids,
        _pending_relation_ids,
    ) = _as_of_duplicate_replay_scenario()

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

    def assert_single_shot_behavior(signature: tuple) -> None:
        competing_winner_signature, retracted_winner_signature = signature
        assert competing_winner_signature is not None
        assert competing_winner_signature[0] == min(competing_revision_ids)
        assert competing_winner_signature[2] == "asserted"
        assert retracted_winner_signature is None

    _assert_duplicate_replay_idempotence(
        replicas,
        query_signature=query_signature,
        assert_single_shot_behavior=assert_single_shot_behavior,
    )


def test_query_revision_lifecycle_as_of_duplicate_replay_idempotence_matches_single_shot() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        _competing_core_id,
        _retracted_core_id,
        competing_revision_ids,
        retracted_revision_id,
        _anchor_core_id,
        _anchor_revision_id,
        _active_relation_ids,
        _pending_relation_ids,
    ) = _as_of_duplicate_replay_scenario()

    def query_signature(store: KnowledgeStore) -> tuple:
        projection = store.query_revision_lifecycle_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
        )
        _assert_revision_projection_ordering(projection)
        return _revision_projection_signatures(projection)

    def assert_single_shot_behavior(signature: tuple) -> None:
        active, retracted = signature
        active_revision_ids = tuple(revision_signature[0] for revision_signature in active)
        retracted_revision_ids = tuple(
            revision_signature[0] for revision_signature in retracted
        )
        assert active_revision_ids == tuple(sorted(active_revision_ids))
        assert retracted_revision_ids == tuple(sorted(retracted_revision_ids))
        assert min(competing_revision_ids) in active_revision_ids
        assert max(competing_revision_ids) not in active_revision_ids
        assert retracted_revision_ids == (retracted_revision_id,)
        assert all(revision_signature[2] == "asserted" for revision_signature in active)
        assert all(revision_signature[2] == "retracted" for revision_signature in retracted)

    _assert_duplicate_replay_idempotence(
        replicas,
        query_signature=query_signature,
        assert_single_shot_behavior=assert_single_shot_behavior,
    )


def test_query_relation_resolution_as_of_duplicate_replay_idempotence_matches_single_shot() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        _competing_core_id,
        _retracted_core_id,
        _competing_revision_ids,
        _retracted_revision_id,
        anchor_core_id,
        _anchor_revision_id,
        active_relation_ids,
        pending_relation_ids,
    ) = _as_of_duplicate_replay_scenario()

    def query_signature(store: KnowledgeStore) -> tuple:
        projection = store.query_relation_resolution_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
            core_id=anchor_core_id,
        )
        _assert_relation_projection_ordering(projection)
        return _relation_projection_signatures(projection)

    def assert_single_shot_behavior(signature: tuple) -> None:
        active, pending = signature
        assert tuple(relation_signature[0] for relation_signature in active) == tuple(
            sorted(active_relation_ids)
        )
        assert tuple(relation_signature[0] for relation_signature in pending) == tuple(
            sorted(pending_relation_ids)
        )

    _assert_duplicate_replay_idempotence(
        replicas,
        query_signature=query_signature,
        assert_single_shot_behavior=assert_single_shot_behavior,
    )


def test_query_relation_lifecycle_as_of_duplicate_replay_idempotence_matches_single_shot() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        _competing_core_id,
        _retracted_core_id,
        _competing_revision_ids,
        _retracted_revision_id,
        _anchor_core_id,
        anchor_revision_id,
        active_relation_ids,
        pending_relation_ids,
    ) = _as_of_duplicate_replay_scenario()

    def query_signature(store: KnowledgeStore) -> tuple:
        projection = store.query_relation_lifecycle_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
            revision_id=anchor_revision_id,
        )
        _assert_relation_projection_ordering(projection)
        return _relation_projection_signatures(projection)

    def assert_single_shot_behavior(signature: tuple) -> None:
        active, pending = signature
        assert tuple(relation_signature[0] for relation_signature in active) == tuple(
            sorted(active_relation_ids)
        )
        assert tuple(relation_signature[0] for relation_signature in pending) == tuple(
            sorted(pending_relation_ids)
        )

    _assert_duplicate_replay_idempotence(
        replicas,
        query_signature=query_signature,
        assert_single_shot_behavior=assert_single_shot_behavior,
    )
