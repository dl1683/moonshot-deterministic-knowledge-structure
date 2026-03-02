from datetime import datetime, timezone
from pathlib import Path

import hashlib
import itertools

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)

SurfaceSnapshotQuerySignature = tuple[str, str, str, str, str, str, str, str | None]


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _force_relation_id(edge: RelationEdge, relation_id: str) -> RelationEdge:
    object.__setattr__(edge, "relation_id", relation_id)
    return edge


def _save_canonical_json(store: KnowledgeStore, snapshot_path: Path) -> None:
    store.to_canonical_json_file(snapshot_path)


def _load_canonical_json(snapshot_path: Path) -> KnowledgeStore:
    return KnowledgeStore.from_canonical_json_file(snapshot_path)


def replay_stream(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple]:
    merged = start if start is not None else KnowledgeStore()
    observed_conflicts = []
    for replica in replicas:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        observed_conflicts.extend(merge_result.conflicts)
    return merged, tuple(observed_conflicts)


def replay_with_restart_snapshots(
    replicas: list[KnowledgeStore],
    *,
    boundaries: tuple[int, ...],
    snapshot_path: Path,
) -> tuple[KnowledgeStore, tuple]:
    merged = KnowledgeStore()
    conflicts = []
    start_index = 0

    for boundary in boundaries + (len(replicas),):
        segment = replicas[start_index:boundary]
        if segment:
            merged, segment_conflicts = replay_stream(segment, start=merged)
            conflicts.extend(segment_conflicts)

            _save_canonical_json(merged, snapshot_path)
            canonical_file_text = snapshot_path.read_text(encoding="utf-8")
            assert canonical_file_text == merged.as_canonical_json()

            merged = _load_canonical_json(snapshot_path)
            assert merged.as_canonical_json() == canonical_file_text

        start_index = boundary

    return merged, tuple(conflicts)


def _build_store_snapshot_restart_replicas(
    *,
    tx_base: int,
) -> tuple[list[KnowledgeStore], datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = tx_base + 2
    tx_to = tx_base + 7

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-restart-subject-{tx_base}"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": f"store-snapshot-restart-anchor-{tx_base}"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": f"store-snapshot-restart-context-{tx_base}"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-restart-retracted-{tx_base}"},
    )
    core_competing = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-restart-competing-{tx_base}"},
    )

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="store snapshot restart anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_restart_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="store snapshot restart context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_restart_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="store snapshot restart subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_restart_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="store snapshot restart retracted asserted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_restart_retracted_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="store snapshot restart competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_store_snapshot_restart_competing_a"),
        confidence_bp=8200,
        status="asserted",
    )
    canonical_relation = replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
    )
    replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=context_revision.revision_id,
        to_revision_id=subject_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
    )

    replica_competing = KnowledgeStore()
    replica_competing.assert_revision(
        core=core_competing,
        assertion="store snapshot restart competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_store_snapshot_restart_competing_b"),
        confidence_bp=8200,
        status="asserted",
    )

    replica_collision = KnowledgeStore()
    collision_anchor_revision = replica_collision.assert_revision(
        core=core_anchor,
        assertion="store snapshot restart anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_restart_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="store snapshot restart subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_restart_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    colliding_relation = _force_relation_id(
        RelationEdge(
            relation_type="depends_on",
            from_revision_id=collision_subject_revision.revision_id,
            to_revision_id=collision_anchor_revision.revision_id,
            transaction_time=TransactionTime(tx_id=tx_base + 5, recorded_at=dt(2024, 1, 6)),
        ),
        canonical_relation.relation_id,
    )
    replica_collision.relations[colliding_relation.relation_id] = colliding_relation

    replica_updates = KnowledgeStore()
    subject_revision_copy = replica_updates.assert_revision(
        core=core_subject,
        assertion="store snapshot restart subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_restart_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_updates.assert_revision(
        core=core_retracted,
        assertion="store snapshot restart retracted final",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_store_snapshot_restart_retracted_final"),
        confidence_bp=8300,
        status="retracted",
    )
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_revision_copy.revision_id,
        to_revision_id=f"missing-store-snapshot-restart-endpoint-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 1, 8)),
    )
    replica_updates.relations[orphan_relation.relation_id] = orphan_relation

    return (
        [replica_base, replica_competing, replica_collision, replica_updates],
        valid_at,
        tx_from,
        tx_to,
        core_subject.core_id,
    )


def _surface_snapshot_query_signature(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    core_id: str | None,
) -> SurfaceSnapshotQuerySignature:
    from_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=core_id,
    )
    as_of_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    window_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_from,
        tx_end=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    transition_fingerprint = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    winner = (
        store.query_as_of(core_id, valid_at=valid_at, tx_id=tx_to)
        if core_id is not None
        else None
    )

    assert transition_fingerprint.from_digest == from_fingerprint.digest
    assert transition_fingerprint.to_digest == as_of_fingerprint.digest

    return (
        as_of_fingerprint.as_canonical_json(),
        as_of_fingerprint.digest,
        window_fingerprint.as_canonical_json(),
        window_fingerprint.digest,
        transition_fingerprint.as_canonical_json(),
        transition_fingerprint.from_digest,
        transition_fingerprint.to_digest,
        winner.revision_id if winner is not None else None,
    )


def _restart_behavior_signature(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    query_core_ids: tuple[str | None, ...],
) -> tuple:
    canonical_payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()
    surface_signatures = tuple(
        _surface_snapshot_query_signature(
            store,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            core_id=query_core_id,
        )
        for query_core_id in query_core_ids
    )

    return (
        canonical_json,
        hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
        tuple(core["core_id"] for core in canonical_payload["cores"]),
        tuple(revision["revision_id"] for revision in canonical_payload["revisions"]),
        tuple(relation["relation_id"] for relation in canonical_payload["active_relations"]),
        tuple(relation["relation_id"] for relation in canonical_payload["pending_relations"]),
        tuple(
            entry["relation_id"] for entry in canonical_payload["relation_variants"]
        ),
        tuple(
            entry["relation_id"]
            for entry in canonical_payload["relation_collision_metadata"]
        ),
        store.revision_state_signatures(),
        store.relation_state_signatures(),
        store.pending_relation_ids(),
        surface_signatures,
    )


def test_store_snapshot_file_io_multi_restart_progression_matches_uninterrupted_progression(
    tmp_path: Path,
) -> None:
    replicas, valid_at, tx_from, tx_to, subject_core_id = (
        _build_store_snapshot_restart_replicas(tx_base=7710)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)

    uninterrupted_merged, uninterrupted_conflicts = replay_stream(replicas)
    uninterrupted_conflict_signatures = KnowledgeStore.conflict_signatures(
        uninterrupted_conflicts
    )
    uninterrupted_signature = _restart_behavior_signature(
        uninterrupted_merged,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        query_core_ids=query_core_ids,
    )

    restart_boundaries = tuple(
        boundaries
        for restart_count in range(1, len(replicas))
        for boundaries in itertools.combinations(range(1, len(replicas)), restart_count)
    )
    assert restart_boundaries
    assert any(len(boundaries) > 1 for boundaries in restart_boundaries)

    snapshot_path = tmp_path / "restart.snapshot.canonical.json"
    for boundaries in restart_boundaries:
        restarted_merged, restarted_conflicts = replay_with_restart_snapshots(
            replicas,
            boundaries=boundaries,
            snapshot_path=snapshot_path,
        )

        assert KnowledgeStore.conflict_signatures(restarted_conflicts) == (
            uninterrupted_conflict_signatures
        )
        assert _restart_behavior_signature(
            restarted_merged,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            query_core_ids=query_core_ids,
        ) == uninterrupted_signature
