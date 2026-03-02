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


_EXPECTED_SUBJECT_CORE_ID = "b984fbe8b2780b998e8d20830c5dc8286497e07e9d05be9cc1f80671707d3f74"
_EXPECTED_GLOBAL_CANONICAL_JSON = '{"digest":"d485a69d93ff0fb5108467dc2b25a237db7a85848288bbce1c34f3dc7a7d9b25","merge_conflict_projection":{"code_counts":[],"signature_counts":[]},"ordered_projection":[["f17bfc80a1cc6c9ea8c7eadb2524789d1b99ceb4d0c5267afde25ea0200acf41"],["edcd30eb65da3f30a4e95676a1023f2323b7deeb6a3d32862893030faafd63f4"],[],["ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8"],[],["ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8"],[],[["pending","ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8","depends_on","8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","missing-golden-mini-pending-endpoint",4,"2024-01-05T00:00:00+00:00"]],[],[]],"relation_lifecycle":{"active":[],"pending":[{"from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","relation_id":"ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8","relation_type":"depends_on","to_revision_id":"missing-golden-mini-pending-endpoint","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4}}]},"relation_lifecycle_signatures":{"active":[],"pending":[{"bucket":"pending","from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","recorded_at":"2024-01-05T00:00:00+00:00","relation_id":"ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8","relation_type":"depends_on","to_revision_id":"missing-golden-mini-pending-endpoint","tx_id":4}]},"relation_resolution":{"active":[],"pending":[{"from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","relation_id":"ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8","relation_type":"depends_on","to_revision_id":"missing-golden-mini-pending-endpoint","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4}}]},"revision_lifecycle":{"active":[{"assertion":"golden mini anchor","confidence_bp":9100,"core_id":"4e440a3e2745beba616e4830b8edc36cc44f50316839a515770ad9a8950980e2","provenance":{"evidence_ref":null,"source":"source_golden_mini_anchor"},"revision_id":"f17bfc80a1cc6c9ea8c7eadb2524789d1b99ceb4d0c5267afde25ea0200acf41","status":"asserted","transaction_time":{"recorded_at":"2024-01-02T00:00:00+00:00","tx_id":1},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}}],"retracted":[{"assertion":"golden mini subject","confidence_bp":8600,"core_id":"b984fbe8b2780b998e8d20830c5dc8286497e07e9d05be9cc1f80671707d3f74","provenance":{"evidence_ref":null,"source":"source_golden_mini_subject_retracted"},"revision_id":"edcd30eb65da3f30a4e95676a1023f2323b7deeb6a3d32862893030faafd63f4","status":"retracted","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}}]}}'
_EXPECTED_GLOBAL_TRANSITION_CANONICAL_JSON = '{"entered_merge_conflict_code_counts":[],"entered_merge_conflict_signature_counts":[],"entered_relation_lifecycle_active":[],"entered_relation_lifecycle_pending":[{"from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","relation_id":"ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8","relation_type":"depends_on","to_revision_id":"missing-golden-mini-pending-endpoint","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4}}],"entered_relation_lifecycle_signature_active":[],"entered_relation_lifecycle_signature_pending":[{"bucket":"pending","from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","recorded_at":"2024-01-05T00:00:00+00:00","relation_id":"ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8","relation_type":"depends_on","to_revision_id":"missing-golden-mini-pending-endpoint","tx_id":4}],"entered_relation_resolution_active":[],"entered_relation_resolution_pending":[{"from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","relation_id":"ce79dfd4c6a455ecddbc2ce65bddffd2c10afc6b9f29a493182f8cef5c9ab1c8","relation_type":"depends_on","to_revision_id":"missing-golden-mini-pending-endpoint","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4}}],"entered_revision_active":[],"entered_revision_retracted":[{"assertion":"golden mini subject","confidence_bp":8600,"core_id":"b984fbe8b2780b998e8d20830c5dc8286497e07e9d05be9cc1f80671707d3f74","provenance":{"evidence_ref":null,"source":"source_golden_mini_subject_retracted"},"revision_id":"edcd30eb65da3f30a4e95676a1023f2323b7deeb6a3d32862893030faafd63f4","status":"retracted","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}}],"exited_merge_conflict_code_counts":[],"exited_merge_conflict_signature_counts":[],"exited_relation_lifecycle_active":[{"from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","relation_id":"2ed37649494a58be6125d142ad0a733212f0f87e2210f945c8a113b5cd0180a4","relation_type":"supports","to_revision_id":"f17bfc80a1cc6c9ea8c7eadb2524789d1b99ceb4d0c5267afde25ea0200acf41","transaction_time":{"recorded_at":"2024-01-04T00:00:00+00:00","tx_id":3}}],"exited_relation_lifecycle_pending":[],"exited_relation_lifecycle_signature_active":[{"bucket":"active","from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","recorded_at":"2024-01-04T00:00:00+00:00","relation_id":"2ed37649494a58be6125d142ad0a733212f0f87e2210f945c8a113b5cd0180a4","relation_type":"supports","to_revision_id":"f17bfc80a1cc6c9ea8c7eadb2524789d1b99ceb4d0c5267afde25ea0200acf41","tx_id":3}],"exited_relation_lifecycle_signature_pending":[],"exited_relation_resolution_active":[{"from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","relation_id":"2ed37649494a58be6125d142ad0a733212f0f87e2210f945c8a113b5cd0180a4","relation_type":"supports","to_revision_id":"f17bfc80a1cc6c9ea8c7eadb2524789d1b99ceb4d0c5267afde25ea0200acf41","transaction_time":{"recorded_at":"2024-01-04T00:00:00+00:00","tx_id":3}}],"exited_relation_resolution_pending":[],"exited_revision_active":[{"assertion":"golden mini subject","confidence_bp":8600,"core_id":"b984fbe8b2780b998e8d20830c5dc8286497e07e9d05be9cc1f80671707d3f74","provenance":{"evidence_ref":null,"source":"source_golden_mini_subject_asserted"},"revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","status":"asserted","transaction_time":{"recorded_at":"2024-01-03T00:00:00+00:00","tx_id":2},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}}],"exited_revision_retracted":[],"from_digest":"f4b98b667d04e37c814837811b82dd3c527495d5a4eacf34683edde730132ef2","to_digest":"d485a69d93ff0fb5108467dc2b25a237db7a85848288bbce1c34f3dc7a7d9b25","tx_from":3,"tx_to":4}'
_EXPECTED_FILTERED_CANONICAL_JSON = '{"digest":"16c2a7cfceab83fce6c45d1929c249e2b7a6279798e4fd7d9ca333c0b8cae382","merge_conflict_projection":{"code_counts":[],"signature_counts":[]},"ordered_projection":[[],["edcd30eb65da3f30a4e95676a1023f2323b7deeb6a3d32862893030faafd63f4"],[],[],[],[],[],[],[],[]],"relation_lifecycle":{"active":[],"pending":[]},"relation_lifecycle_signatures":{"active":[],"pending":[]},"relation_resolution":{"active":[],"pending":[]},"revision_lifecycle":{"active":[],"retracted":[{"assertion":"golden mini subject","confidence_bp":8600,"core_id":"b984fbe8b2780b998e8d20830c5dc8286497e07e9d05be9cc1f80671707d3f74","provenance":{"evidence_ref":null,"source":"source_golden_mini_subject_retracted"},"revision_id":"edcd30eb65da3f30a4e95676a1023f2323b7deeb6a3d32862893030faafd63f4","status":"retracted","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}}]}}'
_EXPECTED_FILTERED_TRANSITION_CANONICAL_JSON = '{"entered_merge_conflict_code_counts":[],"entered_merge_conflict_signature_counts":[],"entered_relation_lifecycle_active":[],"entered_relation_lifecycle_pending":[],"entered_relation_lifecycle_signature_active":[],"entered_relation_lifecycle_signature_pending":[],"entered_relation_resolution_active":[],"entered_relation_resolution_pending":[],"entered_revision_active":[],"entered_revision_retracted":[{"assertion":"golden mini subject","confidence_bp":8600,"core_id":"b984fbe8b2780b998e8d20830c5dc8286497e07e9d05be9cc1f80671707d3f74","provenance":{"evidence_ref":null,"source":"source_golden_mini_subject_retracted"},"revision_id":"edcd30eb65da3f30a4e95676a1023f2323b7deeb6a3d32862893030faafd63f4","status":"retracted","transaction_time":{"recorded_at":"2024-01-05T00:00:00+00:00","tx_id":4},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}}],"exited_merge_conflict_code_counts":[],"exited_merge_conflict_signature_counts":[],"exited_relation_lifecycle_active":[{"from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","relation_id":"2ed37649494a58be6125d142ad0a733212f0f87e2210f945c8a113b5cd0180a4","relation_type":"supports","to_revision_id":"f17bfc80a1cc6c9ea8c7eadb2524789d1b99ceb4d0c5267afde25ea0200acf41","transaction_time":{"recorded_at":"2024-01-04T00:00:00+00:00","tx_id":3}}],"exited_relation_lifecycle_pending":[],"exited_relation_lifecycle_signature_active":[{"bucket":"active","from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","recorded_at":"2024-01-04T00:00:00+00:00","relation_id":"2ed37649494a58be6125d142ad0a733212f0f87e2210f945c8a113b5cd0180a4","relation_type":"supports","to_revision_id":"f17bfc80a1cc6c9ea8c7eadb2524789d1b99ceb4d0c5267afde25ea0200acf41","tx_id":3}],"exited_relation_lifecycle_signature_pending":[],"exited_relation_resolution_active":[{"from_revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","relation_id":"2ed37649494a58be6125d142ad0a733212f0f87e2210f945c8a113b5cd0180a4","relation_type":"supports","to_revision_id":"f17bfc80a1cc6c9ea8c7eadb2524789d1b99ceb4d0c5267afde25ea0200acf41","transaction_time":{"recorded_at":"2024-01-04T00:00:00+00:00","tx_id":3}}],"exited_relation_resolution_pending":[],"exited_revision_active":[{"assertion":"golden mini subject","confidence_bp":8600,"core_id":"b984fbe8b2780b998e8d20830c5dc8286497e07e9d05be9cc1f80671707d3f74","provenance":{"evidence_ref":null,"source":"source_golden_mini_subject_asserted"},"revision_id":"8ec7a5ea769fe12300e4d9942c658a69882eba1677843ec783495a838672e87f","status":"asserted","transaction_time":{"recorded_at":"2024-01-03T00:00:00+00:00","tx_id":2},"valid_time":{"end":null,"start":"2024-01-01T00:00:00+00:00"}}],"exited_revision_retracted":[],"from_digest":"b4ff44ac01a389363d54fe1d104008e7a368961197eaaf1eaa2b0628d287392a","to_digest":"16c2a7cfceab83fce6c45d1929c249e2b7a6279798e4fd7d9ca333c0b8cae382","tx_from":3,"tx_to":4}'

_EXPECTED_GLOBAL_PAYLOAD = json.loads(_EXPECTED_GLOBAL_CANONICAL_JSON)
_EXPECTED_GLOBAL_TRANSITION_PAYLOAD = json.loads(
    _EXPECTED_GLOBAL_TRANSITION_CANONICAL_JSON
)
_EXPECTED_FILTERED_PAYLOAD = json.loads(_EXPECTED_FILTERED_CANONICAL_JSON)
_EXPECTED_FILTERED_TRANSITION_PAYLOAD = json.loads(
    _EXPECTED_FILTERED_TRANSITION_CANONICAL_JSON
)


def _build_state_fingerprint_golden_store() -> tuple[
    KnowledgeStore,
    datetime,
    int,
    int,
    str,
]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 3
    tx_to = 4

    core_anchor = ClaimCore(claim_type="document", slots={"id": "golden-mini-anchor"})
    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": "golden-mini-subject"},
    )

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="golden mini anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_golden_mini_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_asserted = store.assert_revision(
        core=core_subject,
        assertion="golden mini subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_golden_mini_subject_asserted"),
        confidence_bp=8600,
        status="asserted",
    )
    store.assert_revision(
        core=core_subject,
        assertion="golden mini subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_golden_mini_subject_retracted"),
        confidence_bp=8600,
        status="retracted",
    )

    store.attach_relation(
        relation_type="supports",
        from_revision_id=subject_asserted.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )

    orphan_replica = KnowledgeStore()
    pending_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_asserted.revision_id,
        to_revision_id="missing-golden-mini-pending-endpoint",
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    return store, valid_at, tx_from, tx_to, core_subject.core_id


def test_state_fingerprint_canonical_golden_regression_global_surfaces() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_golden_store()
    )
    as_of_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )
    tx_window_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=0,
        tx_end=tx_to,
        valid_at=valid_at,
    )
    transition_fingerprint = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    from_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
    )

    assert subject_core_id == _EXPECTED_SUBJECT_CORE_ID
    assert as_of_fingerprint.as_canonical_json() == _EXPECTED_GLOBAL_CANONICAL_JSON
    assert tx_window_fingerprint.as_canonical_json() == _EXPECTED_GLOBAL_CANONICAL_JSON
    assert (
        transition_fingerprint.as_canonical_json()
        == _EXPECTED_GLOBAL_TRANSITION_CANONICAL_JSON
    )

    as_of_payload = as_of_fingerprint.as_canonical_payload()
    tx_window_payload = tx_window_fingerprint.as_canonical_payload()
    transition_payload = transition_fingerprint.as_canonical_payload()

    assert as_of_payload == _EXPECTED_GLOBAL_PAYLOAD
    assert tx_window_payload == _EXPECTED_GLOBAL_PAYLOAD
    assert transition_payload == _EXPECTED_GLOBAL_TRANSITION_PAYLOAD
    assert set(as_of_payload) == {
        "digest",
        "merge_conflict_projection",
        "ordered_projection",
        "relation_lifecycle",
        "relation_lifecycle_signatures",
        "relation_resolution",
        "revision_lifecycle",
    }
    assert set(transition_payload) == {
        "entered_merge_conflict_code_counts",
        "entered_merge_conflict_signature_counts",
        "entered_relation_lifecycle_active",
        "entered_relation_lifecycle_pending",
        "entered_relation_lifecycle_signature_active",
        "entered_relation_lifecycle_signature_pending",
        "entered_relation_resolution_active",
        "entered_relation_resolution_pending",
        "entered_revision_active",
        "entered_revision_retracted",
        "exited_merge_conflict_code_counts",
        "exited_merge_conflict_signature_counts",
        "exited_relation_lifecycle_active",
        "exited_relation_lifecycle_pending",
        "exited_relation_lifecycle_signature_active",
        "exited_relation_lifecycle_signature_pending",
        "exited_relation_resolution_active",
        "exited_relation_resolution_pending",
        "exited_revision_active",
        "exited_revision_retracted",
        "from_digest",
        "to_digest",
        "tx_from",
        "tx_to",
    }

    assert as_of_payload["digest"] == as_of_fingerprint.digest
    assert tx_window_payload["digest"] == tx_window_fingerprint.digest
    assert transition_payload["from_digest"] == from_fingerprint.digest
    assert transition_payload["to_digest"] == as_of_fingerprint.digest
    assert transition_fingerprint.from_digest == from_fingerprint.digest
    assert transition_fingerprint.to_digest == as_of_fingerprint.digest

    assert as_of_payload["revision_lifecycle"]["active"][0]["assertion"] == "golden mini anchor"
    assert as_of_payload["revision_lifecycle"]["retracted"][0]["status"] == "retracted"
    assert (
        as_of_payload["relation_resolution"]["pending"][0]["to_revision_id"]
        == "missing-golden-mini-pending-endpoint"
    )
    assert transition_payload["entered_revision_retracted"][0]["status"] == "retracted"
    assert transition_payload["exited_revision_active"][0]["status"] == "asserted"
    assert (
        transition_payload["entered_relation_resolution_pending"][0]["relation_type"]
        == "depends_on"
    )
    assert (
        transition_payload["exited_relation_resolution_active"][0]["relation_type"]
        == "supports"
    )


def test_state_fingerprint_canonical_golden_regression_core_filtered_case() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_golden_store()
    )
    filtered_from_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_as_of_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_tx_window_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=0,
        tx_end=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_transition_fingerprint = (
        store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            core_id=subject_core_id,
        )
    )

    assert subject_core_id == _EXPECTED_SUBJECT_CORE_ID
    assert (
        filtered_as_of_fingerprint.as_canonical_json() == _EXPECTED_FILTERED_CANONICAL_JSON
    )
    assert (
        filtered_tx_window_fingerprint.as_canonical_json()
        == _EXPECTED_FILTERED_CANONICAL_JSON
    )
    assert (
        filtered_transition_fingerprint.as_canonical_json()
        == _EXPECTED_FILTERED_TRANSITION_CANONICAL_JSON
    )
    assert (
        filtered_as_of_fingerprint.as_canonical_json() != _EXPECTED_GLOBAL_CANONICAL_JSON
    )

    filtered_as_of_payload = filtered_as_of_fingerprint.as_canonical_payload()
    filtered_tx_window_payload = filtered_tx_window_fingerprint.as_canonical_payload()
    filtered_transition_payload = filtered_transition_fingerprint.as_canonical_payload()

    assert filtered_as_of_payload == _EXPECTED_FILTERED_PAYLOAD
    assert filtered_tx_window_payload == _EXPECTED_FILTERED_PAYLOAD
    assert filtered_transition_payload == _EXPECTED_FILTERED_TRANSITION_PAYLOAD
    assert filtered_as_of_payload["digest"] == filtered_as_of_fingerprint.digest
    assert filtered_tx_window_payload["digest"] == filtered_tx_window_fingerprint.digest
    assert (
        filtered_transition_payload["from_digest"] == filtered_from_fingerprint.digest
    )
    assert (
        filtered_transition_payload["to_digest"] == filtered_as_of_fingerprint.digest
    )
    assert filtered_transition_fingerprint.from_digest == filtered_from_fingerprint.digest
    assert filtered_transition_fingerprint.to_digest == filtered_as_of_fingerprint.digest

    assert filtered_as_of_payload["relation_resolution"] == {"active": [], "pending": []}
    assert filtered_transition_payload["entered_relation_resolution_pending"] == []
    assert (
        filtered_transition_payload["exited_relation_resolution_active"][0]["relation_type"]
        == "supports"
    )
    assert (
        filtered_transition_payload["entered_revision_retracted"][0]["core_id"]
        == subject_core_id
    )
