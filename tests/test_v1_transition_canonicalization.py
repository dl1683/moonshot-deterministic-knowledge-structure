from datetime import datetime, timezone

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


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


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


def _merge_conflict_transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_signature_counts,
        transition.exited_signature_counts,
        transition.entered_code_counts,
        transition.exited_code_counts,
    )


def _signature_transition_buckets(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def _build_lifecycle_transition_store() -> tuple[
    KnowledgeStore,
    datetime,
    int,
    int,
    str,
    str,
    str,
]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 5
    tx_to = 7

    core_anchor = ClaimCore(claim_type="document", slots={"id": "canonical-anchor"})
    core_enter_active = ClaimCore(claim_type="residence", slots={"subject": "canonical-enter"})
    core_exit_active = ClaimCore(claim_type="residence", slots={"subject": "canonical-exit"})
    core_reactivate = ClaimCore(claim_type="residence", slots={"subject": "canonical-reactivate"})
    core_future = ClaimCore(claim_type="document", slots={"id": "canonical-future"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="canonical anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_canonical_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    exited_active_revision = store.assert_revision(
        core=core_exit_active,
        assertion="canonical exited active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_canonical_exit_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_reactivate,
        assertion="canonical reactivate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_canonical_reactivate_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    entered_active_revision = store.assert_revision(
        core=core_enter_active,
        assertion="canonical entered active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_canonical_enter"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_exit_active,
        assertion="canonical exited active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_canonical_exit_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    reactivated_revision = store.assert_revision(
        core=core_reactivate,
        assertion="canonical reactivate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_canonical_reactivate_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    future_revision = store.assert_revision(
        core=core_future,
        assertion="canonical future",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_canonical_future"),
        confidence_bp=9000,
        status="asserted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=exited_active_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=future_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=reactivated_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )

    orphan_replica = KnowledgeStore()
    stable_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id="missing-canonical-stable",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    entered_pending = RelationEdge(
        relation_type="supports",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id="missing-canonical-entered",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    orphan_replica.relations[stable_pending.relation_id] = stable_pending
    orphan_replica.relations[entered_pending.relation_id] = entered_pending
    store = store.merge(orphan_replica).merged

    return (
        store,
        valid_at,
        tx_from,
        tx_to,
        core_exit_active.core_id,
        core_anchor.core_id,
        anchor_revision.revision_id,
    )


def _expected_revision_transition_from_as_of(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    core_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=core_id,
    )
    to_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    from_active = {revision.revision_id: revision for revision in from_projection.active}
    to_active = {revision.revision_id: revision for revision in to_projection.active}
    from_retracted = {
        revision.revision_id: revision for revision in from_projection.retracted
    }
    to_retracted = {revision.revision_id: revision for revision in to_projection.retracted}
    return (
        tuple(to_active[revision_id] for revision_id in sorted(set(to_active) - set(from_active))),
        tuple(from_active[revision_id] for revision_id in sorted(set(from_active) - set(to_active))),
        tuple(
            to_retracted[revision_id]
            for revision_id in sorted(set(to_retracted) - set(from_retracted))
        ),
        tuple(
            from_retracted[revision_id]
            for revision_id in sorted(set(from_retracted) - set(to_retracted))
        ),
    )


def _expected_relation_resolution_transition_from_as_of(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    core_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = store.query_relation_resolution_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=core_id,
    )
    to_projection = store.query_relation_resolution_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=core_id,
    )
    from_active = {relation.relation_id: relation for relation in from_projection.active}
    to_active = {relation.relation_id: relation for relation in to_projection.active}
    from_pending = {relation.relation_id: relation for relation in from_projection.pending}
    to_pending = {relation.relation_id: relation for relation in to_projection.pending}
    return (
        tuple(to_active[relation_id] for relation_id in sorted(set(to_active) - set(from_active))),
        tuple(from_active[relation_id] for relation_id in sorted(set(from_active) - set(to_active))),
        tuple(
            to_pending[relation_id]
            for relation_id in sorted(set(to_pending) - set(from_pending))
        ),
        tuple(
            from_pending[relation_id]
            for relation_id in sorted(set(from_pending) - set(to_pending))
        ),
    )


def _expected_relation_lifecycle_transition_from_as_of(
    store: KnowledgeStore,
    *,
    tx_from: int,
    tx_to: int,
    valid_at: datetime,
    revision_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        revision_id=revision_id,
    )
    to_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        revision_id=revision_id,
    )
    from_active = {relation.relation_id: relation for relation in from_projection.active}
    to_active = {relation.relation_id: relation for relation in to_projection.active}
    from_pending = {relation.relation_id: relation for relation in from_projection.pending}
    to_pending = {relation.relation_id: relation for relation in to_projection.pending}
    return (
        tuple(to_active[relation_id] for relation_id in sorted(set(to_active) - set(from_active))),
        tuple(from_active[relation_id] for relation_id in sorted(set(from_active) - set(to_active))),
        tuple(
            to_pending[relation_id]
            for relation_id in sorted(set(to_pending) - set(from_pending))
        ),
        tuple(
            from_pending[relation_id]
            for relation_id in sorted(set(from_pending) - set(to_pending))
        ),
    )


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="canonical-orphan-a",
        details="missing endpoint canonical-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="canonical-orphan-b",
        details="missing endpoint canonical-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="canonical-competing-subject",
        details="competing asserted revisions",
    )
    return (
        (10, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (12, MergeResult(merged=KnowledgeStore(), conflicts=(competing,))),
    )


def _signature_count_sort_key(signature_count: tuple[str, str, str, int]) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _expected_merge_conflict_transition_from_as_of(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_from: int,
    tx_to: int,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        merge_results_by_tx,
        tx_id=tx_from,
    )
    to_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        merge_results_by_tx,
        tx_id=tx_to,
    )
    return (
        tuple(
            sorted(
                set(to_projection.signature_counts) - set(from_projection.signature_counts),
                key=_signature_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(from_projection.signature_counts) - set(to_projection.signature_counts),
                key=_signature_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(to_projection.code_counts) - set(from_projection.code_counts),
                key=_code_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(from_projection.code_counts) - set(to_projection.code_counts),
                key=_code_count_sort_key,
            )
        ),
    )


def _replay_replicas(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> KnowledgeStore:
    merged = start if start is not None else KnowledgeStore()
    for replica in replicas:
        merged = merged.merge(replica).merged
    return merged


def _build_relation_lifecycle_signature_store(
    *,
    tx_base: int,
) -> tuple[KnowledgeStore, int, int, datetime, datetime, str]:
    residence_core = ClaimCore(
        claim_type="residence",
        slots={"subject": "canonical-signature-residence"},
    )
    evidence_core = ClaimCore(
        claim_type="document",
        slots={"id": f"canonical-signature-doc-{tx_base}"},
    )

    seed = KnowledgeStore()
    residence_early_revision = seed.assert_revision(
        core=residence_core,
        assertion="canonical signature early",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=dt(2024, 4, 1)),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_canonical_signature_early"),
        confidence_bp=7100,
    )
    evidence_revision = seed.assert_revision(
        core=evidence_core,
        assertion="canonical signature evidence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_canonical_signature_evidence"),
        confidence_bp=9200,
    )
    residence_late_revision = seed.assert_revision(
        core=residence_core,
        assertion="canonical signature late",
        valid_time=ValidTime(start=dt(2024, 4, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 4, 2)),
        provenance=Provenance(source="source_canonical_signature_late"),
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
        to_revision_id=f"canonical-signature-missing-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 4, 15)),
    )

    replica_orphan_early = KnowledgeStore()
    replica_orphan_early.relations[active_early_relation.relation_id] = active_early_relation
    replica_orphan_late = KnowledgeStore()
    replica_orphan_late.relations[active_late_relation.relation_id] = active_late_relation
    replica_pending_unresolved = KnowledgeStore()
    replica_pending_unresolved.relations[
        pending_unresolved_relation.relation_id
    ] = pending_unresolved_relation

    replica_endpoints_early = KnowledgeStore()
    replica_endpoints_early.assert_revision(
        core=residence_core,
        assertion="canonical signature early",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=dt(2024, 4, 1)),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_canonical_signature_early"),
        confidence_bp=7100,
    )
    replica_endpoints_early.assert_revision(
        core=evidence_core,
        assertion="canonical signature evidence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_canonical_signature_evidence"),
        confidence_bp=9200,
    )

    replica_endpoint_late = KnowledgeStore()
    replica_endpoint_late.assert_revision(
        core=residence_core,
        assertion="canonical signature late",
        valid_time=ValidTime(start=dt(2024, 4, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 4, 2)),
        provenance=Provenance(source="source_canonical_signature_late"),
        confidence_bp=7300,
    )

    store = _replay_replicas(
        [
            seed,
            replica_orphan_early,
            replica_orphan_late,
            replica_pending_unresolved,
            replica_endpoints_early,
            replica_endpoint_late,
        ]
    )
    return (
        store,
        tx_base + 5,
        tx_base + 7,
        dt(2024, 3, 1),
        dt(2024, 6, 1),
        evidence_revision.revision_id,
    )


def _filter_signatures_for_tx_window(
    signatures: tuple[tuple[str, str, str, str, str, int, str], ...],
    *,
    tx_start: int,
    tx_end: int,
) -> tuple[tuple[str, str, str, str, str, int, str], ...]:
    return tuple(signature for signature in signatures if tx_start <= signature[5] <= tx_end)


def _expected_signature_transition_from_as_of_window_diffs(
    store: KnowledgeStore,
    *,
    tx_start: int,
    tx_end: int,
    valid_from: datetime,
    valid_to: datetime,
    revision_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_end,
        valid_at=valid_from,
        revision_id=revision_id,
    )
    to_projection = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_end,
        valid_at=valid_to,
        revision_id=revision_id,
    )
    from_active = _filter_signatures_for_tx_window(
        from_projection.active,
        tx_start=tx_start,
        tx_end=tx_end,
    )
    to_active = _filter_signatures_for_tx_window(
        to_projection.active,
        tx_start=tx_start,
        tx_end=tx_end,
    )
    from_pending = _filter_signatures_for_tx_window(
        from_projection.pending,
        tx_start=tx_start,
        tx_end=tx_end,
    )
    to_pending = _filter_signatures_for_tx_window(
        to_projection.pending,
        tx_start=tx_start,
        tx_end=tx_end,
    )
    return (
        tuple(sorted(set(to_active) - set(from_active))),
        tuple(sorted(set(from_active) - set(to_active))),
        tuple(sorted(set(to_pending) - set(from_pending))),
        tuple(sorted(set(from_pending) - set(to_pending))),
    )


def test_transition_canonicalization_matches_explicit_as_of_diffs_for_revision_and_relation_surfaces() -> None:
    (
        store,
        valid_at,
        tx_from,
        tx_to,
        exiting_core_id,
        anchor_core_id,
        anchor_revision_id,
    ) = _build_lifecycle_transition_store()

    revision_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert _revision_transition_buckets(revision_transition) == _expected_revision_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )

    filtered_revision_transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=exiting_core_id,
    )
    assert _revision_transition_buckets(
        filtered_revision_transition
    ) == _expected_revision_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=exiting_core_id,
    )

    resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert _relation_transition_buckets(
        resolution_transition
    ) == _expected_relation_resolution_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )

    filtered_resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=anchor_core_id,
    )
    assert _relation_transition_buckets(
        filtered_resolution_transition
    ) == _expected_relation_resolution_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=anchor_core_id,
    )

    lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert _relation_transition_buckets(
        lifecycle_transition
    ) == _expected_relation_lifecycle_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )

    filtered_lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )
    assert _relation_transition_buckets(
        filtered_lifecycle_transition
    ) == _expected_relation_lifecycle_transition_from_as_of(
        store,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )


def test_transition_canonicalization_matches_explicit_as_of_diffs_for_merge_conflict_surface() -> None:
    stream = _build_merge_conflict_stream()
    tx_from = 10
    tx_to = 12
    transition = KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
        stream,
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=dt(2024, 6, 1),
    )
    assert _merge_conflict_transition_buckets(
        transition
    ) == _expected_merge_conflict_transition_from_as_of(
        stream,
        tx_from=tx_from,
        tx_to=tx_to,
    )


def test_transition_canonicalization_matches_explicit_as_of_diffs_for_relation_signature_surface() -> None:
    (
        store,
        tx_start,
        tx_end,
        valid_from,
        valid_to,
        evidence_revision_id,
    ) = _build_relation_lifecycle_signature_store(tx_base=6400)

    transition = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    assert _signature_transition_buckets(
        transition
    ) == _expected_signature_transition_from_as_of_window_diffs(
        store,
        tx_start=tx_start,
        tx_end=tx_end,
        valid_from=valid_from,
        valid_to=valid_to,
    )

    filtered_transition = store.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_from=valid_from,
        valid_to=valid_to,
        revision_id=evidence_revision_id,
    )
    assert _signature_transition_buckets(
        filtered_transition
    ) == _expected_signature_transition_from_as_of_window_diffs(
        store,
        tx_start=tx_start,
        tx_end=tx_end,
        valid_from=valid_from,
        valid_to=valid_to,
        revision_id=evidence_revision_id,
    )
