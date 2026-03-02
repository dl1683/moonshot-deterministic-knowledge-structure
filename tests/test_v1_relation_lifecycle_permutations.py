from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    RelationLifecycleProjection,
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


def _relation_signature(relation) -> tuple[str, str, str, str, int, str]:
    return (
        relation.relation_id,
        relation.relation_type,
        relation.from_revision_id,
        relation.to_revision_id,
        relation.transaction_time.tx_id,
        relation.transaction_time.recorded_at.isoformat(),
    )


def _projection_signatures(
    projection: RelationLifecycleProjection,
) -> tuple[
    tuple[tuple[str, str, str, str, int, str], ...],
    tuple[tuple[str, str, str, str, int, str], ...],
]:
    return (
        tuple(_relation_signature(relation) for relation in projection.active),
        tuple(_relation_signature(relation) for relation in projection.pending),
    )


def _relation_lifecycle_checkpoint_scenario() -> tuple[
    list[KnowledgeStore],
    datetime,
    int,
    int,
    int,
    str,
    str,
]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_as_of = 41
    tx_start = 40
    tx_end = 41

    core_target = ClaimCore(claim_type="residence", slots={"subject": "lifecycle target"})
    core_doc_a = ClaimCore(claim_type="document", slots={"id": "lifecycle-doc-a"})
    core_doc_b = ClaimCore(claim_type="document", slots={"id": "lifecycle-doc-b"})
    core_competing = ClaimCore(claim_type="residence", slots={"subject": "lifecycle competing"})

    replica_base = KnowledgeStore()
    target_revision = replica_base.assert_revision(
        core=core_target,
        assertion="target winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=40, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_target"),
        confidence_bp=8500,
        status="asserted",
    )
    doc_a_revision = replica_base.assert_revision(
        core=core_doc_a,
        assertion="doc a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=40, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_doc_a"),
        confidence_bp=9000,
        status="asserted",
    )
    doc_b_revision = replica_base.assert_revision(
        core=core_doc_b,
        assertion="doc b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=38, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_doc_b"),
        confidence_bp=9000,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=40, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_competing_a"),
        confidence_bp=8500,
        status="asserted",
    )

    outside_window_active = replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=target_revision.revision_id,
        to_revision_id=doc_b_revision.revision_id,
        transaction_time=TransactionTime(tx_id=38, recorded_at=dt(2024, 1, 8)),
    )
    replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=target_revision.revision_id,
        to_revision_id=doc_a_revision.revision_id,
        transaction_time=TransactionTime(tx_id=40, recorded_at=dt(2024, 1, 10)),
    )

    replica_pending = KnowledgeStore()
    outside_window_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=target_revision.revision_id,
        to_revision_id="missing-lifecycle-outside-window",
        transaction_time=TransactionTime(tx_id=39, recorded_at=dt(2024, 1, 9)),
    )
    window_pending = RelationEdge(
        relation_type="supports",
        from_revision_id=target_revision.revision_id,
        to_revision_id="missing-lifecycle-window",
        transaction_time=TransactionTime(tx_id=41, recorded_at=dt(2024, 1, 11)),
    )
    replica_pending.relations[outside_window_pending.relation_id] = outside_window_pending
    replica_pending.relations[window_pending.relation_id] = window_pending

    replica_competing = KnowledgeStore()
    replica_competing.assert_revision(
        core=core_competing,
        assertion="competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=40, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_competing_b"),
        confidence_bp=8500,
        status="asserted",
    )

    return (
        [replica_base, replica_pending, replica_competing],
        valid_at,
        tx_as_of,
        tx_start,
        tx_end,
        outside_window_active.relation_id,
        outside_window_pending.relation_id,
    )


def test_query_relation_lifecycle_as_of_checkpoint_resumed_permutation_replay_matches_unsplit() -> None:
    (
        replicas,
        valid_at,
        tx_as_of,
        _tx_start,
        _tx_end,
        outside_window_active_relation_id,
        outside_window_pending_relation_id,
    ) = _relation_lifecycle_checkpoint_scenario()
    baseline_projection_signatures = None
    baseline_conflict_signatures = None

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = merge_replicas(ordered_replicas)

        unsplit_projection = unsplit_merged.query_relation_lifecycle_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
        )
        unsplit_signatures = _projection_signatures(unsplit_projection)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        assert KnowledgeStore.conflict_code_counts(unsplit_conflicts) == (
            (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
            (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 2),
        )
        assert unsplit_signatures[0]
        assert unsplit_signatures[1]
        assert tuple(signature[0] for signature in unsplit_signatures[0]) == tuple(
            sorted(signature[0] for signature in unsplit_signatures[0])
        )
        assert tuple(signature[0] for signature in unsplit_signatures[1]) == tuple(
            sorted(signature[0] for signature in unsplit_signatures[1])
        )
        assert outside_window_active_relation_id in {
            signature[0] for signature in unsplit_signatures[0]
        }
        assert outside_window_pending_relation_id in {
            signature[0] for signature in unsplit_signatures[1]
        }

        if baseline_projection_signatures is None:
            baseline_projection_signatures = unsplit_signatures
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_signatures == baseline_projection_signatures
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_conflicts = merge_replicas(ordered_replicas[:split_index])
            resumed_merged, resumed_suffix_conflicts = merge_replicas(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_projection = resumed_merged.query_relation_lifecycle_as_of(
                tx_id=tx_as_of,
                valid_at=valid_at,
            )
            resumed_signatures = _projection_signatures(resumed_projection)
            resumed_conflict_signatures = KnowledgeStore.conflict_signatures(
                prefix_conflicts + resumed_suffix_conflicts
            )

            assert resumed_projection == unsplit_projection
            assert resumed_signatures == unsplit_signatures
            assert resumed_conflict_signatures == unsplit_conflict_signatures


def test_query_relation_lifecycle_for_tx_window_checkpoint_resumed_permutation_replay_matches_unsplit() -> None:
    (
        replicas,
        valid_at,
        _tx_as_of,
        tx_start,
        tx_end,
        outside_window_active_relation_id,
        outside_window_pending_relation_id,
    ) = _relation_lifecycle_checkpoint_scenario()
    baseline_projection_signatures = None
    baseline_conflict_signatures = None

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = merge_replicas(ordered_replicas)

        unsplit_projection = unsplit_merged.query_relation_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
        )
        unsplit_signatures = _projection_signatures(unsplit_projection)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        assert KnowledgeStore.conflict_code_counts(unsplit_conflicts) == (
            (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
            (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 2),
        )
        assert unsplit_signatures[0]
        assert unsplit_signatures[1]
        assert tuple(signature[0] for signature in unsplit_signatures[0]) == tuple(
            sorted(signature[0] for signature in unsplit_signatures[0])
        )
        assert tuple(signature[0] for signature in unsplit_signatures[1]) == tuple(
            sorted(signature[0] for signature in unsplit_signatures[1])
        )
        assert outside_window_active_relation_id not in {
            signature[0] for signature in unsplit_signatures[0]
        }
        assert outside_window_pending_relation_id not in {
            signature[0] for signature in unsplit_signatures[1]
        }
        assert all(
            tx_start <= signature[4] <= tx_end
            for signature in unsplit_signatures[0] + unsplit_signatures[1]
        )

        if baseline_projection_signatures is None:
            baseline_projection_signatures = unsplit_signatures
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_signatures == baseline_projection_signatures
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_conflicts = merge_replicas(ordered_replicas[:split_index])
            resumed_merged, resumed_suffix_conflicts = merge_replicas(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_projection = resumed_merged.query_relation_lifecycle_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
            )
            resumed_signatures = _projection_signatures(resumed_projection)
            resumed_conflict_signatures = KnowledgeStore.conflict_signatures(
                prefix_conflicts + resumed_suffix_conflicts
            )

            assert resumed_projection == unsplit_projection
            assert resumed_signatures == unsplit_signatures
            assert resumed_conflict_signatures == unsplit_conflict_signatures
