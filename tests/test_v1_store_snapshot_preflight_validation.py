import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    SnapshotValidationError,
    SnapshotValidationReport,
    TransactionTime,
    ValidTime,
)

SnapshotPayloadMutation = Callable[[dict[str, Any]], None]


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _build_store_snapshot_fixture() -> KnowledgeStore:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    store = KnowledgeStore()

    core_anchor = ClaimCore(claim_type="document", slots={"id": "preflight-anchor"})
    core_subject = ClaimCore(claim_type="fact", slots={"id": "preflight-subject"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="preflight anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_preflight_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = store.assert_revision(
        core=core_subject,
        assertion="preflight subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_preflight_subject"),
        confidence_bp=8800,
        status="asserted",
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    return store


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


def _validate_payload_via_entrypoint(
    *,
    entrypoint: str,
    payload: dict[str, Any],
    tmp_path,
) -> SnapshotValidationReport:
    if entrypoint == "payload":
        return KnowledgeStore.validate_canonical_payload(payload)
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if entrypoint == "json":
        return KnowledgeStore.validate_canonical_json(canonical_json)
    snapshot_path = tmp_path / "snapshot.canonical.json"
    snapshot_path.write_text(canonical_json, encoding="utf-8")
    return KnowledgeStore.validate_canonical_json_file(snapshot_path)


def _expected_report_from_store(store: KnowledgeStore) -> SnapshotValidationReport:
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    return SnapshotValidationReport(
        schema_version=payload["snapshot_schema_version"],
        snapshot_checksum=payload["snapshot_checksum"],
        canonical_content_digest=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
    )


@pytest.mark.parametrize("entrypoint", ("payload", "json", "json_file"))
def test_store_snapshot_preflight_validation_success_matches_load_entrypoints(
    entrypoint: str,
    tmp_path,
) -> None:
    store = _build_store_snapshot_fixture()
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    expected_report = _expected_report_from_store(store)

    restored = _deserialize_payload_via_entrypoint(
        entrypoint=entrypoint,
        payload=payload,
        tmp_path=tmp_path,
    )
    report = _validate_payload_via_entrypoint(
        entrypoint=entrypoint,
        payload=payload,
        tmp_path=tmp_path,
    )

    assert restored.as_canonical_payload() == payload
    assert restored.as_canonical_json() == canonical_json
    assert report == expected_report
    assert report.as_dict() == {
        "schema_version": payload["snapshot_schema_version"],
        "snapshot_checksum": payload["snapshot_checksum"],
        "canonical_content_digest": hashlib.sha256(
            canonical_json.encode("utf-8")
        ).hexdigest(),
    }


def _set_schema_version_unsupported(payload: dict[str, Any]) -> None:
    payload["snapshot_schema_version"] = (
        KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION + 1
    )


def _remove_revisions(payload: dict[str, Any]) -> None:
    payload.pop("revisions")


def _set_cores_object(payload: dict[str, Any]) -> None:
    payload["cores"] = {}


def _tamper_snapshot_content(payload: dict[str, Any]) -> None:
    payload["cores"] = list(reversed(payload["cores"]))


_ERROR_CASES: tuple[tuple[str, SnapshotPayloadMutation], ...] = (
    ("schema_version", _set_schema_version_unsupported),
    ("strict_key_set", _remove_revisions),
    ("malformed_type", _set_cores_object),
    ("checksum_mismatch", _tamper_snapshot_content),
)


@pytest.mark.parametrize("entrypoint", ("payload", "json", "json_file"))
@pytest.mark.parametrize(
    ("case_id", "mutate"),
    _ERROR_CASES,
    ids=[case[0] for case in _ERROR_CASES],
)
def test_store_snapshot_preflight_validation_error_code_path_parity(
    entrypoint: str,
    case_id: str,
    mutate: SnapshotPayloadMutation,
    tmp_path,
) -> None:
    del case_id
    store = _build_store_snapshot_fixture()
    malformed_payload = copy.deepcopy(store.as_canonical_payload())
    mutate(malformed_payload)

    with pytest.raises(SnapshotValidationError) as load_exc_info:
        _deserialize_payload_via_entrypoint(
            entrypoint=entrypoint,
            payload=malformed_payload,
            tmp_path=tmp_path,
        )
    with pytest.raises(SnapshotValidationError) as validate_exc_info:
        _validate_payload_via_entrypoint(
            entrypoint=entrypoint,
            payload=malformed_payload,
            tmp_path=tmp_path,
        )

    load_error = load_exc_info.value
    validate_error = validate_exc_info.value
    assert isinstance(load_error, ValueError)
    assert isinstance(validate_error, ValueError)
    assert validate_error.code == load_error.code
    assert validate_error.path == load_error.path
    assert validate_error.message == load_error.message
    assert validate_error.as_dict() == load_error.as_dict()
    assert str(validate_error) == str(load_error)


def test_store_snapshot_preflight_validation_report_is_stable(tmp_path) -> None:
    store = _build_store_snapshot_fixture()
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    expected_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    report_payload_first = KnowledgeStore.validate_canonical_payload(payload)
    report_payload_second = KnowledgeStore.validate_canonical_payload(copy.deepcopy(payload))
    report_json = KnowledgeStore.validate_canonical_json(canonical_json)

    canonical_path = tmp_path / "stable.canonical.json"
    canonical_path.write_text(canonical_json, encoding="utf-8")
    report_file_first = KnowledgeStore.validate_canonical_json_file(canonical_path)
    report_file_second = KnowledgeStore.validate_canonical_json_file(canonical_path)

    assert report_payload_first == report_payload_second
    assert report_payload_first == report_json
    assert report_payload_first == report_file_first
    assert report_file_first == report_file_second
    assert report_payload_first.schema_version == payload["snapshot_schema_version"]
    assert report_payload_first.snapshot_checksum == payload["snapshot_checksum"]
    assert report_payload_first.canonical_content_digest == expected_digest
    assert report_payload_first.as_dict() == {
        "schema_version": payload["snapshot_schema_version"],
        "snapshot_checksum": payload["snapshot_checksum"],
        "canonical_content_digest": expected_digest,
    }
