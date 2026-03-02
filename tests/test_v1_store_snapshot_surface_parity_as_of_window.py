from datetime import datetime, timezone
from pathlib import Path

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    MergeConflict,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)

MergeStream = tuple[tuple[int, MergeResult], ...]


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _force_relation_id(edge: RelationEdge, relation_id: str) -> RelationEdge:
    object.__setattr__(edge, "relation_id", relation_id)
    return edge


def _save_canonical_json(store: KnowledgeStore, snapshot_path: Path) -> None:
    store.to_canonical_json_file(snapshot_path)


def _load_canonical_json(snapshot_path: Path) -> KnowledgeStore:
    return KnowledgeStore.from_canonical_json_file(snapshot_path)


def _assert_revision_ordering(revisions: tuple) -> None:
    revision_ids = tuple(revision.revision_id for revision in revisions)
    assert revision_ids == tuple(sorted(revision_ids))


def _assert_relation_ordering(relations: tuple) -> None:
    relation_ids = tuple(relation.relation_id for relation in relations)
    assert relation_ids == tuple(sorted(relation_ids))


def _assert_signature_ordering(signatures: tuple) -> None:
    assert signatures == tuple(sorted(signatures))


def _assert_merge_conflict_projection_ordering(projection) -> None:
    assert projection.signature_counts == tuple(
        sorted(projection.signature_counts, key=lambda signature_count: signature_count[:3])
    )
    assert projection.code_counts == tuple(
        sorted(projection.code_counts, key=lambda code_count: code_count[0])
    )


def _assert_state_fingerprint_ordering(fingerprint) -> None:
    _assert_revision_ordering(fingerprint.revision_lifecycle.active)
    _assert_revision_ordering(fingerprint.revision_lifecycle.retracted)
    _assert_relation_ordering(fingerprint.relation_resolution.active)
    _assert_relation_ordering(fingerprint.relation_resolution.pending)
    _assert_relation_ordering(fingerprint.relation_lifecycle.active)
    _assert_relation_ordering(fingerprint.relation_lifecycle.pending)
    _assert_signature_ordering(fingerprint.relation_lifecycle_signatures.active)
    _assert_signature_ordering(fingerprint.relation_lifecycle_signatures.pending)
    _assert_merge_conflict_projection_ordering(fingerprint.merge_conflict_projection)


def _revision_signature(revision) -> tuple[str, str, str, int, str]:
    return (
        revision.revision_id,
        revision.core_id,
        revision.status,
        revision.transaction_time.tx_id,
        revision.transaction_time.recorded_at.isoformat(),
    )


def _relation_signature(relation) -> tuple[str, str, str, str, int, str]:
    return (
        relation.relation_id,
        relation.relation_type,
        relation.from_revision_id,
        relation.to_revision_id,
        relation.transaction_time.tx_id,
        relation.transaction_time.recorded_at.isoformat(),
    )


def _revision_projection_signature(projection) -> tuple[tuple, tuple]:
    return (
        tuple(_revision_signature(revision) for revision in projection.active),
        tuple(_revision_signature(revision) for revision in projection.retracted),
    )


def _relation_projection_signature(projection) -> tuple[tuple, tuple]:
    return (
        tuple(_relation_signature(relation) for relation in projection.active),
        tuple(_relation_signature(relation) for relation in projection.pending),
    )


def _conflict_signatures_from_stream(merge_stream: MergeStream) -> tuple:
    conflicts = tuple(
        conflict
        for _merge_tx_id, merge_result in merge_stream
        for conflict in merge_result.conflicts
    )
    return KnowledgeStore.conflict_signatures(conflicts)


def _collect_surface_signature(
    store: KnowledgeStore,
    *,
    merge_stream: MergeStream,
    valid_at: datetime,
    tx_start: int,
    tx_end: int,
    subject_core_id: str,
    retracted_core_id: str,
) -> tuple:
    subject_winner = store.query_as_of(subject_core_id, valid_at=valid_at, tx_id=tx_end)
    assert subject_winner is not None
    subject_revision_id = subject_winner.revision_id

    retracted_winner = store.query_as_of(retracted_core_id, valid_at=valid_at, tx_id=tx_end)
    assert retracted_winner is None

    revision_as_of = store.query_revision_lifecycle_as_of(tx_id=tx_end, valid_at=valid_at)
    revision_window = store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    revision_as_of_filtered = store.query_revision_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    revision_window_filtered = store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    _assert_revision_ordering(revision_as_of.active)
    _assert_revision_ordering(revision_as_of.retracted)
    _assert_revision_ordering(revision_window.active)
    _assert_revision_ordering(revision_window.retracted)
    _assert_revision_ordering(revision_as_of_filtered.active)
    _assert_revision_ordering(revision_as_of_filtered.retracted)
    _assert_revision_ordering(revision_window_filtered.active)
    _assert_revision_ordering(revision_window_filtered.retracted)

    relation_resolution_as_of = store.query_relation_resolution_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )
    relation_resolution_window = store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    relation_resolution_as_of_filtered = store.query_relation_resolution_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    relation_resolution_window_filtered = store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    _assert_relation_ordering(relation_resolution_as_of.active)
    _assert_relation_ordering(relation_resolution_as_of.pending)
    _assert_relation_ordering(relation_resolution_window.active)
    _assert_relation_ordering(relation_resolution_window.pending)
    _assert_relation_ordering(relation_resolution_as_of_filtered.active)
    _assert_relation_ordering(relation_resolution_as_of_filtered.pending)
    _assert_relation_ordering(relation_resolution_window_filtered.active)
    _assert_relation_ordering(relation_resolution_window_filtered.pending)

    relation_lifecycle_as_of = store.query_relation_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )
    relation_lifecycle_window = store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    relation_lifecycle_as_of_filtered = store.query_relation_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        revision_id=subject_revision_id,
    )
    relation_lifecycle_window_filtered = store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        revision_id=subject_revision_id,
    )
    _assert_relation_ordering(relation_lifecycle_as_of.active)
    _assert_relation_ordering(relation_lifecycle_as_of.pending)
    _assert_relation_ordering(relation_lifecycle_window.active)
    _assert_relation_ordering(relation_lifecycle_window.pending)
    _assert_relation_ordering(relation_lifecycle_as_of_filtered.active)
    _assert_relation_ordering(relation_lifecycle_as_of_filtered.pending)
    _assert_relation_ordering(relation_lifecycle_window_filtered.active)
    _assert_relation_ordering(relation_lifecycle_window_filtered.pending)

    merge_conflict_as_of = KnowledgeStore.query_merge_conflict_projection_as_of(
        merge_stream,
        tx_id=tx_end,
    )
    merge_conflict_window = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        merge_stream,
        tx_start=tx_start,
        tx_end=tx_end,
    )
    _assert_merge_conflict_projection_ordering(merge_conflict_as_of)
    _assert_merge_conflict_projection_ordering(merge_conflict_window)

    relation_signatures_as_of = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )
    relation_signatures_window = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    relation_signatures_as_of_filtered = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        revision_id=subject_revision_id,
    )
    relation_signatures_window_filtered = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        revision_id=subject_revision_id,
    )
    _assert_signature_ordering(relation_signatures_as_of.active)
    _assert_signature_ordering(relation_signatures_as_of.pending)
    _assert_signature_ordering(relation_signatures_window.active)
    _assert_signature_ordering(relation_signatures_window.pending)
    _assert_signature_ordering(relation_signatures_as_of_filtered.active)
    _assert_signature_ordering(relation_signatures_as_of_filtered.pending)
    _assert_signature_ordering(relation_signatures_window_filtered.active)
    _assert_signature_ordering(relation_signatures_window_filtered.pending)

    fingerprint_as_of = store.query_state_fingerprint_as_of(tx_id=tx_end, valid_at=valid_at)
    fingerprint_window = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    fingerprint_as_of_filtered = store.query_state_fingerprint_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    fingerprint_window_filtered = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    _assert_state_fingerprint_ordering(fingerprint_as_of)
    _assert_state_fingerprint_ordering(fingerprint_window)
    _assert_state_fingerprint_ordering(fingerprint_as_of_filtered)
    _assert_state_fingerprint_ordering(fingerprint_window_filtered)

    return (
        store.as_canonical_json(),
        store.revision_state_signatures(),
        store.relation_state_signatures(),
        store.pending_relation_ids(),
        _conflict_signatures_from_stream(merge_stream),
        subject_winner.revision_id,
        None if retracted_winner is None else retracted_winner.revision_id,
        _revision_projection_signature(revision_as_of),
        _revision_projection_signature(revision_window),
        _revision_projection_signature(revision_as_of_filtered),
        _revision_projection_signature(revision_window_filtered),
        _relation_projection_signature(relation_resolution_as_of),
        _relation_projection_signature(relation_resolution_window),
        _relation_projection_signature(relation_resolution_as_of_filtered),
        _relation_projection_signature(relation_resolution_window_filtered),
        _relation_projection_signature(relation_lifecycle_as_of),
        _relation_projection_signature(relation_lifecycle_window),
        _relation_projection_signature(relation_lifecycle_as_of_filtered),
        _relation_projection_signature(relation_lifecycle_window_filtered),
        merge_conflict_as_of.summary,
        merge_conflict_window.summary,
        (
            relation_signatures_as_of.active,
            relation_signatures_as_of.pending,
        ),
        (
            relation_signatures_window.active,
            relation_signatures_window.pending,
        ),
        (
            relation_signatures_as_of_filtered.active,
            relation_signatures_as_of_filtered.pending,
        ),
        (
            relation_signatures_window_filtered.active,
            relation_signatures_window_filtered.pending,
        ),
        fingerprint_as_of.as_canonical_json(),
        fingerprint_window.as_canonical_json(),
        fingerprint_as_of_filtered.as_canonical_json(),
        fingerprint_window_filtered.as_canonical_json(),
    )


def _replay_uninterrupted(replicas_by_tx: tuple[tuple[int, KnowledgeStore], ...]) -> tuple[KnowledgeStore, MergeStream]:
    merged = KnowledgeStore()
    merge_stream: list[tuple[int, MergeResult]] = []
    for merge_tx_id, replica in replicas_by_tx:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_stream.append((merge_tx_id, merge_result))
    return merged, tuple(merge_stream)


def _replay_with_payload_json_restarts(
    replicas_by_tx: tuple[tuple[int, KnowledgeStore], ...],
) -> tuple[KnowledgeStore, MergeStream]:
    merged = KnowledgeStore()
    merge_stream: list[tuple[int, MergeResult]] = []
    for index, (merge_tx_id, replica) in enumerate(replicas_by_tx):
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_stream.append((merge_tx_id, merge_result))

        canonical_payload = merged.as_canonical_payload()
        canonical_json = merged.as_canonical_json()
        restored_from_payload = KnowledgeStore.from_canonical_payload(canonical_payload)
        restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)

        assert restored_from_payload.as_canonical_payload() == canonical_payload
        assert restored_from_payload.as_canonical_json() == canonical_json
        assert restored_from_json.as_canonical_payload() == canonical_payload
        assert restored_from_json.as_canonical_json() == canonical_json

        merged = restored_from_payload if index % 2 == 0 else restored_from_json

    return merged, tuple(merge_stream)


def _replay_with_file_restarts(
    replicas_by_tx: tuple[tuple[int, KnowledgeStore], ...],
    *,
    snapshot_path: Path,
) -> tuple[KnowledgeStore, MergeStream]:
    merged = KnowledgeStore()
    merge_stream: list[tuple[int, MergeResult]] = []
    for merge_tx_id, replica in replicas_by_tx:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_stream.append((merge_tx_id, merge_result))

        _save_canonical_json(merged, snapshot_path)
        canonical_file_text = snapshot_path.read_text(encoding="utf-8")
        assert canonical_file_text == merged.as_canonical_json()

        merged = _load_canonical_json(snapshot_path)
        assert merged.as_canonical_json() == canonical_file_text

    return merged, tuple(merge_stream)


def _build_surface_parity_replicas(
    *,
    tx_base: int,
) -> tuple[tuple[tuple[int, KnowledgeStore], ...], datetime, int, int, str, str]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_start = tx_base + 2
    tx_end = tx_base + 7

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-surface-parity-subject-{tx_base}"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": f"store-snapshot-surface-parity-anchor-{tx_base}"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": f"store-snapshot-surface-parity-context-{tx_base}"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-surface-parity-retracted-{tx_base}"},
    )
    core_competing = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-surface-parity-competing-{tx_base}"},
    )

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="store snapshot surface parity anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_surface_parity_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="store snapshot surface parity context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_surface_parity_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="store snapshot surface parity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_surface_parity_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="store snapshot surface parity retracted asserted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(
            source="source_store_snapshot_surface_parity_retracted_asserted"
        ),
        confidence_bp=8300,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="store snapshot surface parity competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_store_snapshot_surface_parity_competing_a"),
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
        assertion="store snapshot surface parity competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_store_snapshot_surface_parity_competing_b"),
        confidence_bp=8200,
        status="asserted",
    )

    replica_collision = KnowledgeStore()
    collision_anchor_revision = replica_collision.assert_revision(
        core=core_anchor,
        assertion="store snapshot surface parity anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_surface_parity_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="store snapshot surface parity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_surface_parity_subject"),
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
        assertion="store snapshot surface parity subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_surface_parity_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_updates.assert_revision(
        core=core_retracted,
        assertion="store snapshot surface parity retracted final",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(
            source="source_store_snapshot_surface_parity_retracted_final"
        ),
        confidence_bp=8300,
        status="retracted",
    )
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_revision_copy.revision_id,
        to_revision_id=f"missing-store-snapshot-surface-parity-endpoint-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 1, 8)),
    )
    replica_updates.relations[orphan_relation.relation_id] = orphan_relation

    return (
        (
            (tx_base + 3, replica_base),
            (tx_base + 4, replica_competing),
            (tx_base + 5, replica_collision),
            (tx_base + 7, replica_updates),
        ),
        valid_at,
        tx_start,
        tx_end,
        core_subject.core_id,
        core_retracted.core_id,
    )


def _merge_conflict_stream_with_surface_extras(
    merge_stream: MergeStream,
    *,
    tx_end: int,
) -> MergeStream:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id=f"store-snapshot-surface-parity-extra-orphan-a-{tx_end}",
        details="extra orphan merge conflict for as-of+tx-window parity",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id=f"store-snapshot-surface-parity-extra-orphan-b-{tx_end}",
        details="extra orphan merge conflict for as-of+tx-window parity",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id=f"store-snapshot-surface-parity-extra-competing-{tx_end}",
        details="extra competing merge conflict for as-of+tx-window parity",
    )
    return merge_stream + (
        (tx_end - 2, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (tx_end - 1, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (tx_end, MergeResult(merged=KnowledgeStore(), conflicts=(competing, orphan_b))),
    )


def test_store_snapshot_surface_parity_as_of_window_payload_json_restore() -> None:
    (
        replicas_by_tx,
        valid_at,
        tx_start,
        tx_end,
        subject_core_id,
        retracted_core_id,
    ) = _build_surface_parity_replicas(tx_base=8410)

    uninterrupted_store, uninterrupted_merge_stream = _replay_uninterrupted(replicas_by_tx)
    uninterrupted_merge_stream = _merge_conflict_stream_with_surface_extras(
        uninterrupted_merge_stream,
        tx_end=tx_end,
    )
    uninterrupted_signature = _collect_surface_signature(
        uninterrupted_store,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
        retracted_core_id=retracted_core_id,
    )

    restarted_store, restarted_merge_stream = _replay_with_payload_json_restarts(replicas_by_tx)
    restarted_merge_stream = _merge_conflict_stream_with_surface_extras(
        restarted_merge_stream,
        tx_end=tx_end,
    )
    assert restarted_store.as_canonical_payload() == uninterrupted_store.as_canonical_payload()
    assert restarted_store.as_canonical_json() == uninterrupted_store.as_canonical_json()
    assert _collect_surface_signature(
        restarted_store,
        merge_stream=restarted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
        retracted_core_id=retracted_core_id,
    ) == uninterrupted_signature

    restored_from_payload = KnowledgeStore.from_canonical_payload(
        uninterrupted_store.as_canonical_payload()
    )
    restored_from_json = KnowledgeStore.from_canonical_json(
        uninterrupted_store.as_canonical_json()
    )
    assert _collect_surface_signature(
        restored_from_payload,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
        retracted_core_id=retracted_core_id,
    ) == uninterrupted_signature
    assert _collect_surface_signature(
        restored_from_json,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
        retracted_core_id=retracted_core_id,
    ) == uninterrupted_signature


def test_store_snapshot_surface_parity_as_of_window_file_restore(tmp_path: Path) -> None:
    (
        replicas_by_tx,
        valid_at,
        tx_start,
        tx_end,
        subject_core_id,
        retracted_core_id,
    ) = _build_surface_parity_replicas(tx_base=8530)

    uninterrupted_store, uninterrupted_merge_stream = _replay_uninterrupted(replicas_by_tx)
    uninterrupted_merge_stream = _merge_conflict_stream_with_surface_extras(
        uninterrupted_merge_stream,
        tx_end=tx_end,
    )
    uninterrupted_signature = _collect_surface_signature(
        uninterrupted_store,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
        retracted_core_id=retracted_core_id,
    )

    snapshot_path = tmp_path / "surface-parity-as-of-window.snapshot.canonical.json"
    restarted_store, restarted_merge_stream = _replay_with_file_restarts(
        replicas_by_tx,
        snapshot_path=snapshot_path,
    )
    restarted_merge_stream = _merge_conflict_stream_with_surface_extras(
        restarted_merge_stream,
        tx_end=tx_end,
    )
    assert restarted_store.as_canonical_payload() == uninterrupted_store.as_canonical_payload()
    assert restarted_store.as_canonical_json() == uninterrupted_store.as_canonical_json()
    assert _collect_surface_signature(
        restarted_store,
        merge_stream=restarted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
        retracted_core_id=retracted_core_id,
    ) == uninterrupted_signature

    _save_canonical_json(uninterrupted_store, snapshot_path)
    restored_from_file = _load_canonical_json(snapshot_path)
    assert _collect_surface_signature(
        restored_from_file,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
        retracted_core_id=retracted_core_id,
    ) == uninterrupted_signature
