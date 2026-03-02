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


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="merge-conflict-journal-orphan-a",
        details="missing endpoint merge-conflict-journal-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="merge-conflict-journal-orphan-b",
        details="missing endpoint merge-conflict-journal-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="merge-conflict-journal-competing",
        details="competing revisions merge-conflict-journal-competing",
    )
    lifecycle = MergeConflict(
        code=ConflictCode.COMPETING_LIFECYCLE_SAME_SLOT,
        entity_id="merge-conflict-journal-lifecycle",
        details="competing lifecycle merge-conflict-journal-lifecycle",
    )
    return (
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_b,))),
        (7, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(competing,))),
        (12, MergeResult(merged=KnowledgeStore(), conflicts=(lifecycle,))),
    )


def _build_merge_conflict_continuation_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_c = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="merge-conflict-journal-orphan-c",
        details="missing endpoint merge-conflict-journal-orphan-c",
    )
    competing_followup = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="merge-conflict-journal-competing-followup",
        details="competing revisions merge-conflict-journal-competing-followup",
    )
    return (
        (10, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_c,))),
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(competing_followup,))),
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


def _build_store_with_known_journal_tx_ids() -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    for index, tx_id in enumerate((7, 8, 9, 10, 11, 12), start=1):
        store.assert_revision(
            core=ClaimCore(
                claim_type="merge_conflict_journal_seed",
                slots={"subject": f"merge-conflict-journal-known-tx-{tx_id}"},
            ),
            assertion=f"merge-conflict-journal known tx {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 1, index + 1),
            ),
            provenance=Provenance(
                source=f"source_merge_conflict_journal_known_tx_{tx_id}"
            ),
            confidence_bp=8000,
            status="asserted",
        )
    return store


def _build_state_fingerprint_store() -> tuple[KnowledgeStore, datetime, int, int]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 2
    tx_to = 5

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": "merge-conflict-journal-subject"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": "merge-conflict-journal-anchor"},
    )

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="journal anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_merge_conflict_journal_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision_a = store.assert_revision(
        core=core_subject,
        assertion="subject candidate A",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_merge_conflict_journal_subject_a"),
        confidence_bp=8400,
        status="asserted",
    )
    subject_revision_b = store.assert_revision(
        core=core_subject,
        assertion="subject candidate B",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_merge_conflict_journal_subject_b"),
        confidence_bp=8400,
        status="asserted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=subject_revision_a.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision_b.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )

    for index, tx_id in enumerate((7, 8, 9, 10, 11, 12), start=1):
        store.assert_revision(
            core=ClaimCore(
                claim_type="merge_conflict_journal_state_seed",
                slots={"subject": f"merge-conflict-journal-state-known-tx-{tx_id}"},
            ),
            assertion=f"merge-conflict-journal state known tx {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 2, index),
            ),
            provenance=Provenance(
                source=f"source_merge_conflict_journal_state_known_tx_{tx_id}"
            ),
            confidence_bp=7800,
            status="asserted",
        )

    return store, valid_at, tx_from, tx_to


def test_merge_conflict_journal_record_and_retrieve_normalize_shuffled_one_shot_inputs() -> None:
    store = _build_store_with_known_journal_tx_ids()
    initial_stream = _build_merge_conflict_stream()
    expected_initial = _canonical_stream(initial_stream)

    recorded_initial = store.record_merge_conflict_journal(OneShotIterable(initial_stream))
    assert recorded_initial == expected_initial
    assert store.merge_conflict_journal() == expected_initial

    continuation_stream = _build_merge_conflict_continuation_stream()
    expected_continuation = _canonical_stream(continuation_stream)
    expected_full = _canonical_stream(expected_initial + expected_continuation)

    recorded_full = store.record_merge_conflict_journal(
        OneShotIterable(continuation_stream)
    )
    assert recorded_full == expected_full
    assert store.merge_conflict_journal() == expected_full

    checkpoint = store.checkpoint()
    assert checkpoint.merge_conflict_journal() == expected_full


def test_merge_conflict_journal_parity_with_direct_projection_routes() -> None:
    store = _build_store_with_known_journal_tx_ids()
    stream = _build_merge_conflict_stream()
    canonical_stream = _canonical_stream(stream)
    valid_at = dt(2024, 6, 1)

    store.record_merge_conflict_journal(OneShotIterable(stream))
    journal_stream = store.merge_conflict_journal()

    for tx_id in (6, 7, 8, 9, 10, 11, 12, 13):
        assert KnowledgeStore.query_merge_conflict_projection_as_of(
            journal_stream,
            tx_id=tx_id,
        ) == KnowledgeStore.query_merge_conflict_projection_as_of(
            canonical_stream,
            tx_id=tx_id,
        )

    for tx_start, tx_end in ((7, 7), (7, 9), (8, 11), (10, 12), (7, 13)):
        assert KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            journal_stream,
            tx_start=tx_start,
            tx_end=tx_end,
        ) == KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            canonical_stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )

    for tx_from, tx_to in ((7, 7), (7, 9), (8, 11), (10, 12), (7, 13)):
        assert KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            journal_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        ) == KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            canonical_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )


def test_merge_conflict_journal_parity_with_conflict_aware_state_fingerprint_routes() -> None:
    store, valid_at, tx_from, tx_to = _build_state_fingerprint_store()
    stream = _build_merge_conflict_stream()
    canonical_stream = _canonical_stream(stream)

    store.record_merge_conflict_journal(OneShotIterable(stream))
    journal_stream = store.merge_conflict_journal()

    for tx_id in (1, 2, 3, 4, 5, 6):
        assert store.query_state_fingerprint_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            merge_results_by_tx=journal_stream,
        ) == store.query_state_fingerprint_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            merge_results_by_tx=canonical_stream,
        )

    assert store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=journal_stream,
    ) == store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=canonical_stream,
    )

    assert store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=journal_stream,
    ) == store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        merge_results_by_tx=canonical_stream,
    )
