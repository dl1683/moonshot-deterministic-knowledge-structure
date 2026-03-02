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
    TransactionTime,
    ValidTime,
)

MalformedPayloadMutation = Callable[[dict[str, Any]], None]
MalformedPayloadCase = tuple[str, MalformedPayloadMutation, str]


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

    core_anchor = ClaimCore(claim_type="document", slots={"id": "malformed-anchor"})
    core_subject = ClaimCore(claim_type="fact", slots={"id": "malformed-subject"})
    core_context = ClaimCore(claim_type="fact", slots={"id": "malformed-context"})

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="malformed anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_malformed_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="malformed subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_malformed_subject_asserted"),
        confidence_bp=8700,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_context,
        assertion="malformed context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_malformed_context"),
        confidence_bp=8600,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_subject,
        assertion="malformed subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_malformed_subject_retracted"),
        confidence_bp=8700,
        status="retracted",
    )
    canonical_relation = replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )

    replica_collision = KnowledgeStore()
    collision_anchor_revision = replica_collision.assert_revision(
        core=core_anchor,
        assertion="malformed anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_malformed_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="malformed subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_malformed_subject_asserted"),
        confidence_bp=8700,
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
        to_revision_id="missing-malformed-pending-endpoint",
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
) -> tuple:
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


def _set_schema_version_string(payload: dict[str, Any]) -> None:
    payload["snapshot_schema_version"] = "1"


def _set_schema_version_float(payload: dict[str, Any]) -> None:
    payload["snapshot_schema_version"] = 1.0


def _set_schema_version_bool(payload: dict[str, Any]) -> None:
    payload["snapshot_schema_version"] = True


def _set_schema_version_list(payload: dict[str, Any]) -> None:
    payload["snapshot_schema_version"] = [1]


def _set_schema_version_object(payload: dict[str, Any]) -> None:
    payload["snapshot_schema_version"] = {"version": 1}


def _set_cores_object(payload: dict[str, Any]) -> None:
    payload["cores"] = {}


def _set_revisions_scalar(payload: dict[str, Any]) -> None:
    payload["revisions"] = 1


def _set_active_relations_object(payload: dict[str, Any]) -> None:
    payload["active_relations"] = {}


def _set_pending_relations_scalar(payload: dict[str, Any]) -> None:
    payload["pending_relations"] = "pending"


def _set_relation_variants_object(payload: dict[str, Any]) -> None:
    payload["relation_variants"] = {}


def _set_relation_collision_metadata_scalar(payload: dict[str, Any]) -> None:
    payload["relation_collision_metadata"] = 0


def _set_core_entry_list(payload: dict[str, Any]) -> None:
    payload["cores"][0] = []


def _set_revision_entry_scalar(payload: dict[str, Any]) -> None:
    payload["revisions"][0] = "revision"


def _set_relation_variant_entry_list(payload: dict[str, Any]) -> None:
    payload["relation_variants"][0] = []


def _set_variants_collection_object(payload: dict[str, Any]) -> None:
    payload["relation_variants"][0]["variants"] = {}


def _set_collision_entry_scalar(payload: dict[str, Any]) -> None:
    payload["relation_collision_metadata"][0] = "collision"


def _set_collision_pairs_object(payload: dict[str, Any]) -> None:
    payload["relation_collision_metadata"][0]["collision_pairs"] = {}


_MALFORMED_PAYLOAD_TYPE_CASES: tuple[MalformedPayloadCase, ...] = (
    (
        "schema_version_string",
        _set_schema_version_string,
        r"payload\.snapshot_schema_version: expected integer, got str",
    ),
    (
        "schema_version_float",
        _set_schema_version_float,
        r"payload\.snapshot_schema_version: expected integer, got float",
    ),
    (
        "schema_version_bool",
        _set_schema_version_bool,
        r"payload\.snapshot_schema_version: expected integer, got bool",
    ),
    (
        "schema_version_list",
        _set_schema_version_list,
        r"payload\.snapshot_schema_version: expected integer, got list",
    ),
    (
        "schema_version_object",
        _set_schema_version_object,
        r"payload\.snapshot_schema_version: expected integer, got dict",
    ),
    ("cores_object", _set_cores_object, r"payload\.cores: expected array, got dict"),
    (
        "revisions_scalar",
        _set_revisions_scalar,
        r"payload\.revisions: expected array, got int",
    ),
    (
        "active_relations_object",
        _set_active_relations_object,
        r"payload\.active_relations: expected array, got dict",
    ),
    (
        "pending_relations_scalar",
        _set_pending_relations_scalar,
        r"payload\.pending_relations: expected array, got str",
    ),
    (
        "relation_variants_object",
        _set_relation_variants_object,
        r"payload\.relation_variants: expected array, got dict",
    ),
    (
        "relation_collision_metadata_scalar",
        _set_relation_collision_metadata_scalar,
        r"payload\.relation_collision_metadata: expected array, got int",
    ),
    (
        "core_entry_list",
        _set_core_entry_list,
        r"payload\.cores\[0\]: expected object, got list",
    ),
    (
        "revision_entry_scalar",
        _set_revision_entry_scalar,
        r"payload\.revisions\[0\]: expected object, got str",
    ),
    (
        "relation_variant_entry_list",
        _set_relation_variant_entry_list,
        r"payload\.relation_variants\[0\]: expected object, got list",
    ),
    (
        "variants_collection_object",
        _set_variants_collection_object,
        r"payload\.relation_variants\[0\]\.variants: expected array, got dict",
    ),
    (
        "collision_entry_scalar",
        _set_collision_entry_scalar,
        r"payload\.relation_collision_metadata\[0\]: expected object, got str",
    ),
    (
        "collision_pairs_object",
        _set_collision_pairs_object,
        r"payload\.relation_collision_metadata\[0\]\.collision_pairs: expected array, got dict",
    ),
)

_TOP_LEVEL_PAYLOAD_NON_OBJECT_CASES: tuple[tuple[Any, str], ...] = (
    ([], r"payload: expected object, got list"),
    (1, r"payload: expected object, got int"),
    ("snapshot", r"payload: expected object, got str"),
    (True, r"payload: expected object, got bool"),
    (None, r"payload: expected object, got NoneType"),
)

_TOP_LEVEL_JSON_NON_OBJECT_CASES: tuple[tuple[str, str], ...] = (
    ("[]", r"canonical_json: expected top-level JSON object"),
    ("1", r"canonical_json: expected top-level JSON object"),
    ("\"snapshot\"", r"canonical_json: expected top-level JSON object"),
    ("true", r"canonical_json: expected top-level JSON object"),
    ("null", r"canonical_json: expected top-level JSON object"),
)


@pytest.mark.parametrize(
    ("payload_value", "error_pattern"),
    _TOP_LEVEL_PAYLOAD_NON_OBJECT_CASES,
    ids=("list", "integer", "string", "boolean", "null"),
)
def test_store_snapshot_malformed_inputs_reject_non_object_payload_values(
    payload_value: Any,
    error_pattern: str,
) -> None:
    with pytest.raises(ValueError, match=error_pattern):
        KnowledgeStore.from_canonical_payload(payload_value)


@pytest.mark.parametrize(
    ("case_id", "mutate", "error_pattern"),
    _MALFORMED_PAYLOAD_TYPE_CASES,
    ids=[case[0] for case in _MALFORMED_PAYLOAD_TYPE_CASES],
)
def test_store_snapshot_malformed_inputs_reject_payload_type_matrix(
    case_id: str,
    mutate: MalformedPayloadMutation,
    error_pattern: str,
) -> None:
    del case_id
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_fixture()
    malformed_payload = copy.deepcopy(store.as_canonical_payload())
    mutate(malformed_payload)

    with pytest.raises(ValueError, match=error_pattern):
        KnowledgeStore.from_canonical_payload(malformed_payload)


@pytest.mark.parametrize(
    ("json_text", "error_pattern"),
    _TOP_LEVEL_JSON_NON_OBJECT_CASES,
    ids=("array", "integer", "string", "boolean", "null"),
)
def test_store_snapshot_malformed_inputs_reject_non_object_json_text(
    json_text: str,
    error_pattern: str,
) -> None:
    with pytest.raises(ValueError, match=error_pattern):
        KnowledgeStore.from_canonical_json(json_text)


@pytest.mark.parametrize(
    ("case_id", "mutate", "error_pattern"),
    _MALFORMED_PAYLOAD_TYPE_CASES,
    ids=[case[0] for case in _MALFORMED_PAYLOAD_TYPE_CASES],
)
def test_store_snapshot_malformed_inputs_reject_json_type_matrix(
    case_id: str,
    mutate: MalformedPayloadMutation,
    error_pattern: str,
) -> None:
    del case_id
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_fixture()
    malformed_payload = copy.deepcopy(store.as_canonical_payload())
    mutate(malformed_payload)
    malformed_json = json.dumps(
        malformed_payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    with pytest.raises(ValueError, match=error_pattern):
        KnowledgeStore.from_canonical_json(malformed_json)


@pytest.mark.parametrize(
    ("json_text", "error_pattern"),
    _TOP_LEVEL_JSON_NON_OBJECT_CASES,
    ids=("array", "integer", "string", "boolean", "null"),
)
def test_store_snapshot_malformed_inputs_reject_non_object_json_file_text(
    tmp_path,
    json_text: str,
    error_pattern: str,
) -> None:
    snapshot_path = tmp_path / "non_object_snapshot.canonical.json"
    snapshot_path.write_text(json_text, encoding="utf-8")

    with pytest.raises(ValueError, match=error_pattern):
        KnowledgeStore.from_canonical_json_file(snapshot_path)


@pytest.mark.parametrize(
    ("case_id", "mutate", "error_pattern"),
    _MALFORMED_PAYLOAD_TYPE_CASES,
    ids=[case[0] for case in _MALFORMED_PAYLOAD_TYPE_CASES],
)
def test_store_snapshot_malformed_inputs_reject_json_file_type_matrix(
    tmp_path,
    case_id: str,
    mutate: MalformedPayloadMutation,
    error_pattern: str,
) -> None:
    del case_id
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_fixture()
    malformed_payload = copy.deepcopy(store.as_canonical_payload())
    mutate(malformed_payload)

    snapshot_path = tmp_path / "malformed_snapshot.canonical.json"
    snapshot_path.write_text(
        json.dumps(malformed_payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=error_pattern):
        KnowledgeStore.from_canonical_json_file(snapshot_path)


def test_store_snapshot_malformed_inputs_valid_restore_query_semantics_unchanged(
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

    malformed_payload = copy.deepcopy(payload)
    _set_schema_version_string(malformed_payload)
    with pytest.raises(
        ValueError,
        match=r"payload\.snapshot_schema_version: expected integer, got str",
    ):
        KnowledgeStore.from_canonical_payload(malformed_payload)

    malformed_json = json.dumps(
        malformed_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(
        ValueError,
        match=r"payload\.snapshot_schema_version: expected integer, got str",
    ):
        KnowledgeStore.from_canonical_json(malformed_json)

    malformed_path = tmp_path / "malformed.canonical.json"
    malformed_path.write_text(malformed_json, encoding="utf-8")
    with pytest.raises(
        ValueError,
        match=r"payload\.snapshot_schema_version: expected integer, got str",
    ):
        KnowledgeStore.from_canonical_json_file(malformed_path)

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
