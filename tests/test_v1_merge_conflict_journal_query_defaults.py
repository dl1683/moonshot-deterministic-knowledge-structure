from datetime import datetime, timezone

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    MergeConflict,
    MergeResult,
    Provenance,
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


def _build_store_with_known_journal_tx_ids() -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    for index, tx_id in enumerate((7, 8, 9, 10, 11, 12), start=1):
        store.assert_revision(
            core=ClaimCore(
                claim_type="journal_default_seed",
                slots={"subject": f"journal-default-known-tx-{tx_id}"},
            ),
            assertion=f"journal-default known tx {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 1, index + 1),
            ),
            provenance=Provenance(source=f"source_journal_default_known_tx_{tx_id}"),
            confidence_bp=8000,
            status="asserted",
        )
    return store


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="journal-default-orphan-a",
        details="missing endpoint journal-default-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="journal-default-orphan-b",
        details="missing endpoint journal-default-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="journal-default-competing",
        details="competing revisions journal-default-competing",
    )
    lifecycle = MergeConflict(
        code=ConflictCode.COMPETING_LIFECYCLE_SAME_SLOT,
        entity_id="journal-default-lifecycle",
        details="competing lifecycle journal-default-lifecycle",
    )
    return (
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(competing,))),
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (7, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_b,))),
        (12, MergeResult(merged=KnowledgeStore(), conflicts=(lifecycle,))),
    )


def _build_override_stream() -> tuple[tuple[int, MergeResult], ...]:
    override_orphan = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="journal-default-override-orphan",
        details="missing endpoint journal-default-override-orphan",
    )
    return (
        (8, MergeResult(merged=KnowledgeStore(), conflicts=(override_orphan,))),
    )


def _canonical_stream(
    stream: tuple[tuple[int, MergeResult], ...],
) -> tuple[tuple[int, MergeResult], ...]:
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


def test_journal_projection_routes_and_state_fingerprint_none_match_explicit_stream() -> None:
    store = _build_store_with_known_journal_tx_ids()
    stream = _build_merge_conflict_stream()
    canonical_stream = _canonical_stream(stream)
    valid_at = dt(2024, 6, 1)

    store.record_merge_conflict_journal(OneShotIterable(stream))
    assert store.merge_conflict_journal() == canonical_stream

    for tx_id in (6, 7, 8, 9, 10, 11, 12, 13):
        assert store.query_merge_conflict_projection_as_of_from_journal(
            tx_id=tx_id,
        ) == KnowledgeStore.query_merge_conflict_projection_as_of(
            canonical_stream,
            tx_id=tx_id,
        )
        assert store.query_state_fingerprint_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            merge_results_by_tx=None,
        ) == store.query_state_fingerprint_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            merge_results_by_tx=canonical_stream,
        )

    for tx_start, tx_end in ((7, 7), (7, 9), (8, 11), (9, 12), (7, 13)):
        assert store.query_merge_conflict_projection_for_tx_window_from_journal(
            tx_start=tx_start,
            tx_end=tx_end,
        ) == KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            canonical_stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        assert store.query_state_fingerprint_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            merge_results_by_tx=None,
        ) == store.query_state_fingerprint_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            merge_results_by_tx=canonical_stream,
        )

    for tx_from, tx_to in ((7, 7), (7, 9), (8, 11), (9, 12), (7, 13)):
        assert store.query_merge_conflict_projection_transition_for_tx_window_from_journal(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        ) == KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            canonical_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )
        assert store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            merge_results_by_tx=None,
        ) == store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            merge_results_by_tx=canonical_stream,
        )


def test_state_fingerprint_journal_resolution_preserves_explicit_override_and_one_shot_safety() -> None:
    store = _build_store_with_known_journal_tx_ids()
    stream = _build_merge_conflict_stream()
    override_stream = _build_override_stream()
    valid_at = dt(2024, 6, 1)
    tx_from = 7
    tx_to = 12

    store.record_merge_conflict_journal(OneShotIterable(stream))

    as_of_from_journal = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=None,
    )
    as_of_override_tuple = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=override_stream,
    )
    as_of_override_one_shot = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(override_stream),
    )
    assert as_of_override_one_shot == as_of_override_tuple
    assert (
        as_of_override_tuple.merge_conflict_projection
        != as_of_from_journal.merge_conflict_projection
    )

    as_of_explicit_empty = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=(),
    )
    assert (
        as_of_explicit_empty.merge_conflict_projection
        != as_of_from_journal.merge_conflict_projection
    )

    window_override_tuple = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=override_stream,
    )
    window_override_one_shot = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(override_stream),
    )
    assert window_override_one_shot == window_override_tuple

    transition_override_tuple = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=override_stream,
    )
    transition_override_one_shot = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(override_stream),
    )
    assert transition_override_one_shot == transition_override_tuple


def test_journal_backed_state_fingerprint_digest_is_stable_across_same_tx_order_variants() -> None:
    valid_at = dt(2024, 6, 1)
    tx_from = 8
    tx_to = 12

    stream = _build_merge_conflict_stream()
    stream_variant = (
        stream[0],
        stream[3],
        stream[2],
        stream[1],
        stream[4],
    )

    store_left = _build_store_with_known_journal_tx_ids()
    store_right = _build_store_with_known_journal_tx_ids()
    store_left.record_merge_conflict_journal(OneShotIterable(stream))
    store_right.record_merge_conflict_journal(OneShotIterable(stream_variant))

    assert store_left.merge_conflict_journal() != store_right.merge_conflict_journal()

    as_of_left = store_left.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=None,
    )
    as_of_right = store_right.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=None,
    )
    assert as_of_left == as_of_right
    assert as_of_left.digest == as_of_right.digest

    window_left = store_left.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=None,
    )
    window_right = store_right.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=None,
    )
    assert window_left == window_right
    assert window_left.digest == window_right.digest

    transition_left = store_left.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=None,
    )
    transition_right = store_right.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=None,
    )
    assert transition_left == transition_right
