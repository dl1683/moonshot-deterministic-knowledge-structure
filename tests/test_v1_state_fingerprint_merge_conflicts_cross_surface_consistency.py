from datetime import datetime, timezone

import pytest

from dks import (
    ConflictCode,
    DeterministicStateFingerprint,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    MergeConflict,
    MergeConflictProjection,
    MergeResult,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _signature_count_sort_key(
    signature_count: tuple[str, str, str, int],
) -> tuple[str, str, str]:
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


def _assert_transition_ordering(
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


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="state-fingerprint-cross-surface-orphan-a",
        details="missing endpoint state-fingerprint-cross-surface-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="state-fingerprint-cross-surface-orphan-b",
        details="missing endpoint state-fingerprint-cross-surface-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="state-fingerprint-cross-surface-competing",
        details="competing revisions state-fingerprint-cross-surface",
    )
    return (
        (10, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (12, MergeResult(merged=KnowledgeStore(), conflicts=(competing,))),
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


def _expected_transition_merge_buckets_from_as_of_fingerprints(
    from_fingerprint: DeterministicStateFingerprint,
    to_fingerprint: DeterministicStateFingerprint,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_signature_counts = set(from_fingerprint.merge_conflict_projection.signature_counts)
    to_signature_counts = set(to_fingerprint.merge_conflict_projection.signature_counts)
    from_code_counts = set(from_fingerprint.merge_conflict_projection.code_counts)
    to_code_counts = set(to_fingerprint.merge_conflict_projection.code_counts)
    return (
        tuple(
            sorted(
                to_signature_counts - from_signature_counts,
                key=_signature_count_sort_key,
            )
        ),
        tuple(
            sorted(
                from_signature_counts - to_signature_counts,
                key=_signature_count_sort_key,
            )
        ),
        tuple(
            sorted(
                to_code_counts - from_code_counts,
                key=_code_count_sort_key,
            )
        ),
        tuple(
            sorted(
                from_code_counts - to_code_counts,
                key=_code_count_sort_key,
            )
        ),
    )


def test_state_fingerprint_merge_conflict_components_match_direct_as_of_and_window_projection_routes() -> None:
    store = KnowledgeStore()
    valid_at = dt(2024, 6, 1)
    stream = _build_merge_conflict_stream()

    for tx_id in (9, 10, 11, 12, 13):
        fingerprint = store.query_state_fingerprint_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            merge_results_by_tx=stream,
        )
        expected_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            stream,
            tx_id=tx_id,
        )
        assert fingerprint.merge_conflict_projection == expected_projection
        _assert_projection_ordering(fingerprint.merge_conflict_projection)

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
        fingerprint = store.query_state_fingerprint_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            merge_results_by_tx=stream,
        )
        expected_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        assert fingerprint.merge_conflict_projection == expected_projection
        _assert_projection_ordering(fingerprint.merge_conflict_projection)

    boundary_start_inclusive = store.query_state_fingerprint_for_tx_window(
        tx_start=10,
        tx_end=11,
        valid_at=valid_at,
        merge_results_by_tx=stream,
    )
    boundary_start_exclusive = store.query_state_fingerprint_for_tx_window(
        tx_start=11,
        tx_end=11,
        valid_at=valid_at,
        merge_results_by_tx=stream,
    )
    assert boundary_start_inclusive.merge_conflict_projection.code_counts == (
        (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 3),
    )
    assert boundary_start_exclusive.merge_conflict_projection.code_counts == (
        (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 2),
    )

    boundary_end_inclusive = store.query_state_fingerprint_for_tx_window(
        tx_start=10,
        tx_end=11,
        valid_at=valid_at,
        merge_results_by_tx=stream,
    )
    boundary_end_exclusive = store.query_state_fingerprint_for_tx_window(
        tx_start=10,
        tx_end=10,
        valid_at=valid_at,
        merge_results_by_tx=stream,
    )
    assert boundary_end_inclusive.merge_conflict_projection.code_counts == (
        (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 3),
    )
    assert boundary_end_exclusive.merge_conflict_projection.code_counts == (
        (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 1),
    )


def test_state_fingerprint_merge_conflict_transition_matches_as_of_endpoint_diffs_and_direct_projection_routes() -> None:
    store = KnowledgeStore()
    valid_at = dt(2024, 6, 1)
    stream = _build_merge_conflict_stream()

    tx_windows = (
        (9, 10),
        (10, 11),
        (10, 12),
        (11, 12),
    )
    for tx_from, tx_to in tx_windows:
        transition = store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            merge_results_by_tx=stream,
        )
        from_fingerprint = store.query_state_fingerprint_as_of(
            tx_id=tx_from,
            valid_at=valid_at,
            merge_results_by_tx=stream,
        )
        to_fingerprint = store.query_state_fingerprint_as_of(
            tx_id=tx_to,
            valid_at=valid_at,
            merge_results_by_tx=stream,
        )
        expected_merge_buckets = _expected_transition_merge_buckets_from_as_of_fingerprints(
            from_fingerprint,
            to_fingerprint,
        )
        direct_merge_transition = (
            KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
                stream,
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
            )
        )

        assert transition.tx_from == tx_from
        assert transition.tx_to == tx_to
        assert transition.from_digest == from_fingerprint.digest
        assert transition.to_digest == to_fingerprint.digest
        assert _transition_merge_buckets(transition) == expected_merge_buckets
        assert transition.entered_merge_conflict_signature_counts == (
            direct_merge_transition.entered_signature_counts
        )
        assert transition.exited_merge_conflict_signature_counts == (
            direct_merge_transition.exited_signature_counts
        )
        assert transition.entered_merge_conflict_code_counts == (
            direct_merge_transition.entered_code_counts
        )
        assert transition.exited_merge_conflict_code_counts == (
            direct_merge_transition.exited_code_counts
        )
        _assert_transition_ordering(transition)

    boundary_transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=9,
        tx_to=10,
        valid_at=valid_at,
        merge_results_by_tx=stream,
    )
    to_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        stream,
        tx_id=10,
    )
    assert boundary_transition.entered_merge_conflict_signature_counts == (
        to_projection.signature_counts
    )
    assert boundary_transition.exited_merge_conflict_signature_counts == ()
    assert boundary_transition.entered_merge_conflict_code_counts == (
        to_projection.code_counts
    )
    assert boundary_transition.exited_merge_conflict_code_counts == ()


def test_state_fingerprint_merge_conflict_transition_zero_delta_identity_matches_as_of_diff_identity() -> None:
    store = KnowledgeStore()
    valid_at = dt(2024, 6, 1)
    stream = _build_merge_conflict_stream()

    transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=11,
        tx_to=11,
        valid_at=valid_at,
        merge_results_by_tx=stream,
    )
    as_of_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=11,
        valid_at=valid_at,
        merge_results_by_tx=stream,
    )
    assert transition.from_digest == as_of_fingerprint.digest
    assert transition.to_digest == as_of_fingerprint.digest
    assert _transition_merge_buckets(transition) == ((), (), (), ())
    assert _transition_merge_buckets(transition) == (
        _expected_transition_merge_buckets_from_as_of_fingerprints(
            as_of_fingerprint,
            as_of_fingerprint,
        )
    )
    _assert_transition_ordering(transition)


def test_state_fingerprint_merge_conflict_cross_surface_inverted_windows_raise_value_error() -> None:
    store = KnowledgeStore()
    stream = _build_merge_conflict_stream()

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_state_fingerprint_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=dt(2024, 6, 1),
            merge_results_by_tx=stream,
        )

    with pytest.raises(
        ValueError,
        match="tx_to must be greater than or equal to tx_from",
    ):
        store.query_state_fingerprint_transition_for_tx_window(
            tx_from=12,
            tx_to=11,
            valid_at=dt(2024, 6, 1),
            merge_results_by_tx=stream,
        )
