import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    SnapshotValidationError,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _build_store_snapshot_integrity_fixture() -> tuple[KnowledgeStore, datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 1
    tx_to = 3

    core_anchor = ClaimCore(claim_type="document", slots={"id": "integrity-anchor"})
    core_subject = ClaimCore(claim_type="fact", slots={"id": "integrity-subject"})

    store = KnowledgeStore()
    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="integrity anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_integrity_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = store.assert_revision(
        core=core_subject,
        assertion="integrity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_integrity_subject"),
        confidence_bp=8800,
        status="asserted",
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    return store, valid_at, tx_from, tx_to, core_subject.core_id


def _query_signature(
    store: KnowledgeStore,
    *,
    valid_at: datetime,
    tx_from: int,
    tx_to: int,
    core_id: str,
) -> tuple[Any, ...]:
    as_of_global = store.query_state_fingerprint_as_of(tx_id=tx_to, valid_at=valid_at)
    as_of_filtered = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    window_filtered = store.query_state_fingerprint_for_tx_window(
        tx_start=0,
        tx_end=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    transition_filtered = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    winner = store.query_as_of(core_id, valid_at=valid_at, tx_id=tx_to)
    return (
        store.revision_state_signatures(),
        store.relation_state_signatures(),
        store.pending_relation_ids(),
        tuple(relation.relation_id for relation in store.query_relations_as_of(tx_id=tx_to)),
        tuple(
            relation.relation_id
            for relation in store.query_pending_relations_as_of(tx_id=tx_to)
        ),
        winner.revision_id if winner is not None else None,
        as_of_global.as_canonical_json(),
        as_of_filtered.as_canonical_json(),
        window_filtered.as_canonical_json(),
        transition_filtered.as_canonical_json(),
    )


def _deserialize_payload_via_entrypoint(
    *,
    entrypoint: str,
    payload: dict[str, Any],
    tmp_path,
) -> KnowledgeStore:
    if entrypoint == "payload":
        return KnowledgeStore.from_canonical_payload(payload)
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if entrypoint == "json":
        return KnowledgeStore.from_canonical_json(canonical_json)
    snapshot_path = tmp_path / "snapshot.canonical.json"
    snapshot_path.write_text(canonical_json, encoding="utf-8")
    return KnowledgeStore.from_canonical_json_file(snapshot_path)


def test_store_snapshot_checksum_round_trip_payload_json_and_query_parity(
    tmp_path,
) -> None:
    store, valid_at, tx_from, tx_to, core_id = _build_store_snapshot_integrity_fixture()
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    expected_signature = _query_signature(
        store,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    )

    snapshot_checksum = payload["snapshot_checksum"]
    assert isinstance(snapshot_checksum, str)
    assert len(snapshot_checksum) == 64
    assert all(ch in "0123456789abcdef" for ch in snapshot_checksum)

    payload_without_checksum = copy.deepcopy(payload)
    payload_without_checksum.pop("snapshot_checksum")
    expected_checksum = hashlib.sha256(
        json.dumps(payload_without_checksum, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert snapshot_checksum == expected_checksum
    assert canonical_json == json.dumps(payload, sort_keys=True, separators=(",", ":"))

    restored_from_payload = KnowledgeStore.from_canonical_payload(payload)
    restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)

    canonical_path = tmp_path / "valid.canonical.json"
    canonical_path.write_text(canonical_json, encoding="utf-8")
    restored_from_file = KnowledgeStore.from_canonical_json_file(canonical_path)

    assert restored_from_payload.as_canonical_payload() == payload
    assert restored_from_payload.as_canonical_json() == canonical_json
    assert restored_from_json.as_canonical_payload() == payload
    assert restored_from_json.as_canonical_json() == canonical_json
    assert restored_from_file.as_canonical_payload() == payload
    assert restored_from_file.as_canonical_json() == canonical_json

    assert _query_signature(
        restored_from_payload,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    ) == expected_signature
    assert _query_signature(
        restored_from_json,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    ) == expected_signature
    assert _query_signature(
        restored_from_file,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    ) == expected_signature


@pytest.mark.parametrize("entrypoint", ("payload", "json", "json_file"))
def test_store_snapshot_checksum_rejects_tampered_payload(entrypoint: str, tmp_path) -> None:
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_integrity_fixture()
    tampered_payload = copy.deepcopy(store.as_canonical_payload())
    tampered_payload["cores"] = list(reversed(tampered_payload["cores"]))

    with pytest.raises(SnapshotValidationError) as exc_info:
        _deserialize_payload_via_entrypoint(
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


@pytest.mark.parametrize("entrypoint", ("payload", "json", "json_file"))
def test_store_snapshot_checksum_missing_key_is_rejected(entrypoint: str, tmp_path) -> None:
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_integrity_fixture()
    missing_checksum_payload = copy.deepcopy(store.as_canonical_payload())
    missing_checksum_payload.pop("snapshot_checksum")

    with pytest.raises(SnapshotValidationError) as exc_info:
        _deserialize_payload_via_entrypoint(
            entrypoint=entrypoint,
            payload=missing_checksum_payload,
            tmp_path=tmp_path,
        )

    error = exc_info.value
    assert error.code == SnapshotValidationError.CODE_STRICT_KEY_SET
    assert error.path == "payload"
    assert error.message == "missing keys ['snapshot_checksum']"
