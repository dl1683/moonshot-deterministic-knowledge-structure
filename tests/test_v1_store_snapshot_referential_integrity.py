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
SnapshotReferentialIntegrityCase = tuple[str, SnapshotPayloadMutation, str, str, str]

_MISSING_ACTIVE_ENDPOINT = "missing-referential-integrity-active-endpoint"
_MISSING_VARIANT_ENDPOINT = "missing-referential-integrity-variant-endpoint"


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _build_store_snapshot_fixture() -> tuple[KnowledgeStore, datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 2
    tx_to = 4

    store = KnowledgeStore()
    core_anchor = ClaimCore(claim_type="document", slots={"id": "referential-integrity-anchor"})
    core_subject = ClaimCore(claim_type="fact", slots={"id": "referential-integrity-subject"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="referential integrity anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_referential_integrity_anchor"),
        confidence_bp=9200,
        status="asserted",
    )
    subject_revision = store.assert_revision(
        core=core_subject,
        assertion="referential integrity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_referential_integrity_subject"),
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
        assertion="referential integrity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_referential_integrity_subject_retracted"),
        confidence_bp=8800,
        status="retracted",
    )
    # Canonical snapshot variants/collision metadata are populated through merge routing.
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


def _snapshot_route(
    *,
    entrypoint: str,
    payload: dict[str, Any],
    tmp_path,
) -> Any:
    if entrypoint == "from_payload":
        return KnowledgeStore.from_canonical_payload(payload)
    if entrypoint == "validate_payload":
        return KnowledgeStore.validate_canonical_payload(payload)

    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if entrypoint == "from_json":
        return KnowledgeStore.from_canonical_json(canonical_json)
    if entrypoint == "validate_json":
        return KnowledgeStore.validate_canonical_json(canonical_json)

    snapshot_path = tmp_path / f"{entrypoint}.canonical.json"
    snapshot_path.write_text(canonical_json, encoding="utf-8")
    if entrypoint == "from_json_file":
        return KnowledgeStore.from_canonical_json_file(snapshot_path)
    if entrypoint == "validate_json_file":
        return KnowledgeStore.validate_canonical_json_file(snapshot_path)
    raise AssertionError(f"unsupported entrypoint {entrypoint!r}")


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


_ERROR_CASES: tuple[SnapshotReferentialIntegrityCase, ...] = (
    (
        "revision_core_reference_missing",
        _remove_referenced_core,
        SnapshotValidationError.CODE_VALIDATION_FAILED,
        "payload.revisions[0].core_id",
        "unknown core_id ",
    ),
    (
        "active_relation_endpoint_missing",
        _set_active_relation_endpoint_missing,
        SnapshotValidationError.CODE_VALIDATION_FAILED,
        "payload.active_relations[0]",
        (
            "active relation references missing revision endpoints: "
            f"{_MISSING_ACTIVE_ENDPOINT}"
        ),
    ),
    (
        "active_relation_variant_endpoint_missing",
        _set_active_relation_variant_endpoint_missing,
        SnapshotValidationError.CODE_VALIDATION_FAILED,
        "payload.relation_variants[0].variants[0].relation",
        (
            "relation variant references missing revision endpoints: "
            f"{_MISSING_VARIANT_ENDPOINT}"
        ),
    ),
)


@pytest.mark.parametrize(
    "entrypoint",
    (
        "from_payload",
        "from_json",
        "from_json_file",
        "validate_payload",
        "validate_json",
        "validate_json_file",
    ),
)
@pytest.mark.parametrize(
    ("case_id", "mutate", "expected_code", "expected_path", "expected_message"),
    _ERROR_CASES,
    ids=[case[0] for case in _ERROR_CASES],
)
def test_store_snapshot_referential_integrity_rejects_dangling_references(
    entrypoint: str,
    case_id: str,
    mutate: SnapshotPayloadMutation,
    expected_code: str,
    expected_path: str,
    expected_message: str,
    tmp_path,
) -> None:
    del case_id
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_fixture()
    malformed_payload = copy.deepcopy(store.as_canonical_payload())
    mutate(malformed_payload)

    with pytest.raises(SnapshotValidationError) as exc_info:
        _snapshot_route(
            entrypoint=entrypoint,
            payload=malformed_payload,
            tmp_path=tmp_path,
        )

    error = exc_info.value
    assert isinstance(error, ValueError)
    assert error.code == expected_code
    assert error.path == expected_path
    assert error.message.startswith(expected_message)
    assert error.as_dict() == {
        "code": expected_code,
        "path": expected_path,
        "message": error.message,
    }
    assert str(error) == f"{expected_path}: {error.message}"


def test_store_snapshot_referential_integrity_valid_round_trip_and_query_parity(
    tmp_path,
) -> None:
    store, valid_at, tx_from, tx_to, core_id = _build_store_snapshot_fixture()
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    expected_query_signature = _query_signature(
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

    restored_from_payload = KnowledgeStore.from_canonical_payload(copy.deepcopy(payload))
    restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)
    canonical_path = tmp_path / "valid.canonical.json"
    canonical_path.write_text(canonical_json, encoding="utf-8")
    restored_from_file = KnowledgeStore.from_canonical_json_file(canonical_path)

    validated_from_payload = KnowledgeStore.validate_canonical_payload(copy.deepcopy(payload))
    validated_from_json = KnowledgeStore.validate_canonical_json(canonical_json)
    validated_from_file = KnowledgeStore.validate_canonical_json_file(canonical_path)

    assert restored_from_payload.as_canonical_payload() == payload
    assert restored_from_payload.as_canonical_json() == canonical_json
    assert restored_from_json.as_canonical_payload() == payload
    assert restored_from_json.as_canonical_json() == canonical_json
    assert restored_from_file.as_canonical_payload() == payload
    assert restored_from_file.as_canonical_json() == canonical_json

    assert validated_from_payload == expected_report
    assert validated_from_json == expected_report
    assert validated_from_file == expected_report

    assert _query_signature(
        restored_from_payload,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    ) == expected_query_signature
    assert _query_signature(
        restored_from_json,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    ) == expected_query_signature
    assert _query_signature(
        restored_from_file,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    ) == expected_query_signature
