from datetime import datetime, timezone

import pytest

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


def test_query_relation_lifecycle_signatures_as_of_returns_stable_bucketed_signatures() -> None:
    tx_base = 3600
    (
        residence_revision_id,
        evidence_primary_revision_id,
        promoted_primary_relation,
        promoted_secondary_relation,
        pending_unresolved_relation,
        replay_sequence,
    ) = build_mixed_relation_lifecycle_signature_replay_replicas(tx_base=tx_base)
    merged, _conflicts = replay_stream(replay_sequence)

    projection_tx_base_plus_5 = merged.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_base + 5,
        valid_at=dt(2024, 6, 1),
    )
    assert projection_tx_base_plus_5.active == (
        relation_state_signature("active", promoted_primary_relation),
    )
    assert projection_tx_base_plus_5.pending == ()

    expected_active_at_tx_base_plus_7 = tuple(
        sorted(
            (
                relation_state_signature("active", promoted_primary_relation),
                relation_state_signature("active", promoted_secondary_relation),
            )
        )
    )
    expected_pending_at_tx_base_plus_7 = (
        relation_state_signature("pending", pending_unresolved_relation),
    )
    projection_tx_base_plus_7 = merged.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_base + 7,
        valid_at=dt(2024, 6, 1),
    )
    assert projection_tx_base_plus_7.active == expected_active_at_tx_base_plus_7
    assert projection_tx_base_plus_7.pending == expected_pending_at_tx_base_plus_7

    residence_filtered_projection = merged.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_base + 7,
        valid_at=dt(2024, 6, 1),
        revision_id=residence_revision_id,
    )
    assert residence_filtered_projection == projection_tx_base_plus_7

    evidence_primary_filtered_projection = merged.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_base + 7,
        valid_at=dt(2024, 6, 1),
        revision_id=evidence_primary_revision_id,
    )
    assert evidence_primary_filtered_projection.active == (
        relation_state_signature("active", promoted_primary_relation),
    )
    assert evidence_primary_filtered_projection.pending == ()


def test_query_relation_lifecycle_signatures_for_tx_window_matches_as_of_filtered_projection() -> None:
    tx_base = 4000
    (
        residence_revision_id,
        evidence_primary_revision_id,
        promoted_primary_relation,
        promoted_secondary_relation,
        pending_unresolved_relation,
        replay_sequence,
    ) = build_mixed_relation_lifecycle_signature_replay_replicas(tx_base=tx_base)
    merged, _conflicts = replay_stream(replay_sequence)

    tx_windows = (
        (tx_base + 4, tx_base + 4),
        (tx_base + 5, tx_base + 5),
        (tx_base + 5, tx_base + 6),
        (tx_base + 6, tx_base + 7),
        (tx_base + 8, tx_base + 9),
        (tx_base + 5, tx_base + 7),
    )
    for tx_start, tx_end in tx_windows:
        projection = merged.query_relation_lifecycle_signatures_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=dt(2024, 6, 1),
        )
        as_of_projection = merged.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_end,
            valid_at=dt(2024, 6, 1),
        )
        expected_active = tuple(
            signature
            for signature in as_of_projection.active
            if tx_start <= signature[5] <= tx_end
        )
        expected_pending = tuple(
            signature
            for signature in as_of_projection.pending
            if tx_start <= signature[5] <= tx_end
        )
        assert projection.active == expected_active
        assert projection.pending == expected_pending

    full_window_projection = merged.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 6, 1),
    )
    assert full_window_projection.active == tuple(
        sorted(
            (
                relation_state_signature("active", promoted_primary_relation),
                relation_state_signature("active", promoted_secondary_relation),
            )
        )
    )
    assert full_window_projection.pending == (
        relation_state_signature("pending", pending_unresolved_relation),
    )

    residence_window_projection = merged.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 6,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 6, 1),
        revision_id=residence_revision_id,
    )
    assert residence_window_projection.active == (
        relation_state_signature("active", promoted_secondary_relation),
    )
    assert residence_window_projection.pending == (
        relation_state_signature("pending", pending_unresolved_relation),
    )

    evidence_primary_window_projection = merged.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 6,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 6, 1),
        revision_id=evidence_primary_revision_id,
    )
    assert evidence_primary_window_projection.active == ()
    assert evidence_primary_window_projection.pending == ()


def test_query_relation_lifecycle_signatures_for_tx_window_rejects_inverted_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore().query_relation_lifecycle_signatures_for_tx_window(
            tx_start=12,
            tx_end=11,
            valid_at=dt(2024, 6, 1),
        )


def test_query_relation_lifecycle_signature_transition_for_tx_window_tracks_valid_time_endpoint_swaps() -> None:
    tx_base = 4200
    (
        residence_late_revision_id,
        active_early_relation,
        active_late_relation,
        pending_unresolved_relation,
        replay_sequence,
    ) = build_valid_time_transition_lifecycle_signature_replay_replicas(tx_base=tx_base)
    merged, _conflicts = replay_stream(replay_sequence)

    transition = merged.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_from=dt(2024, 3, 1),
        valid_to=dt(2024, 6, 1),
    )
    assert transition.entered_active == (
        relation_state_signature("active", active_late_relation),
    )
    assert transition.exited_active == (
        relation_state_signature("active", active_early_relation),
    )
    assert transition.entered_pending == ()
    assert transition.exited_pending == ()

    from_projection = merged.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 3, 1),
    )
    to_projection = merged.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_at=dt(2024, 6, 1),
    )
    assert from_projection.active == (
        relation_state_signature("active", active_early_relation),
    )
    assert to_projection.active == (
        relation_state_signature("active", active_late_relation),
    )
    assert from_projection.pending == (
        relation_state_signature("pending", pending_unresolved_relation),
    )
    assert to_projection.pending == (
        relation_state_signature("pending", pending_unresolved_relation),
    )

    filtered_transition = merged.query_relation_lifecycle_signature_transition_for_tx_window(
        tx_start=tx_base + 5,
        tx_end=tx_base + 7,
        valid_from=dt(2024, 3, 1),
        valid_to=dt(2024, 6, 1),
        revision_id=residence_late_revision_id,
    )
    assert filtered_transition.entered_active == (
        relation_state_signature("active", active_late_relation),
    )
    assert filtered_transition.exited_active == ()
    assert filtered_transition.entered_pending == ()
    assert filtered_transition.exited_pending == ()


def test_query_relation_lifecycle_signature_transition_for_tx_window_rejects_inverted_valid_window() -> None:
    with pytest.raises(
        ValueError,
        match="valid_to must be greater than or equal to valid_from",
    ):
        KnowledgeStore().query_relation_lifecycle_signature_transition_for_tx_window(
            tx_start=20,
            tx_end=21,
            valid_from=dt(2024, 6, 1),
            valid_to=dt(2024, 3, 1),
        )
