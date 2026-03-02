from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)

SurfaceSerializationSignature = tuple[str, str, str, str, str, str, str]


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


def _build_state_fingerprint_serialization_replay_replicas(
    *,
    tx_base: int,
) -> tuple[list[KnowledgeStore], datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = tx_base + 2
    tx_to = tx_base + 7

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-serialization-subject-{tx_base}"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": f"state-fingerprint-serialization-anchor-{tx_base}"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": f"state-fingerprint-serialization-context-{tx_base}"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-serialization-retracted-{tx_base}"},
    )
    core_competing = ClaimCore(
        claim_type="residence",
        slots={"subject": f"state-fingerprint-serialization-competing-{tx_base}"},
    )

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="state fingerprint serialization anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_state_fingerprint_serialization_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="state fingerprint serialization context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_state_fingerprint_serialization_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="state fingerprint serialization subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_state_fingerprint_serialization_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="state fingerprint serialization retracted asserted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(
            source="source_state_fingerprint_serialization_retracted_asserted"
        ),
        confidence_bp=8300,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="state fingerprint serialization competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(
            source="source_state_fingerprint_serialization_competing_a"
        ),
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
        assertion="state fingerprint serialization competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(
            source="source_state_fingerprint_serialization_competing_b"
        ),
        confidence_bp=8200,
        status="asserted",
    )

    replica_retracted = KnowledgeStore()
    replica_retracted.assert_revision(
        core=core_retracted,
        assertion="state fingerprint serialization retracted final",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(
            source="source_state_fingerprint_serialization_retracted_final"
        ),
        confidence_bp=8300,
        status="retracted",
    )

    replica_orphan = KnowledgeStore()
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=f"missing-state-fingerprint-serialization-endpoint-{tx_base}",
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


def _surface_serialization_signature(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    core_id: str | None,
) -> SurfaceSerializationSignature:
    from_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=core_id,
    )
    as_of_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    window_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    transition_fingerprint = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )

    as_of_canonical_json = as_of_fingerprint.as_canonical_json()
    window_canonical_json = window_fingerprint.as_canonical_json()
    transition_canonical_json = transition_fingerprint.as_canonical_json()

    assert as_of_canonical_json == as_of_fingerprint.canonical_json()
    assert window_canonical_json == window_fingerprint.canonical_json()
    assert transition_canonical_json == transition_fingerprint.canonical_json()
    assert transition_fingerprint.from_digest == from_fingerprint.digest
    assert transition_fingerprint.to_digest == as_of_fingerprint.digest

    return (
        as_of_canonical_json,
        as_of_fingerprint.digest,
        window_canonical_json,
        window_fingerprint.digest,
        transition_canonical_json,
        transition_fingerprint.from_digest,
        transition_fingerprint.to_digest,
    )


def _assert_surface_serialization_equivalent(
    candidate: SurfaceSerializationSignature,
    expected: SurfaceSerializationSignature,
) -> None:
    (
        candidate_as_of_json,
        candidate_as_of_digest,
        candidate_window_json,
        candidate_window_digest,
        candidate_transition_json,
        candidate_transition_from_digest,
        candidate_transition_to_digest,
    ) = candidate
    (
        expected_as_of_json,
        expected_as_of_digest,
        expected_window_json,
        expected_window_digest,
        expected_transition_json,
        expected_transition_from_digest,
        expected_transition_to_digest,
    ) = expected

    assert candidate_as_of_json == expected_as_of_json
    assert candidate_window_json == expected_window_json
    assert candidate_transition_json == expected_transition_json

    assert candidate_as_of_digest == expected_as_of_digest
    assert candidate_window_digest == expected_window_digest
    assert candidate_transition_from_digest == expected_transition_from_digest
    assert candidate_transition_to_digest == expected_transition_to_digest


def test_state_fingerprint_serialization_permutation_order_and_checkpoint_segmentation_are_equivalent() -> None:
    replicas, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_serialization_replay_replicas(tx_base=6800)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)
    baseline_surfaces_by_core: dict[str | None, SurfaceSerializationSignature] = {}
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

        unsplit_surfaces_by_core: dict[str | None, SurfaceSerializationSignature] = {}
        for query_core_id in query_core_ids:
            unsplit_surface = _surface_serialization_signature(
                unsplit_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                core_id=query_core_id,
            )
            unsplit_surfaces_by_core[query_core_id] = unsplit_surface
            if query_core_id not in baseline_surfaces_by_core:
                baseline_surfaces_by_core[query_core_id] = unsplit_surface
            else:
                _assert_surface_serialization_equivalent(
                    unsplit_surface,
                    baseline_surfaces_by_core[query_core_id],
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
                segmented_surface = _surface_serialization_signature(
                    segmented_merged,
                    tx_from=tx_from,
                    tx_to=tx_to,
                    valid_at=valid_at,
                    core_id=query_core_id,
                )
                _assert_surface_serialization_equivalent(
                    segmented_surface,
                    unsplit_surfaces_by_core[query_core_id],
                )


def test_state_fingerprint_serialization_duplicate_replay_is_idempotent_for_equivalent_history() -> None:
    replicas, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_serialization_replay_replicas(tx_base=6880)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = replay_stream(ordered_replicas)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)
        unsplit_surfaces_by_core: dict[str | None, SurfaceSerializationSignature] = {}

        for query_core_id in query_core_ids:
            unsplit_surfaces_by_core[query_core_id] = _surface_serialization_signature(
                unsplit_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                core_id=query_core_id,
            )

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
            duplicate_surface = _surface_serialization_signature(
                duplicate_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                core_id=query_core_id,
            )
            resumed_duplicate_surface = _surface_serialization_signature(
                resumed_duplicate_merged,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                core_id=query_core_id,
            )
            _assert_surface_serialization_equivalent(
                duplicate_surface,
                unsplit_surfaces_by_core[query_core_id],
            )
            _assert_surface_serialization_equivalent(
                resumed_duplicate_surface,
                unsplit_surfaces_by_core[query_core_id],
            )
