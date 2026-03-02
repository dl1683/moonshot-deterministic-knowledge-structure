import copy
import json
from datetime import datetime, timezone
from typing import Any, Callable

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    SnapshotValidationError,
    TransactionTime,
    ValidTime,
)

SnapshotPayloadMutation = Callable[[dict[str, Any]], None]
SnapshotValidationErrorParityCase = tuple[str, SnapshotPayloadMutation, str, str]


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _force_relation_id(edge: RelationEdge, relation_id: str) -> RelationEdge:
    object.__setattr__(edge, "relation_id", relation_id)
    return edge


def _build_store_snapshot_fixture() -> tuple[KnowledgeStore, datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 4
    tx_to = 7

    core_anchor = ClaimCore(claim_type="document", slots={"id": "validation-parity-anchor"})
    core_subject = ClaimCore(claim_type="fact", slots={"id": "validation-parity-subject"})

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="validation parity anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_validation_parity_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="validation parity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_validation_parity_subject"),
        confidence_bp=8800,
        status="asserted",
    )
    canonical_relation = replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    replica_base.assert_revision(
        core=core_subject,
        assertion="validation parity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_validation_parity_subject_retracted"),
        confidence_bp=8800,
        status="retracted",
    )

    replica_collision = KnowledgeStore()
    collision_anchor_revision = replica_collision.assert_revision(
        core=core_anchor,
        assertion="validation parity anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_validation_parity_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="validation parity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_validation_parity_subject"),
        confidence_bp=8800,
        status="asserted",
    )
    colliding_relation = _force_relation_id(
        RelationEdge(
            relation_type="depends_on",
            from_revision_id=collision_subject_revision.revision_id,
            to_revision_id=collision_anchor_revision.revision_id,
            transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        ),
        canonical_relation.relation_id,
    )
    replica_collision.relations[colliding_relation.relation_id] = colliding_relation

    replica_orphan = KnowledgeStore()
    orphan_relation = RelationEdge(
        relation_type="derived_from",
        from_revision_id=subject_revision.revision_id,
        to_revision_id="missing-validation-parity-endpoint",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    replica_orphan.relations[orphan_relation.relation_id] = orphan_relation

    merged = KnowledgeStore().merge(replica_base).merged
    merged = merged.merge(replica_collision).merged
    merged = merged.merge(replica_orphan).merged
    return merged, valid_at, tx_from, tx_to, core_subject.core_id


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


def _set_schema_version_unsupported(payload: dict[str, Any]) -> None:
    payload["snapshot_schema_version"] = (
        KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION + 1
    )


def _remove_revisions(payload: dict[str, Any]) -> None:
    payload.pop("revisions")


def _set_cores_object(payload: dict[str, Any]) -> None:
    payload["cores"] = {}


def _clear_relation_collision_metadata(payload: dict[str, Any]) -> None:
    payload["relation_collision_metadata"] = []


_ERROR_PARITY_CASES: tuple[SnapshotValidationErrorParityCase, ...] = (
    (
        "schema_version",
        _set_schema_version_unsupported,
        SnapshotValidationError.CODE_SCHEMA_VERSION,
        "payload.snapshot_schema_version",
    ),
    (
        "strict_key_set_top_level",
        _remove_revisions,
        SnapshotValidationError.CODE_STRICT_KEY_SET,
        "payload",
    ),
    (
        "malformed_type_nested",
        _set_cores_object,
        SnapshotValidationError.CODE_MALFORMED_TYPE,
        "payload.cores",
    ),
    (
        "strict_key_set_relation_id_parity",
        _clear_relation_collision_metadata,
        SnapshotValidationError.CODE_STRICT_KEY_SET,
        "payload.relation_collision_metadata",
    ),
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


def _capture_snapshot_validation_error(
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


@pytest.mark.parametrize(
    ("case_id", "mutate", "expected_code", "expected_path"),
    _ERROR_PARITY_CASES,
    ids=[case[0] for case in _ERROR_PARITY_CASES],
)
def test_store_snapshot_validation_error_parity_across_entrypoints(
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

    payload_error = _capture_snapshot_validation_error(
        entrypoint="payload",
        payload=malformed_payload,
        tmp_path=tmp_path,
    )
    json_error = _capture_snapshot_validation_error(
        entrypoint="json",
        payload=malformed_payload,
        tmp_path=tmp_path,
    )
    file_error = _capture_snapshot_validation_error(
        entrypoint="json_file",
        payload=malformed_payload,
        tmp_path=tmp_path,
    )

    assert isinstance(payload_error, ValueError)
    assert isinstance(json_error, ValueError)
    assert isinstance(file_error, ValueError)
    assert (payload_error.code, payload_error.path) == (expected_code, expected_path)
    assert (json_error.code, json_error.path) == (expected_code, expected_path)
    assert (file_error.code, file_error.path) == (expected_code, expected_path)
    assert payload_error.code == json_error.code == file_error.code
    assert payload_error.path == json_error.path == file_error.path
    assert payload_error.message == json_error.message == file_error.message
    assert payload_error.as_dict() == json_error.as_dict() == file_error.as_dict()


def test_store_snapshot_validation_error_parity_valid_restore_semantics(
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
