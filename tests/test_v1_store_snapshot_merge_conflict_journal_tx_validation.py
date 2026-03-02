import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _build_store_with_known_journal_tx_ids(*tx_ids: int) -> KnowledgeStore:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    for index, tx_id in enumerate(sorted(set(tx_ids)), start=1):
        store.assert_revision(
            core=ClaimCore(
                claim_type="snapshot_merge_conflict_journal_tx_validation_seed",
                slots={"subject": f"snapshot-merge-journal-tx-known-{tx_id}"},
            ),
            assertion=f"snapshot merge journal tx known {tx_id}",
            valid_time=valid_time,
            transaction_time=TransactionTime(
                tx_id=tx_id,
                recorded_at=dt(2024, 1, index + 1),
            ),
            provenance=Provenance(
                source=f"source_snapshot_merge_conflict_journal_tx_validation_{tx_id}"
            ),
            confidence_bp=8000,
            status="asserted",
        )
    return store


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="snapshot-merge-journal-tx-validation-orphan-a",
        details="missing endpoint snapshot-merge-journal-tx-validation-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="snapshot-merge-journal-tx-validation-orphan-b",
        details="missing endpoint snapshot-merge-journal-tx-validation-orphan-b",
    )
    return (
        (9, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (7, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_b,))),
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
    snapshot_path = tmp_path / "snapshot-merge-journal-tx-validation.canonical.json"
    snapshot_path.write_text(canonical_json, encoding="utf-8")
    return KnowledgeStore.from_canonical_json_file(snapshot_path)


def _validate_store_payload_via_entrypoint(
    *,
    entrypoint: str,
    payload: dict[str, Any],
    tmp_path: Path,
):
    if entrypoint == "payload":
        return KnowledgeStore.validate_canonical_payload(payload)
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if entrypoint == "json":
        return KnowledgeStore.validate_canonical_json(canonical_json)
    snapshot_path = tmp_path / "validate-merge-journal-tx-validation.canonical.json"
    snapshot_path.write_text(canonical_json, encoding="utf-8")
    return KnowledgeStore.validate_canonical_json_file(snapshot_path)


def _build_unknown_tx_payload() -> tuple[dict[str, Any], str]:
    known_tx_ids = (7, 8, 9)
    unknown_tx_ids = (11,)
    store = _build_store_with_known_journal_tx_ids(*known_tx_ids)
    store.record_merge_conflict_journal(OneShotIterable(_build_merge_conflict_stream()))
    payload = copy.deepcopy(store.as_canonical_payload())
    payload["merge_conflict_journal"][0]["tx_id"] = unknown_tx_ids[0]
    expected_message = (
        "merge-conflict journal tx_id(s) are not present in store tx history: "
        f"{unknown_tx_ids}; known tx_ids: {known_tx_ids}"
    )
    return payload, expected_message


@pytest.mark.parametrize("entrypoint", ("payload", "json", "json_file"))
def test_store_snapshot_merge_conflict_journal_unknown_tx_rejected_for_all_load_entrypoints(
    entrypoint: str,
    tmp_path: Path,
) -> None:
    malformed_payload, expected_message = _build_unknown_tx_payload()

    with pytest.raises(SnapshotValidationError) as exc_info:
        _restore_store_via_entrypoint(
            entrypoint=entrypoint,
            payload=malformed_payload,
            tmp_path=tmp_path,
        )

    error = exc_info.value
    assert isinstance(error, ValueError)
    assert error.code == SnapshotValidationError.CODE_VALIDATION_FAILED
    assert error.path == "payload.merge_conflict_journal"
    assert error.message == expected_message
    assert str(error) == f"{error.path}: {expected_message}"


@pytest.mark.parametrize("entrypoint", ("payload", "json", "json_file"))
def test_store_snapshot_merge_conflict_journal_unknown_tx_preflight_parity(
    entrypoint: str,
    tmp_path: Path,
) -> None:
    malformed_payload, expected_message = _build_unknown_tx_payload()

    with pytest.raises(SnapshotValidationError) as load_exc_info:
        _restore_store_via_entrypoint(
            entrypoint=entrypoint,
            payload=malformed_payload,
            tmp_path=tmp_path,
        )
    with pytest.raises(SnapshotValidationError) as validate_exc_info:
        _validate_store_payload_via_entrypoint(
            entrypoint=entrypoint,
            payload=malformed_payload,
            tmp_path=tmp_path,
        )

    load_error = load_exc_info.value
    validate_error = validate_exc_info.value
    assert isinstance(load_error, ValueError)
    assert isinstance(validate_error, ValueError)
    assert load_error.code == validate_error.code
    assert load_error.path == validate_error.path
    assert load_error.message == validate_error.message
    assert load_error.as_dict() == validate_error.as_dict()
    assert load_error.message == expected_message
    assert load_error.path == "payload.merge_conflict_journal"


def test_store_snapshot_merge_conflict_journal_valid_restore_query_behavior_unchanged(
    tmp_path: Path,
) -> None:
    store = _build_store_with_known_journal_tx_ids(7, 8, 9)
    stream = _build_merge_conflict_stream()
    canonical_stream = _canonical_stream(stream)
    store.record_merge_conflict_journal(OneShotIterable(stream))
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    snapshot_path = tmp_path / "valid-merge-journal-tx-validation.canonical.json"
    store.to_canonical_json_file(snapshot_path)

    restored_payload = KnowledgeStore.from_canonical_payload(payload)
    restored_json = KnowledgeStore.from_canonical_json(canonical_json)
    restored_file = KnowledgeStore.from_canonical_json_file(snapshot_path)

    for restored in (restored_payload, restored_json, restored_file):
        assert restored.as_canonical_payload() == payload
        assert restored.as_canonical_json() == canonical_json
        restored_journal = restored.merge_conflict_journal()
        assert _journal_signature(restored_journal) == _journal_signature(canonical_stream)
        for tx_id in (6, 7, 8, 9, 10):
            assert restored.query_merge_conflict_projection_as_of_from_journal(
                tx_id=tx_id,
            ) == KnowledgeStore.query_merge_conflict_projection_as_of(
                canonical_stream,
                tx_id=tx_id,
            )

