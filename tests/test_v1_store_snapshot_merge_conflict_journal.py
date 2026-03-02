import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    MergeConflict,
    MergeResult,
    Provenance,
    SnapshotValidationError,
    TransactionTime,
    ValidTime,
)

SnapshotPayloadMutation = Callable[[dict[str, Any]], None]
SnapshotPayloadMutationCase = tuple[str, SnapshotPayloadMutation, str]


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
        entity_id="snapshot-merge-journal-orphan-a",
        details="missing endpoint snapshot-merge-journal-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="snapshot-merge-journal-orphan-b",
        details="missing endpoint snapshot-merge-journal-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="snapshot-merge-journal-competing",
        details="competing revisions snapshot-merge-journal-competing",
    )
    lifecycle = MergeConflict(
        code=ConflictCode.COMPETING_LIFECYCLE_SAME_SLOT,
        entity_id="snapshot-merge-journal-lifecycle",
        details="competing lifecycle snapshot-merge-journal-lifecycle",
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
        entity_id="snapshot-merge-journal-orphan-c",
        details="missing endpoint snapshot-merge-journal-orphan-c",
    )
    competing_followup = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="snapshot-merge-journal-competing-followup",
        details="competing revisions snapshot-merge-journal-competing-followup",
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


def _build_store_with_known_journal_tx_ids() -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    for index, tx_id in enumerate((7, 8, 9, 10, 11, 12), start=1):
        store.assert_revision(
            core=ClaimCore(
                claim_type="snapshot_merge_conflict_journal_seed",
                slots={"subject": f"snapshot-merge-journal-known-tx-{tx_id}"},
            ),
            assertion=f"snapshot-merge-journal known tx {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 1, index + 1),
            ),
            provenance=Provenance(
                source=f"source_snapshot_merge_conflict_journal_known_tx_{tx_id}"
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
        slots={"subject": "snapshot-merge-journal-subject"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": "snapshot-merge-journal-anchor"},
    )

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="snapshot merge journal anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_snapshot_merge_journal_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision_a = store.assert_revision(
        core=core_subject,
        assertion="snapshot merge journal subject A",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_snapshot_merge_journal_subject_a"),
        confidence_bp=8400,
        status="asserted",
    )
    subject_revision_b = store.assert_revision(
        core=core_subject,
        assertion="snapshot merge journal subject B",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_snapshot_merge_journal_subject_b"),
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
                claim_type="snapshot_merge_conflict_journal_state_seed",
                slots={"subject": f"snapshot-merge-journal-state-known-tx-{tx_id}"},
            ),
            assertion=f"snapshot-merge-journal state known tx {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 2, index),
            ),
            provenance=Provenance(
                source=(
                    "source_snapshot_merge_conflict_journal_state_known_tx_"
                    f"{tx_id}"
                )
            ),
            confidence_bp=7800,
            status="asserted",
        )

    return store, valid_at, tx_from, tx_to


def _restore_store_via_entrypoint(
    *,
    entrypoint: str,
    payload: dict[str, Any],
    tmp_path: Path,
) -> KnowledgeStore:
    if entrypoint == "payload":
        return KnowledgeStore.from_canonical_payload(payload)
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if entrypoint == "json":
        return KnowledgeStore.from_canonical_json(canonical_json)
    snapshot_path = tmp_path / "snapshot-merge-journal.canonical.json"
    snapshot_path.write_text(canonical_json, encoding="utf-8")
    return KnowledgeStore.from_canonical_json_file(snapshot_path)


def _set_merge_conflict_journal_object(payload: dict[str, Any]) -> None:
    payload["merge_conflict_journal"] = {}


def _set_merge_conflict_journal_entry_scalar(payload: dict[str, Any]) -> None:
    payload["merge_conflict_journal"][0] = "journal-entry"


def _drop_merge_conflict_journal_entry_merge_result(payload: dict[str, Any]) -> None:
    payload["merge_conflict_journal"][0].pop("merge_result")


def _set_merge_conflict_journal_conflicts_object(payload: dict[str, Any]) -> None:
    payload["merge_conflict_journal"][0]["merge_result"]["conflicts"] = {
        "conflicts": payload["merge_conflict_journal"][0]["merge_result"]["conflicts"]
    }


def _set_merge_conflict_journal_conflict_code_unknown(payload: dict[str, Any]) -> None:
    payload["merge_conflict_journal"][0]["merge_result"]["conflicts"][0][
        "code"
    ] = "unknown_merge_conflict_code"


_MALFORMED_SNAPSHOT_PAYLOAD_CASES: tuple[SnapshotPayloadMutationCase, ...] = (
    (
        "merge_conflict_journal_object",
        _set_merge_conflict_journal_object,
        r"payload\.merge_conflict_journal: expected array, got dict",
    ),
    (
        "merge_conflict_journal_entry_scalar",
        _set_merge_conflict_journal_entry_scalar,
        r"payload\.merge_conflict_journal\[0\]: expected object, got str",
    ),
    (
        "merge_conflict_journal_entry_missing_merge_result",
        _drop_merge_conflict_journal_entry_merge_result,
        r"payload\.merge_conflict_journal\[0\]: missing keys \['merge_result'\]",
    ),
    (
        "merge_conflict_journal_conflicts_object",
        _set_merge_conflict_journal_conflicts_object,
        (
            r"payload\.merge_conflict_journal\[0\]\.merge_result\.conflicts: "
            r"expected array, got dict"
        ),
    ),
    (
        "merge_conflict_journal_conflict_unknown_code",
        _set_merge_conflict_journal_conflict_code_unknown,
        (
            r"payload\.merge_conflict_journal\[0\]\.merge_result\.conflicts\[0\]\.code: "
            r"unsupported conflict code 'unknown_merge_conflict_code'"
        ),
    ),
)


def test_store_snapshot_merge_conflict_journal_round_trip_payload_json_file_parity(
    tmp_path: Path,
) -> None:
    store = _build_store_with_known_journal_tx_ids()
    initial_stream = _build_merge_conflict_stream()
    continuation_stream = _build_merge_conflict_continuation_stream()
    expected_stream = _canonical_stream(initial_stream + continuation_stream)

    store.record_merge_conflict_journal(OneShotIterable(initial_stream))
    store.record_merge_conflict_journal(OneShotIterable(continuation_stream))

    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    snapshot_path = tmp_path / "round-trip-merge-conflict-journal.canonical.json"
    store.to_canonical_json_file(snapshot_path)

    assert payload["merge_conflict_journal"]
    assert _journal_signature(store.merge_conflict_journal()) == _journal_signature(
        expected_stream
    )

    restored_payload = KnowledgeStore.from_canonical_payload(payload)
    restored_json = KnowledgeStore.from_canonical_json(canonical_json)
    restored_file = KnowledgeStore.from_canonical_json_file(snapshot_path)

    for restored in (restored_payload, restored_json, restored_file):
        assert restored.as_canonical_payload() == payload
        assert restored.as_canonical_json() == canonical_json
        assert _journal_signature(restored.merge_conflict_journal()) == _journal_signature(
            store.merge_conflict_journal()
        )
        for tx_id in (6, 7, 8, 9, 10, 11, 12, 13):
            assert KnowledgeStore.query_merge_conflict_projection_as_of(
                restored.merge_conflict_journal(),
                tx_id=tx_id,
            ) == KnowledgeStore.query_merge_conflict_projection_as_of(
                store.merge_conflict_journal(),
                tx_id=tx_id,
            )


@pytest.mark.parametrize("entrypoint", ("payload", "json", "json_file"))
@pytest.mark.parametrize(
    ("case_id", "mutate_payload", "error_pattern"),
    _MALFORMED_SNAPSHOT_PAYLOAD_CASES,
    ids=[case[0] for case in _MALFORMED_SNAPSHOT_PAYLOAD_CASES],
)
def test_store_snapshot_merge_conflict_journal_rejects_malformed_payloads(
    entrypoint: str,
    case_id: str,
    mutate_payload: SnapshotPayloadMutation,
    error_pattern: str,
    tmp_path: Path,
) -> None:
    del case_id
    store = _build_store_with_known_journal_tx_ids()
    store.record_merge_conflict_journal(OneShotIterable(_build_merge_conflict_stream()))
    malformed_payload = copy.deepcopy(store.as_canonical_payload())
    mutate_payload(malformed_payload)

    with pytest.raises(ValueError, match=error_pattern):
        _restore_store_via_entrypoint(
            entrypoint=entrypoint,
            payload=malformed_payload,
            tmp_path=tmp_path,
        )


@pytest.mark.parametrize("entrypoint", ("payload", "json", "json_file"))
def test_store_snapshot_merge_conflict_journal_rejects_tampered_checksum_payloads(
    entrypoint: str,
    tmp_path: Path,
) -> None:
    store = _build_store_with_known_journal_tx_ids()
    store.record_merge_conflict_journal(OneShotIterable(_build_merge_conflict_stream()))
    tampered_payload = copy.deepcopy(store.as_canonical_payload())
    tampered_payload["merge_conflict_journal"][0]["merge_result"]["conflicts"][0][
        "details"
    ] = "tampered-merge-conflict-details"

    with pytest.raises(SnapshotValidationError) as exc_info:
        _restore_store_via_entrypoint(
            entrypoint=entrypoint,
            payload=tampered_payload,
            tmp_path=tmp_path,
        )

    error = exc_info.value
    assert error.code == SnapshotValidationError.CODE_NON_CANONICAL
    assert error.path == "payload.snapshot_checksum"
    assert (
        error.message
        == "does not match canonical deterministic knowledge store snapshot checksum"
    )


def test_store_snapshot_merge_conflict_journal_restored_parity_with_in_memory_state(
    tmp_path: Path,
) -> None:
    store, valid_at, tx_from, tx_to = _build_state_fingerprint_store()
    stream = _build_merge_conflict_stream()
    canonical_stream = _canonical_stream(stream)

    store.record_merge_conflict_journal(OneShotIterable(stream))
    expected_journal_signature = _journal_signature(store.merge_conflict_journal())
    assert expected_journal_signature == _journal_signature(canonical_stream)

    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    snapshot_path = tmp_path / "state-parity-merge-conflict-journal.canonical.json"
    store.to_canonical_json_file(snapshot_path)

    restored_payload = KnowledgeStore.from_canonical_payload(payload)
    restored_json = KnowledgeStore.from_canonical_json(canonical_json)
    restored_file = KnowledgeStore.from_canonical_json_file(snapshot_path)

    for restored in (restored_payload, restored_json, restored_file):
        journal_stream = restored.merge_conflict_journal()
        assert _journal_signature(journal_stream) == expected_journal_signature
        for tx_id in (1, 2, 3, 4, 5, 6):
            assert restored.query_state_fingerprint_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                merge_results_by_tx=journal_stream,
            ) == store.query_state_fingerprint_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                merge_results_by_tx=store.merge_conflict_journal(),
            )
        assert restored.query_state_fingerprint_for_tx_window(
            tx_start=tx_from,
            tx_end=tx_to,
            valid_at=valid_at,
            merge_results_by_tx=journal_stream,
        ) == store.query_state_fingerprint_for_tx_window(
            tx_start=tx_from,
            tx_end=tx_to,
            valid_at=valid_at,
            merge_results_by_tx=store.merge_conflict_journal(),
        )
        assert restored.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            merge_results_by_tx=journal_stream,
        ) == store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            merge_results_by_tx=store.merge_conflict_journal(),
        )
