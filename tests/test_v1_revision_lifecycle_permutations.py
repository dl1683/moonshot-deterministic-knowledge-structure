from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    Provenance,
    RevisionLifecycleProjection,
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


def _projection_signatures(
    projection: RevisionLifecycleProjection,
) -> tuple[tuple[tuple[str, str, str, str, str, int, str], ...], tuple[tuple[str, str, str, str, str, int, str], ...]]:
    return (
        tuple(_revision_signature(revision) for revision in projection.active),
        tuple(_revision_signature(revision) for revision in projection.retracted),
    )


def _revision_lifecycle_checkpoint_scenario() -> tuple[list[KnowledgeStore], datetime, int, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)

    core_active = ClaimCore(claim_type="residence", slots={"subject": "active winner"})
    core_retracted = ClaimCore(claim_type="residence", slots={"subject": "retracted winner"})
    core_competing = ClaimCore(claim_type="residence", slots={"subject": "competing winner"})
    core_outside_window = ClaimCore(claim_type="residence", slots={"subject": "outside window"})

    replica_base = KnowledgeStore()
    replica_base.assert_revision(
        core=core_active,
        assertion="active winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=40, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_active"),
        confidence_bp=8400,
        status="asserted",
    )
    outside_window_revision = replica_base.assert_revision(
        core=core_outside_window,
        assertion="outside window",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=38, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_outside"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="retracted winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=39, recorded_at=dt(2024, 1, 9)),
        provenance=Provenance(source="source_retracted_prior"),
        confidence_bp=8400,
        status="asserted",
    )

    replica_retraction = KnowledgeStore()
    replica_retraction.assert_revision(
        core=core_retracted,
        assertion="retracted winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=41, recorded_at=dt(2024, 1, 11)),
        provenance=Provenance(source="source_retracted"),
        confidence_bp=8400,
        status="retracted",
    )

    replica_competing_a = KnowledgeStore()
    replica_competing_a.assert_revision(
        core=core_competing,
        assertion="competing winner a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=40, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_competing_a"),
        confidence_bp=8400,
        status="asserted",
    )

    replica_competing_b = KnowledgeStore()
    replica_competing_b.assert_revision(
        core=core_competing,
        assertion="competing winner b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=40, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_competing_b"),
        confidence_bp=8400,
        status="asserted",
    )

    return (
        [replica_base, replica_retraction, replica_competing_a, replica_competing_b],
        valid_at,
        41,
        40,
        41,
        outside_window_revision.revision_id,
    )


def test_query_revision_lifecycle_as_of_checkpoint_resumed_permutation_replay_matches_unsplit() -> None:
    replicas, valid_at, tx_as_of, _tx_start, _tx_end, outside_window_revision_id = (
        _revision_lifecycle_checkpoint_scenario()
    )
    baseline_projection_signatures = None
    baseline_conflict_signatures = None

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = merge_replicas(ordered_replicas)

        unsplit_projection = unsplit_merged.query_revision_lifecycle_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
        )
        unsplit_signatures = _projection_signatures(unsplit_projection)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        assert KnowledgeStore.conflict_code_counts(unsplit_conflicts) == (
            (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
        )
        assert unsplit_signatures[0]
        assert unsplit_signatures[1]
        assert all(signature[2] == "asserted" for signature in unsplit_signatures[0])
        assert all(signature[2] == "retracted" for signature in unsplit_signatures[1])
        assert outside_window_revision_id in {
            signature[0] for signature in unsplit_signatures[0]
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
            resumed_projection = resumed_merged.query_revision_lifecycle_as_of(
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


def test_query_revision_lifecycle_for_tx_window_checkpoint_resumed_permutation_replay_matches_unsplit() -> None:
    replicas, valid_at, _tx_as_of, tx_start, tx_end, outside_window_revision_id = (
        _revision_lifecycle_checkpoint_scenario()
    )
    baseline_projection_signatures = None
    baseline_conflict_signatures = None

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = merge_replicas(ordered_replicas)

        unsplit_projection = unsplit_merged.query_revision_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
        )
        unsplit_signatures = _projection_signatures(unsplit_projection)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        assert KnowledgeStore.conflict_code_counts(unsplit_conflicts) == (
            (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
        )
        assert unsplit_signatures[0]
        assert unsplit_signatures[1]
        assert all(signature[2] == "asserted" for signature in unsplit_signatures[0])
        assert all(signature[2] == "retracted" for signature in unsplit_signatures[1])
        assert outside_window_revision_id not in {
            signature[0] for signature in unsplit_signatures[0]
        }
        assert all(
            tx_start <= signature[5] <= tx_end
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
            resumed_projection = resumed_merged.query_revision_lifecycle_for_tx_window(
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
