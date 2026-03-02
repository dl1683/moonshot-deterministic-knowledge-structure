import json
from datetime import datetime, timezone

from dks import (
    ClaimCore,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _build_state_fingerprint_serialization_store() -> tuple[
    KnowledgeStore,
    datetime,
    int,
    int,
    str,
]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 4
    tx_to = 6

    core_anchor = ClaimCore(claim_type="document", slots={"id": "serialization-anchor"})
    core_context = ClaimCore(claim_type="fact", slots={"id": "serialization-context"})
    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": "serialization-subject"},
    )

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="serialization anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_serialization_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = store.assert_revision(
        core=core_context,
        assertion="serialization context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_serialization_context"),
        confidence_bp=9000,
        status="asserted",
    )
    subject_asserted = store.assert_revision(
        core=core_subject,
        assertion="serialization subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_serialization_subject_asserted"),
        confidence_bp=8600,
        status="asserted",
    )
    store.assert_revision(
        core=core_subject,
        assertion="serialization subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_serialization_subject_retracted"),
        confidence_bp=8600,
        status="retracted",
    )

    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=context_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=subject_asserted.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )

    orphan_replica = KnowledgeStore()
    pending_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_asserted.revision_id,
        to_revision_id="missing-serialization-pending-endpoint",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    return store, valid_at, tx_from, tx_to, core_subject.core_id


def _revision_ids(revisions_payload: list[dict[str, object]]) -> set[str]:
    return {str(revision["revision_id"]) for revision in revisions_payload}


def test_state_fingerprint_serialization_payload_shape_and_json_stability() -> None:
    store, valid_at, _tx_from, tx_to, _subject_core_id = (
        _build_state_fingerprint_serialization_store()
    )
    fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )

    payload = fingerprint.as_canonical_payload()
    assert set(payload) == {
        "revision_lifecycle",
        "relation_resolution",
        "relation_lifecycle",
        "merge_conflict_projection",
        "relation_lifecycle_signatures",
        "ordered_projection",
        "digest",
    }
    assert set(payload["revision_lifecycle"]) == {"active", "retracted"}
    assert set(payload["relation_resolution"]) == {"active", "pending"}
    assert set(payload["relation_lifecycle"]) == {"active", "pending"}
    assert set(payload["relation_lifecycle_signatures"]) == {"active", "pending"}
    assert set(payload["merge_conflict_projection"]) == {"signature_counts", "code_counts"}
    assert isinstance(payload["ordered_projection"], list)
    assert len(payload["ordered_projection"]) == len(fingerprint.ordered_projection)
    assert payload["digest"] == fingerprint.digest

    relation_signature_payloads = (
        payload["relation_lifecycle_signatures"]["active"]
        + payload["relation_lifecycle_signatures"]["pending"]
    )
    for relation_signature in relation_signature_payloads:
        assert set(relation_signature) == {
            "bucket",
            "relation_id",
            "relation_type",
            "from_revision_id",
            "to_revision_id",
            "tx_id",
            "recorded_at",
        }

    canonical_json = fingerprint.as_canonical_json()
    assert canonical_json == json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert canonical_json == fingerprint.canonical_json()
    assert canonical_json == fingerprint.as_canonical_json()
    assert ": " not in canonical_json
    assert ", " not in canonical_json


def test_state_fingerprint_serialization_as_of_window_parity() -> None:
    store, valid_at, _tx_from, tx_to, _subject_core_id = (
        _build_state_fingerprint_serialization_store()
    )

    as_of_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )
    window_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=0,
        tx_end=tx_to,
        valid_at=valid_at,
    )

    assert as_of_fingerprint.as_canonical_payload() == window_fingerprint.as_canonical_payload()
    assert as_of_fingerprint.as_canonical_json() == window_fingerprint.as_canonical_json()


def test_state_fingerprint_transition_serialization_parity_and_ordering_stability() -> None:
    store, valid_at, tx_from, tx_to, _subject_core_id = (
        _build_state_fingerprint_serialization_store()
    )

    from_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
    )
    to_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )
    transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    payload = transition.as_canonical_payload()

    assert payload["from_digest"] == from_fingerprint.digest
    assert payload["to_digest"] == to_fingerprint.digest

    from_active_ids = _revision_ids(from_fingerprint.as_canonical_payload()["revision_lifecycle"]["active"])
    to_active_ids = _revision_ids(to_fingerprint.as_canonical_payload()["revision_lifecycle"]["active"])
    entered_active_ids = [
        revision["revision_id"] for revision in payload["entered_revision_active"]
    ]
    exited_active_ids = [
        revision["revision_id"] for revision in payload["exited_revision_active"]
    ]
    assert entered_active_ids == sorted(to_active_ids - from_active_ids)
    assert exited_active_ids == sorted(from_active_ids - to_active_ids)

    canonical_json = transition.as_canonical_json()
    assert canonical_json == json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert canonical_json == transition.canonical_json()

    reordered_transition = DeterministicStateFingerprintTransition(
        tx_from=transition.tx_from,
        tx_to=transition.tx_to,
        from_digest=transition.from_digest,
        to_digest=transition.to_digest,
        entered_revision_active=tuple(reversed(transition.entered_revision_active)),
        exited_revision_active=tuple(reversed(transition.exited_revision_active)),
        entered_revision_retracted=tuple(reversed(transition.entered_revision_retracted)),
        exited_revision_retracted=tuple(reversed(transition.exited_revision_retracted)),
        entered_relation_resolution_active=tuple(
            reversed(transition.entered_relation_resolution_active)
        ),
        exited_relation_resolution_active=tuple(
            reversed(transition.exited_relation_resolution_active)
        ),
        entered_relation_resolution_pending=tuple(
            reversed(transition.entered_relation_resolution_pending)
        ),
        exited_relation_resolution_pending=tuple(
            reversed(transition.exited_relation_resolution_pending)
        ),
        entered_relation_lifecycle_active=tuple(
            reversed(transition.entered_relation_lifecycle_active)
        ),
        exited_relation_lifecycle_active=tuple(
            reversed(transition.exited_relation_lifecycle_active)
        ),
        entered_relation_lifecycle_pending=tuple(
            reversed(transition.entered_relation_lifecycle_pending)
        ),
        exited_relation_lifecycle_pending=tuple(
            reversed(transition.exited_relation_lifecycle_pending)
        ),
        entered_relation_lifecycle_signature_active=tuple(
            reversed(transition.entered_relation_lifecycle_signature_active)
        ),
        exited_relation_lifecycle_signature_active=tuple(
            reversed(transition.exited_relation_lifecycle_signature_active)
        ),
        entered_relation_lifecycle_signature_pending=tuple(
            reversed(transition.entered_relation_lifecycle_signature_pending)
        ),
        exited_relation_lifecycle_signature_pending=tuple(
            reversed(transition.exited_relation_lifecycle_signature_pending)
        ),
        entered_merge_conflict_signature_counts=tuple(
            reversed(transition.entered_merge_conflict_signature_counts)
        ),
        exited_merge_conflict_signature_counts=tuple(
            reversed(transition.exited_merge_conflict_signature_counts)
        ),
        entered_merge_conflict_code_counts=tuple(
            reversed(transition.entered_merge_conflict_code_counts)
        ),
        exited_merge_conflict_code_counts=tuple(
            reversed(transition.exited_merge_conflict_code_counts)
        ),
    )
    assert reordered_transition.as_canonical_payload() == payload
    assert reordered_transition.as_canonical_json() == canonical_json


def test_state_fingerprint_serialization_core_filtered_behavior_parity() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_serialization_store()
    )

    global_as_of_to = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )
    filtered_as_of_from = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_as_of_to = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_window = store.query_state_fingerprint_for_tx_window(
        tx_start=0,
        tx_end=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )

    assert filtered_as_of_to.as_canonical_payload() == filtered_window.as_canonical_payload()
    assert filtered_as_of_to.as_canonical_json() == filtered_window.as_canonical_json()
    assert filtered_as_of_to.as_canonical_json() != global_as_of_to.as_canonical_json()

    filtered_transition_payload = filtered_transition.as_canonical_payload()
    assert filtered_transition_payload["from_digest"] == filtered_as_of_from.digest
    assert filtered_transition_payload["to_digest"] == filtered_as_of_to.digest
    assert filtered_transition.as_canonical_json() == filtered_transition.as_canonical_json()
