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
SnapshotReferentialIntegrityParityCase = tuple[str, SnapshotPayloadMutation, str, str]

_MISSING_ACTIVE_ENDPOINT = "missing-referential-integrity-active-endpoint-parity"
_MISSING_VARIANT_ENDPOINT = "missing-referential-integrity-variant-endpoint-parity"


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _build_store_snapshot_fixture() -> tuple[KnowledgeStore, datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 2
    tx_to = 4

    store = KnowledgeStore()
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": "referential-integrity-parity-anchor"},
    )
    core_subject = ClaimCore(claim_type="fact", slots={"id": "referential-integrity-parity-subject"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="referential integrity parity anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_referential_integrity_parity_anchor"),
        confidence_bp=9200,
        status="asserted",
    )
    subject_revision = store.assert_revision(
        core=core_subject,
        assertion="referential integrity parity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_referential_integrity_parity_subject"),
        confidence_bp=8800,
        status="asserted",
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    store.assert_revision(
        core=core_subject,
        assertion="referential integrity parity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_referential_integrity_parity_subject_retracted"),
        confidence_bp=8800,
        status="retracted",
    )
    store = KnowledgeStore().merge(store).merged
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


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _deserialize_payload_via_entrypoint(
    *,
    entrypoint: str,
    payload: dict[str, Any],
    tmp_path,
) -> KnowledgeStore:
    if entrypoint == "payload":
        return KnowledgeStore.from_canonical_payload(payload)
    canonical_json = _canonical_json(payload)
    if entrypoint == "json":
        return KnowledgeStore.from_canonical_json(canonical_json)
    snapshot_path = tmp_path / "snapshot.referential-integrity-parity.canonical.json"
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
    canonical_json = _canonical_json(payload)
    if entrypoint == "json":
        return KnowledgeStore.validate_canonical_json(canonical_json)
    snapshot_path = tmp_path / "snapshot.referential-integrity-parity.canonical.json"
    snapshot_path.write_text(canonical_json, encoding="utf-8")
    return KnowledgeStore.validate_canonical_json_file(snapshot_path)


def _capture_load_error(
    *,
    entrypoint: str,
    payload: dict[str, Any],
    tmp_path,
) -> SnapshotValidationError:
    with pytest.raises(SnapshotValidationError) as exc_info:
        _deserialize_payload_via_entrypoint(
            entrypoint=entrypoint,
            payload=payload,
            tmp_path=tmp_path,
        )
    return exc_info.value


def _capture_validate_error(
    *,
    entrypoint: str,
    payload: dict[str, Any],
    tmp_path,
) -> SnapshotValidationError:
    with pytest.raises(SnapshotValidationError) as exc_info:
        _validate_payload_via_entrypoint(
            entrypoint=entrypoint,
            payload=payload,
            tmp_path=tmp_path,
        )
    return exc_info.value


def _remove_referenced_core(payload: dict[str, Any]) -> None:
    referenced_core_id = payload["revisions"][0]["core_id"]
    payload["cores"] = [
        core for core in payload["cores"] if core["core_id"] != referenced_core_id
    ]


def _set_active_relation_endpoint_missing(payload: dict[str, Any]) -> None:
    payload["active_relations"][0]["to_revision_id"] = _MISSING_ACTIVE_ENDPOINT


def _set_active_relation_variant_endpoint_missing(payload: dict[str, Any]) -> None:
    payload["relation_variants"][0]["variants"][0]["relation"]["to_revision_id"] = (
        _MISSING_VARIANT_ENDPOINT
    )
    payload["relation_variants"][0]["variants"][0]["relation_key"]["to_revision_id"] = (
        _MISSING_VARIANT_ENDPOINT
    )


_ERROR_PARITY_CASES: tuple[SnapshotReferentialIntegrityParityCase, ...] = (
    (
        "revision_core_reference_missing",
        _remove_referenced_core,
        SnapshotValidationError.CODE_VALIDATION_FAILED,
        "payload.revisions[0].core_id",
    ),
    (
        "active_relation_endpoint_missing",
        _set_active_relation_endpoint_missing,
        SnapshotValidationError.CODE_VALIDATION_FAILED,
        "payload.active_relations[0]",
    ),
    (
        "active_relation_variant_endpoint_missing",
        _set_active_relation_variant_endpoint_missing,
        SnapshotValidationError.CODE_VALIDATION_FAILED,
        "payload.relation_variants[0].variants[0].relation",
    ),
)


@pytest.mark.parametrize(
    ("case_id", "mutate", "expected_code", "expected_path"),
    _ERROR_PARITY_CASES,
    ids=[case[0] for case in _ERROR_PARITY_CASES],
)
def test_store_snapshot_referential_integrity_error_parity_across_entrypoints(
    tmp_path,
    case_id: str,
    mutate: SnapshotPayloadMutation,
    expected_code: str,
    expected_path: str,
) -> None:
    del case_id
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_fixture()
    malformed_payload = copy.deepcopy(store.as_canonical_payload())
    mutate(malformed_payload)

    load_errors = {
        entrypoint: _capture_load_error(
            entrypoint=entrypoint,
            payload=copy.deepcopy(malformed_payload),
            tmp_path=tmp_path,
        )
        for entrypoint in ("payload", "json", "json_file")
    }
    validate_errors = {
        entrypoint: _capture_validate_error(
            entrypoint=entrypoint,
            payload=copy.deepcopy(malformed_payload),
            tmp_path=tmp_path,
        )
        for entrypoint in ("payload", "json", "json_file")
    }

    assert all(isinstance(error, ValueError) for error in load_errors.values())
    assert all(isinstance(error, ValueError) for error in validate_errors.values())

    for entrypoint in ("payload", "json", "json_file"):
        load_error = load_errors[entrypoint]
        validate_error = validate_errors[entrypoint]
        assert (load_error.code, load_error.path) == (expected_code, expected_path)
        assert (validate_error.code, validate_error.path) == (expected_code, expected_path)
        assert validate_error.code == load_error.code
        assert validate_error.path == load_error.path

    assert load_errors["payload"].code == load_errors["json"].code == load_errors["json_file"].code
    assert load_errors["payload"].path == load_errors["json"].path == load_errors["json_file"].path
    assert (
        validate_errors["payload"].code
        == validate_errors["json"].code
        == validate_errors["json_file"].code
    )
    assert (
        validate_errors["payload"].path
        == validate_errors["json"].path
        == validate_errors["json_file"].path
    )


def test_store_snapshot_referential_integrity_parity_valid_restore_semantics(
    tmp_path,
) -> None:
    store, valid_at, tx_from, tx_to, core_id = _build_store_snapshot_fixture()
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    expected_signature = _query_signature(
        store,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    )
    expected_report = SnapshotValidationReport(
        schema_version=payload["snapshot_schema_version"],
        snapshot_checksum=payload["snapshot_checksum"],
        canonical_content_digest=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
    )

    restored_from_payload = _deserialize_payload_via_entrypoint(
        entrypoint="payload",
        payload=copy.deepcopy(payload),
        tmp_path=tmp_path,
    )
    restored_from_json = _deserialize_payload_via_entrypoint(
        entrypoint="json",
        payload=copy.deepcopy(payload),
        tmp_path=tmp_path,
    )
    restored_from_file = _deserialize_payload_via_entrypoint(
        entrypoint="json_file",
        payload=copy.deepcopy(payload),
        tmp_path=tmp_path,
    )

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

    report_payload = _validate_payload_via_entrypoint(
        entrypoint="payload",
        payload=copy.deepcopy(payload),
        tmp_path=tmp_path,
    )
    report_json = _validate_payload_via_entrypoint(
        entrypoint="json",
        payload=copy.deepcopy(payload),
        tmp_path=tmp_path,
    )
    report_file = _validate_payload_via_entrypoint(
        entrypoint="json_file",
        payload=copy.deepcopy(payload),
        tmp_path=tmp_path,
    )

    assert report_payload == expected_report
    assert report_json == expected_report
    assert report_file == expected_report
