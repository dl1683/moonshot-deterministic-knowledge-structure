from dataclasses import dataclass
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


def _assert_signature_counts_ordering(
    signature_counts: tuple[tuple[str, str, str, int], ...],
) -> None:
    assert signature_counts == tuple(
        sorted(
            signature_counts,
            key=lambda signature_count: (
                signature_count[0],
                signature_count[1],
                signature_count[2],
            ),
        )
    )


def _assert_code_counts_ordering(code_counts: tuple[tuple[str, int], ...]) -> None:
    assert code_counts == tuple(
        sorted(
            code_counts,
            key=lambda code_count: code_count[0],
        )
    )


def _assert_revision_transition_ordering(transition) -> None:
    _assert_revision_ordering(transition.entered_active)
    _assert_revision_ordering(transition.exited_active)
    _assert_revision_ordering(transition.entered_retracted)
    _assert_revision_ordering(transition.exited_retracted)


def _assert_relation_transition_ordering(transition) -> None:
    _assert_relation_ordering(transition.entered_active)
    _assert_relation_ordering(transition.exited_active)
    _assert_relation_ordering(transition.entered_pending)
    _assert_relation_ordering(transition.exited_pending)


def _assert_merge_conflict_transition_ordering(transition) -> None:
    _assert_signature_counts_ordering(transition.entered_signature_counts)
    _assert_signature_counts_ordering(transition.exited_signature_counts)
    _assert_code_counts_ordering(transition.entered_code_counts)
    _assert_code_counts_ordering(transition.exited_code_counts)


def _assert_signature_transition_ordering(transition) -> None:
    _assert_signature_ordering(transition.entered_active)
    _assert_signature_ordering(transition.exited_active)
    _assert_signature_ordering(transition.entered_pending)
    _assert_signature_ordering(transition.exited_pending)


def _state_fingerprint_transition_bucket_map(transition) -> dict[str, tuple]:
    return {
        "entered_revision_active": transition.entered_revision_active,
        "exited_revision_active": transition.exited_revision_active,
        "entered_revision_retracted": transition.entered_revision_retracted,
        "exited_revision_retracted": transition.exited_revision_retracted,
        "entered_relation_resolution_active": transition.entered_relation_resolution_active,
        "exited_relation_resolution_active": transition.exited_relation_resolution_active,
        "entered_relation_resolution_pending": transition.entered_relation_resolution_pending,
        "exited_relation_resolution_pending": transition.exited_relation_resolution_pending,
        "entered_relation_lifecycle_active": transition.entered_relation_lifecycle_active,
        "exited_relation_lifecycle_active": transition.exited_relation_lifecycle_active,
        "entered_relation_lifecycle_pending": transition.entered_relation_lifecycle_pending,
        "exited_relation_lifecycle_pending": transition.exited_relation_lifecycle_pending,
        "entered_relation_lifecycle_signature_active": transition.entered_relation_lifecycle_signature_active,
        "exited_relation_lifecycle_signature_active": transition.exited_relation_lifecycle_signature_active,
        "entered_relation_lifecycle_signature_pending": transition.entered_relation_lifecycle_signature_pending,
        "exited_relation_lifecycle_signature_pending": transition.exited_relation_lifecycle_signature_pending,
        "entered_merge_conflict_signature_counts": transition.entered_merge_conflict_signature_counts,
        "exited_merge_conflict_signature_counts": transition.exited_merge_conflict_signature_counts,
        "entered_merge_conflict_code_counts": transition.entered_merge_conflict_code_counts,
        "exited_merge_conflict_code_counts": transition.exited_merge_conflict_code_counts,
    }


def _assert_state_fingerprint_transition_ordering(transition) -> None:
    _assert_revision_ordering(transition.entered_revision_active)
    _assert_revision_ordering(transition.exited_revision_active)
    _assert_revision_ordering(transition.entered_revision_retracted)
    _assert_revision_ordering(transition.exited_revision_retracted)

    _assert_relation_ordering(transition.entered_relation_resolution_active)
    _assert_relation_ordering(transition.exited_relation_resolution_active)
    _assert_relation_ordering(transition.entered_relation_resolution_pending)
    _assert_relation_ordering(transition.exited_relation_resolution_pending)

    _assert_relation_ordering(transition.entered_relation_lifecycle_active)
    _assert_relation_ordering(transition.exited_relation_lifecycle_active)
    _assert_relation_ordering(transition.entered_relation_lifecycle_pending)
    _assert_relation_ordering(transition.exited_relation_lifecycle_pending)

    _assert_signature_ordering(transition.entered_relation_lifecycle_signature_active)
    _assert_signature_ordering(transition.exited_relation_lifecycle_signature_active)
    _assert_signature_ordering(transition.entered_relation_lifecycle_signature_pending)
    _assert_signature_ordering(transition.exited_relation_lifecycle_signature_pending)

    _assert_signature_counts_ordering(transition.entered_merge_conflict_signature_counts)
    _assert_signature_counts_ordering(transition.exited_merge_conflict_signature_counts)
    _assert_code_counts_ordering(transition.entered_merge_conflict_code_counts)
    _assert_code_counts_ordering(transition.exited_merge_conflict_code_counts)


def _revision_transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_active,
        transition.exited_active,
        transition.entered_retracted,
        transition.exited_retracted,
    )


def _relation_transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def _signature_transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def _merge_conflict_transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_signature_counts,
        transition.exited_signature_counts,
        transition.entered_code_counts,
        transition.exited_code_counts,
    )


def _merge_conflict_transition_has_delta(transition) -> bool:
    return any(_merge_conflict_transition_buckets(transition))


def _relation_state_signature(
    bucket: str,
    relation: RelationEdge,
) -> tuple[str, str, str, str, str, int, str]:
    return (
        bucket,
        relation.relation_id,
        relation.relation_type,
        relation.from_revision_id,
        relation.to_revision_id,
        relation.transaction_time.tx_id,
        relation.transaction_time.recorded_at.isoformat(),
    )


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


def _revision_transition_signature(transition) -> tuple:
    return (
        transition.tx_from,
        transition.tx_to,
        tuple(_revision_signature(revision) for revision in transition.entered_active),
        tuple(_revision_signature(revision) for revision in transition.exited_active),
        tuple(_revision_signature(revision) for revision in transition.entered_retracted),
        tuple(_revision_signature(revision) for revision in transition.exited_retracted),
    )


def _relation_transition_signature(transition) -> tuple:
    return (
        transition.tx_from,
        transition.tx_to,
        tuple(_relation_signature(relation) for relation in transition.entered_active),
        tuple(_relation_signature(relation) for relation in transition.exited_active),
        tuple(_relation_signature(relation) for relation in transition.entered_pending),
        tuple(_relation_signature(relation) for relation in transition.exited_pending),
    )


def _merge_conflict_transition_signature(transition) -> tuple:
    return (
        transition.tx_from,
        transition.tx_to,
        transition.entered_signature_counts,
        transition.exited_signature_counts,
        transition.entered_code_counts,
        transition.exited_code_counts,
    )


def _signature_transition_signature(transition) -> tuple:
    return (
        transition.valid_from.isoformat(),
        transition.valid_to.isoformat(),
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def _state_fingerprint_transition_signature(transition) -> tuple:
    return (
        transition.tx_from,
        transition.tx_to,
        transition.from_digest,
        transition.to_digest,
        tuple(_revision_signature(revision) for revision in transition.entered_revision_active),
        tuple(_revision_signature(revision) for revision in transition.exited_revision_active),
        tuple(
            _revision_signature(revision)
            for revision in transition.entered_revision_retracted
        ),
        tuple(
            _revision_signature(revision)
            for revision in transition.exited_revision_retracted
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.entered_relation_resolution_active
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.exited_relation_resolution_active
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.entered_relation_resolution_pending
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.exited_relation_resolution_pending
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.entered_relation_lifecycle_active
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.exited_relation_lifecycle_active
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.entered_relation_lifecycle_pending
        ),
        tuple(
            _relation_signature(relation)
            for relation in transition.exited_relation_lifecycle_pending
        ),
        transition.entered_relation_lifecycle_signature_active,
        transition.exited_relation_lifecycle_signature_active,
        transition.entered_relation_lifecycle_signature_pending,
        transition.exited_relation_lifecycle_signature_pending,
        transition.entered_merge_conflict_signature_counts,
        transition.exited_merge_conflict_signature_counts,
        transition.entered_merge_conflict_code_counts,
        transition.exited_merge_conflict_code_counts,
    )


def _conflict_signatures_from_stream(merge_stream: MergeStream) -> tuple:
    conflicts = tuple(
        conflict
        for _merge_tx_id, merge_result in merge_stream
        for conflict in merge_result.conflicts
    )
    return KnowledgeStore.conflict_signatures(conflicts)


@dataclass(frozen=True)
class TransitionSurfaceScenario:
    valid_at: datetime
    tx_from: int
    tx_to: int
    tx_base: int
    subject_core_id: str
    anchor_core_id: str
    anchor_revision_id: str
    signature_revision_id: str
    signature_valid_from: datetime
    signature_valid_to: datetime
    revision_start_boundary_revision_id: str
    revision_end_boundary_revision_id: str
    relation_start_boundary_relation_id: str
    relation_end_boundary_relation_id: str
    signature_start_boundary: tuple[str, str, str, str, str, int, str]
    signature_end_boundary: tuple[str, str, str, str, str, int, str]


def _build_transition_surface_parity_replicas(
    *,
    tx_base: int,
) -> tuple[tuple[tuple[int, KnowledgeStore], ...], TransitionSurfaceScenario]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    signature_valid_from = dt(2024, 3, 1)
    signature_valid_to = dt(2024, 6, 1)
    tx_from = tx_base + 2
    tx_to = tx_base + 7

    core_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-transition-subject-{tx_base}"},
    )
    core_anchor = ClaimCore(
        claim_type="document",
        slots={"id": f"store-snapshot-transition-anchor-{tx_base}"},
    )
    core_context = ClaimCore(
        claim_type="fact",
        slots={"id": f"store-snapshot-transition-context-{tx_base}"},
    )
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-transition-retracted-{tx_base}"},
    )
    core_competing = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-transition-competing-{tx_base}"},
    )
    core_boundary_end = ClaimCore(
        claim_type="document",
        slots={"id": f"store-snapshot-transition-boundary-end-{tx_base}"},
    )
    core_signature_subject = ClaimCore(
        claim_type="residence",
        slots={"subject": f"store-snapshot-transition-signature-subject-{tx_base}"},
    )
    core_signature_evidence = ClaimCore(
        claim_type="document",
        slots={"id": f"store-snapshot-transition-signature-evidence-{tx_base}"},
    )

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=core_anchor,
        assertion="store snapshot transition anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_transition_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = replica_base.assert_revision(
        core=core_context,
        assertion="store snapshot transition context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_transition_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision = replica_base.assert_revision(
        core=core_subject,
        assertion="store snapshot transition subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_transition_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_retracted,
        assertion="store snapshot transition retracted asserted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(
            source="source_store_snapshot_transition_retracted_asserted"
        ),
        confidence_bp=8300,
        status="asserted",
    )
    replica_base.assert_revision(
        core=core_competing,
        assertion="store snapshot transition competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_store_snapshot_transition_competing_a"),
        confidence_bp=8200,
        status="asserted",
    )

    signature_evidence_revision = replica_base.assert_revision(
        core=core_signature_evidence,
        assertion="store snapshot transition signature evidence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(
            source="source_store_snapshot_transition_signature_evidence"
        ),
        confidence_bp=9200,
        status="asserted",
    )
    signature_early_revision = replica_base.assert_revision(
        core=core_signature_subject,
        assertion="store snapshot transition signature subject",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=dt(2024, 4, 1)),
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_transition_signature_early"),
        confidence_bp=7300,
        status="asserted",
    )
    signature_late_revision = replica_base.assert_revision(
        core=core_signature_subject,
        assertion="store snapshot transition signature subject",
        valid_time=ValidTime(start=dt(2024, 4, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 4, 2)),
        provenance=Provenance(source="source_store_snapshot_transition_signature_late"),
        confidence_bp=7400,
        status="asserted",
    )

    canonical_relation = replica_base.attach_relation(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
    )
    context_relation = replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=context_revision.revision_id,
        to_revision_id=subject_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
    )
    signature_active_early_relation = replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=signature_early_revision.revision_id,
        to_revision_id=signature_evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 5, recorded_at=dt(2024, 2, 1)),
    )
    signature_active_late_relation = replica_base.attach_relation(
        relation_type="derived_from",
        from_revision_id=signature_late_revision.revision_id,
        to_revision_id=signature_evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 5, 1)),
    )

    replica_competing = KnowledgeStore()
    replica_competing.assert_revision(
        core=core_competing,
        assertion="store snapshot transition competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_store_snapshot_transition_competing_b"),
        confidence_bp=8200,
        status="asserted",
    )

    replica_collision = KnowledgeStore()
    collision_anchor_revision = replica_collision.assert_revision(
        core=core_anchor,
        assertion="store snapshot transition anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_store_snapshot_transition_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    collision_subject_revision = replica_collision.assert_revision(
        core=core_subject,
        assertion="store snapshot transition subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_transition_subject"),
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
        assertion="store snapshot transition subject",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_store_snapshot_transition_subject"),
        confidence_bp=8400,
        status="asserted",
    )
    replica_updates.assert_revision(
        core=core_retracted,
        assertion="store snapshot transition retracted final",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_store_snapshot_transition_retracted_final"),
        confidence_bp=8300,
        status="retracted",
    )
    boundary_end_revision = replica_updates.assert_revision(
        core=core_boundary_end,
        assertion="store snapshot transition boundary end",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_store_snapshot_transition_boundary_end"),
        confidence_bp=9050,
        status="asserted",
    )
    signature_late_revision_copy = replica_updates.assert_revision(
        core=core_signature_subject,
        assertion="store snapshot transition signature subject",
        valid_time=ValidTime(start=dt(2024, 4, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 4, 2)),
        provenance=Provenance(source="source_store_snapshot_transition_signature_late"),
        confidence_bp=7400,
        status="asserted",
    )

    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_revision_copy.revision_id,
        to_revision_id=f"missing-store-snapshot-transition-endpoint-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 1, 8)),
    )
    pending_signature_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=signature_late_revision_copy.revision_id,
        to_revision_id=f"missing-store-snapshot-transition-signature-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 4, 15)),
    )
    replica_updates.relations[orphan_relation.relation_id] = orphan_relation
    replica_updates.relations[
        pending_signature_relation.relation_id
    ] = pending_signature_relation

    scenario = TransitionSurfaceScenario(
        valid_at=valid_at,
        tx_from=tx_from,
        tx_to=tx_to,
        tx_base=tx_base,
        subject_core_id=core_subject.core_id,
        anchor_core_id=core_anchor.core_id,
        anchor_revision_id=anchor_revision.revision_id,
        signature_revision_id=signature_evidence_revision.revision_id,
        signature_valid_from=signature_valid_from,
        signature_valid_to=signature_valid_to,
        revision_start_boundary_revision_id=subject_revision.revision_id,
        revision_end_boundary_revision_id=boundary_end_revision.revision_id,
        relation_start_boundary_relation_id=context_relation.relation_id,
        relation_end_boundary_relation_id=signature_active_late_relation.relation_id,
        signature_start_boundary=_relation_state_signature(
            "active",
            signature_active_early_relation,
        ),
        signature_end_boundary=_relation_state_signature(
            "active",
            signature_active_late_relation,
        ),
    )

    return (
        (
            (tx_base + 3, replica_base),
            (tx_base + 4, replica_competing),
            (tx_base + 5, replica_collision),
            (tx_base + 7, replica_updates),
        ),
        scenario,
    )


def _merge_conflict_stream_with_surface_extras(
    merge_stream: MergeStream,
    *,
    tx_base: int,
) -> MergeStream:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id=f"store-snapshot-transition-extra-orphan-a-{tx_base}",
        details="extra orphan merge conflict for transition parity",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id=f"store-snapshot-transition-extra-orphan-b-{tx_base}",
        details="extra orphan merge conflict for transition parity",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id=f"store-snapshot-transition-extra-competing-{tx_base}",
        details="extra competing merge conflict for transition parity",
    )
    return merge_stream + (
        (tx_base + 5, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (
            tx_base + 6,
            MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b)),
        ),
        (
            tx_base + 7,
            MergeResult(merged=KnowledgeStore(), conflicts=(competing, orphan_b)),
        ),
    )


def _replay_uninterrupted(
    replicas_by_tx: tuple[tuple[int, KnowledgeStore], ...],
) -> tuple[KnowledgeStore, MergeStream]:
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


def _collect_transition_surface_signature(
    store: KnowledgeStore,
    *,
    merge_stream: MergeStream,
    scenario: TransitionSurfaceScenario,
) -> tuple:
    valid_at = scenario.valid_at
    tx_from = scenario.tx_from
    tx_to = scenario.tx_to
    tx_base = scenario.tx_base

    revision_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    filtered_revision_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=scenario.subject_core_id,
    )
    zero_delta_revision_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_to,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    boundary_start_inclusive_revision = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_base + 1,
        tx_to=tx_base + 2,
        valid_at=valid_at,
    )
    boundary_start_exclusive_revision = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_base + 2,
        tx_to=tx_base + 2,
        valid_at=valid_at,
    )
    boundary_end_inclusive_revision = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_base + 6,
        tx_to=tx_base + 7,
        valid_at=valid_at,
    )
    boundary_end_exclusive_revision = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_base + 6,
        tx_to=tx_base + 6,
        valid_at=valid_at,
    )
    for transition in (
        revision_transition,
        filtered_revision_transition,
        zero_delta_revision_transition,
        boundary_start_inclusive_revision,
        boundary_start_exclusive_revision,
        boundary_end_inclusive_revision,
        boundary_end_exclusive_revision,
    ):
        _assert_revision_transition_ordering(transition)
    assert _revision_transition_buckets(zero_delta_revision_transition) == ((), (), (), ())
    assert any(
        revision.revision_id == scenario.revision_start_boundary_revision_id
        for revision in boundary_start_inclusive_revision.entered_active
    )
    assert boundary_start_exclusive_revision.entered_active == ()
    assert any(
        revision.revision_id == scenario.revision_end_boundary_revision_id
        for revision in boundary_end_inclusive_revision.entered_active
    )
    assert boundary_end_exclusive_revision.entered_active == ()

    resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    filtered_resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=scenario.anchor_core_id,
    )
    zero_delta_resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_to,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    boundary_start_inclusive_resolution = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_base + 2,
        tx_to=tx_base + 3,
        valid_at=valid_at,
    )
    boundary_start_exclusive_resolution = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_base + 3,
        tx_to=tx_base + 3,
        valid_at=valid_at,
    )
    boundary_end_inclusive_resolution = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_base + 6,
        tx_to=tx_base + 7,
        valid_at=valid_at,
    )
    boundary_end_exclusive_resolution = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_base + 6,
        tx_to=tx_base + 6,
        valid_at=valid_at,
    )
    for transition in (
        resolution_transition,
        filtered_resolution_transition,
        zero_delta_resolution_transition,
        boundary_start_inclusive_resolution,
        boundary_start_exclusive_resolution,
        boundary_end_inclusive_resolution,
        boundary_end_exclusive_resolution,
    ):
        _assert_relation_transition_ordering(transition)
    assert _relation_transition_buckets(zero_delta_resolution_transition) == ((), (), (), ())
    assert scenario.relation_start_boundary_relation_id in {
        relation.relation_id for relation in boundary_start_inclusive_resolution.entered_active
    }
    assert boundary_start_exclusive_resolution.entered_active == ()
    assert scenario.relation_end_boundary_relation_id in {
        relation.relation_id for relation in boundary_end_inclusive_resolution.entered_active
    }
    assert boundary_end_exclusive_resolution.entered_active == ()

    lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    filtered_lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        revision_id=scenario.anchor_revision_id,
    )
    zero_delta_lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_to,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    boundary_start_inclusive_lifecycle = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_base + 2,
        tx_to=tx_base + 3,
        valid_at=valid_at,
    )
    boundary_start_exclusive_lifecycle = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_base + 3,
        tx_to=tx_base + 3,
        valid_at=valid_at,
    )
    boundary_end_inclusive_lifecycle = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_base + 6,
        tx_to=tx_base + 7,
        valid_at=valid_at,
    )
    boundary_end_exclusive_lifecycle = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_base + 6,
        tx_to=tx_base + 6,
        valid_at=valid_at,
    )
    for transition in (
        lifecycle_transition,
        filtered_lifecycle_transition,
        zero_delta_lifecycle_transition,
        boundary_start_inclusive_lifecycle,
        boundary_start_exclusive_lifecycle,
        boundary_end_inclusive_lifecycle,
        boundary_end_exclusive_lifecycle,
    ):
        _assert_relation_transition_ordering(transition)
    assert _relation_transition_buckets(zero_delta_lifecycle_transition) == ((), (), (), ())
    assert scenario.relation_start_boundary_relation_id in {
        relation.relation_id for relation in boundary_start_inclusive_lifecycle.entered_active
    }
    assert boundary_start_exclusive_lifecycle.entered_active == ()
    assert scenario.relation_end_boundary_relation_id in {
        relation.relation_id for relation in boundary_end_inclusive_lifecycle.entered_active
    }
    assert boundary_end_exclusive_lifecycle.entered_active == ()

    merge_conflict_transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        merge_stream,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    zero_delta_merge_conflict_transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        merge_stream,
        tx_from=tx_to,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    boundary_start_inclusive_merge_conflict_transition = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            merge_stream,
            tx_from=tx_base + 4,
            tx_to=tx_base + 5,
            valid_at=valid_at,
        )
    )
    boundary_start_exclusive_merge_conflict_transition = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            merge_stream,
            tx_from=tx_base + 5,
            tx_to=tx_base + 5,
            valid_at=valid_at,
        )
    )
    boundary_end_inclusive_merge_conflict_transition = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            merge_stream,
            tx_from=tx_base + 6,
            tx_to=tx_base + 7,
            valid_at=valid_at,
        )
    )
    boundary_end_exclusive_merge_conflict_transition = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            merge_stream,
            tx_from=tx_base + 6,
            tx_to=tx_base + 6,
            valid_at=valid_at,
        )
    )
    for transition in (
        merge_conflict_transition,
        zero_delta_merge_conflict_transition,
        boundary_start_inclusive_merge_conflict_transition,
        boundary_start_exclusive_merge_conflict_transition,
        boundary_end_inclusive_merge_conflict_transition,
        boundary_end_exclusive_merge_conflict_transition,
    ):
        _assert_merge_conflict_transition_ordering(transition)
    assert _merge_conflict_transition_buckets(zero_delta_merge_conflict_transition) == (
        (),
        (),
        (),
        (),
    )
    assert _merge_conflict_transition_has_delta(
        boundary_start_inclusive_merge_conflict_transition
    )
    assert not _merge_conflict_transition_has_delta(
        boundary_start_exclusive_merge_conflict_transition
    )
    assert _merge_conflict_transition_has_delta(
        boundary_end_inclusive_merge_conflict_transition
    )
    assert not _merge_conflict_transition_has_delta(
        boundary_end_exclusive_merge_conflict_transition
    )

    relation_signature_transition = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_from=scenario.signature_valid_from,
        valid_to=scenario.signature_valid_to,
    )
    filtered_relation_signature_transition = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_from=scenario.signature_valid_from,
        valid_to=scenario.signature_valid_to,
        revision_id=scenario.signature_revision_id,
    )
    zero_delta_relation_signature_transition = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_from=scenario.signature_valid_to,
        valid_to=scenario.signature_valid_to,
    )
    boundary_start_inclusive_relation_signature_transition = (
        store.query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=tx_base + 5,
            tx_end=tx_base + 7,
            valid_from=scenario.signature_valid_from,
            valid_to=scenario.signature_valid_to,
        )
    )
    boundary_start_exclusive_relation_signature_transition = (
        store.query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=tx_base + 6,
            tx_end=tx_base + 7,
            valid_from=scenario.signature_valid_from,
            valid_to=scenario.signature_valid_to,
        )
    )
    boundary_end_inclusive_relation_signature_transition = (
        store.query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=tx_base + 6,
            tx_end=tx_base + 7,
            valid_from=scenario.signature_valid_from,
            valid_to=scenario.signature_valid_to,
        )
    )
    boundary_end_exclusive_relation_signature_transition = (
        store.query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=tx_base + 6,
            tx_end=tx_base + 6,
            valid_from=scenario.signature_valid_from,
            valid_to=scenario.signature_valid_to,
        )
    )
    for transition in (
        relation_signature_transition,
        filtered_relation_signature_transition,
        zero_delta_relation_signature_transition,
        boundary_start_inclusive_relation_signature_transition,
        boundary_start_exclusive_relation_signature_transition,
        boundary_end_inclusive_relation_signature_transition,
        boundary_end_exclusive_relation_signature_transition,
    ):
        _assert_signature_transition_ordering(transition)
    assert _signature_transition_buckets(zero_delta_relation_signature_transition) == (
        (),
        (),
        (),
        (),
    )
    assert scenario.signature_start_boundary in (
        boundary_start_inclusive_relation_signature_transition.exited_active
    )
    assert boundary_start_exclusive_relation_signature_transition.exited_active == ()
    assert scenario.signature_end_boundary in (
        boundary_end_inclusive_relation_signature_transition.entered_active
    )
    assert boundary_end_exclusive_relation_signature_transition.entered_active == ()

    state_fingerprint_transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    filtered_state_fingerprint_transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=scenario.subject_core_id,
    )
    zero_delta_state_fingerprint_transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_to,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    boundary_start_inclusive_state_fingerprint_transition = (
        store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_base + 1,
            tx_to=tx_base + 2,
            valid_at=valid_at,
        )
    )
    boundary_start_exclusive_state_fingerprint_transition = (
        store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_base + 2,
            tx_to=tx_base + 2,
            valid_at=valid_at,
        )
    )
    boundary_end_inclusive_state_fingerprint_transition = (
        store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_base + 6,
            tx_to=tx_base + 7,
            valid_at=valid_at,
        )
    )
    boundary_end_exclusive_state_fingerprint_transition = (
        store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_base + 6,
            tx_to=tx_base + 6,
            valid_at=valid_at,
        )
    )
    for transition in (
        state_fingerprint_transition,
        filtered_state_fingerprint_transition,
        zero_delta_state_fingerprint_transition,
        boundary_start_inclusive_state_fingerprint_transition,
        boundary_start_exclusive_state_fingerprint_transition,
        boundary_end_inclusive_state_fingerprint_transition,
        boundary_end_exclusive_state_fingerprint_transition,
    ):
        _assert_state_fingerprint_transition_ordering(transition)
    assert (
        zero_delta_state_fingerprint_transition.from_digest
        == zero_delta_state_fingerprint_transition.to_digest
    )
    for bucket in _state_fingerprint_transition_bucket_map(
        zero_delta_state_fingerprint_transition
    ).values():
        assert bucket == ()
    assert any(
        revision.revision_id == scenario.revision_start_boundary_revision_id
        for revision in boundary_start_inclusive_state_fingerprint_transition.entered_revision_active
    )
    for bucket in _state_fingerprint_transition_bucket_map(
        boundary_start_exclusive_state_fingerprint_transition
    ).values():
        assert bucket == ()
    assert any(
        revision.revision_id == scenario.revision_end_boundary_revision_id
        for revision in boundary_end_inclusive_state_fingerprint_transition.entered_revision_active
    )
    for bucket in _state_fingerprint_transition_bucket_map(
        boundary_end_exclusive_state_fingerprint_transition
    ).values():
        assert bucket == ()

    return (
        store.as_canonical_json(),
        store.revision_state_signatures(),
        store.relation_state_signatures(),
        store.pending_relation_ids(),
        _conflict_signatures_from_stream(merge_stream),
        _revision_transition_signature(revision_transition),
        _revision_transition_signature(filtered_revision_transition),
        _revision_transition_signature(zero_delta_revision_transition),
        _revision_transition_signature(boundary_start_inclusive_revision),
        _revision_transition_signature(boundary_start_exclusive_revision),
        _revision_transition_signature(boundary_end_inclusive_revision),
        _revision_transition_signature(boundary_end_exclusive_revision),
        _relation_transition_signature(resolution_transition),
        _relation_transition_signature(filtered_resolution_transition),
        _relation_transition_signature(zero_delta_resolution_transition),
        _relation_transition_signature(boundary_start_inclusive_resolution),
        _relation_transition_signature(boundary_start_exclusive_resolution),
        _relation_transition_signature(boundary_end_inclusive_resolution),
        _relation_transition_signature(boundary_end_exclusive_resolution),
        _relation_transition_signature(lifecycle_transition),
        _relation_transition_signature(filtered_lifecycle_transition),
        _relation_transition_signature(zero_delta_lifecycle_transition),
        _relation_transition_signature(boundary_start_inclusive_lifecycle),
        _relation_transition_signature(boundary_start_exclusive_lifecycle),
        _relation_transition_signature(boundary_end_inclusive_lifecycle),
        _relation_transition_signature(boundary_end_exclusive_lifecycle),
        _merge_conflict_transition_signature(merge_conflict_transition),
        _merge_conflict_transition_signature(zero_delta_merge_conflict_transition),
        _merge_conflict_transition_signature(
            boundary_start_inclusive_merge_conflict_transition
        ),
        _merge_conflict_transition_signature(
            boundary_start_exclusive_merge_conflict_transition
        ),
        _merge_conflict_transition_signature(
            boundary_end_inclusive_merge_conflict_transition
        ),
        _merge_conflict_transition_signature(
            boundary_end_exclusive_merge_conflict_transition
        ),
        _signature_transition_signature(relation_signature_transition),
        _signature_transition_signature(filtered_relation_signature_transition),
        _signature_transition_signature(zero_delta_relation_signature_transition),
        _signature_transition_signature(
            boundary_start_inclusive_relation_signature_transition
        ),
        _signature_transition_signature(
            boundary_start_exclusive_relation_signature_transition
        ),
        _signature_transition_signature(boundary_end_inclusive_relation_signature_transition),
        _signature_transition_signature(boundary_end_exclusive_relation_signature_transition),
        _state_fingerprint_transition_signature(state_fingerprint_transition),
        _state_fingerprint_transition_signature(filtered_state_fingerprint_transition),
        _state_fingerprint_transition_signature(zero_delta_state_fingerprint_transition),
        _state_fingerprint_transition_signature(
            boundary_start_inclusive_state_fingerprint_transition
        ),
        _state_fingerprint_transition_signature(
            boundary_start_exclusive_state_fingerprint_transition
        ),
        _state_fingerprint_transition_signature(
            boundary_end_inclusive_state_fingerprint_transition
        ),
        _state_fingerprint_transition_signature(
            boundary_end_exclusive_state_fingerprint_transition
        ),
    )


def test_store_snapshot_surface_parity_transitions_payload_json_restore() -> None:
    replicas_by_tx, scenario = _build_transition_surface_parity_replicas(tx_base=8920)

    uninterrupted_store, uninterrupted_merge_stream = _replay_uninterrupted(replicas_by_tx)
    uninterrupted_merge_stream = _merge_conflict_stream_with_surface_extras(
        uninterrupted_merge_stream,
        tx_base=scenario.tx_base,
    )
    uninterrupted_signature = _collect_transition_surface_signature(
        uninterrupted_store,
        merge_stream=uninterrupted_merge_stream,
        scenario=scenario,
    )

    restarted_store, restarted_merge_stream = _replay_with_payload_json_restarts(replicas_by_tx)
    restarted_merge_stream = _merge_conflict_stream_with_surface_extras(
        restarted_merge_stream,
        tx_base=scenario.tx_base,
    )
    assert restarted_store.as_canonical_payload() == uninterrupted_store.as_canonical_payload()
    assert restarted_store.as_canonical_json() == uninterrupted_store.as_canonical_json()
    assert _collect_transition_surface_signature(
        restarted_store,
        merge_stream=restarted_merge_stream,
        scenario=scenario,
    ) == uninterrupted_signature

    restored_from_payload = KnowledgeStore.from_canonical_payload(
        uninterrupted_store.as_canonical_payload()
    )
    restored_from_json = KnowledgeStore.from_canonical_json(
        uninterrupted_store.as_canonical_json()
    )
    assert _collect_transition_surface_signature(
        restored_from_payload,
        merge_stream=uninterrupted_merge_stream,
        scenario=scenario,
    ) == uninterrupted_signature
    assert _collect_transition_surface_signature(
        restored_from_json,
        merge_stream=uninterrupted_merge_stream,
        scenario=scenario,
    ) == uninterrupted_signature


def test_store_snapshot_surface_parity_transitions_file_restore(tmp_path: Path) -> None:
    replicas_by_tx, scenario = _build_transition_surface_parity_replicas(tx_base=9050)

    uninterrupted_store, uninterrupted_merge_stream = _replay_uninterrupted(replicas_by_tx)
    uninterrupted_merge_stream = _merge_conflict_stream_with_surface_extras(
        uninterrupted_merge_stream,
        tx_base=scenario.tx_base,
    )
    uninterrupted_signature = _collect_transition_surface_signature(
        uninterrupted_store,
        merge_stream=uninterrupted_merge_stream,
        scenario=scenario,
    )

    snapshot_path = tmp_path / "surface-parity-transitions.snapshot.canonical.json"
    restarted_store, restarted_merge_stream = _replay_with_file_restarts(
        replicas_by_tx,
        snapshot_path=snapshot_path,
    )
    restarted_merge_stream = _merge_conflict_stream_with_surface_extras(
        restarted_merge_stream,
        tx_base=scenario.tx_base,
    )
    assert restarted_store.as_canonical_payload() == uninterrupted_store.as_canonical_payload()
    assert restarted_store.as_canonical_json() == uninterrupted_store.as_canonical_json()
    assert _collect_transition_surface_signature(
        restarted_store,
        merge_stream=restarted_merge_stream,
        scenario=scenario,
    ) == uninterrupted_signature

    _save_canonical_json(uninterrupted_store, snapshot_path)
    restored_from_file = _load_canonical_json(snapshot_path)
    assert _collect_transition_surface_signature(
        restored_from_file,
        merge_stream=uninterrupted_merge_stream,
        scenario=scenario,
    ) == uninterrupted_signature
