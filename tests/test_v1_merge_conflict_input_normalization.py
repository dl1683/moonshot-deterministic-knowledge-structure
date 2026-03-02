from datetime import datetime, timezone

from dks import (
    ConflictCode,
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
        entity_id="merge-normalization-orphan-a",
        details="missing endpoint merge-normalization-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="merge-normalization-orphan-b",
        details="missing endpoint merge-normalization-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="merge-normalization-competing",
        details="competing revisions merge-normalization-competing",
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


def _merge_results_as_of(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_id: int,
) -> tuple[MergeResult, ...]:
    return tuple(
        merge_result
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if merge_result_tx_id <= tx_id
    )


def _merge_results_for_window(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_start: int,
    tx_end: int,
) -> tuple[MergeResult, ...]:
    return tuple(
        merge_result
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if tx_start <= merge_result_tx_id <= tx_end
    )


def _signature_count_sort_key(
    signature_count: tuple[str, str, str, int],
) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _transition_buckets(
    transition: MergeConflictProjectionTransition,
) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_signature_counts,
        transition.exited_signature_counts,
        transition.entered_code_counts,
        transition.exited_code_counts,
    )


def _expected_transition_buckets_from_as_of_diffs(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_from: int,
    tx_to: int,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        merge_results_by_tx,
        tx_id=tx_from,
    )
    to_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        merge_results_by_tx,
        tx_id=tx_to,
    )
    return (
        tuple(
            sorted(
                set(to_projection.signature_counts) - set(from_projection.signature_counts),
                key=_signature_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(from_projection.signature_counts) - set(to_projection.signature_counts),
                key=_signature_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(to_projection.code_counts) - set(from_projection.code_counts),
                key=_code_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(from_projection.code_counts) - set(to_projection.code_counts),
                key=_code_count_sort_key,
            )
        ),
    )


def test_merge_conflict_projection_input_normalization_is_shuffle_invariant() -> None:
    valid_at = dt(2024, 6, 1)
    tx_from = 8
    tx_to = 11
    shuffled_stream = _build_merge_conflict_stream()
    canonical_stream = _canonical_stream()

    as_of_canonical = KnowledgeStore.query_merge_conflict_projection_as_of(
        canonical_stream,
        tx_id=tx_to,
    )
    as_of_shuffled = KnowledgeStore.query_merge_conflict_projection_as_of(
        shuffled_stream,
        tx_id=tx_to,
    )
    assert as_of_shuffled == as_of_canonical

    window_canonical = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        canonical_stream,
        tx_start=tx_from,
        tx_end=tx_to,
    )
    window_shuffled = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        shuffled_stream,
        tx_start=tx_from,
        tx_end=tx_to,
    )
    assert window_shuffled == window_canonical

    transition_canonical = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            canonical_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
    )
    transition_shuffled = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            shuffled_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
    )
    assert transition_shuffled == transition_canonical


def test_merge_conflict_projection_input_normalization_one_shot_parity() -> None:
    valid_at = dt(2024, 6, 1)
    tx_from = 8
    tx_to = 11
    shuffled_stream = _build_merge_conflict_stream()

    as_of_tuple = KnowledgeStore.query_merge_conflict_projection_as_of(
        shuffled_stream,
        tx_id=tx_to,
    )
    as_of_one_shot = KnowledgeStore.query_merge_conflict_projection_as_of(
        OneShotIterable(shuffled_stream),
        tx_id=tx_to,
    )
    assert as_of_one_shot == as_of_tuple

    window_tuple = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        shuffled_stream,
        tx_start=tx_from,
        tx_end=tx_to,
    )
    window_one_shot = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        OneShotIterable(shuffled_stream),
        tx_start=tx_from,
        tx_end=tx_to,
    )
    assert window_one_shot == window_tuple

    transition_tuple = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        shuffled_stream,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    transition_one_shot = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            OneShotIterable(shuffled_stream),
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
    )
    assert transition_one_shot == transition_tuple


def test_merge_conflict_projection_input_normalization_preserves_signature_and_code_bucket_semantics() -> None:
    valid_at = dt(2024, 6, 1)
    tx_from = 8
    tx_to = 11
    canonical_stream = _canonical_stream()

    as_of_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        canonical_stream,
        tx_id=tx_to,
    )
    expected_as_of_summary = MergeResult.stream_conflict_summary(
        _merge_results_as_of(canonical_stream, tx_id=tx_to)
    )
    assert as_of_projection.summary == expected_as_of_summary

    window_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        canonical_stream,
        tx_start=tx_from,
        tx_end=tx_to,
    )
    expected_window_summary = MergeResult.stream_conflict_summary(
        _merge_results_for_window(
            canonical_stream,
            tx_start=tx_from,
            tx_end=tx_to,
        )
    )
    assert window_projection.summary == expected_window_summary

    transition_projection = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            canonical_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
    )
    expected_transition_buckets = _expected_transition_buckets_from_as_of_diffs(
        canonical_stream,
        tx_from=tx_from,
        tx_to=tx_to,
    )
    assert _transition_buckets(transition_projection) == expected_transition_buckets
