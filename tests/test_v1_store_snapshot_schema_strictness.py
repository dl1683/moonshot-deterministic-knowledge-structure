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


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _force_relation_id(edge: RelationEdge, relation_id: str) -> RelationEdge:
    object.__setattr__(edge, "relation_id", relation_id)
    return edge


def _build_store_snapshot_schema_strictness_fixture() -> KnowledgeStore:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    core_anchor = ClaimCore(claim_type="document", slots={"id": "schema-strict-anchor"})
    core_subject = ClaimCore(claim_type="fact", slots={"id": "schema-strict-subject"})

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="schema strict anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_schema_strict_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="schema strict subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_schema_strict_subject"),
        confidence_bp=8900,
        status="asserted",
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
        assertion="schema strict anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_schema_strict_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="schema strict subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_schema_strict_subject"),
        confidence_bp=8900,
        status="asserted",
    )
    colliding_relation = _force_relation_id(
        RelationEdge(
            relation_type="depends_on",
            from_revision_id=collision_subject_revision.revision_id,
            to_revision_id=collision_anchor_revision.revision_id,
            transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        ),
        canonical_relation.relation_id,
    )
    replica_collision.relations[colliding_relation.relation_id] = colliding_relation

    merged = KnowledgeStore().merge(replica_base).merged
    merged = merged.merge(replica_collision).merged
    return merged


def _add_top_level_unknown_key(payload: dict[str, Any]) -> None:
    payload["unexpected_snapshot_key"] = []


def _add_nested_unknown_key(payload: dict[str, Any]) -> None:
    collision_metadata = payload["relation_collision_metadata"]
    assert isinstance(collision_metadata, list)
    assert collision_metadata
    entry = collision_metadata[0]
    assert isinstance(entry, dict)
    entry["unexpected"] = []


@pytest.mark.parametrize(
    ("mutate", "error_pattern"),
    [
        (
            _add_top_level_unknown_key,
            r"payload: unexpected keys \['unexpected_snapshot_key'\]",
        ),
        (
            _add_nested_unknown_key,
            r"payload\.relation_collision_metadata\[0\]: unexpected keys \['unexpected'\]",
        ),
    ],
)
def test_store_snapshot_schema_strictness_rejects_unknown_keys(
    mutate: Callable[[dict[str, Any]], None],
    error_pattern: str,
) -> None:
    store = _build_store_snapshot_schema_strictness_fixture()
    payload = copy.deepcopy(store.as_canonical_payload())
    mutate(payload)

    with pytest.raises(ValueError, match=error_pattern):
        KnowledgeStore.from_canonical_payload(payload)


def test_store_snapshot_schema_strictness_rejects_missing_keys() -> None:
    store = _build_store_snapshot_schema_strictness_fixture()

    missing_top_level = copy.deepcopy(store.as_canonical_payload())
    missing_top_level.pop("revisions")
    with pytest.raises(
        ValueError,
        match=r"payload: missing keys \['revisions'\]",
    ):
        KnowledgeStore.from_canonical_payload(missing_top_level)

    missing_nested_key_set = copy.deepcopy(store.as_canonical_payload())
    missing_nested_key_set["relation_collision_metadata"] = []
    with pytest.raises(
        ValueError,
        match=r"payload\.relation_collision_metadata: missing relation_id entries \[",
    ):
        KnowledgeStore.from_canonical_payload(missing_nested_key_set)


def test_store_snapshot_schema_strictness_round_trip_payload_and_json_parity() -> None:
    store = _build_store_snapshot_schema_strictness_fixture()
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    assert payload["relation_variants"]
    assert payload["relation_collision_metadata"]
    assert {
        entry["relation_id"] for entry in payload["relation_variants"]
    } == {
        entry["relation_id"] for entry in payload["relation_collision_metadata"]
    }
    assert canonical_json == json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    restored_from_payload = KnowledgeStore.from_canonical_payload(payload)
    restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)

    assert restored_from_payload.as_canonical_payload() == payload
    assert restored_from_payload.as_canonical_json() == canonical_json
    assert restored_from_json.as_canonical_payload() == payload
    assert restored_from_json.as_canonical_json() == canonical_json
    assert restored_from_payload.revision_state_signatures() == store.revision_state_signatures()
    assert restored_from_payload.relation_state_signatures() == store.relation_state_signatures()
    assert restored_from_payload.pending_relation_ids() == store.pending_relation_ids()
