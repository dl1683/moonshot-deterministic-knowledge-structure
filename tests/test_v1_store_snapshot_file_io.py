import json
from datetime import datetime, timezone

import pytest

import dks.core as core_module
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


def _windows_lock_permission_error() -> PermissionError:
    error = PermissionError("simulated transient lock")
    error.winerror = 32
    return error


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


def test_store_snapshot_file_round_trip_parity(tmp_path) -> None:
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_fixture()

    snapshot_path = tmp_path / "snapshot.canonical.json"
    snapshot_path.write_text("stale-content", encoding="utf-8")
    store.to_canonical_json_file(snapshot_path)

    assert snapshot_path.read_text(encoding="utf-8") == store.as_canonical_json()

    restored = KnowledgeStore.from_canonical_json_file(snapshot_path)
    assert restored.as_canonical_payload() == store.as_canonical_payload()
    assert restored.as_canonical_json() == store.as_canonical_json()


def test_store_snapshot_file_io_rejects_malformed_files(tmp_path) -> None:
    store, _valid_at, _tx_from, _tx_to, _core_id = _build_store_snapshot_fixture()
    payload = store.as_canonical_payload()

    invalid_utf8_path = tmp_path / "invalid_utf8_snapshot.canonical.json"
    invalid_utf8_path.write_bytes(b"{\"cores\":\xff}")
    with pytest.raises(
        ValueError,
        match=r"canonical_json_file: invalid UTF-8 encoded snapshot content",
    ):
        KnowledgeStore.from_canonical_json_file(invalid_utf8_path)

    invalid_json_path = tmp_path / "invalid_json_snapshot.canonical.json"
    invalid_json_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match=r"canonical_json: invalid JSON"):
        KnowledgeStore.from_canonical_json_file(invalid_json_path)

    pretty_json_path = tmp_path / "pretty_snapshot.canonical.json"
    pretty_json_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match=r"canonical_json: does not match canonical deterministic knowledge store JSON",
    ):
        KnowledgeStore.from_canonical_json_file(pretty_json_path)


def test_store_snapshot_file_restore_query_parity_with_in_memory_snapshot(tmp_path) -> None:
    store, valid_at, tx_from, tx_to, core_id = _build_store_snapshot_fixture()
    checkpoint = store.checkpoint()

    in_memory_restored = KnowledgeStore.from_canonical_json(checkpoint.as_canonical_json())

    snapshot_path = tmp_path / "checkpoint.canonical.json"
    checkpoint.to_canonical_json_file(snapshot_path)
    file_restored = KnowledgeStore.from_canonical_json_file(snapshot_path)

    assert _query_signature(
        file_restored,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    ) == _query_signature(
        in_memory_restored,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    )


def test_store_snapshot_file_io_retries_transient_replace_lock_errors(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, valid_at, tx_from, tx_to, core_id = _build_store_snapshot_fixture()
    snapshot_path = tmp_path / "snapshot.canonical.json"
    real_replace = core_module.os.replace
    replace_call_count = 0
    retry_delays: list[float] = []

    def flaky_replace(source, target) -> None:
        nonlocal replace_call_count
        replace_call_count += 1
        if replace_call_count <= 2:
            raise _windows_lock_permission_error()
        real_replace(source, target)

    monkeypatch.setattr(core_module.os, "replace", flaky_replace)
    monkeypatch.setattr(core_module.time, "sleep", retry_delays.append)

    store.to_canonical_json_file(snapshot_path)

    assert replace_call_count == 3
    assert len(retry_delays) == 2
    assert retry_delays[0] > 0
    assert retry_delays[1] > retry_delays[0]
    assert snapshot_path.read_text(encoding="utf-8") == store.as_canonical_json()

    restored = KnowledgeStore.from_canonical_json_file(snapshot_path)
    assert _query_signature(
        restored,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    ) == _query_signature(
        store,
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        core_id=core_id,
    )
