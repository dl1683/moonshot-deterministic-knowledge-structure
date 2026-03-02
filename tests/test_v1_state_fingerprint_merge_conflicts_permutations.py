from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    DeterministicStateFingerprint,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def replica_stream_tx_id(replica: KnowledgeStore) -> int:
    tx_ids = [revision.transaction_time.tx_id for revision in replica.revisions.values()]
    tx_ids.extend(relation.transaction_time.tx_id for relation in replica.relations.values())
    tx_ids.extend(
        relation.transaction_time.tx_id for relation in replica._pending_relations.values()
    )
    return max(tx_ids, default=0)


def replay_stream_with_merge_results(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple[tuple[int, MergeResult], ...]]:
    merged = start if start is not None else KnowledgeStore()
    merge_results_by_tx: list[tuple[int, MergeResult]] = []
    for replica in replicas:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_results_by_tx.append((replica_stream_tx_id(replica), merge_result))
    return merged, tuple(merge_results_by_tx)


def replay_with_checkpoint_segments_with_merge_results(
    replicas: list[KnowledgeStore],
    *,
    boundaries: tuple[int, ...],
) -> tuple[KnowledgeStore, tuple[tuple[int, MergeResult], ...]]:
    merged = KnowledgeStore()
    stream: list[tuple[int, MergeResult]] = []
    start_index = 0

    for boundary in boundaries + (len(replicas),):
        segment = replicas[start_index:boundary]
        segment_start = merged if start_index == 0 else merged.checkpoint()
        merged, segment_stream = replay_stream_with_merge_results(segment, start=segment_start)
        stream.extend(segment_stream)
        start_index = boundary

    return merged, tuple(stream)


def _stream_conflict_signatures(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
) -> tuple[tuple[str, str, str], ...]:
    conflicts = tuple(
        conflict
        for _tx_id, merge_result in merge_results_by_tx
        for conflict in merge_result.conflicts
    )
    return KnowledgeStore.conflict_signatures(conflicts)


def _signature_count_sort_key(
    signature_count: tuple[str, str, str, int],
) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _assert_fingerprint_merge_ordering(
    fingerprint: DeterministicStateFingerprint,
) -> None:
    projection = fingerprint.merge_conflict_projection
    assert projection.signature_counts == tuple(
        sorted(
            projection.signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert projection.code_counts == tuple(
        sorted(
            projection.code_counts,
            key=_code_count_sort_key,
        )
    )


def _assert_transition_merge_ordering(
    transition: DeterministicStateFingerprintTransition,
) -> None:
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


def _fingerprint_merge_buckets(
    fingerprint: DeterministicStateFingerprint,
) -> tuple[tuple, tuple]:
    projection = fingerprint.merge_conflict_projection
    return (projection.signature_counts, projection.code_counts)


def _transition_merge_buckets(
    transition: DeterministicStateFingerprintTransition,
) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_merge_conflict_signature_counts,
        transition.exited_merge_conflict_signature_counts,
        transition.entered_merge_conflict_code_counts,
        transition.exited_merge_conflict_code_counts,
    )


def _assert_fingerprint_equivalent(
    candidate: DeterministicStateFingerprint,
    expected: DeterministicStateFingerprint,
) -> None:
    assert candidate.digest == expected.digest
    assert candidate.ordered_projection == expected.ordered_projection
    assert _fingerprint_merge_buckets(candidate) == _fingerprint_merge_buckets(expected)


def _assert_transition_equivalent(
    candidate: DeterministicStateFingerprintTransition,
    expected: DeterministicStateFingerprintTransition,
) -> None:
    assert candidate.tx_from == expected.tx_from
    assert candidate.tx_to == expected.tx_to
    assert candidate.from_digest == expected.from_digest
    assert candidate.to_digest == expected.to_digest
    assert _transition_merge_buckets(candidate) == _transition_merge_buckets(expected)


def _build_state_fingerprint_merge_conflict_replay_replicas(
    *,
    tx_base: int,
) -> tuple[list[KnowledgeStore], datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = tx_base + 2
    tx_to = tx_base + 7

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-merge-conflict-subject-{tx_base}"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": f"state-fingerprint-merge-conflict-anchor-{tx_base}"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": f"state-fingerprint-merge-conflict-context-{tx_base}"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-merge-conflict-retracted-{tx_base}"},
    )
    core_competing = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-merge-conflict-competing-{tx_base}"},
    )

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="state fingerprint merge conflict anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_state_fingerprint_merge_conflict_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="state fingerprint merge conflict context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_state_fingerprint_merge_conflict_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="state fingerprint merge conflict subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_state_fingerprint_merge_conflict_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="state fingerprint merge conflict retracted asserted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(
            source="source_state_fingerprint_merge_conflict_retracted_asserted"
        ),
        confidence_bp=8300,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="state fingerprint merge conflict competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_state_fingerprint_merge_conflict_competing_a"),
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
        assertion="state fingerprint merge conflict competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_state_fingerprint_merge_conflict_competing_b"),
        confidence_bp=8200,
        status="asserted",
    )

    replica_retracted = KnowledgeStore()
    replica_retracted.assert_revision(
        core=core_retracted,
        assertion="state fingerprint merge conflict retracted final",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_state_fingerprint_merge_conflict_retracted_final"),
        confidence_bp=8300,
        status="retracted",
    )

    replica_orphan = KnowledgeStore()
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=f"missing-state-fingerprint-merge-conflict-endpoint-{tx_base}",
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


def _query_conflict_aware_surfaces(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    core_id: str | None,
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
) -> tuple[
    DeterministicStateFingerprint,
    DeterministicStateFingerprint,
    DeterministicStateFingerprintTransition,
]:
    as_of_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=core_id,
        merge_results_by_tx=merge_results_by_tx,
    )
    tx_window_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        core_id=core_id,
        merge_results_by_tx=merge_results_by_tx,
    )
    transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=core_id,
        merge_results_by_tx=merge_results_by_tx,
    )

    _assert_fingerprint_merge_ordering(as_of_fingerprint)
    _assert_fingerprint_merge_ordering(tx_window_fingerprint)
    _assert_transition_merge_ordering(transition)

    return as_of_fingerprint, tx_window_fingerprint, transition


def test_state_fingerprint_merge_conflicts_permutation_order_and_checkpoint_segmentation_are_equivalent() -> None:
    replicas, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_merge_conflict_replay_replicas(tx_base=6720)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)
    baseline_surfaces_by_core: dict[
        str | None,
        tuple[
            DeterministicStateFingerprint,
            DeterministicStateFingerprint,
            DeterministicStateFingerprintTransition,
        ],
    ] = {}
    checkpoint_boundaries = tuple(
        boundaries
        for checkpoint_count in range(1, len(replicas))
        for boundaries in itertools.combinations(range(1, len(replicas)), checkpoint_count)
    )
    assert checkpoint_boundaries

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_stream = replay_stream_with_merge_results(ordered_replicas)
        unsplit_conflict_signatures = _stream_conflict_signatures(unsplit_stream)
        unsplit_surfaces_by_core: dict[
            str | None,
            tuple[
                DeterministicStateFingerprint,
                DeterministicStateFingerprint,
                DeterministicStateFingerprintTransition,
            ],
        ] = {}

        for query_core_id in query_core_ids:
            unsplit_surfaces = _query_conflict_aware_surfaces(
                unsplit_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                core_id=query_core_id,
                merge_results_by_tx=unsplit_stream,
            )
            unsplit_surfaces_by_core[query_core_id] = unsplit_surfaces

            if query_core_id not in baseline_surfaces_by_core:
                baseline_surfaces_by_core[query_core_id] = unsplit_surfaces
            else:
                baseline_as_of, baseline_window, baseline_transition = (
                    baseline_surfaces_by_core[query_core_id]
                )
                unsplit_as_of, unsplit_window, unsplit_transition = unsplit_surfaces
                _assert_fingerprint_equivalent(unsplit_as_of, baseline_as_of)
                _assert_fingerprint_equivalent(unsplit_window, baseline_window)
                _assert_transition_equivalent(unsplit_transition, baseline_transition)

        for boundaries in checkpoint_boundaries:
            segmented_merged, segmented_stream = (
                replay_with_checkpoint_segments_with_merge_results(
                    ordered_replicas,
                    boundaries=boundaries,
                )
            )
            assert (
                _stream_conflict_signatures(segmented_stream) == unsplit_conflict_signatures
            )

            for query_core_id in query_core_ids:
                segmented_surfaces = _query_conflict_aware_surfaces(
                    segmented_merged,
                    tx_from=tx_from,
                    tx_to=tx_to,
                    valid_at=valid_at,
                    core_id=query_core_id,
                    merge_results_by_tx=segmented_stream,
                )
                unsplit_as_of, unsplit_window, unsplit_transition = (
                    unsplit_surfaces_by_core[query_core_id]
                )
                segmented_as_of, segmented_window, segmented_transition = segmented_surfaces
                _assert_fingerprint_equivalent(segmented_as_of, unsplit_as_of)
                _assert_fingerprint_equivalent(segmented_window, unsplit_window)
                _assert_transition_equivalent(segmented_transition, unsplit_transition)


def test_state_fingerprint_merge_conflicts_duplicate_replay_is_idempotent_for_equivalent_history() -> None:
    replicas, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_merge_conflict_replay_replicas(tx_base=6800)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_stream = replay_stream_with_merge_results(ordered_replicas)
        unsplit_conflict_signatures = _stream_conflict_signatures(unsplit_stream)
        duplicate_merged, duplicate_stream = replay_stream_with_merge_results(
            ordered_replicas,
            start=unsplit_merged,
        )
        resumed_duplicate_merged, resumed_duplicate_stream = replay_stream_with_merge_results(
            ordered_replicas,
            start=unsplit_merged.checkpoint(),
        )

        assert all(not merge_result.conflicts for _tx_id, merge_result in duplicate_stream)
        assert all(
            not merge_result.conflicts
            for _tx_id, merge_result in resumed_duplicate_stream
        )

        duplicate_history_stream = unsplit_stream + duplicate_stream
        resumed_duplicate_history_stream = unsplit_stream + resumed_duplicate_stream
        assert (
            _stream_conflict_signatures(duplicate_history_stream)
            == unsplit_conflict_signatures
        )
        assert (
            _stream_conflict_signatures(resumed_duplicate_history_stream)
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
            unsplit_surfaces = _query_conflict_aware_surfaces(
                unsplit_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                core_id=query_core_id,
                merge_results_by_tx=unsplit_stream,
            )
            duplicate_surfaces = _query_conflict_aware_surfaces(
                duplicate_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                core_id=query_core_id,
                merge_results_by_tx=duplicate_history_stream,
            )
            resumed_duplicate_surfaces = _query_conflict_aware_surfaces(
                resumed_duplicate_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                core_id=query_core_id,
                merge_results_by_tx=resumed_duplicate_history_stream,
            )

            unsplit_as_of, unsplit_window, unsplit_transition = unsplit_surfaces
            duplicate_as_of, duplicate_window, duplicate_transition = duplicate_surfaces
            resumed_duplicate_as_of, resumed_duplicate_window, resumed_duplicate_transition = (
                resumed_duplicate_surfaces
            )

            _assert_fingerprint_equivalent(duplicate_as_of, unsplit_as_of)
            _assert_fingerprint_equivalent(duplicate_window, unsplit_window)
            _assert_transition_equivalent(duplicate_transition, unsplit_transition)
            _assert_fingerprint_equivalent(resumed_duplicate_as_of, unsplit_as_of)
            _assert_fingerprint_equivalent(resumed_duplicate_window, unsplit_window)
            _assert_transition_equivalent(
                resumed_duplicate_transition,
                unsplit_transition,
            )
