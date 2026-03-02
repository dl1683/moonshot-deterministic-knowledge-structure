import hashlib
import json
from datetime import datetime, timezone

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


_EXPECTED_SUBJECT_CORE_ID = "bbc05e27e9b6f8af710a515a09fcee1a26c5a24c9c108efb32ba69ae8e04de63"
_EXPECTED_CANONICAL_JSON = '{"active_relations":[{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","relation_id":"7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441","relation_type":"depends_on","to_revision_id":"4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21","transaction_time":{"recorded_at":"2024-01-06T00:00:00+00:00","tx_id":5}},{"from_revision_id":"8a711ef16be11302003588989b106d6a4a63d4624168e7f263cb3951f8f54677","relation_id":"e6fa859ac5b2ad5dbcc6cddc37ef798ba2bf0cf6bb91cf5db7c7e6b9c2b78dfa","relation_type":"derived_from","to_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4}}],"cores":[{"claim_type":"fact","core_id":"b603ab3dafa967354bb4026ad5ae1876b1c249907cb10dc93217e033b3ff5438","slots":{"id":"golden-store-context"}},{"claim_type":"residence","core_id":"bbc05e27e9b6f8af710a515a09fcee1a26c5a24c9c108efb32ba69ae8e04de63","slots":{"subject":"golden-store-subject"}},{"claim_type":"document","core_id":"c57b1fdbfdb50ce389fa96443042b5c18899edc5b558bef6133366ac6d5f8193","slots":{"id":"golden-store-anchor"}}],"pending_relations":[{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","relation_id":"3d220e869833fd40992c6bf7fb60414835cc61b96523f9c8b95500f22c757b68","relation_type":"depends_on","to_revision_id":"missing-golden-store-pending-endpoint","transaction_time":{"recorded_at":"2024-01-08T00:00:00+00:00","tx_id":7}}],"relation_collision_metadata":[{"collision_pairs":[],"relation_id":"3d220e869833fd40992c6bf7fb60414835cc61b96523f9c8b95500f22c757b68"},{"collision_pairs":[{"left":{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","recorded_at":"2024-01-06T00:00:00+00:00","relation_type":"depends_on","to_revision_id":"4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21","tx_id":5},"right":{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","recorded_at":"2024-01-04T00:00:00+00:00","relation_type":"supports","to_revision_id":"4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21","tx_id":3}}],"relation_id":"7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441"},{"collision_pairs":[],"relation_id":"e6fa859ac5b2ad5dbcc6cddc37ef798ba2bf0cf6bb91cf5db7c7e6b9c2b78dfa"}],"relation_variants":[{"relation_id":"3d220e869833fd40992c6bf7fb60414835cc61b96523f9c8b95500f22c757b68","variants":[{"relation":{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","relation_id":"3d220e869833fd40992c6bf7fb60414835cc61b96523f9c8b95500f22c757b68","relation_type":"depends_on","to_revision_id":"missing-golden-store-pending-endpoint","transaction_time":{"recorded_at":"2024-01-08T00:00:00+00:00","tx_id":7}},"relation_key":{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","recorded_at":"2024-01-08T00:00:00+00:00","relation_type":"depends_on","to_revision_id":"missing-golden-store-pending-endpoint","tx_id":7}}]},{"relation_id":"7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441","variants":[{"relation":{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","relation_id":"7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441","relation_type":"depends_on","to_revision_id":"4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21","transaction_time":{"recorded_at":"2024-01-06T00:00:00+00:00","tx_id":5}},"relation_key":{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","recorded_at":"2024-01-06T00:00:00+00:00","relation_type":"depends_on","to_revision_id":"4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21","tx_id":5}},{"relation":{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","relation_id":"7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441","relation_type":"supports","to_revision_id":"4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21","transaction_time":{"recorded_at":"2024-01-04T00:00:00+00:00","tx_id":3}},"relation_key":{"from_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","recorded_at":"2024-01-04T00:00:00+00:00","relation_type":"supports","to_revision_id":"4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21","tx_id":3}}]},{"relation_id":"e6fa859ac5b2ad5dbcc6cddc37ef798ba2bf0cf6bb91cf5db7c7e6b9c2b78dfa","variants":[{"relation":{"from_revision_id":"8a711ef16be11302003588989b106d6a4a63d4624168e7f263cb3951f8f54677","relation_id":"e6fa859ac5b2ad5dbcc6cddc37ef798ba2bf0cf6bb91cf5db7c7e6b9c2b78dfa","relation_type":"derived_from","to_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4}},"relation_key":{"from_revision_id":"8a711ef16be11302003588989b106d6a4a63d4624168e7f263cb3951f8f54677","recorded_at":"2024-01-05T00:00:00+00:00","relation_type":"derived_from","to_revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","tx_id":4}}]}],"revisions":[{"assertion":"golden store subject","confidence_bp":8600,"core_id":"bbc05e27e9b6f8af710a515a09fcee1a26c5a24c9c108efb32ba69ae8e04de63","provenance":{"evidence_ref":null,"source":"source_golden_store_subject_retracted"},"revision_id":"3409f77e15c86ef42370759025a6d868fe5e0d232487d3b4d2f27ab945f905fb","status":"retracted","transaction_time":{"recorded_at":"2024-01-07T00:00:00+00:00","tx_id":6},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}},{"assertion":"golden store anchor","confidence_bp":9100,"core_id":"c57b1fdbfdb50ce389fa96443042b5c18899edc5b558bef6133366ac6d5f8193","provenance":{"evidence_ref":null,"source":"source_golden_store_anchor"},"revision_id":"4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21","status":"asserted","transaction_time":{"recorded_at":"2024-01-02T00:00:00+00:00","tx_id":1},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}},{"assertion":"golden store context","confidence_bp":8500,"core_id":"b603ab3dafa967354bb4026ad5ae1876b1c249907cb10dc93217e033b3ff5438","provenance":{"evidence_ref":null,"source":"source_golden_store_context"},"revision_id":"8a711ef16be11302003588989b106d6a4a63d4624168e7f263cb3951f8f54677","status":"asserted","transaction_time":{"recorded_at":"2024-01-03T00:00:00+00:00","tx_id":2},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}},{"assertion":"golden store subject","confidence_bp":8600,"core_id":"bbc05e27e9b6f8af710a515a09fcee1a26c5a24c9c108efb32ba69ae8e04de63","provenance":{"evidence_ref":null,"source":"source_golden_store_subject_asserted"},"revision_id":"a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c","status":"asserted","transaction_time":{"recorded_at":"2024-01-03T00:00:00+00:00","tx_id":2},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}}]}'
_EXPECTED_CANONICAL_PAYLOAD = json.loads(_EXPECTED_CANONICAL_JSON)
_EXPECTED_CANONICAL_PAYLOAD["snapshot_schema_version"] = 1
_EXPECTED_CANONICAL_PAYLOAD["merge_conflict_journal"] = []
_EXPECTED_CANONICAL_PAYLOAD["snapshot_checksum"] = hashlib.sha256(
    json.dumps(
        _EXPECTED_CANONICAL_PAYLOAD,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
_EXPECTED_CANONICAL_JSON = json.dumps(
    _EXPECTED_CANONICAL_PAYLOAD,
    sort_keys=True,
    separators=(",", ":"),
)
_EXPECTED_CORE_ORDER = [
    "b603ab3dafa967354bb4026ad5ae1876b1c249907cb10dc93217e033b3ff5438",
    "bbc05e27e9b6f8af710a515a09fcee1a26c5a24c9c108efb32ba69ae8e04de63",
    "c57b1fdbfdb50ce389fa96443042b5c18899edc5b558bef6133366ac6d5f8193",
]
_EXPECTED_REVISION_ORDER = [
    "3409f77e15c86ef42370759025a6d868fe5e0d232487d3b4d2f27ab945f905fb",
    "4c797c2a03cdef9c392f9b575fbed88486fad0de8cf7fd8a505b62286f265e21",
    "8a711ef16be11302003588989b106d6a4a63d4624168e7f263cb3951f8f54677",
    "a53609b5139c2dce39579f867aca340183316302cda8234eea055d97c5637d9c",
]
_EXPECTED_ACTIVE_RELATION_ORDER = [
    "7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441",
    "e6fa859ac5b2ad5dbcc6cddc37ef798ba2bf0cf6bb91cf5db7c7e6b9c2b78dfa",
]
_EXPECTED_PENDING_RELATION_ORDER = [
    "3d220e869833fd40992c6bf7fb60414835cc61b96523f9c8b95500f22c757b68",
]
_EXPECTED_RELATION_VARIANT_ORDER = [
    "3d220e869833fd40992c6bf7fb60414835cc61b96523f9c8b95500f22c757b68",
    "7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441",
    "e6fa859ac5b2ad5dbcc6cddc37ef798ba2bf0cf6bb91cf5db7c7e6b9c2b78dfa",
]
_EXPECTED_COLLISION_METADATA_ORDER = [
    "3d220e869833fd40992c6bf7fb60414835cc61b96523f9c8b95500f22c757b68",
    "7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441",
    "e6fa859ac5b2ad5dbcc6cddc37ef798ba2bf0cf6bb91cf5db7c7e6b9c2b78dfa",
]
_EXPECTED_COLLIDING_RELATION_ID = "7a9f2f7a31f614c43daa47f7ac7959cc7b9f346a018570c4eee8dbffb9aeb441"


def _build_store_snapshot_golden_fixture() -> tuple[KnowledgeStore, datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 4
    tx_to = 7

    core_anchor = ClaimCore(claim_type="document", slots={"id": "golden-store-anchor"})
    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": "golden-store-subject"},
    )
    core_context = ClaimCore(claim_type="fact", slots={"id": "golden-store-context"})

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="golden store anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_golden_store_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_asserted_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="golden store subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_golden_store_subject_asserted"),
        confidence_bp=8600,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="golden store context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_golden_store_context"),
        confidence_bp=8500,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_subject,
        assertion="golden store subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_golden_store_subject_retracted"),
        confidence_bp=8600,
        status="retracted",
    )
    canonical_relation = replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=subject_asserted_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=context_revision.revision_id,
        to_revision_id=subject_asserted_revision.revision_id,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )

    replica_collision = KnowledgeStore()
    collision_anchor_revision = replica_collision.assert_revision(
        core=core_anchor,
        assertion="golden store anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_golden_store_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="golden store subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_golden_store_subject_asserted"),
        confidence_bp=8600,
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
        relation_type="depends_on",
        from_revision_id=subject_asserted_revision.revision_id,
        to_revision_id="missing-golden-store-pending-endpoint",
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )
    replica_orphan.relations[orphan_relation.relation_id] = orphan_relation

    store = KnowledgeStore().merge(replica_base).merged
    store = store.merge(replica_collision).merged
    store = store.merge(replica_orphan).merged
    return store, valid_at, tx_from, tx_to, core_subject.core_id


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
    tx_window_filtered = store.query_state_fingerprint_for_tx_window(
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
        tx_window_filtered.as_canonical_json(),
        transition_filtered.as_canonical_json(),
    )


def test_store_snapshot_canonical_golden_regression_payload_and_json() -> None:
    store, _valid_at, _tx_from, _tx_to, subject_core_id = (
        _build_store_snapshot_golden_fixture()
    )
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()

    assert subject_core_id == _EXPECTED_SUBJECT_CORE_ID
    assert payload == _EXPECTED_CANONICAL_PAYLOAD
    assert canonical_json == _EXPECTED_CANONICAL_JSON
    assert json.loads(canonical_json) == _EXPECTED_CANONICAL_PAYLOAD

    assert [core["core_id"] for core in payload["cores"]] == _EXPECTED_CORE_ORDER
    assert [
        revision["revision_id"] for revision in payload["revisions"]
    ] == _EXPECTED_REVISION_ORDER
    assert [
        relation["relation_id"] for relation in payload["active_relations"]
    ] == _EXPECTED_ACTIVE_RELATION_ORDER
    assert [
        relation["relation_id"] for relation in payload["pending_relations"]
    ] == _EXPECTED_PENDING_RELATION_ORDER
    assert [
        entry["relation_id"] for entry in payload["relation_variants"]
    ] == _EXPECTED_RELATION_VARIANT_ORDER
    assert [
        entry["relation_id"] for entry in payload["relation_collision_metadata"]
    ] == _EXPECTED_COLLISION_METADATA_ORDER

    colliding_variants = next(
        entry["variants"]
        for entry in payload["relation_variants"]
        if entry["relation_id"] == _EXPECTED_COLLIDING_RELATION_ID
    )
    assert [
        variant["relation_key"]["relation_type"] for variant in colliding_variants
    ] == ["depends_on", "supports"]

    colliding_collision_pairs = next(
        entry["collision_pairs"]
        for entry in payload["relation_collision_metadata"]
        if entry["relation_id"] == _EXPECTED_COLLIDING_RELATION_ID
    )
    assert len(colliding_collision_pairs) == 1
    assert colliding_collision_pairs[0]["left"]["relation_type"] == "depends_on"
    assert colliding_collision_pairs[0]["right"]["relation_type"] == "supports"


def test_store_snapshot_canonical_golden_regression_restore_parity() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = (
        _build_store_snapshot_golden_fixture()
    )

    restored = KnowledgeStore.from_canonical_json(_EXPECTED_CANONICAL_JSON)

    assert restored.as_canonical_payload() == _EXPECTED_CANONICAL_PAYLOAD
    assert restored.as_canonical_json() == _EXPECTED_CANONICAL_JSON
    assert _query_signature(
        restored,
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
