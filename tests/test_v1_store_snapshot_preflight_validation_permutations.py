from datetime import datetime, timezone
from pathlib import Path

import hashlib
import itertools
import json

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


def replay_with_checkpoint_segments(
    replicas: list[KnowledgeStore],
    *,
    boundaries: tuple[int, ...],
) -> tuple[KnowledgeStore, tuple]:
    merged = KnowledgeStore()
    conflicts = []
    start_index = 0

    for boundary in boundaries + (len(replicas),):
        segment = replicas[start_index:boundary]
        segment_start = merged if start_index == 0 else merged.checkpoint()
        merged, segment_conflicts = replay_stream(segment, start=segment_start)
        conflicts.extend(segment_conflicts)
        start_index = boundary

    return merged, tuple(conflicts)


def replay_with_restart_snapshots(
    replicas: list[KnowledgeStore],
    *,
    boundaries: tuple[int, ...],
    snapshot_path: Path,
    restart_round_trips: int,
) -> tuple[KnowledgeStore, tuple]:
    merged = KnowledgeStore()
    conflicts = []
    start_index = 0

    for boundary in boundaries + (len(replicas),):
        segment = replicas[start_index:boundary]
        segment_start = merged if start_index == 0 else merged.checkpoint()
        merged, segment_conflicts = replay_stream(segment, start=segment_start)
        conflicts.extend(segment_conflicts)

        for _ in range(restart_round_trips):
            merged.to_canonical_json_file(snapshot_path)
            canonical_file_text = snapshot_path.read_text(encoding="utf-8")
            assert canonical_file_text == merged.as_canonical_json()

            merged = KnowledgeStore.from_canonical_json_file(snapshot_path)
            assert merged.as_canonical_json() == canonical_file_text

        start_index = boundary

    return merged, tuple(conflicts)


def _build_store_snapshot_preflight_validation_replay_replicas(
    *,
    tx_base: int,
) -> tuple[list[KnowledgeStore], datetime, int, int, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = tx_base + 2
    tx_to = tx_base + 7

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-preflight-subject-{tx_base}"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": f"store-snapshot-preflight-anchor-{tx_base}"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": f"store-snapshot-preflight-context-{tx_base}"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-preflight-retracted-{tx_base}"},
    )
    core_competing = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-preflight-competing-{tx_base}"},
    )

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="store snapshot preflight anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_preflight_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="store snapshot preflight context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_preflight_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="store snapshot preflight subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_preflight_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="store snapshot preflight retracted asserted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_preflight_retracted_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="store snapshot preflight competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_store_snapshot_preflight_competing_a"),
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
        assertion="store snapshot preflight competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_store_snapshot_preflight_competing_b"),
        confidence_bp=8200,
        status="asserted",
    )

    replica_collision = KnowledgeStore()
    collision_anchor_revision = replica_collision.assert_revision(
        core=core_anchor,
        assertion="store snapshot preflight anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_preflight_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="store snapshot preflight subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_preflight_subject"),
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
        assertion="store snapshot preflight subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_preflight_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_updates.assert_revision(
        core=core_retracted,
        assertion="store snapshot preflight retracted final",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_store_snapshot_preflight_retracted_final"),
        confidence_bp=8300,
        status="retracted",
    )
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_revision_copy.revision_id,
        to_revision_id=f"missing-store-snapshot-preflight-endpoint-{tx_base}",
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


def _preflight_validation_signature(
    store: KnowledgeStore,
    *,
    snapshot_path: Path,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    query_core_ids: tuple[str | None, ...],
) -> tuple:
    canonical_payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()

    assert canonical_json == json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    payload_without_checksum = {
        key: value
        for key, value in canonical_payload.items()
        if key != "snapshot_checksum"
    }
    expected_snapshot_checksum = hashlib.sha256(
        json.dumps(
            payload_without_checksum,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    expected_content_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    payload_report = KnowledgeStore.validate_canonical_payload(canonical_payload)
    json_report = KnowledgeStore.validate_canonical_json(canonical_json)

    store.to_canonical_json_file(snapshot_path)
    canonical_file_text = snapshot_path.read_text(encoding="utf-8")
    assert canonical_file_text == canonical_json
    file_report = KnowledgeStore.validate_canonical_json_file(snapshot_path)

    assert payload_report == json_report
    assert payload_report == file_report
    assert payload_report.schema_version == canonical_payload["snapshot_schema_version"]
    assert payload_report.snapshot_checksum == expected_snapshot_checksum
    assert payload_report.canonical_content_digest == expected_content_digest
    assert payload_report.as_dict() == {
        "schema_version": canonical_payload["snapshot_schema_version"],
        "snapshot_checksum": expected_snapshot_checksum,
        "canonical_content_digest": expected_content_digest,
    }
    assert json_report.as_dict() == payload_report.as_dict()
    assert file_report.as_dict() == payload_report.as_dict()

    restored_from_payload = KnowledgeStore.from_canonical_payload(canonical_payload)
    restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)
    restored_from_file = KnowledgeStore.from_canonical_json_file(snapshot_path)

    assert restored_from_payload.as_canonical_payload() == canonical_payload
    assert restored_from_payload.as_canonical_json() == canonical_json
    assert restored_from_json.as_canonical_payload() == canonical_payload
    assert restored_from_json.as_canonical_json() == canonical_json
    assert restored_from_file.as_canonical_payload() == canonical_payload
    assert restored_from_file.as_canonical_json() == canonical_json

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
    payload_surface_signatures = tuple(
        _surface_snapshot_query_signature(
            restored_from_payload,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            core_id=query_core_id,
        )
        for query_core_id in query_core_ids
    )
    json_surface_signatures = tuple(
        _surface_snapshot_query_signature(
            restored_from_json,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            core_id=query_core_id,
        )
        for query_core_id in query_core_ids
    )
    file_surface_signatures = tuple(
        _surface_snapshot_query_signature(
            restored_from_file,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            core_id=query_core_id,
        )
        for query_core_id in query_core_ids
    )
    assert payload_surface_signatures == surface_signatures
    assert json_surface_signatures == surface_signatures
    assert file_surface_signatures == surface_signatures

    return (
        canonical_payload,
        canonical_json,
        (
            payload_report.schema_version,
            payload_report.snapshot_checksum,
            payload_report.canonical_content_digest,
        ),
        (
            payload_report.as_dict(),
            json_report.as_dict(),
            file_report.as_dict(),
        ),
        store.revision_state_signatures(),
        store.relation_state_signatures(),
        store.pending_relation_ids(),
        surface_signatures,
    )


def test_store_snapshot_preflight_validation_reports_are_invariant_for_equivalent_histories(
    tmp_path: Path,
) -> None:
    replicas, valid_at, tx_from, tx_to, subject_core_id = (
        _build_store_snapshot_preflight_validation_replay_replicas(tx_base=8050)
    )
    query_core_ids: tuple[str | None, ...] = (None, subject_core_id)
    baseline_snapshot_signature = None
    baseline_conflict_signatures = None

    checkpoint_boundaries = tuple(
        boundaries
        for checkpoint_count in range(1, len(replicas))
        for boundaries in itertools.combinations(
            range(1, len(replicas)),
            checkpoint_count,
        )
    )
    restart_boundaries = tuple(
        boundaries
        for restart_count in range(1, len(replicas))
        for boundaries in itertools.combinations(range(1, len(replicas)), restart_count)
    )
    assert checkpoint_boundaries
    assert restart_boundaries
    assert any(len(boundaries) > 1 for boundaries in restart_boundaries)

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        order_label = "-".join(str(index) for index in order)
        unsplit_merged, unsplit_conflicts = replay_stream(ordered_replicas)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        if baseline_conflict_signatures is None:
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        unsplit_signature = _preflight_validation_signature(
            unsplit_merged,
            snapshot_path=tmp_path / f"preflight-unsplit-{order_label}.canonical.json",
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            query_core_ids=query_core_ids,
        )

        if baseline_snapshot_signature is None:
            baseline_snapshot_signature = unsplit_signature
        else:
            assert unsplit_signature == baseline_snapshot_signature

        for boundaries in checkpoint_boundaries:
            segmented_merged, segmented_conflicts = replay_with_checkpoint_segments(
                ordered_replicas,
                boundaries=boundaries,
            )
            assert (
                KnowledgeStore.conflict_signatures(segmented_conflicts)
                == unsplit_conflict_signatures
            )
            segmented_signature = _preflight_validation_signature(
                segmented_merged,
                snapshot_path=tmp_path / f"preflight-segmented-{order_label}.canonical.json",
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                query_core_ids=query_core_ids,
            )
            assert segmented_signature == unsplit_signature

        duplicate_merged, duplicate_conflicts = replay_stream(
            ordered_replicas,
            start=unsplit_merged,
        )
        resumed_duplicate_merged, resumed_duplicate_conflicts = replay_stream(
            ordered_replicas,
            start=unsplit_merged.checkpoint(),
        )
        assert duplicate_conflicts == ()
        assert resumed_duplicate_conflicts == ()
        assert (
            KnowledgeStore.conflict_signatures(unsplit_conflicts + duplicate_conflicts)
            == unsplit_conflict_signatures
        )
        assert (
            KnowledgeStore.conflict_signatures(
                unsplit_conflicts + resumed_duplicate_conflicts
            )
            == unsplit_conflict_signatures
        )

        duplicate_signature = _preflight_validation_signature(
            duplicate_merged,
            snapshot_path=tmp_path / f"preflight-duplicate-{order_label}.canonical.json",
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            query_core_ids=query_core_ids,
        )
        resumed_duplicate_signature = _preflight_validation_signature(
            resumed_duplicate_merged,
            snapshot_path=tmp_path
            / f"preflight-duplicate-checkpoint-{order_label}.canonical.json",
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            query_core_ids=query_core_ids,
        )
        assert duplicate_signature == unsplit_signature
        assert resumed_duplicate_signature == unsplit_signature

        for boundaries in restart_boundaries:
            restarted_merged, restarted_conflicts = replay_with_restart_snapshots(
                ordered_replicas,
                boundaries=boundaries,
                snapshot_path=tmp_path / f"preflight-restart-{order_label}.canonical.json",
                restart_round_trips=2,
            )
            assert (
                KnowledgeStore.conflict_signatures(restarted_conflicts)
                == unsplit_conflict_signatures
            )
            restarted_signature = _preflight_validation_signature(
                restarted_merged,
                snapshot_path=tmp_path / f"preflight-restarted-{order_label}.canonical.json",
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=valid_at,
                query_core_ids=query_core_ids,
            )
            assert restarted_signature == unsplit_signature
