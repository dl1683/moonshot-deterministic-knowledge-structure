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


def _build_store_with_known_tx_ids(*tx_ids: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    for index, tx_id in enumerate(sorted(set(tx_ids)), start=1):
        store.assert_revision(
            core=ClaimCore(
                claim_type="merge_conflict_journal_tx_consistency_seed",
                slots={"subject": f"journal-tx-consistency-known-tx-{tx_id}"},
            ),
            assertion=f"journal-tx-consistency known tx {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 1, index + 1),
            ),
            provenance=Provenance(source=f"source_journal_tx_consistency_{tx_id}"),
            confidence_bp=8000,
            status="asserted",
        )
    return store


def _build_incoming_single_tx_store(*, tx_id: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    revision = store.assert_revision(
        core=ClaimCore(
            claim_type="residence",
            slots={"subject": f"journal-tx-consistency-single-tx-{tx_id}"},
        ),
        assertion=f"journal-tx-consistency revision {tx_id}",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_id, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source=f"source_journal_tx_consistency_single_{tx_id}"),
        confidence_bp=8500,
        status="asserted",
    )
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=revision.revision_id,
        to_revision_id=f"missing-journal-tx-consistency-endpoint-{tx_id}",
        transaction_time=TransactionTime(tx_id=tx_id, recorded_at=dt(2024, 1, 3)),
    )
    store.relations[orphan_relation.relation_id] = orphan_relation
    return store


def _seed_journal_entry(*, tx_id: int, marker: str) -> tuple[int, MergeResult]:
    conflict = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id=f"journal-tx-consistency-seed-{marker}",
        details=f"journal-tx-consistency seeded conflict {marker}",
    )
    return (
        tx_id,
        MergeResult(merged=KnowledgeStore(), conflicts=(conflict,)),
    )


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


def test_merge_and_record_conflicts_accepts_matching_explicit_tx_id_for_unique_derivation() -> None:
    base = _build_store_with_known_tx_ids(700, 701)
    seeded_entry = _seed_journal_entry(tx_id=700, marker="match-success")
    base.record_merge_conflict_journal((seeded_entry,))

    incoming = _build_incoming_single_tx_store(tx_id=701)
    merge_result = base.merge_and_record_conflicts(incoming, journal_tx_id=701)

    assert _journal_signature(merge_result.merged.merge_conflict_journal()) == _journal_signature(
        (seeded_entry, (701, merge_result))
    )


def test_merge_and_record_conflicts_rejects_mismatched_explicit_tx_id_for_unique_derivation() -> None:
    base = _build_store_with_known_tx_ids(700, 701, 702)
    seeded_entry = _seed_journal_entry(tx_id=700, marker="mismatch-baseline")
    base.record_merge_conflict_journal((seeded_entry,))

    incoming = _build_incoming_single_tx_store(tx_id=701)
    with pytest.raises(
        ValueError,
        match=(
            r"merge-conflict journal_tx_id override must match derived tx_id "
            r"from incoming merge content when derivation is unambiguous: "
            r"journal_tx_id=702, derived_tx_id=701"
        ),
    ):
        base.merge_and_record_conflicts(incoming, journal_tx_id=702)

    assert _journal_signature(base.merge_conflict_journal()) == _journal_signature(
        (seeded_entry,)
    )


def test_merge_and_record_conflicts_matching_explicit_tx_id_keeps_manual_append_parity() -> None:
    manual_base = _build_store_with_known_tx_ids(880, 611)
    api_base = _build_store_with_known_tx_ids(880, 611)
    seeded_entry = _seed_journal_entry(tx_id=880, marker="manual-parity")
    manual_base.record_merge_conflict_journal((seeded_entry,))
    api_base.record_merge_conflict_journal((seeded_entry,))

    incoming = _build_incoming_single_tx_store(tx_id=611)
    manual_merge_result = manual_base.merge(incoming)
    manual_merge_result.merged.record_merge_conflict_journal(
        ((611, manual_merge_result),)
    )

    api_merge_result = api_base.merge_and_record_conflicts(
        incoming,
        journal_tx_id=611,
    )

    assert api_merge_result.conflicts == manual_merge_result.conflicts
    assert (
        api_merge_result.merged.as_canonical_json()
        == manual_merge_result.merged.as_canonical_json()
    )
    assert _journal_signature(
        api_merge_result.merged.merge_conflict_journal()
    ) == _journal_signature(manual_merge_result.merged.merge_conflict_journal())
