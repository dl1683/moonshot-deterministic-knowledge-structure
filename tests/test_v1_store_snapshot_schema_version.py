import copy
import json
from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _build_store_snapshot_fixture() -> KnowledgeStore:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    store = KnowledgeStore()
    anchor_revision = store.assert_revision(
        core=ClaimCore(claim_type="document", slots={"id": "schema-anchor"}),
        assertion="schema anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_schema_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    subject_revision = store.assert_revision(
        core=ClaimCore(claim_type="fact", slots={"id": "schema-subject"}),
        assertion="schema subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_schema_subject"),
        confidence_bp=8800,
        status="asserted",
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    return store


def test_store_snapshot_schema_version_round_trip_payload_and_json_parity() -> None:
    store = _build_store_snapshot_fixture()
    payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()

    assert payload["snapshot_schema_version"] == 1
    assert canonical_json == json.dumps(payload, sort_keys=True, separators=(",", ":"))

    from_payload = KnowledgeStore.from_canonical_payload(payload)
    from_json = KnowledgeStore.from_canonical_json(canonical_json)

    assert from_payload.as_canonical_payload() == payload
    assert from_payload.as_canonical_json() == canonical_json
    assert from_json.as_canonical_payload() == payload
    assert from_json.as_canonical_json() == canonical_json
    assert from_payload.revision_state_signatures() == store.revision_state_signatures()
    assert from_payload.relation_state_signatures() == store.relation_state_signatures()
    assert from_payload.pending_relation_ids() == store.pending_relation_ids()


def test_store_snapshot_schema_version_rejects_unsupported_versions() -> None:
    store = _build_store_snapshot_fixture()
    unsupported_payload = copy.deepcopy(store.as_canonical_payload())
    unsupported_payload["snapshot_schema_version"] = 999

    with pytest.raises(
        ValueError,
        match=(
            r"payload\.snapshot_schema_version: unsupported snapshot schema version "
            r"999; expected 1"
        ),
    ):
        KnowledgeStore.from_canonical_payload(unsupported_payload)

    unsupported_json = json.dumps(
        unsupported_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(
        ValueError,
        match=(
            r"payload\.snapshot_schema_version: unsupported snapshot schema version "
            r"999; expected 1"
        ),
    ):
        KnowledgeStore.from_canonical_json(unsupported_json)


def test_store_snapshot_schema_version_rejects_missing_version() -> None:
    store = _build_store_snapshot_fixture()
    missing_version_payload = copy.deepcopy(store.as_canonical_payload())
    missing_version_payload.pop("snapshot_schema_version")

    with pytest.raises(
        ValueError,
        match=r"payload: missing keys \['snapshot_schema_version'\]",
    ):
        KnowledgeStore.from_canonical_payload(missing_version_payload)

    missing_version_json = json.dumps(
        missing_version_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(
        ValueError,
        match=r"payload: missing keys \['snapshot_schema_version'\]",
    ):
        KnowledgeStore.from_canonical_json(missing_version_json)
