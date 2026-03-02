from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    DeterministicStateFingerprintTransition,
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


def _signature_count_sort_key(
    signature_count: tuple[str, str, str, int],
) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _transition_bucket_signature(
    transition: DeterministicStateFingerprintTransition,
) -> tuple[tuple, ...]:
    return (
        tuple(
            _revision_signature(revision)
            for revision in transition.entered_revision_active
        ),
        tuple(
            _revision_signature(revision)
            for revision in transition.exited_revision_active
        ),
        tuple(
            _revision_signature(revision)
            for revision in transition.entered_revision_retracted
        ),
        tuple(
            _revision_signature(revision)
            for revision in transition.exited_revision_retracted
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.entered_relation_resolution_active
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.exited_relation_resolution_active
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.entered_relation_resolution_pending
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.exited_relation_resolution_pending
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.entered_relation_lifecycle_active
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.exited_relation_lifecycle_active
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.entered_relation_lifecycle_pending
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.exited_relation_lifecycle_pending
        ),
        transition.entered_relation_lifecycle_signature_active,
        transition.exited_relation_lifecycle_signature_active,
        transition.entered_relation_lifecycle_signature_pending,
        transition.exited_relation_lifecycle_signature_pending,
        transition.entered_merge_conflict_signature_counts,
        transition.exited_merge_conflict_signature_counts,
        transition.entered_merge_conflict_code_counts,
        transition.exited_merge_conflict_code_counts,
    )


def _assert_transition_ordering(
    transition: DeterministicStateFingerprintTransition,
) -> None:
    assert tuple(
        revision.revision_id for revision in transition.entered_revision_active
    ) == tuple(sorted(revision.revision_id for revision in transition.entered_revision_active))
    assert tuple(
        revision.revision_id for revision in transition.exited_revision_active
    ) == tuple(sorted(revision.revision_id for revision in transition.exited_revision_active))
    assert tuple(
        revision.revision_id for revision in transition.entered_revision_retracted
    ) == tuple(
        sorted(
            revision.revision_id for revision in transition.entered_revision_retracted
        )
    )
    assert tuple(
        revision.revision_id for revision in transition.exited_revision_retracted
    ) == tuple(
        sorted(
            revision.revision_id for revision in transition.exited_revision_retracted
        )
    )
    assert tuple(
        relation.relation_id
        for relation in transition.entered_relation_resolution_active
    ) == tuple(
        sorted(
            relation.relation_id
            for relation in transition.entered_relation_resolution_active
        )
    )
    assert tuple(
        relation.relation_id
        for relation in transition.exited_relation_resolution_active
    ) == tuple(
        sorted(
            relation.relation_id
            for relation in transition.exited_relation_resolution_active
        )
    )
    assert tuple(
        relation.relation_id
        for relation in transition.entered_relation_resolution_pending
    ) == tuple(
        sorted(
            relation.relation_id
            for relation in transition.entered_relation_resolution_pending
        )
    )
    assert tuple(
        relation.relation_id
        for relation in transition.exited_relation_resolution_pending
    ) == tuple(
        sorted(
            relation.relation_id
            for relation in transition.exited_relation_resolution_pending
        )
    )
    assert tuple(
        relation.relation_id
        for relation in transition.entered_relation_lifecycle_active
    ) == tuple(
        sorted(
            relation.relation_id
            for relation in transition.entered_relation_lifecycle_active
        )
    )
    assert tuple(
        relation.relation_id
        for relation in transition.exited_relation_lifecycle_active
    ) == tuple(
        sorted(
            relation.relation_id
            for relation in transition.exited_relation_lifecycle_active
        )
    )
    assert tuple(
        relation.relation_id
        for relation in transition.entered_relation_lifecycle_pending
    ) == tuple(
        sorted(
            relation.relation_id
            for relation in transition.entered_relation_lifecycle_pending
        )
    )
    assert tuple(
        relation.relation_id
        for relation in transition.exited_relation_lifecycle_pending
    ) == tuple(
        sorted(
            relation.relation_id
            for relation in transition.exited_relation_lifecycle_pending
        )
    )
    assert transition.entered_relation_lifecycle_signature_active == tuple(
        sorted(transition.entered_relation_lifecycle_signature_active)
    )
    assert transition.exited_relation_lifecycle_signature_active == tuple(
        sorted(transition.exited_relation_lifecycle_signature_active)
    )
    assert transition.entered_relation_lifecycle_signature_pending == tuple(
        sorted(transition.entered_relation_lifecycle_signature_pending)
    )
    assert transition.exited_relation_lifecycle_signature_pending == tuple(
        sorted(transition.exited_relation_lifecycle_signature_pending)
    )
    assert transition.entered_merge_conflict_signature_counts == tuple(
        sorted(
            transition.entered_merge_conflict_signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert transition.exited_merge_conflict_signature_counts == tuple(
        sorted(
            transition.exited_merge_conflict_signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert transition.entered_merge_conflict_code_counts == tuple(
        sorted(
            transition.entered_merge_conflict_code_counts,
            key=_code_count_sort_key,
        )
    )
    assert transition.exited_merge_conflict_code_counts == tuple(
        sorted(
            transition.exited_merge_conflict_code_counts,
            key=_code_count_sort_key,
        )
    )


def _assert_transition_equivalent(
    candidate: DeterministicStateFingerprintTransition,
    expected: DeterministicStateFingerprintTransition,
) -> None:
    assert candidate.tx_from == expected.tx_from
    assert candidate.tx_to == expected.tx_to
    assert candidate.from_digest == expected.from_digest
    assert candidate.to_digest == expected.to_digest
    assert _transition_bucket_signature(candidate) == _transition_bucket_signature(expected)


def _build_state_fingerprint_transition_replay_replicas(
    *,
    tx_base: int,
) -> tuple[list[KnowledgeStore], datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = tx_base + 2
    tx_to = tx_base + 7

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-transition-subject-{tx_base}"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": f"state-fingerprint-transition-anchor-{tx_base}"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": f"state-fingerprint-transition-context-{tx_base}"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-transition-retracted-{tx_base}"},
    )
    core_competing = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-transition-competing-{tx_base}"},
    )

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="state fingerprint transition anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_state_fingerprint_transition_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="state fingerprint transition context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_state_fingerprint_transition_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="state fingerprint transition subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_state_fingerprint_transition_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="state fingerprint transition retracted asserted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(
            source="source_state_fingerprint_transition_retracted_asserted"
        ),
        confidence_bp=8300,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="state fingerprint transition competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_state_fingerprint_transition_competing_a"),
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
        assertion="state fingerprint transition competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_state_fingerprint_transition_competing_b"),
        confidence_bp=8200,
        status="asserted",
    )

    replica_retracted = KnowledgeStore()
    replica_retracted.assert_revision(
        core=core_retracted,
        assertion="state fingerprint transition retracted final",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_state_fingerprint_transition_retracted_final"),
        confidence_bp=8300,
        status="retracted",
    )

    replica_orphan = KnowledgeStore()
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=f"missing-state-fingerprint-transition-endpoint-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 1, 8)),
    )
    replica_orphan.relations[orphan_relation.relation_id] = orphan_relation

    return (
        [replica_base, replica_competing, replica_retracted, replica_orphan],
        valid_at,
        tx_from,
        tx_to,
        core_subject.core_id,
    )


def test_query_state_fingerprint_transition_for_tx_window_permutation_order_and_checkpoint_segmentation_are_equivalent() -> None:
    replicas, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_transition_replay_replicas(tx_base=6600)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)
    baseline_transitions_by_core: dict[str | None, DeterministicStateFingerprintTransition] = {}
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

        unsplit_transitions_by_core: dict[
            str | None, DeterministicStateFingerprintTransition
        ] = {}
        for query_core_id in query_core_ids:
            unsplit_transition = (
                unsplit_merged.query_state_fingerprint_transition_for_tx_window(
                    tx_from=tx_from,
                    tx_to=tx_to,
                    valid_at=valid_at,
                    core_id=query_core_id,
                )
            )
            _assert_transition_ordering(unsplit_transition)
            unsplit_transitions_by_core[query_core_id] = unsplit_transition
            if query_core_id not in baseline_transitions_by_core:
                baseline_transitions_by_core[query_core_id] = unsplit_transition
            else:
                _assert_transition_equivalent(
                    unsplit_transition,
                    baseline_transitions_by_core[query_core_id],
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
                segmented_transition = (
                    segmented_merged.query_state_fingerprint_transition_for_tx_window(
                        tx_from=tx_from,
                        tx_to=tx_to,
                        valid_at=valid_at,
                        core_id=query_core_id,
                    )
                )
                _assert_transition_ordering(segmented_transition)
                _assert_transition_equivalent(
                    segmented_transition,
                    unsplit_transitions_by_core[query_core_id],
                )


def test_query_state_fingerprint_transition_for_tx_window_duplicate_replay_is_idempotent_for_equivalent_history() -> None:
    replicas, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_transition_replay_replicas(tx_base=6680)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = replay_stream(ordered_replicas)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)
        unsplit_transitions_by_core: dict[
            str | None, DeterministicStateFingerprintTransition
        ] = {}

        for query_core_id in query_core_ids:
            unsplit_transition = (
                unsplit_merged.query_state_fingerprint_transition_for_tx_window(
                    tx_from=tx_from,
                    tx_to=tx_to,
                    valid_at=valid_at,
                    core_id=query_core_id,
                )
            )
            _assert_transition_ordering(unsplit_transition)
            unsplit_transitions_by_core[query_core_id] = unsplit_transition

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
            duplicate_transition = (
                duplicate_merged.query_state_fingerprint_transition_for_tx_window(
                    tx_from=tx_from,
                    tx_to=tx_to,
                    valid_at=valid_at,
                    core_id=query_core_id,
                )
            )
            resumed_duplicate_transition = (
                resumed_duplicate_merged.query_state_fingerprint_transition_for_tx_window(
                    tx_from=tx_from,
                    tx_to=tx_to,
                    valid_at=valid_at,
                    core_id=query_core_id,
                )
            )
            _assert_transition_ordering(duplicate_transition)
            _assert_transition_ordering(resumed_duplicate_transition)
            _assert_transition_equivalent(
                duplicate_transition,
                unsplit_transitions_by_core[query_core_id],
            )
            _assert_transition_equivalent(
                resumed_duplicate_transition,
                unsplit_transitions_by_core[query_core_id],
            )
