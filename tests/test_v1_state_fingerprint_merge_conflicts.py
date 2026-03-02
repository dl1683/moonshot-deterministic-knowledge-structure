from datetime import datetime, timezone

from dks import (
    ClaimCore,
    ConflictCode,
    DeterministicStateFingerprint,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    MergeConflict,
    MergeConflictProjectionTransition,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


class OneShotIterable:
    def __init__(self, values: tuple) -> None:
        self._values = values
        self._iterated = False

    def __iter__(self):
        if self._iterated:
            raise AssertionError("one-shot iterable was iterated more than once")
        self._iterated = True
        return iter(self._values)


def _build_state_fingerprint_store() -> tuple[KnowledgeStore, datetime, int, int, str]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 2
    tx_to = 5

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": "state-fingerprint-merge-conflicts-subject"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": "state-fingerprint-merge-conflicts-anchor"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": "state-fingerprint-merge-conflicts-context"},
    )

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="merge conflicts anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_merge_conflicts_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = store.assert_revision(
        core=core_context,
        assertion="merge conflicts context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_merge_conflicts_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision_a = store.assert_revision(
        core=core_subject,
        assertion="subject candidate A",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_merge_conflicts_subject_a"),
        confidence_bp=8400,
        status="asserted",
    )
    subject_revision_b = store.assert_revision(
        core=core_subject,
        assertion="subject candidate B",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_merge_conflicts_subject_b"),
        confidence_bp=8400,
        status="asserted",
    )
    subject_winner = (
        subject_revision_a
        if subject_revision_a.revision_id < subject_revision_b.revision_id
        else subject_revision_b
    )
    subject_loser = (
        subject_revision_b
        if subject_winner.revision_id == subject_revision_a.revision_id
        else subject_revision_a
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=subject_winner.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=context_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=subject_loser.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )

    orphan_replica = KnowledgeStore()
    pending_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_winner.revision_id,
        to_revision_id="missing-state-fingerprint-merge-conflicts-endpoint",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    return store, valid_at, tx_from, tx_to, core_subject.core_id


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="state-fingerprint-merge-conflicts-orphan-a",
        details="missing endpoint state-fingerprint-merge-conflicts-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="state-fingerprint-merge-conflicts-orphan-b",
        details="missing endpoint state-fingerprint-merge-conflicts-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="state-fingerprint-merge-conflicts-competing",
        details="competing revision winner",
    )
    return (
        (2, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (4, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (5, MergeResult(merged=KnowledgeStore(), conflicts=(competing,))),
    )


def _assert_non_merge_surfaces_equal(
    left: DeterministicStateFingerprint,
    right: DeterministicStateFingerprint,
) -> None:
    assert left.revision_lifecycle == right.revision_lifecycle
    assert left.relation_resolution == right.relation_resolution
    assert left.relation_lifecycle == right.relation_lifecycle
    assert left.relation_lifecycle_signatures == right.relation_lifecycle_signatures


def _transition_non_merge_buckets(
    transition: DeterministicStateFingerprintTransition,
) -> tuple[tuple, ...]:
    return (
        transition.entered_revision_active,
        transition.exited_revision_active,
        transition.entered_revision_retracted,
        transition.exited_revision_retracted,
        transition.entered_relation_resolution_active,
        transition.exited_relation_resolution_active,
        transition.entered_relation_resolution_pending,
        transition.exited_relation_resolution_pending,
        transition.entered_relation_lifecycle_active,
        transition.exited_relation_lifecycle_active,
        transition.entered_relation_lifecycle_pending,
        transition.exited_relation_lifecycle_pending,
        transition.entered_relation_lifecycle_signature_active,
        transition.exited_relation_lifecycle_signature_active,
        transition.entered_relation_lifecycle_signature_pending,
        transition.exited_relation_lifecycle_signature_pending,
    )


def _transition_merge_buckets(
    transition: DeterministicStateFingerprintTransition,
) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_merge_conflict_signature_counts,
        transition.exited_merge_conflict_signature_counts,
        transition.entered_merge_conflict_code_counts,
        transition.exited_merge_conflict_code_counts,
    )


def _merge_projection_transition_buckets(
    transition: MergeConflictProjectionTransition,
) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_signature_counts,
        transition.exited_signature_counts,
        transition.entered_code_counts,
        transition.exited_code_counts,
    )


def test_state_fingerprint_merge_conflicts_as_of_and_window_match_direct_projection_routes() -> None:
    store, valid_at, _tx_from, _tx_to, _subject_core_id = _build_state_fingerprint_store()
    merge_results_by_tx = _build_merge_conflict_stream()

    for tx_id in (1, 2, 3, 4, 5, 6):
        fingerprint = store.query_state_fingerprint_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            merge_results_by_tx=merge_results_by_tx,
        )
        expected_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            merge_results_by_tx,
            tx_id=tx_id,
        )
        assert fingerprint.merge_conflict_projection == expected_projection

    for tx_start, tx_end in ((1, 1), (2, 2), (2, 4), (4, 5), (5, 6), (1, 6)):
        fingerprint = store.query_state_fingerprint_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            merge_results_by_tx=merge_results_by_tx,
        )
        expected_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            merge_results_by_tx,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        assert fingerprint.merge_conflict_projection == expected_projection


def test_state_fingerprint_merge_conflicts_one_shot_iterables_match_tuple_routes() -> None:
    store, valid_at, tx_from, tx_to, _subject_core_id = _build_state_fingerprint_store()
    merge_results_by_tx = _build_merge_conflict_stream()

    as_of_tuple = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=merge_results_by_tx,
    )
    as_of_one_shot = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    assert as_of_one_shot == as_of_tuple

    window_tuple = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=merge_results_by_tx,
    )
    window_one_shot = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    assert window_one_shot == window_tuple

    transition_tuple = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=merge_results_by_tx,
    )
    transition_one_shot = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    assert transition_one_shot == transition_tuple


def test_state_fingerprint_merge_conflicts_transition_and_core_filtering_stay_stable() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = _build_state_fingerprint_store()
    merge_results_by_tx = _build_merge_conflict_stream()

    as_of_unfiltered_with_merge = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=merge_results_by_tx,
    )
    as_of_filtered_without_merge = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    as_of_filtered_with_merge = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=merge_results_by_tx,
    )
    _assert_non_merge_surfaces_equal(as_of_filtered_with_merge, as_of_filtered_without_merge)
    assert (
        as_of_filtered_with_merge.merge_conflict_projection
        == as_of_unfiltered_with_merge.merge_conflict_projection
    )
    assert as_of_filtered_with_merge.merge_conflict_projection == (
        KnowledgeStore.query_merge_conflict_projection_as_of(
            merge_results_by_tx,
            tx_id=tx_to,
        )
    )

    window_filtered_without_merge = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    window_filtered_with_merge = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=merge_results_by_tx,
    )
    _assert_non_merge_surfaces_equal(
        window_filtered_with_merge,
        window_filtered_without_merge,
    )
    assert window_filtered_with_merge.merge_conflict_projection == (
        KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            merge_results_by_tx,
            tx_start=tx_from,
            tx_end=tx_to,
        )
    )

    transition_without_merge = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    transition_with_merge = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=merge_results_by_tx,
    )
    assert (
        _transition_non_merge_buckets(transition_with_merge)
        == _transition_non_merge_buckets(transition_without_merge)
    )

    expected_merge_transition = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            merge_results_by_tx,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
    )
    assert _transition_merge_buckets(transition_with_merge) == (
        _merge_projection_transition_buckets(expected_merge_transition)
    )
