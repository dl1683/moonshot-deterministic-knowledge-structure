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


def relation_state_signature(bucket: str, relation: RelationEdge) -> tuple[str, str, str, str, str, int, str]:
    return (
        bucket,
        relation.relation_id,
        relation.relation_type,
        relation.from_revision_id,
        relation.to_revision_id,
        relation.transaction_time.tx_id,
        relation.transaction_time.recorded_at.isoformat(),
    )


def _assert_projection_ordering(projection) -> None:
    assert projection.active == tuple(sorted(projection.active))
    assert projection.pending == tuple(sorted(projection.pending))


def _assert_transition_ordering(transition) -> None:
    assert transition.entered_active == tuple(sorted(transition.entered_active))
    assert transition.exited_active == tuple(sorted(transition.exited_active))
    assert transition.entered_pending == tuple(sorted(transition.entered_pending))
    assert transition.exited_pending == tuple(sorted(transition.exited_pending))


def _duplicate_replay_store_variants(
    replicas: list[KnowledgeStore],
) -> tuple[KnowledgeStore, KnowledgeStore, KnowledgeStore]:
    single_shot_merged, single_shot_conflicts = replay_stream(replicas)
    single_shot_conflict_signatures = KnowledgeStore.conflict_signatures(single_shot_conflicts)

    duplicate_merged, duplicate_conflicts = replay_stream(
        replicas,
        start=single_shot_merged,
    )
    assert duplicate_conflicts == ()
    assert (
        KnowledgeStore.conflict_signatures(single_shot_conflicts + duplicate_conflicts)
        == single_shot_conflict_signatures
    )
    assert duplicate_merged.revision_state_signatures() == single_shot_merged.revision_state_signatures()
    assert duplicate_merged.relation_state_signatures() == single_shot_merged.relation_state_signatures()
    assert duplicate_merged.pending_relation_ids() == single_shot_merged.pending_relation_ids()

    resumed_merged, resumed_conflicts = replay_stream(
        replicas,
        start=single_shot_merged.checkpoint(),
    )
    assert resumed_conflicts == ()
    assert (
        KnowledgeStore.conflict_signatures(single_shot_conflicts + resumed_conflicts)
        == single_shot_conflict_signatures
    )
    assert resumed_merged.revision_state_signatures() == single_shot_merged.revision_state_signatures()
    assert resumed_merged.relation_state_signatures() == single_shot_merged.relation_state_signatures()
    assert resumed_merged.pending_relation_ids() == single_shot_merged.pending_relation_ids()

    return single_shot_merged, duplicate_merged, resumed_merged


def build_relation_lifecycle_signature_duplicate_replay_replicas(
    *,
    tx_base: int,
) -> tuple[RelationEdge, RelationEdge, RelationEdge, list[KnowledgeStore]]:
    residence_core = ClaimCore(
        claim_type="residence",
        slots={"subject": "Ada Lovelace"},
    )
    evidence_core = ClaimCore(
        claim_type="document",
        slots={"id": f"archive-lifecycle-duplicate-signature-{tx_base}"},
    )

    seed = KnowledgeStore()
    residence_early_revision = seed.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=dt(2024, 4, 1)),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence_early"),
        confidence_bp=7100,
    )
    evidence_revision = seed.assert_revision(
        core=evidence_core,
        assertion="Archive timeline records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_evidence"),
        confidence_bp=9200,
    )
    residence_late_revision = seed.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 4, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 4, 2)),
        provenance=Provenance(source="source_residence_late"),
        confidence_bp=7300,
    )

    active_early_relation = RelationEdge(
        relation_type="derived_from",
        from_revision_id=residence_early_revision.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 5, recorded_at=dt(2024, 2, 1)),
    )
    active_late_relation = RelationEdge(
        relation_type="derived_from",
        from_revision_id=residence_late_revision.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 5, 1)),
    )
    pending_unresolved_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=residence_late_revision.revision_id,
        to_revision_id=f"missing-duplicate-signature-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 4, 15)),
    )

    replica_orphan_early = KnowledgeStore()
    replica_orphan_early.relations[
        active_early_relation.relation_id
    ] = active_early_relation

    replica_orphan_late = KnowledgeStore()
    replica_orphan_late.relations[active_late_relation.relation_id] = active_late_relation

    replica_pending_unresolved = KnowledgeStore()
    replica_pending_unresolved.relations[
        pending_unresolved_relation.relation_id
    ] = pending_unresolved_relation

    replica_endpoints_early = KnowledgeStore()
    replica_endpoints_early.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=dt(2024, 4, 1)),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence_early"),
        confidence_bp=7100,
    )
    replica_endpoints_early.assert_revision(
        core=evidence_core,
        assertion="Archive timeline records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_evidence"),
        confidence_bp=9200,
    )

    replica_endpoint_late = KnowledgeStore()
    replica_endpoint_late.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 4, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 4, 2)),
        provenance=Provenance(source="source_residence_late"),
        confidence_bp=7300,
    )

    replay_sequence = [
        replica_orphan_early,
        replica_orphan_late,
        replica_pending_unresolved,
        replica_endpoints_early,
        replica_endpoint_late,
    ]

    return (
        active_early_relation,
        active_late_relation,
        pending_unresolved_relation,
        replay_sequence,
    )


def test_query_relation_lifecycle_signatures_as_of_duplicate_replay_idempotence_matches_single_shot() -> None:
    tx_base = 5400
    (
        active_early_relation,
        active_late_relation,
        pending_unresolved_relation,
        replicas,
    ) = build_relation_lifecycle_signature_duplicate_replay_replicas(tx_base=tx_base)
    single_shot_merged, duplicate_merged, resumed_merged = _duplicate_replay_store_variants(
        replicas
    )

    query_points = (
        (tx_base + 4, dt(2024, 3, 1)),
        (tx_base + 5, dt(2024, 3, 1)),
        (tx_base + 6, dt(2024, 6, 1)),
        (tx_base + 7, dt(2024, 6, 1)),
    )
    for tx_id, valid_at in query_points:
        single_shot_projection = single_shot_merged.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
        )
        duplicate_projection = duplicate_merged.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
        )
        resumed_projection = resumed_merged.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
        )
        assert duplicate_projection == single_shot_projection
        assert resumed_projection == single_shot_projection
        _assert_projection_ordering(single_shot_projection)
        _assert_projection_ordering(duplicate_projection)
        _assert_projection_ordering(resumed_projection)

    from_projection = single_shot_merged.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_base + 5,
        valid_at=dt(2024, 3, 1),
    )
    to_projection = single_shot_merged.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_base + 7,
        valid_at=dt(2024, 6, 1),
    )
    assert from_projection.active == (
        relation_state_signature("active", active_early_relation),
    )
    assert from_projection.pending == ()
    assert to_projection.active == (
        relation_state_signature("active", active_late_relation),
    )
    assert to_projection.pending == (
        relation_state_signature("pending", pending_unresolved_relation),
    )


def test_query_relation_lifecycle_signatures_for_tx_window_duplicate_replay_idempotence_matches_single_shot() -> None:
    tx_base = 5480
    (
        active_early_relation,
        active_late_relation,
        pending_unresolved_relation,
        replicas,
    ) = build_relation_lifecycle_signature_duplicate_replay_replicas(tx_base=tx_base)
    single_shot_merged, duplicate_merged, resumed_merged = _duplicate_replay_store_variants(
        replicas
    )

    tx_windows = (
        (tx_base + 5, tx_base + 5, dt(2024, 3, 1)),
        (tx_base + 6, tx_base + 6, dt(2024, 6, 1)),
        (tx_base + 7, tx_base + 7, dt(2024, 6, 1)),
        (tx_base + 5, tx_base + 7, dt(2024, 6, 1)),
    )
    for tx_start, tx_end, valid_at in tx_windows:
        single_shot_projection = (
            single_shot_merged.query_relation_lifecycle_signatures_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
            )
        )
        duplicate_projection = (
            duplicate_merged.query_relation_lifecycle_signatures_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
            )
        )
        resumed_projection = (
            resumed_merged.query_relation_lifecycle_signatures_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
            )
        )
        assert duplicate_projection == single_shot_projection
        assert resumed_projection == single_shot_projection
        _assert_projection_ordering(single_shot_projection)
        _assert_projection_ordering(duplicate_projection)
        _assert_projection_ordering(resumed_projection)

    early_window_projection = single_shot_merged.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 5,
        valid_at=dt(2024, 3, 1),
    )
    full_window_projection = single_shot_merged.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 6, 1),
    )
    assert early_window_projection.active == (
        relation_state_signature("active", active_early_relation),
    )
    assert early_window_projection.pending == ()
    assert full_window_projection.active == (
        relation_state_signature("active", active_late_relation),
    )
    assert full_window_projection.pending == (
        relation_state_signature("pending", pending_unresolved_relation),
    )


def test_query_relation_lifecycle_signature_transition_for_tx_window_duplicate_replay_idempotence_matches_single_shot() -> None:
    tx_base = 5560
    (
        active_early_relation,
        active_late_relation,
        _pending_unresolved_relation,
        replicas,
    ) = build_relation_lifecycle_signature_duplicate_replay_replicas(tx_base=tx_base)
    single_shot_merged, duplicate_merged, resumed_merged = _duplicate_replay_store_variants(
        replicas
    )

    single_shot_transition = (
        single_shot_merged.query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=tx_base + 5,
            tx_end=tx_base + 7,
            valid_from=dt(2024, 3, 1),
            valid_to=dt(2024, 6, 1),
        )
    )
    duplicate_transition = (
        duplicate_merged.query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=tx_base + 5,
            tx_end=tx_base + 7,
            valid_from=dt(2024, 3, 1),
            valid_to=dt(2024, 6, 1),
        )
    )
    resumed_transition = (
        resumed_merged.query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=tx_base + 5,
            tx_end=tx_base + 7,
            valid_from=dt(2024, 3, 1),
            valid_to=dt(2024, 6, 1),
        )
    )

    assert duplicate_transition == single_shot_transition
    assert resumed_transition == single_shot_transition
    _assert_transition_ordering(single_shot_transition)
    _assert_transition_ordering(duplicate_transition)
    _assert_transition_ordering(resumed_transition)

    assert single_shot_transition.entered_active == (
        relation_state_signature("active", active_late_relation),
    )
    assert single_shot_transition.exited_active == (
        relation_state_signature("active", active_early_relation),
    )
    assert single_shot_transition.entered_pending == ()
    assert single_shot_transition.exited_pending == ()
