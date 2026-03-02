from datetime import datetime, timezone

import pytest

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


def _assert_transition_buckets_deterministically_sorted(
    transition: MergeConflictProjectionTransition,
) -> None:
    assert transition.entered_signature_counts == tuple(
        sorted(
            transition.entered_signature_counts,
            key=lambda signature_count: (
                signature_count[0],
                signature_count[1],
                signature_count[2],
            ),
        )
    )
    assert transition.exited_signature_counts == tuple(
        sorted(
            transition.exited_signature_counts,
            key=lambda signature_count: (
                signature_count[0],
                signature_count[1],
                signature_count[2],
            ),
        )
    )
    assert transition.entered_code_counts == tuple(
        sorted(
            transition.entered_code_counts,
            key=lambda code_count: code_count[0],
        )
    )
    assert transition.exited_code_counts == tuple(
        sorted(
            transition.exited_code_counts,
            key=lambda code_count: code_count[0],
        )
    )


def test_query_merge_conflict_projection_transition_for_tx_window_tracks_entered_and_exited_counts() -> None:
    stream = _build_merge_conflict_stream()

    transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        stream,
        tx_from=10,
        tx_to=11,
        valid_at=dt(2024, 6, 1),
    )

    assert transition.tx_from == 10
    assert transition.tx_to == 11
    assert transition.entered_signature_counts == (
        ("orphan_relation_endpoint", "orphan-a", "missing endpoint orphan-a", 2),
        ("orphan_relation_endpoint", "orphan-b", "missing endpoint orphan-b", 1),
    )
    assert transition.exited_signature_counts == (
        ("orphan_relation_endpoint", "orphan-a", "missing endpoint orphan-a", 1),
    )
    assert transition.entered_code_counts == (("orphan_relation_endpoint", 3),)
    assert transition.exited_code_counts == (("orphan_relation_endpoint", 1),)
    _assert_transition_buckets_deterministically_sorted(transition)


def test_query_merge_conflict_projection_transition_for_tx_window_zero_delta_has_empty_buckets() -> None:
    transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        OneShotIterable(_build_merge_conflict_stream()),
        tx_from=11,
        tx_to=11,
        valid_at=dt(2024, 6, 1),
    )

    assert transition.entered_signature_counts == ()
    assert transition.exited_signature_counts == ()
    assert transition.entered_code_counts == ()
    assert transition.exited_code_counts == ()


def test_query_merge_conflict_projection_transition_for_tx_window_includes_cutoff_boundaries() -> None:
    stream = _build_merge_conflict_stream()
    transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        stream,
        tx_from=9,
        tx_to=10,
        valid_at=dt(2024, 6, 1),
    )
    to_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        stream,
        tx_id=10,
    )

    assert transition.entered_signature_counts == to_projection.signature_counts
    assert transition.exited_signature_counts == ()
    assert transition.entered_code_counts == to_projection.code_counts
    assert transition.exited_code_counts == ()
    _assert_transition_buckets_deterministically_sorted(transition)


def test_query_merge_conflict_projection_transition_for_tx_window_matches_explicit_as_of_diffs() -> None:
    stream = _build_merge_conflict_stream()
    tx_from = 10
    tx_to = 12

    from_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        stream,
        tx_id=tx_from,
    )
    to_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        stream,
        tx_id=tx_to,
    )
    transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        stream,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=dt(2024, 6, 1),
    )

    expected_entered_signature_counts = tuple(
        sorted(
            set(to_projection.signature_counts) - set(from_projection.signature_counts),
            key=lambda signature_count: (
                signature_count[0],
                signature_count[1],
                signature_count[2],
            ),
        )
    )
    expected_exited_signature_counts = tuple(
        sorted(
            set(from_projection.signature_counts) - set(to_projection.signature_counts),
            key=lambda signature_count: (
                signature_count[0],
                signature_count[1],
                signature_count[2],
            ),
        )
    )
    expected_entered_code_counts = tuple(
        sorted(
            set(to_projection.code_counts) - set(from_projection.code_counts),
            key=lambda code_count: code_count[0],
        )
    )
    expected_exited_code_counts = tuple(
        sorted(
            set(from_projection.code_counts) - set(to_projection.code_counts),
            key=lambda code_count: code_count[0],
        )
    )

    assert transition.entered_signature_counts == expected_entered_signature_counts
    assert transition.exited_signature_counts == expected_exited_signature_counts
    assert transition.entered_code_counts == expected_entered_code_counts
    assert transition.exited_code_counts == expected_exited_code_counts
    _assert_transition_buckets_deterministically_sorted(transition)


def test_query_merge_conflict_projection_transition_for_tx_window_rejects_inverted_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_to must be greater than or equal to tx_from",
    ):
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            (),
            tx_from=11,
            tx_to=10,
            valid_at=dt(2024, 6, 1),
        )
