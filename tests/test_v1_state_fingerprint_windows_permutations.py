from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    DeterministicStateFingerprint,
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
        merged, segment_conflicts = replay_stream(segment, start=segment_start)
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


def _fingerprint_bucket_signature(
    fingerprint: DeterministicStateFingerprint,
) -> tuple[tuple, ...]:
    return (
        tuple(
            _revision_signature(revision)
            for revision in fingerprint.revision_lifecycle.active
        ),
        tuple(
            _revision_signature(revision)
            for revision in fingerprint.revision_lifecycle.retracted
        ),
        tuple(
            _relation_signature(relation)
            for relation in fingerprint.relation_resolution.active
        ),
        tuple(
            _relation_signature(relation)
            for relation in fingerprint.relation_resolution.pending
        ),
        tuple(
            _relation_signature(relation)
            for relation in fingerprint.relation_lifecycle.active
        ),
        tuple(
            _relation_signature(relation)
            for relation in fingerprint.relation_lifecycle.pending
        ),
        fingerprint.relation_lifecycle_signatures.active,
        fingerprint.relation_lifecycle_signatures.pending,
        fingerprint.merge_conflict_projection.signature_counts,
        fingerprint.merge_conflict_projection.code_counts,
    )


def _assert_fingerprint_ordering(fingerprint: DeterministicStateFingerprint) -> None:
    assert tuple(
        revision.revision_id for revision in fingerprint.revision_lifecycle.active
    ) == tuple(sorted(revision.revision_id for revision in fingerprint.revision_lifecycle.active))
    assert tuple(
        revision.revision_id for revision in fingerprint.revision_lifecycle.retracted
    ) == tuple(sorted(revision.revision_id for revision in fingerprint.revision_lifecycle.retracted))
    assert tuple(
        relation.relation_id for relation in fingerprint.relation_resolution.active
    ) == tuple(sorted(relation.relation_id for relation in fingerprint.relation_resolution.active))
    assert tuple(
        relation.relation_id for relation in fingerprint.relation_resolution.pending
    ) == tuple(sorted(relation.relation_id for relation in fingerprint.relation_resolution.pending))
    assert tuple(
        relation.relation_id for relation in fingerprint.relation_lifecycle.active
    ) == tuple(sorted(relation.relation_id for relation in fingerprint.relation_lifecycle.active))
    assert tuple(
        relation.relation_id for relation in fingerprint.relation_lifecycle.pending
    ) == tuple(sorted(relation.relation_id for relation in fingerprint.relation_lifecycle.pending))
    assert fingerprint.relation_lifecycle_signatures.active == tuple(
        sorted(fingerprint.relation_lifecycle_signatures.active)
    )
    assert fingerprint.relation_lifecycle_signatures.pending == tuple(
        sorted(fingerprint.relation_lifecycle_signatures.pending)
    )
    assert fingerprint.merge_conflict_projection.signature_counts == tuple(
        sorted(fingerprint.merge_conflict_projection.signature_counts)
    )
    assert fingerprint.merge_conflict_projection.code_counts == tuple(
        sorted(fingerprint.merge_conflict_projection.code_counts)
    )


def _assert_fingerprint_equivalent(
    candidate: DeterministicStateFingerprint,
    expected: DeterministicStateFingerprint,
) -> None:
    assert candidate.digest == expected.digest
    assert candidate.ordered_projection == expected.ordered_projection
    assert _fingerprint_bucket_signature(candidate) == _fingerprint_bucket_signature(expected)


def _build_state_fingerprint_window_replay_replicas(
    *,
    tx_base: int,
) -> tuple[list[KnowledgeStore], datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_start = tx_base + 2
    tx_end = tx_base + 7

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-window-subject-{tx_base}"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": f"state-fingerprint-window-anchor-{tx_base}"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": f"state-fingerprint-window-context-{tx_base}"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-window-retracted-{tx_base}"},
    )
    core_competing = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-window-competing-{tx_base}"},
    )

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="state fingerprint window anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_state_fingerprint_window_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="state fingerprint window context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_state_fingerprint_window_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="state fingerprint window subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_state_fingerprint_window_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="state fingerprint window retracted asserted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_state_fingerprint_window_retracted_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="state fingerprint window competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_state_fingerprint_window_competing_a"),
        confidence_bp=8200,
        status="asserted",
    )
    replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
    )
    replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=context_revision.revision_id,
        to_revision_id=subject_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
    )

    replica_competing = KnowledgeStore()
    replica_competing.assert_revision(
        core=core_competing,
        assertion="state fingerprint window competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_state_fingerprint_window_competing_b"),
        confidence_bp=8200,
        status="asserted",
    )

    replica_retracted = KnowledgeStore()
    replica_retracted.assert_revision(
        core=core_retracted,
        assertion="state fingerprint window retracted final",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_state_fingerprint_window_retracted_final"),
        confidence_bp=8300,
        status="retracted",
    )

    replica_orphan = KnowledgeStore()
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=f"missing-state-fingerprint-window-endpoint-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 1, 8)),
    )
    replica_orphan.relations[orphan_relation.relation_id] = orphan_relation

    return (
        [replica_base, replica_competing, replica_retracted, replica_orphan],
        valid_at,
        tx_start,
        tx_end,
        core_subject.core_id,
    )


def test_query_state_fingerprint_for_tx_window_permutation_order_and_checkpoint_segmentation_are_equivalent() -> None:
    replicas, valid_at, tx_start, tx_end, subject_core_id = (
        _build_state_fingerprint_window_replay_replicas(tx_base=6400)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)
    baseline_fingerprints_by_core: dict[str | None, DeterministicStateFingerprint] = {}
    baseline_conflict_signatures = None
    checkpoint_boundaries = tuple(
        boundaries
        for checkpoint_count in range(1, len(replicas))
        for boundaries in itertools.combinations(range(1, len(replicas)), checkpoint_count)
    )
    assert checkpoint_boundaries

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = replay_stream(ordered_replicas)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)
        if baseline_conflict_signatures is None:
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        unsplit_fingerprints_by_core: dict[str | None, DeterministicStateFingerprint] = {}
        for query_core_id in query_core_ids:
            unsplit_fingerprint = unsplit_merged.query_state_fingerprint_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
                core_id=query_core_id,
            )
            _assert_fingerprint_ordering(unsplit_fingerprint)
            unsplit_fingerprints_by_core[query_core_id] = unsplit_fingerprint
            if query_core_id not in baseline_fingerprints_by_core:
                baseline_fingerprints_by_core[query_core_id] = unsplit_fingerprint
            else:
                _assert_fingerprint_equivalent(
                    unsplit_fingerprint,
                    baseline_fingerprints_by_core[query_core_id],
                )

        for boundaries in checkpoint_boundaries:
            segmented_merged, segmented_conflicts = replay_with_checkpoint_segments(
                ordered_replicas,
                boundaries=boundaries,
            )
            assert (
                KnowledgeStore.conflict_signatures(segmented_conflicts)
                == unsplit_conflict_signatures
            )
            for query_core_id in query_core_ids:
                segmented_fingerprint = segmented_merged.query_state_fingerprint_for_tx_window(
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_at=valid_at,
                    core_id=query_core_id,
                )
                _assert_fingerprint_ordering(segmented_fingerprint)
                _assert_fingerprint_equivalent(
                    segmented_fingerprint,
                    unsplit_fingerprints_by_core[query_core_id],
                )


def test_query_state_fingerprint_for_tx_window_duplicate_replay_is_idempotent_for_equivalent_history() -> None:
    replicas, valid_at, tx_start, tx_end, subject_core_id = (
        _build_state_fingerprint_window_replay_replicas(tx_base=6480)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = replay_stream(ordered_replicas)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)
        unsplit_fingerprints_by_core: dict[str | None, DeterministicStateFingerprint] = {}

        for query_core_id in query_core_ids:
            unsplit_fingerprint = unsplit_merged.query_state_fingerprint_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
                core_id=query_core_id,
            )
            _assert_fingerprint_ordering(unsplit_fingerprint)
            unsplit_fingerprints_by_core[query_core_id] = unsplit_fingerprint

        duplicate_merged, duplicate_conflicts = replay_stream(
            ordered_replicas,
            start=unsplit_merged,
        )
        resumed_duplicate_merged, resumed_duplicate_conflicts = replay_stream(
            ordered_replicas,
            start=unsplit_merged.checkpoint(),
        )
        assert duplicate_conflicts == ()
        assert resumed_duplicate_conflicts == ()
        assert (
            KnowledgeStore.conflict_signatures(unsplit_conflicts + duplicate_conflicts)
            == unsplit_conflict_signatures
        )
        assert (
            KnowledgeStore.conflict_signatures(
                unsplit_conflicts + resumed_duplicate_conflicts
            )
            == unsplit_conflict_signatures
        )
        assert (
            duplicate_merged.revision_state_signatures()
            == unsplit_merged.revision_state_signatures()
        )
        assert (
            duplicate_merged.relation_state_signatures()
            == unsplit_merged.relation_state_signatures()
        )
        assert duplicate_merged.pending_relation_ids() == unsplit_merged.pending_relation_ids()
        assert (
            resumed_duplicate_merged.revision_state_signatures()
            == unsplit_merged.revision_state_signatures()
        )
        assert (
            resumed_duplicate_merged.relation_state_signatures()
            == unsplit_merged.relation_state_signatures()
        )
        assert (
            resumed_duplicate_merged.pending_relation_ids()
            == unsplit_merged.pending_relation_ids()
        )

        for query_core_id in query_core_ids:
            duplicate_fingerprint = duplicate_merged.query_state_fingerprint_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
                core_id=query_core_id,
            )
            resumed_duplicate_fingerprint = (
                resumed_duplicate_merged.query_state_fingerprint_for_tx_window(
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_at=valid_at,
                    core_id=query_core_id,
                )
            )
            _assert_fingerprint_ordering(duplicate_fingerprint)
            _assert_fingerprint_ordering(resumed_duplicate_fingerprint)
            _assert_fingerprint_equivalent(
                duplicate_fingerprint,
                unsplit_fingerprints_by_core[query_core_id],
            )
            _assert_fingerprint_equivalent(
                resumed_duplicate_fingerprint,
                unsplit_fingerprints_by_core[query_core_id],
            )
