from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    MergeConflict,
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


def _build_store_with_known_tx_ids(*tx_ids: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    for index, tx_id in enumerate(sorted(set(tx_ids)), start=1):
        store.assert_revision(
            core=ClaimCore(
                claim_type="merge_conflict_journal_tx_validation_seed",
                slots={"subject": f"journal-tx-validation-known-tx-{tx_id}"},
            ),
            assertion=f"journal-tx-validation known tx {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 1, index + 1),
            ),
            provenance=Provenance(source=f"source_journal_tx_validation_{tx_id}"),
            confidence_bp=8000,
            status="asserted",
        )
    return store


def _journal_signature(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
) -> tuple[tuple[int, tuple[tuple[str, str, str], ...]], ...]:
    return tuple(
        (
            tx_id,
            tuple(
                (conflict.code.value, conflict.entity_id, conflict.details)
                for conflict in merge_result.conflicts
            ),
        )
        for tx_id, merge_result in merge_results_by_tx
    )


def _seed_journal_entry(*, tx_id: int, marker: str) -> tuple[int, MergeResult]:
    conflict = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id=f"journal-tx-validation-seed-{marker}",
        details=f"journal-tx-validation seeded conflict {marker}",
    )
    return (
        tx_id,
        MergeResult(merged=KnowledgeStore(), conflicts=(conflict,)),
    )


def _build_incoming_single_tx_store(*, tx_id: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    core = ClaimCore(
        claim_type="residence",
        slots={"subject": f"journal-tx-validation-single-tx-{tx_id}"},
    )
    revision = store.assert_revision(
        core=core,
        assertion=f"journal-tx-validation revision {tx_id}",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_id, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source=f"source_journal_tx_validation_single_tx_{tx_id}"),
        confidence_bp=8500,
        status="asserted",
    )
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=revision.revision_id,
        to_revision_id=f"missing-journal-tx-validation-endpoint-{tx_id}",
        transaction_time=TransactionTime(tx_id=tx_id, recorded_at=dt(2024, 1, 3)),
    )
    store.relations[orphan_relation.relation_id] = orphan_relation
    return store


def _build_incoming_ambiguous_tx_store(*, tx_left: int, tx_right: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    left_core = ClaimCore(
        claim_type="document",
        slots={"id": f"journal-tx-validation-ambiguous-left-{tx_left}"},
    )
    right_core = ClaimCore(
        claim_type="document",
        slots={"id": f"journal-tx-validation-ambiguous-right-{tx_right}"},
    )
    store.assert_revision(
        core=left_core,
        assertion="journal-tx-validation ambiguous left",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_left, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_journal_tx_validation_ambiguous_left"),
        confidence_bp=9000,
        status="asserted",
    )
    store.assert_revision(
        core=right_core,
        assertion="journal-tx-validation ambiguous right",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_right, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_journal_tx_validation_ambiguous_right"),
        confidence_bp=9000,
        status="asserted",
    )
    return store


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="journal-tx-validation-orphan-a",
        details="missing endpoint journal-tx-validation-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="journal-tx-validation-orphan-b",
        details="missing endpoint journal-tx-validation-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="journal-tx-validation-competing",
        details="competing revisions journal-tx-validation-competing",
    )
    lifecycle = MergeConflict(
        code=ConflictCode.COMPETING_LIFECYCLE_SAME_SLOT,
        entity_id="journal-tx-validation-lifecycle",
        details="competing lifecycle journal-tx-validation-lifecycle",
    )
    return (
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(competing,))),
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (7, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_b,))),
        (12, MergeResult(merged=KnowledgeStore(), conflicts=(lifecycle,))),
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


def test_record_merge_conflict_journal_rejects_unknown_tx_ids_fail_closed() -> None:
    store = _build_store_with_known_tx_ids(7, 9)
    baseline_entry = _seed_journal_entry(tx_id=7, marker="baseline")
    store.record_merge_conflict_journal((baseline_entry,))

    unknown_entry = _seed_journal_entry(tx_id=11, marker="unknown")
    with pytest.raises(
        ValueError,
        match=r"merge-conflict journal tx_id\(s\) are not present in store tx history",
    ):
        store.record_merge_conflict_journal(OneShotIterable((unknown_entry,)))

    assert _journal_signature(store.merge_conflict_journal()) == _journal_signature(
        (baseline_entry,)
    )


def test_merge_and_record_conflicts_derived_tx_happy_path_matches_manual_parity() -> None:
    manual_base = _build_store_with_known_tx_ids(900)
    api_base = _build_store_with_known_tx_ids(900)
    seeded_entry = _seed_journal_entry(tx_id=900, marker="manual-parity")
    manual_base.record_merge_conflict_journal((seeded_entry,))
    api_base.record_merge_conflict_journal((seeded_entry,))

    incoming = _build_incoming_single_tx_store(tx_id=777)
    manual_merge_result = manual_base.merge(incoming)
    manual_merge_result.merged.record_merge_conflict_journal(
        ((777, manual_merge_result),)
    )
    api_merge_result = api_base.merge_and_record_conflicts(incoming)

    assert api_merge_result.conflicts == manual_merge_result.conflicts
    assert (
        api_merge_result.merged.as_canonical_json()
        == manual_merge_result.merged.as_canonical_json()
    )
    assert _journal_signature(
        api_merge_result.merged.merge_conflict_journal()
    ) == _journal_signature(manual_merge_result.merged.merge_conflict_journal())


def test_merge_and_record_conflicts_explicit_override_requires_known_tx_membership() -> None:
    base = KnowledgeStore()
    incoming = _build_incoming_ambiguous_tx_store(tx_left=401, tx_right=402)

    with pytest.raises(
        ValueError,
        match=r"merge-conflict journal tx_id\(s\) are not present in store tx history",
    ):
        base.merge_and_record_conflicts(
            incoming,
            journal_tx_id=999,
        )
    assert base.merge_conflict_journal() == ()

    merge_result = base.merge_and_record_conflicts(
        incoming,
        journal_tx_id=401,
    )
    assert tuple(tx_id for tx_id, _merge_result in merge_result.merged.merge_conflict_journal()) == (
        401,
    )


def test_journal_backed_query_outputs_unchanged_when_tx_labels_are_valid() -> None:
    store = _build_store_with_known_tx_ids(7, 8, 9, 10, 11, 12)
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
