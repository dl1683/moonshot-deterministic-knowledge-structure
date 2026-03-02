from datetime import datetime, timezone

import pytest

from dks import (
    ConflictCode,
    KnowledgeStore,
    MergeConflict,
    MergeConflictProjection,
    MergeConflictProjectionTransition,
    MergeResult,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _signature_count_sort_key(signature_count: tuple[str, str, str, int]) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _assert_projection_ordering(projection: MergeConflictProjection) -> None:
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


def _assert_transition_ordering(transition: MergeConflictProjectionTransition) -> None:
    assert transition.entered_signature_counts == tuple(
        sorted(
            transition.entered_signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert transition.exited_signature_counts == tuple(
        sorted(
            transition.exited_signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert transition.entered_code_counts == tuple(
        sorted(
            transition.entered_code_counts,
            key=_code_count_sort_key,
        )
    )
    assert transition.exited_code_counts == tuple(
        sorted(
            transition.exited_code_counts,
            key=_code_count_sort_key,
        )
    )


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="orphan-a",
        details="missing endpoint orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="orphan-b",
        details="missing endpoint orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="competing-subject",
        details="competing asserted revisions",
    )
    return (
        (
            10,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(orphan_a,),
            ),
        ),
        (
            11,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(orphan_a, orphan_b),
            ),
        ),
        (
            12,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(competing,),
            ),
        ),
    )


def _expected_window_projection_from_as_of_filtering(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_start: int,
    tx_end: int,
) -> MergeConflictProjection:
    as_of_stream_at_tx_end = tuple(
        (merge_result_tx_id, merge_result)
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if merge_result_tx_id <= tx_end
    )
    explicitly_filtered_as_of_stream = tuple(
        (merge_result_tx_id, merge_result)
        for merge_result_tx_id, merge_result in as_of_stream_at_tx_end
        if tx_start <= merge_result_tx_id
    )
    return KnowledgeStore.query_merge_conflict_projection_as_of(
        explicitly_filtered_as_of_stream,
        tx_id=tx_end,
    )


def _transition_buckets(
    transition: MergeConflictProjectionTransition,
) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_signature_counts,
        transition.exited_signature_counts,
        transition.entered_code_counts,
        transition.exited_code_counts,
    )


def _expected_transition_from_as_of_diffs(
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


def test_merge_conflict_tx_window_cross_surface_matches_as_of_filtering_and_boundaries() -> None:
    stream = _build_merge_conflict_stream()

    tx_windows = (
        (9, 9),
        (10, 10),
        (10, 11),
        (11, 11),
        (11, 12),
        (12, 12),
        (13, 13),
        (9, 12),
    )
    for tx_start, tx_end in tx_windows:
        window_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        expected_projection = _expected_window_projection_from_as_of_filtering(
            stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        assert window_projection.summary == expected_projection.summary
        _assert_projection_ordering(window_projection)

    boundary_start_inclusive = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        stream,
        tx_start=10,
        tx_end=11,
    )
    boundary_start_exclusive = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        stream,
        tx_start=11,
        tx_end=11,
    )
    assert boundary_start_inclusive.code_counts == ((ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 3),)
    assert boundary_start_exclusive.code_counts == ((ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 2),)

    boundary_end_inclusive = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        stream,
        tx_start=10,
        tx_end=11,
    )
    boundary_end_exclusive = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        stream,
        tx_start=10,
        tx_end=10,
    )
    assert boundary_end_inclusive.code_counts == ((ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 3),)
    assert boundary_end_exclusive.code_counts == ((ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 1),)


def test_merge_conflict_transition_cross_surface_matches_as_of_set_diffs_and_boundaries() -> None:
    stream = _build_merge_conflict_stream()

    tx_windows = (
        (9, 10),
        (10, 11),
        (10, 12),
        (11, 12),
    )
    for tx_from, tx_to in tx_windows:
        transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=dt(2024, 6, 1),
        )
        expected_buckets = _expected_transition_from_as_of_diffs(
            stream,
            tx_from=tx_from,
            tx_to=tx_to,
        )
        assert transition.tx_from == tx_from
        assert transition.tx_to == tx_to
        assert _transition_buckets(transition) == expected_buckets
        _assert_transition_ordering(transition)

    boundary_transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        stream,
        tx_from=9,
        tx_to=10,
        valid_at=dt(2024, 6, 1),
    )
    to_projection = KnowledgeStore.query_merge_conflict_projection_as_of(stream, tx_id=10)
    assert boundary_transition.entered_signature_counts == to_projection.signature_counts
    assert boundary_transition.exited_signature_counts == ()
    assert boundary_transition.entered_code_counts == to_projection.code_counts
    assert boundary_transition.exited_code_counts == ()


def test_merge_conflict_transition_zero_delta_identity_matches_as_of_diff_identity() -> None:
    stream = _build_merge_conflict_stream()
    transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        stream,
        tx_from=11,
        tx_to=11,
        valid_at=dt(2024, 6, 1),
    )

    assert _transition_buckets(transition) == ((), (), (), ())
    assert _transition_buckets(transition) == _expected_transition_from_as_of_diffs(
        stream,
        tx_from=11,
        tx_to=11,
    )
    _assert_transition_ordering(transition)


def test_merge_conflict_cross_surface_inverted_windows_raise_value_error() -> None:
    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            (),
            tx_start=11,
            tx_end=10,
        )

    with pytest.raises(
        ValueError,
        match="tx_to must be greater than or equal to tx_from",
    ):
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            (),
            tx_from=12,
            tx_to=11,
            valid_at=dt(2024, 6, 1),
        )
