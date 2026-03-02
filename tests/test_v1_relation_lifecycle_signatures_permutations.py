from datetime import datetime, timezone

import itertools

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


def _projection_signatures(projection) -> tuple[tuple, tuple]:
    return (projection.active, projection.pending)


def _transition_signatures(transition) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_active,
        transition.exited_active,
        transition.entered_pending,
        transition.exited_pending,
    )


def _assert_bucket_order(*buckets: tuple[tuple, ...]) -> None:
    for bucket in buckets:
        assert bucket == tuple(sorted(bucket))


def _expected_transition_signatures_from_window_projections(
    store: KnowledgeStore,
    *,
    tx_start: int,
    tx_end: int,
    valid_from: datetime,
    valid_to: datetime,
    revision_id: str | None = None,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_from,
        revision_id=revision_id,
    )
    to_projection = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_to,
        revision_id=revision_id,
    )
    return (
        tuple(sorted(set(to_projection.active) - set(from_projection.active))),
        tuple(sorted(set(from_projection.active) - set(to_projection.active))),
        tuple(sorted(set(to_projection.pending) - set(from_projection.pending))),
        tuple(sorted(set(from_projection.pending) - set(to_projection.pending))),
    )


def build_mixed_relation_lifecycle_signature_replay_replicas(
    *,
    tx_base: int,
) -> tuple[str, str, RelationEdge, RelationEdge, RelationEdge, list[KnowledgeStore]]:
    residence_core = ClaimCore(
        claim_type="residence",
        slots={"subject": "Ada Lovelace"},
    )
    evidence_primary_core = ClaimCore(
        claim_type="document",
        slots={"id": f"archive-lifecycle-signature-primary-{tx_base}"},
    )
    evidence_secondary_core = ClaimCore(
        claim_type="document",
        slots={"id": f"archive-lifecycle-signature-secondary-{tx_base}"},
    )

    seed = KnowledgeStore()
    residence_revision = seed.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_a"),
        confidence_bp=7000,
    )
    evidence_primary_revision = seed.assert_revision(
        core=evidence_primary_core,
        assertion="Archive primary records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_primary"),
        confidence_bp=9100,
    )
    evidence_secondary_revision = seed.assert_revision(
        core=evidence_secondary_core,
        assertion="Archive secondary records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_secondary"),
        confidence_bp=9050,
    )

    promoted_primary_relation = RelationEdge(
        relation_type="derived_from",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=evidence_primary_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 5, recorded_at=dt(2024, 1, 5)),
    )
    promoted_secondary_relation = RelationEdge(
        relation_type="supports",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=evidence_secondary_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 6, recorded_at=dt(2024, 1, 6)),
    )
    pending_unresolved_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=f"missing-lifecycle-signature-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 7, recorded_at=dt(2024, 1, 7)),
    )

    replica_orphan_primary = KnowledgeStore()
    replica_orphan_primary.relations[
        promoted_primary_relation.relation_id
    ] = promoted_primary_relation

    replica_orphan_secondary = KnowledgeStore()
    replica_orphan_secondary.relations[
        promoted_secondary_relation.relation_id
    ] = promoted_secondary_relation

    replica_pending_unresolved = KnowledgeStore()
    replica_pending_unresolved.relations[
        pending_unresolved_relation.relation_id
    ] = pending_unresolved_relation

    replica_endpoints_primary = KnowledgeStore()
    replica_endpoints_primary.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_a"),
        confidence_bp=7000,
    )
    replica_endpoints_primary.assert_revision(
        core=evidence_primary_core,
        assertion="Archive primary records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_primary"),
        confidence_bp=9100,
    )

    replica_endpoint_secondary = KnowledgeStore()
    replica_endpoint_secondary.assert_revision(
        core=evidence_secondary_core,
        assertion="Archive secondary records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_secondary"),
        confidence_bp=9050,
    )

    replay_sequence = [
        replica_orphan_primary,
        replica_endpoint_secondary,
        replica_orphan_secondary,
        replica_endpoints_primary,
        replica_pending_unresolved,
    ]

    return (
        residence_revision.revision_id,
        evidence_primary_revision.revision_id,
        promoted_primary_relation,
        promoted_secondary_relation,
        pending_unresolved_relation,
        replay_sequence,
    )


def build_valid_time_transition_lifecycle_signature_replay_replicas(
    *,
    tx_base: int,
) -> tuple[str, RelationEdge, RelationEdge, RelationEdge, list[KnowledgeStore]]:
    residence_core = ClaimCore(
        claim_type="residence",
        slots={"subject": "Ada Lovelace"},
    )
    evidence_core = ClaimCore(
        claim_type="document",
        slots={"id": f"archive-lifecycle-transition-signature-{tx_base}"},
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
        to_revision_id=f"missing-transition-signature-{tx_base}",
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
        residence_late_revision.revision_id,
        active_early_relation,
        active_late_relation,
        pending_unresolved_relation,
        replay_sequence,
    )


def test_query_relation_lifecycle_signatures_as_of_permutation_order_and_checkpoint_resume_are_equivalent() -> None:
    tx_base = 3700
    (
        residence_revision_id,
        evidence_primary_revision_id,
        promoted_primary_relation,
        promoted_secondary_relation,
        pending_unresolved_relation,
        replay_sequence,
    ) = build_mixed_relation_lifecycle_signature_replay_replicas(tx_base=tx_base)

    expected_active = tuple(
        sorted(
            (
                relation_state_signature("active", promoted_primary_relation),
                relation_state_signature("active", promoted_secondary_relation),
            )
        )
    )
    expected_pending = (
        relation_state_signature("pending", pending_unresolved_relation),
    )

    baseline_projection_signatures = None
    baseline_conflict_signatures = None

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        unsplit_merged, unsplit_conflicts = replay_stream(ordered_replicas)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        unsplit_projection = unsplit_merged.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_base + 7,
            valid_at=dt(2024, 6, 1),
        )
        unsplit_residence_projection = unsplit_merged.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_base + 7,
            valid_at=dt(2024, 6, 1),
            revision_id=residence_revision_id,
        )
        unsplit_evidence_primary_projection = (
            unsplit_merged.query_relation_lifecycle_signatures_as_of(
                tx_id=tx_base + 7,
                valid_at=dt(2024, 6, 1),
                revision_id=evidence_primary_revision_id,
            )
        )

        assert unsplit_projection.active == expected_active
        assert unsplit_projection.pending == expected_pending
        assert unsplit_residence_projection == unsplit_projection
        assert unsplit_evidence_primary_projection.active == (
            relation_state_signature("active", promoted_primary_relation),
        )
        assert unsplit_evidence_primary_projection.pending == ()

        _assert_bucket_order(unsplit_projection.active, unsplit_projection.pending)
        _assert_bucket_order(
            unsplit_residence_projection.active,
            unsplit_residence_projection.pending,
        )
        _assert_bucket_order(
            unsplit_evidence_primary_projection.active,
            unsplit_evidence_primary_projection.pending,
        )

        unsplit_projection_signatures = (
            _projection_signatures(unsplit_projection),
            _projection_signatures(unsplit_residence_projection),
            _projection_signatures(unsplit_evidence_primary_projection),
        )
        if baseline_projection_signatures is None:
            baseline_projection_signatures = unsplit_projection_signatures
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_projection_signatures == baseline_projection_signatures
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_conflicts = replay_stream(ordered_replicas[:split_index])
            resumed_merged, resumed_suffix_conflicts = replay_stream(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_conflict_signatures = KnowledgeStore.conflict_signatures(
                prefix_conflicts + resumed_suffix_conflicts
            )

            resumed_projection = resumed_merged.query_relation_lifecycle_signatures_as_of(
                tx_id=tx_base + 7,
                valid_at=dt(2024, 6, 1),
            )
            resumed_residence_projection = (
                resumed_merged.query_relation_lifecycle_signatures_as_of(
                    tx_id=tx_base + 7,
                    valid_at=dt(2024, 6, 1),
                    revision_id=residence_revision_id,
                )
            )
            resumed_evidence_primary_projection = (
                resumed_merged.query_relation_lifecycle_signatures_as_of(
                    tx_id=tx_base + 7,
                    valid_at=dt(2024, 6, 1),
                    revision_id=evidence_primary_revision_id,
                )
            )

            resumed_projection_signatures = (
                _projection_signatures(resumed_projection),
                _projection_signatures(resumed_residence_projection),
                _projection_signatures(resumed_evidence_primary_projection),
            )

            assert resumed_projection_signatures == unsplit_projection_signatures
            assert resumed_conflict_signatures == unsplit_conflict_signatures


def test_query_relation_lifecycle_signatures_for_tx_window_permutation_order_and_checkpoint_resume_are_equivalent() -> None:
    tx_base = 4100
    (
        residence_revision_id,
        evidence_primary_revision_id,
        _promoted_primary_relation,
        promoted_secondary_relation,
        pending_unresolved_relation,
        replay_sequence,
    ) = build_mixed_relation_lifecycle_signature_replay_replicas(tx_base=tx_base)

    tx_start = tx_base + 6
    tx_end = tx_base + 7
    expected_active = (
        relation_state_signature("active", promoted_secondary_relation),
    )
    expected_pending = (
        relation_state_signature("pending", pending_unresolved_relation),
    )

    baseline_projection_signatures = None
    baseline_conflict_signatures = None
    permutation_orders = itertools.islice(
        itertools.permutations(range(len(replay_sequence))),
        48,
    )
    for order in permutation_orders:
        ordered_replicas = [replay_sequence[index] for index in order]
        unsplit_merged, unsplit_conflicts = replay_stream(ordered_replicas)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        unsplit_projection = unsplit_merged.query_relation_lifecycle_signatures_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=dt(2024, 6, 1),
        )
        unsplit_residence_projection = (
            unsplit_merged.query_relation_lifecycle_signatures_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=dt(2024, 6, 1),
                revision_id=residence_revision_id,
            )
        )
        unsplit_evidence_primary_projection = (
            unsplit_merged.query_relation_lifecycle_signatures_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=dt(2024, 6, 1),
                revision_id=evidence_primary_revision_id,
            )
        )
        unsplit_as_of_projection = unsplit_merged.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_end,
            valid_at=dt(2024, 6, 1),
        )

        assert unsplit_projection.active == expected_active
        assert unsplit_projection.pending == expected_pending
        assert unsplit_projection.active == tuple(
            signature
            for signature in unsplit_as_of_projection.active
            if tx_start <= signature[5] <= tx_end
        )
        assert unsplit_projection.pending == tuple(
            signature
            for signature in unsplit_as_of_projection.pending
            if tx_start <= signature[5] <= tx_end
        )
        assert unsplit_residence_projection == unsplit_projection
        assert unsplit_evidence_primary_projection.active == ()
        assert unsplit_evidence_primary_projection.pending == ()

        _assert_bucket_order(unsplit_projection.active, unsplit_projection.pending)
        _assert_bucket_order(
            unsplit_residence_projection.active,
            unsplit_residence_projection.pending,
        )
        _assert_bucket_order(
            unsplit_evidence_primary_projection.active,
            unsplit_evidence_primary_projection.pending,
        )

        unsplit_projection_signatures = (
            _projection_signatures(unsplit_projection),
            _projection_signatures(unsplit_residence_projection),
            _projection_signatures(unsplit_evidence_primary_projection),
        )
        if baseline_projection_signatures is None:
            baseline_projection_signatures = unsplit_projection_signatures
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_projection_signatures == baseline_projection_signatures
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_conflicts = replay_stream(ordered_replicas[:split_index])
            resumed_merged, resumed_suffix_conflicts = replay_stream(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_conflict_signatures = KnowledgeStore.conflict_signatures(
                prefix_conflicts + resumed_suffix_conflicts
            )

            resumed_projection = (
                resumed_merged.query_relation_lifecycle_signatures_for_tx_window(
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_at=dt(2024, 6, 1),
                )
            )
            resumed_residence_projection = (
                resumed_merged.query_relation_lifecycle_signatures_for_tx_window(
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_at=dt(2024, 6, 1),
                    revision_id=residence_revision_id,
                )
            )
            resumed_evidence_primary_projection = (
                resumed_merged.query_relation_lifecycle_signatures_for_tx_window(
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_at=dt(2024, 6, 1),
                    revision_id=evidence_primary_revision_id,
                )
            )

            resumed_projection_signatures = (
                _projection_signatures(resumed_projection),
                _projection_signatures(resumed_residence_projection),
                _projection_signatures(resumed_evidence_primary_projection),
            )

            assert resumed_projection_signatures == unsplit_projection_signatures
            assert resumed_conflict_signatures == unsplit_conflict_signatures


def test_query_relation_lifecycle_signature_transition_for_tx_window_permutation_order_and_checkpoint_resume_are_equivalent() -> None:
    tx_base = 4300
    (
        residence_late_revision_id,
        active_early_relation,
        active_late_relation,
        pending_unresolved_relation,
        replay_sequence,
    ) = build_valid_time_transition_lifecycle_signature_replay_replicas(tx_base=tx_base)

    tx_start = tx_base + 5
    tx_end = tx_base + 7
    valid_from = dt(2024, 3, 1)
    valid_to = dt(2024, 6, 1)

    baseline_transition_signatures = None
    baseline_filtered_transition_signatures = None
    baseline_conflict_signatures = None
    permutation_orders = itertools.islice(
        itertools.permutations(range(len(replay_sequence))),
        48,
    )
    for order in permutation_orders:
        ordered_replicas = [replay_sequence[index] for index in order]
        unsplit_merged, unsplit_conflicts = replay_stream(ordered_replicas)
        unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)

        unsplit_transition = (
            unsplit_merged.query_relation_lifecycle_signature_transition_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_from=valid_from,
                valid_to=valid_to,
            )
        )
        unsplit_filtered_transition = (
            unsplit_merged.query_relation_lifecycle_signature_transition_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_from=valid_from,
                valid_to=valid_to,
                revision_id=residence_late_revision_id,
            )
        )

        unsplit_transition_signatures = _transition_signatures(unsplit_transition)
        unsplit_filtered_transition_signatures = _transition_signatures(
            unsplit_filtered_transition
        )
        expected_transition_signatures = (
            _expected_transition_signatures_from_window_projections(
                unsplit_merged,
                tx_start=tx_start,
                tx_end=tx_end,
                valid_from=valid_from,
                valid_to=valid_to,
            )
        )
        expected_filtered_transition_signatures = (
            _expected_transition_signatures_from_window_projections(
                unsplit_merged,
                tx_start=tx_start,
                tx_end=tx_end,
                valid_from=valid_from,
                valid_to=valid_to,
                revision_id=residence_late_revision_id,
            )
        )

        assert unsplit_transition.entered_active == (
            relation_state_signature("active", active_late_relation),
        )
        assert unsplit_transition.exited_active == (
            relation_state_signature("active", active_early_relation),
        )
        assert unsplit_transition.entered_pending == ()
        assert unsplit_transition.exited_pending == ()
        assert unsplit_filtered_transition.entered_active == (
            relation_state_signature("active", active_late_relation),
        )
        assert unsplit_filtered_transition.exited_active == ()
        assert unsplit_filtered_transition.entered_pending == ()
        assert unsplit_filtered_transition.exited_pending == ()
        assert unsplit_transition_signatures == expected_transition_signatures
        assert (
            unsplit_filtered_transition_signatures
            == expected_filtered_transition_signatures
        )
        _assert_bucket_order(*unsplit_transition_signatures)
        _assert_bucket_order(*unsplit_filtered_transition_signatures)

        from_projection = unsplit_merged.query_relation_lifecycle_signatures_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_from,
        )
        to_projection = unsplit_merged.query_relation_lifecycle_signatures_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_to,
        )
        assert from_projection.pending == (
            relation_state_signature("pending", pending_unresolved_relation),
        )
        assert to_projection.pending == (
            relation_state_signature("pending", pending_unresolved_relation),
        )

        if baseline_transition_signatures is None:
            baseline_transition_signatures = unsplit_transition_signatures
            baseline_filtered_transition_signatures = (
                unsplit_filtered_transition_signatures
            )
            baseline_conflict_signatures = unsplit_conflict_signatures
        else:
            assert unsplit_transition_signatures == baseline_transition_signatures
            assert (
                unsplit_filtered_transition_signatures
                == baseline_filtered_transition_signatures
            )
            assert unsplit_conflict_signatures == baseline_conflict_signatures

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_conflicts = replay_stream(ordered_replicas[:split_index])
            resumed_merged, resumed_suffix_conflicts = replay_stream(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_conflict_signatures = KnowledgeStore.conflict_signatures(
                prefix_conflicts + resumed_suffix_conflicts
            )

            resumed_transition = (
                resumed_merged.query_relation_lifecycle_signature_transition_for_tx_window(
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_from=valid_from,
                    valid_to=valid_to,
                )
            )
            resumed_filtered_transition = (
                resumed_merged.query_relation_lifecycle_signature_transition_for_tx_window(
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    revision_id=residence_late_revision_id,
                )
            )

            resumed_transition_signatures = _transition_signatures(resumed_transition)
            resumed_filtered_transition_signatures = _transition_signatures(
                resumed_filtered_transition
            )
            resumed_expected_transition_signatures = (
                _expected_transition_signatures_from_window_projections(
                    resumed_merged,
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_from=valid_from,
                    valid_to=valid_to,
                )
            )
            resumed_expected_filtered_transition_signatures = (
                _expected_transition_signatures_from_window_projections(
                    resumed_merged,
                    tx_start=tx_start,
                    tx_end=tx_end,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    revision_id=residence_late_revision_id,
                )
            )

            assert resumed_transition_signatures == unsplit_transition_signatures
            assert (
                resumed_filtered_transition_signatures
                == unsplit_filtered_transition_signatures
            )
            assert resumed_transition_signatures == resumed_expected_transition_signatures
            assert (
                resumed_filtered_transition_signatures
                == resumed_expected_filtered_transition_signatures
            )
            assert resumed_conflict_signatures == unsplit_conflict_signatures
            _assert_bucket_order(*resumed_transition_signatures)
            _assert_bucket_order(*resumed_filtered_transition_signatures)
