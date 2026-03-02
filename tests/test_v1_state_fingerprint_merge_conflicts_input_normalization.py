from datetime import datetime, timezone

from dks import (
    ConflictCode,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    MergeConflict,
    MergeConflictProjectionTransition,
    MergeResult,
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


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="state-fingerprint-normalization-orphan-a",
        details="missing endpoint state-fingerprint-normalization-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="state-fingerprint-normalization-orphan-b",
        details="missing endpoint state-fingerprint-normalization-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="state-fingerprint-normalization-competing",
        details="competing revision state-fingerprint-normalization-competing",
    )
    return (
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(competing,))),
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (7, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (10, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_b,))),
    )


def _canonical_stream() -> tuple[tuple[int, MergeResult], ...]:
    stream = _build_merge_conflict_stream()
    return tuple(
        merge_result_by_tx
        for _index, merge_result_by_tx in sorted(
            enumerate(stream),
            key=lambda indexed_merge_result: (
                indexed_merge_result[1][0],
                indexed_merge_result[0],
            ),
        )
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


def test_state_fingerprint_merge_conflicts_input_normalization_is_shuffle_invariant() -> None:
    store = KnowledgeStore()
    valid_at = dt(2024, 6, 1)
    tx_from = 8
    tx_to = 11
    shuffled_stream = _build_merge_conflict_stream()
    canonical_stream = _canonical_stream()

    as_of_canonical = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=canonical_stream,
    )
    as_of_shuffled = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=shuffled_stream,
    )
    assert as_of_shuffled == as_of_canonical

    window_canonical = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=canonical_stream,
    )
    window_shuffled = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=shuffled_stream,
    )
    assert window_shuffled == window_canonical

    transition_canonical = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=canonical_stream,
    )
    transition_shuffled = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=shuffled_stream,
    )
    assert transition_shuffled == transition_canonical


def test_state_fingerprint_merge_conflicts_input_normalization_one_shot_parity() -> None:
    store = KnowledgeStore()
    valid_at = dt(2024, 6, 1)
    tx_from = 8
    tx_to = 11
    shuffled_stream = _build_merge_conflict_stream()

    as_of_tuple = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=shuffled_stream,
    )
    as_of_one_shot = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(shuffled_stream),
    )
    assert as_of_one_shot == as_of_tuple

    window_tuple = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=shuffled_stream,
    )
    window_one_shot = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(shuffled_stream),
    )
    assert window_one_shot == window_tuple

    transition_tuple = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=shuffled_stream,
    )
    transition_one_shot = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(shuffled_stream),
    )
    assert transition_one_shot == transition_tuple


def test_state_fingerprint_merge_conflicts_input_normalization_preserves_digest_and_bucket_semantics() -> None:
    store = KnowledgeStore()
    valid_at = dt(2024, 6, 1)
    tx_from = 8
    tx_to = 11
    canonical_stream = _canonical_stream()

    as_of_implicit = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )
    as_of_explicit_empty = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=(),
    )
    assert as_of_explicit_empty == as_of_implicit

    window_implicit = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
    )
    window_explicit_empty = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=(),
    )
    assert window_explicit_empty == window_implicit

    transition_implicit = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    transition_explicit_empty = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=(),
    )
    assert transition_explicit_empty == transition_implicit

    as_of_with_merge = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=canonical_stream,
    )
    window_with_merge = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=canonical_stream,
    )
    transition_with_merge = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=canonical_stream,
    )

    assert as_of_with_merge.merge_conflict_projection == (
        KnowledgeStore.query_merge_conflict_projection_as_of(
            canonical_stream,
            tx_id=tx_to,
        )
    )
    assert window_with_merge.merge_conflict_projection == (
        KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            canonical_stream,
            tx_start=tx_from,
            tx_end=tx_to,
        )
    )

    expected_transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        canonical_stream,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert _transition_merge_buckets(transition_with_merge) == (
        _merge_projection_transition_buckets(expected_transition)
    )
