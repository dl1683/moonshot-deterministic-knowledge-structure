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
        entity_id=f"merge-and-record-seed-{marker}",
        details=f"merge-and-record seeded conflict {marker}",
    )
    return (
        tx_id,
        MergeResult(merged=KnowledgeStore(), conflicts=(conflict,)),
    )


def _build_store_with_known_tx_ids(*tx_ids: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    for index, tx_id in enumerate(sorted(set(tx_ids)), start=1):
        store.assert_revision(
            core=ClaimCore(
                claim_type="merge_and_record_seed",
                slots={"subject": f"merge-and-record-known-tx-{tx_id}"},
            ),
            assertion=f"merge-and-record known tx {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 1, index + 1),
            ),
            provenance=Provenance(
                source=f"source_merge_and_record_known_tx_{tx_id}"
            ),
            confidence_bp=8000,
            status="asserted",
        )
    return store


def _build_incoming_single_tx_store(*, tx_id: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    core = ClaimCore(
        claim_type="residence",
        slots={"subject": f"merge-and-record-single-tx-{tx_id}"},
    )
    revision = store.assert_revision(
        core=core,
        assertion=f"merge-and-record revision {tx_id}",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_id, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source=f"source_merge_and_record_single_tx_{tx_id}"),
        confidence_bp=8500,
        status="asserted",
    )
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=revision.revision_id,
        to_revision_id=f"missing-merge-and-record-endpoint-{tx_id}",
        transaction_time=TransactionTime(tx_id=tx_id, recorded_at=dt(2024, 1, 3)),
    )
    store.relations[orphan_relation.relation_id] = orphan_relation
    return store


def _build_incoming_ambiguous_tx_store(*, tx_left: int, tx_right: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    left_core = ClaimCore(
        claim_type="document",
        slots={"id": f"merge-and-record-ambiguous-left-{tx_left}"},
    )
    right_core = ClaimCore(
        claim_type="document",
        slots={"id": f"merge-and-record-ambiguous-right-{tx_right}"},
    )
    store.assert_revision(
        core=left_core,
        assertion="merge-and-record ambiguous left",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_left, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_merge_and_record_ambiguous_left"),
        confidence_bp=9000,
        status="asserted",
    )
    store.assert_revision(
        core=right_core,
        assertion="merge-and-record ambiguous right",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_right, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_merge_and_record_ambiguous_right"),
        confidence_bp=9000,
        status="asserted",
    )
    return store


def test_merge_and_record_conflicts_derives_tx_id_and_normalizes_journal_append_order() -> None:
    base = _build_store_with_known_tx_ids(900)
    seeded_entry = _seed_journal_entry(tx_id=900, marker="existing")
    base.record_merge_conflict_journal((seeded_entry,))

    incoming = _build_incoming_single_tx_store(tx_id=777)
    merge_result = base.merge_and_record_conflicts(incoming)

    journal_stream = merge_result.merged.merge_conflict_journal()
    assert tuple(tx_id for tx_id, _merge_result in journal_stream) == (777, 900)
    assert _journal_signature(journal_stream) == _journal_signature(
        ((777, merge_result), seeded_entry)
    )


def test_merge_and_record_conflicts_supports_explicit_journal_tx_override() -> None:
    incoming = _build_incoming_ambiguous_tx_store(tx_left=401, tx_right=402)
    merge_result = KnowledgeStore().merge_and_record_conflicts(
        incoming,
        journal_tx_id=401,
    )
    journal_stream = merge_result.merged.merge_conflict_journal()
    assert tuple(tx_id for tx_id, _merge_result in journal_stream) == (401,)
    assert _journal_signature(journal_stream) == _journal_signature(
        ((401, merge_result),)
    )


def test_merge_and_record_conflicts_fails_closed_for_empty_incoming_content() -> None:
    base = _build_store_with_known_tx_ids(303)
    seeded_entry = _seed_journal_entry(tx_id=303, marker="baseline-empty")
    base.record_merge_conflict_journal((seeded_entry,))

    with pytest.raises(
        ValueError,
        match=r"incoming merge content has no revisions or relations",
    ):
        base.merge_and_record_conflicts(KnowledgeStore())

    assert _journal_signature(base.merge_conflict_journal()) == _journal_signature(
        (seeded_entry,)
    )


def test_merge_and_record_conflicts_fails_closed_for_ambiguous_incoming_content() -> None:
    base = _build_store_with_known_tx_ids(304)
    seeded_entry = _seed_journal_entry(tx_id=304, marker="baseline-ambiguous")
    base.record_merge_conflict_journal((seeded_entry,))

    incoming = _build_incoming_ambiguous_tx_store(tx_left=501, tx_right=502)
    with pytest.raises(
        ValueError,
        match=r"incoming merge content is ambiguous across tx_ids",
    ):
        base.merge_and_record_conflicts(incoming)

    assert _journal_signature(base.merge_conflict_journal()) == _journal_signature(
        (seeded_entry,)
    )


def test_merge_and_record_conflicts_matches_manual_merge_plus_journal_append_semantics() -> None:
    manual_base = _build_store_with_known_tx_ids(880)
    api_base = _build_store_with_known_tx_ids(880)
    seeded_entry = _seed_journal_entry(tx_id=880, marker="manual-parity")
    manual_base.record_merge_conflict_journal((seeded_entry,))
    api_base.record_merge_conflict_journal((seeded_entry,))

    incoming = _build_incoming_single_tx_store(tx_id=611)

    manual_merge_result = manual_base.merge(incoming)
    manual_merge_result.merged.record_merge_conflict_journal(
        ((611, manual_merge_result),)
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
