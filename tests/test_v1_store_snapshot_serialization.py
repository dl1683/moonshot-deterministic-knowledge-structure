import copy
import json
from datetime import datetime, timezone

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


def _build_store_snapshot_fixture() -> tuple[KnowledgeStore, datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 4
    tx_to = 7

    core_anchor = ClaimCore(claim_type="document", slots={"id": "snapshot-anchor"})
    core_subject = ClaimCore(claim_type="residence", slots={"subject": "snapshot-subject"})
    core_context = ClaimCore(claim_type="fact", slots={"id": "snapshot-context"})

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="snapshot anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_snapshot_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="snapshot subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_snapshot_subject_asserted"),
        confidence_bp=8700,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_context,
        assertion="snapshot context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_snapshot_context"),
        confidence_bp=8600,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_subject,
        assertion="snapshot subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_snapshot_subject_retracted"),
        confidence_bp=8700,
        status="retracted",
    )
    canonical_relation = replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )

    replica_collision = KnowledgeStore()
    collision_anchor_revision = replica_collision.assert_revision(
        core=core_anchor,
        assertion="snapshot anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_snapshot_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="snapshot subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_snapshot_subject_asserted"),
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
        to_revision_id="missing-snapshot-pending-endpoint",
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


def test_store_snapshot_round_trip_payload_and_json_parity() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = _build_store_snapshot_fixture()

    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    from_payload = KnowledgeStore.from_canonical_payload(payload)
    from_json = KnowledgeStore.from_canonical_json(canonical_json)

    assert payload["relation_variants"]
    assert any(
        entry["collision_pairs"]
        for entry in payload["relation_collision_metadata"]
    )
    assert from_payload.as_canonical_payload() == payload
    assert from_payload.as_canonical_json() == canonical_json
    assert from_json.as_canonical_payload() == payload
    assert from_json.as_canonical_json() == canonical_json
    assert from_payload.revision_state_signatures() == store.revision_state_signatures()
    assert from_payload.relation_state_signatures() == store.relation_state_signatures()
    assert from_payload.pending_relation_ids() == store.pending_relation_ids()
    assert _query_signature(
        from_payload,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=subject_core_id,
    ) == _query_signature(
        store,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=subject_core_id,
    )


def test_store_snapshot_query_parity_for_pre_serialized_checkpoint() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = _build_store_snapshot_fixture()
    checkpoint = store.checkpoint()
    pre_serialized_json = checkpoint.as_canonical_json()
    reloaded = KnowledgeStore.from_canonical_json(pre_serialized_json)

    assert _query_signature(
        reloaded,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=subject_core_id,
    ) == _query_signature(
        checkpoint,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=subject_core_id,
    )


def test_store_snapshot_deserialization_rejects_malformed_input() -> None:
    store, _valid_at, _tx_from, _tx_to, _subject_core_id = _build_store_snapshot_fixture()
    payload = store.as_canonical_payload()

    missing_metadata = copy.deepcopy(payload)
    missing_metadata.pop("relation_collision_metadata")
    with pytest.raises(
        ValueError,
        match=r"payload: missing keys \['relation_collision_metadata'\]",
    ):
        KnowledgeStore.from_canonical_payload(missing_metadata)

    wrong_pending_type = copy.deepcopy(payload)
    wrong_pending_type["pending_relations"] = tuple(wrong_pending_type["pending_relations"])
    with pytest.raises(
        ValueError,
        match=r"payload\.pending_relations: expected array, got tuple",
    ):
        KnowledgeStore.from_canonical_payload(wrong_pending_type)

    relation_key_drift = copy.deepcopy(payload)
    relation_key_drift["relation_variants"][0]["variants"][0]["relation_key"]["tx_id"] += 1
    with pytest.raises(
        ValueError,
        match=r"relation_key: does not match relation payload sort key",
    ):
        KnowledgeStore.from_canonical_payload(relation_key_drift)

    unknown_variant_pair = copy.deepcopy(payload)
    collision_entry = next(
        entry
        for entry in unknown_variant_pair["relation_collision_metadata"]
        if entry["collision_pairs"]
    )
    collision_entry["collision_pairs"][0]["left"]["tx_id"] += 99
    with pytest.raises(
        ValueError,
        match=r"collision pair references unknown relation variants",
    ):
        KnowledgeStore.from_canonical_payload(unknown_variant_pair)

    with pytest.raises(ValueError, match=r"canonical_json: invalid JSON"):
        KnowledgeStore.from_canonical_json("{not-json")

    pretty_json = json.dumps(payload, sort_keys=True, indent=2)
    with pytest.raises(
        ValueError,
        match=r"canonical_json: does not match canonical deterministic knowledge store JSON",
    ):
        KnowledgeStore.from_canonical_json(pretty_json)

    with pytest.raises(
        ValueError,
        match=r"canonical_json: expected top-level JSON object",
    ):
        KnowledgeStore.from_canonical_json("[]")


def test_store_snapshot_checkpoint_copy_equivalence() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = _build_store_snapshot_fixture()
    checkpoint = store.checkpoint()
    copied = store.copy()

    assert checkpoint.as_canonical_payload() == store.as_canonical_payload()
    assert copied.as_canonical_payload() == store.as_canonical_payload()
    assert checkpoint.as_canonical_json() == store.as_canonical_json()
    assert copied.as_canonical_json() == store.as_canonical_json()

    checkpoint_round_trip = KnowledgeStore.from_canonical_json(checkpoint.as_canonical_json())
    copy_round_trip = KnowledgeStore.from_canonical_payload(copied.as_canonical_payload())
    assert _query_signature(
        checkpoint_round_trip,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=subject_core_id,
    ) == _query_signature(
        copy_round_trip,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=subject_core_id,
    )
