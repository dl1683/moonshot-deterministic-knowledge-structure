import copy
import json
from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    DeterministicStateFingerprint,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _build_state_fingerprint_deserialization_store() -> tuple[
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


def test_state_fingerprint_deserialization_round_trip_payload_and_digest_parity() -> None:
    store, valid_at, tx_from, tx_to, _subject_core_id = (
        _build_state_fingerprint_deserialization_store()
    )
    as_of = store.query_state_fingerprint_as_of(tx_id=tx_to, valid_at=valid_at)
    tx_window = store.query_state_fingerprint_for_tx_window(
        tx_start=0,
        tx_end=tx_to,
        valid_at=valid_at,
    )
    transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    from_fingerprint = store.query_state_fingerprint_as_of(tx_id=tx_from, valid_at=valid_at)

    as_of_payload = as_of.as_canonical_payload()
    as_of_json = as_of.as_canonical_json()
    round_trip_as_of_payload = DeterministicStateFingerprint.from_canonical_payload(
        as_of_payload
    )
    round_trip_as_of_json = DeterministicStateFingerprint.from_canonical_json(as_of_json)
    round_trip_tx_window_payload = DeterministicStateFingerprint.from_canonical_payload(
        tx_window.as_canonical_payload()
    )

    assert round_trip_as_of_payload.as_canonical_payload() == as_of_payload
    assert round_trip_as_of_payload.as_canonical_json() == as_of_json
    assert round_trip_as_of_json.as_canonical_payload() == as_of_payload
    assert round_trip_as_of_json.as_canonical_json() == as_of_json
    assert round_trip_as_of_payload.digest == as_of.digest
    assert round_trip_as_of_json.digest == as_of.digest
    assert round_trip_tx_window_payload.as_canonical_payload() == as_of_payload
    assert round_trip_tx_window_payload.digest == as_of.digest

    transition_payload = transition.as_canonical_payload()
    transition_json = transition.as_canonical_json()
    round_trip_transition_payload = (
        DeterministicStateFingerprintTransition.from_canonical_payload(
            transition_payload
        )
    )
    round_trip_transition_json = (
        DeterministicStateFingerprintTransition.from_canonical_json(transition_json)
    )

    assert round_trip_transition_payload.as_canonical_payload() == transition_payload
    assert round_trip_transition_payload.as_canonical_json() == transition_json
    assert round_trip_transition_json.as_canonical_payload() == transition_payload
    assert round_trip_transition_json.as_canonical_json() == transition_json
    assert round_trip_transition_payload.from_digest == from_fingerprint.digest
    assert round_trip_transition_payload.to_digest == as_of.digest
    assert round_trip_transition_json.from_digest == from_fingerprint.digest
    assert round_trip_transition_json.to_digest == as_of.digest


def test_state_fingerprint_deserialization_round_trip_core_filtered_case() -> None:
    store, valid_at, tx_from, tx_to, subject_core_id = (
        _build_state_fingerprint_deserialization_store()
    )
    global_as_of = store.query_state_fingerprint_as_of(tx_id=tx_to, valid_at=valid_at)
    filtered_from = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_as_of = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_tx_window = store.query_state_fingerprint_for_tx_window(
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

    filtered_round_trip = DeterministicStateFingerprint.from_canonical_payload(
        filtered_as_of.as_canonical_payload()
    )
    filtered_round_trip_json = DeterministicStateFingerprint.from_canonical_json(
        filtered_as_of.as_canonical_json()
    )
    filtered_transition_round_trip = (
        DeterministicStateFingerprintTransition.from_canonical_payload(
            filtered_transition.as_canonical_payload()
        )
    )
    filtered_transition_round_trip_json = (
        DeterministicStateFingerprintTransition.from_canonical_json(
            filtered_transition.as_canonical_json()
        )
    )

    assert filtered_round_trip.as_canonical_payload() == filtered_as_of.as_canonical_payload()
    assert filtered_round_trip.as_canonical_json() == filtered_as_of.as_canonical_json()
    assert (
        filtered_round_trip_json.as_canonical_payload()
        == filtered_as_of.as_canonical_payload()
    )
    assert filtered_round_trip.digest == filtered_as_of.digest
    assert filtered_round_trip_json.digest == filtered_as_of.digest
    assert filtered_as_of.as_canonical_payload() == filtered_tx_window.as_canonical_payload()
    assert filtered_as_of.as_canonical_json() == filtered_tx_window.as_canonical_json()
    assert filtered_round_trip.digest != global_as_of.digest

    assert (
        filtered_transition_round_trip.as_canonical_payload()
        == filtered_transition.as_canonical_payload()
    )
    assert (
        filtered_transition_round_trip_json.as_canonical_payload()
        == filtered_transition.as_canonical_payload()
    )
    assert filtered_transition_round_trip.from_digest == filtered_from.digest
    assert filtered_transition_round_trip.to_digest == filtered_as_of.digest
    assert filtered_transition_round_trip_json.from_digest == filtered_from.digest
    assert filtered_transition_round_trip_json.to_digest == filtered_as_of.digest


def test_state_fingerprint_deserialization_rejects_malformed_input() -> None:
    store, valid_at, _tx_from, tx_to, _subject_core_id = (
        _build_state_fingerprint_deserialization_store()
    )
    payload = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    ).as_canonical_payload()

    missing_digest = copy.deepcopy(payload)
    missing_digest.pop("digest")
    with pytest.raises(ValueError, match=r"payload: missing keys \['digest'\]"):
        DeterministicStateFingerprint.from_canonical_payload(missing_digest)

    digest_mismatch = copy.deepcopy(payload)
    digest_mismatch["digest"] = "0" * 64
    with pytest.raises(ValueError, match=r"payload\.digest: mismatch; expected "):
        DeterministicStateFingerprint.from_canonical_payload(digest_mismatch)

    non_canonical_text = copy.deepcopy(payload)
    non_canonical_text["revision_lifecycle"]["active"][0]["assertion"] = "Serialization Anchor"
    with pytest.raises(
        ValueError,
        match=r"payload: does not match canonical deterministic state fingerprint payload",
    ):
        DeterministicStateFingerprint.from_canonical_payload(non_canonical_text)

    wrong_bucket_type = copy.deepcopy(payload)
    wrong_bucket_type["revision_lifecycle"]["active"] = tuple(
        wrong_bucket_type["revision_lifecycle"]["active"]
    )
    with pytest.raises(
        ValueError,
        match=r"payload\.revision_lifecycle\.active: expected array, got tuple",
    ):
        DeterministicStateFingerprint.from_canonical_payload(wrong_bucket_type)

    with pytest.raises(ValueError, match=r"canonical_json: invalid JSON"):
        DeterministicStateFingerprint.from_canonical_json("{not-json")

    pretty_json = json.dumps(payload, sort_keys=True, indent=2)
    with pytest.raises(
        ValueError,
        match=r"canonical_json: does not match canonical deterministic state fingerprint JSON",
    ):
        DeterministicStateFingerprint.from_canonical_json(pretty_json)

    with pytest.raises(
        ValueError,
        match=r"canonical_json: expected top-level JSON object",
    ):
        DeterministicStateFingerprint.from_canonical_json("[]")


def test_state_fingerprint_transition_deserialization_rejects_malformed_input() -> None:
    store, valid_at, tx_from, tx_to, _subject_core_id = (
        _build_state_fingerprint_deserialization_store()
    )
    transition_payload = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    ).as_canonical_payload()

    missing_to_digest = copy.deepcopy(transition_payload)
    missing_to_digest.pop("to_digest")
    with pytest.raises(ValueError, match=r"payload: missing keys \['to_digest'\]"):
        DeterministicStateFingerprintTransition.from_canonical_payload(missing_to_digest)

    tx_range_drift = copy.deepcopy(transition_payload)
    tx_range_drift["tx_to"] = tx_from - 1
    with pytest.raises(
        ValueError,
        match=r"payload\.tx_to: must be greater than or equal to payload\.tx_from",
    ):
        DeterministicStateFingerprintTransition.from_canonical_payload(tx_range_drift)

    wrong_tx_type = copy.deepcopy(transition_payload)
    wrong_tx_type["tx_from"] = True
    with pytest.raises(
        ValueError,
        match=r"payload\.tx_from: expected integer, got bool",
    ):
        DeterministicStateFingerprintTransition.from_canonical_payload(wrong_tx_type)

    digest_drift = copy.deepcopy(transition_payload)
    digest_drift["from_digest"] = "not-a-digest"
    with pytest.raises(
        ValueError,
        match=r"payload\.from_digest: expected 64-char lowercase hex digest",
    ):
        DeterministicStateFingerprintTransition.from_canonical_payload(digest_drift)

    with pytest.raises(ValueError, match=r"canonical_json: invalid JSON"):
        DeterministicStateFingerprintTransition.from_canonical_json("{not-json")

    pretty_json = json.dumps(transition_payload, sort_keys=True, indent=2)
    with pytest.raises(
        ValueError,
        match=(
            r"canonical_json: does not match canonical deterministic state fingerprint "
            r"transition JSON"
        ),
    ):
        DeterministicStateFingerprintTransition.from_canonical_json(pretty_json)

    with pytest.raises(
        ValueError,
        match=r"canonical_json: expected top-level JSON object",
    ):
        DeterministicStateFingerprintTransition.from_canonical_json("[]")
