from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    Provenance,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def merge_replicas(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple]:
    merged = start if start is not None else KnowledgeStore()
    conflicts = []
    for replica in replicas:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        conflicts.extend(merge_result.conflicts)
    return merged, tuple(conflicts)


def _winner_scenario() -> tuple[ClaimCore, list[KnowledgeStore], str]:
    core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    replica_a = KnowledgeStore()
    asserted_a = replica_a.assert_revision(
        core=core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_a"),
        confidence_bp=7600,
        status="asserted",
    )

    replica_b = KnowledgeStore()
    asserted_b = replica_b.assert_revision(
        core=core,
        assertion="Ada lives in Paris",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_b"),
        confidence_bp=7600,
        status="asserted",
    )

    expected_winner_revision_id = min(asserted_a.revision_id, asserted_b.revision_id)
    return core, [replica_a, replica_b], expected_winner_revision_id


def _relation_projection_scenario() -> tuple[ClaimCore, list[KnowledgeStore], str, str]:
    residence_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    evidence_core = ClaimCore(claim_type="document", slots={"id": "archive-1"})
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    replica_endpoints = KnowledgeStore()
    residence_asserted = replica_endpoints.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=20, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8000,
        status="asserted",
    )
    replica_endpoints.assert_revision(
        core=evidence_core,
        assertion="Archive A records London residence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=20, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_document"),
        confidence_bp=9000,
        status="asserted",
    )

    replica_relation = KnowledgeStore()
    relation_residence_revision = replica_relation.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=20, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8000,
        status="asserted",
    )
    relation_evidence_revision = replica_relation.assert_revision(
        core=evidence_core,
        assertion="Archive A records London residence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=20, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_document"),
        confidence_bp=9000,
        status="asserted",
    )
    relation = replica_relation.attach_relation(
        relation_type="derived_from",
        from_revision_id=relation_residence_revision.revision_id,
        to_revision_id=relation_evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=21, recorded_at=dt(2024, 1, 3)),
    )

    replica_retraction = KnowledgeStore()
    replica_retraction.assert_revision(
        core=residence_core,
        assertion="Ada residence claim retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=22, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_retraction"),
        confidence_bp=8000,
        status="retracted",
    )

    return (
        residence_core,
        [replica_endpoints, replica_relation, replica_retraction],
        residence_asserted.revision_id,
        relation.relation_id,
    )


def _checkpoint_replay_scenario() -> tuple[ClaimCore, list[KnowledgeStore], str, str]:
    core_residence = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    core_fact = ClaimCore(claim_type="fact", slots={"subject": "London"})
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    replica_residence = KnowledgeStore()
    asserted_residence = replica_residence.assert_revision(
        core=core_residence,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=30, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8100,
        status="asserted",
    )

    replica_fact = KnowledgeStore()
    replica_fact.assert_revision(
        core=core_fact,
        assertion="London is in the UK",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=31, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_fact"),
        confidence_bp=8100,
        status="asserted",
    )

    replica_relation = KnowledgeStore()
    relation_residence_revision = replica_relation.assert_revision(
        core=core_residence,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=30, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8100,
        status="asserted",
    )
    relation_fact_revision = replica_relation.assert_revision(
        core=core_fact,
        assertion="London is in the UK",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=31, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_fact"),
        confidence_bp=8100,
        status="asserted",
    )
    relation = replica_relation.attach_relation(
        relation_type="supports",
        from_revision_id=relation_residence_revision.revision_id,
        to_revision_id=relation_fact_revision.revision_id,
        transaction_time=TransactionTime(tx_id=32, recorded_at=dt(2024, 1, 3)),
    )

    replica_competing = KnowledgeStore()
    competing_residence = replica_competing.assert_revision(
        core=core_residence,
        assertion="Ada lives in Paris",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=30, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_competing"),
        confidence_bp=8100,
        status="asserted",
    )

    expected_winner_revision_id = min(
        asserted_residence.revision_id,
        competing_residence.revision_id,
    )
    return (
        core_residence,
        [replica_residence, replica_fact, replica_relation, replica_competing],
        expected_winner_revision_id,
        relation.relation_id,
    )


def test_merge_permutation_order_preserves_winner_semantics() -> None:
    core, replicas, expected_winner_revision_id = _winner_scenario()
    baseline_conflict_signatures = None

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        merged, conflicts = merge_replicas(ordered_replicas)

        assert merged.query_as_of(core.core_id, valid_at=dt(2024, 1, 5), tx_id=9) is None
        winner = merged.query_as_of(core.core_id, valid_at=dt(2024, 1, 5), tx_id=10)
        assert winner is not None
        assert winner.revision_id == expected_winner_revision_id
        assert KnowledgeStore.conflict_code_counts(conflicts) == (
            (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
        )

        conflict_signatures = KnowledgeStore.conflict_signatures(conflicts)
        if baseline_conflict_signatures is None:
            baseline_conflict_signatures = conflict_signatures
        else:
            assert conflict_signatures == baseline_conflict_signatures


def test_merge_permutation_order_keeps_query_and_lifecycle_signatures_projection_content_stable() -> None:
    residence_core, replicas, expected_asserted_revision_id, expected_relation_id = (
        _relation_projection_scenario()
    )
    baseline_projection = None

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        merged, conflicts = merge_replicas(ordered_replicas)

        assert conflicts == ()

        winner_before_retraction = merged.query_as_of(
            residence_core.core_id,
            valid_at=dt(2024, 1, 5),
            tx_id=21,
        )
        assert winner_before_retraction is not None
        assert winner_before_retraction.revision_id == expected_asserted_revision_id
        assert (
            merged.query_as_of(
                residence_core.core_id,
                valid_at=dt(2024, 1, 5),
                tx_id=22,
            )
            is None
        )

        visible_relation_ids = tuple(
            relation.relation_id for relation in merged.query_relations_as_of(tx_id=21)
        )
        assert visible_relation_ids == (expected_relation_id,)
        assert merged.query_relations_as_of(
            tx_id=22,
            valid_at=dt(2024, 1, 5),
            active_only=True,
        ) == ()

        lifecycle_projection = merged.query_relation_lifecycle_as_of(
            tx_id=21,
            valid_at=dt(2024, 1, 5),
        )
        assert tuple(
            relation.relation_id for relation in lifecycle_projection.active
        ) == (expected_relation_id,)
        assert lifecycle_projection.pending == ()

        lifecycle_signatures = merged.query_relation_lifecycle_signatures_as_of(
            tx_id=21,
            valid_at=dt(2024, 1, 5),
        )
        if baseline_projection is None:
            baseline_projection = lifecycle_signatures
        else:
            assert lifecycle_signatures == baseline_projection


def test_checkpoint_replay_equivalence_is_permutation_deterministic_for_lifecycle_signatures() -> None:
    core_residence, replicas, expected_winner_revision_id, expected_relation_id = (
        _checkpoint_replay_scenario()
    )
    valid_at = dt(2024, 1, 5)

    for order in itertools.permutations(range(len(replicas))):
        ordered_replicas = [replicas[index] for index in order]
        unsplit_merged, unsplit_conflicts = merge_replicas(ordered_replicas)
        unsplit_winner = unsplit_merged.query_as_of(
            core_residence.core_id,
            valid_at=valid_at,
            tx_id=30,
        )
        assert unsplit_winner is not None
        assert unsplit_winner.revision_id == expected_winner_revision_id
        assert tuple(
            relation.relation_id for relation in unsplit_merged.query_relations_as_of(tx_id=32)
        ) == (expected_relation_id,)
        unsplit_lifecycle_projection = unsplit_merged.query_relation_lifecycle_as_of(
            tx_id=32,
            valid_at=valid_at,
        )
        unsplit_lifecycle_signatures = unsplit_merged.query_relation_lifecycle_signatures_as_of(
            tx_id=32,
            valid_at=valid_at,
        )

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_conflicts = merge_replicas(ordered_replicas[:split_index])
            resumed_merged, resumed_suffix_conflicts = merge_replicas(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )

            resumed_winner = resumed_merged.query_as_of(
                core_residence.core_id,
                valid_at=valid_at,
                tx_id=30,
            )
            assert resumed_winner is not None
            assert resumed_winner.revision_id == unsplit_winner.revision_id
            assert tuple(
                relation.relation_id
                for relation in resumed_merged.query_relations_as_of(tx_id=32)
            ) == (expected_relation_id,)
            assert resumed_merged.query_relation_lifecycle_as_of(
                tx_id=32,
                valid_at=valid_at,
            ) == unsplit_lifecycle_projection
            assert resumed_merged.query_relation_lifecycle_signatures_as_of(
                tx_id=32,
                valid_at=valid_at,
            ) == unsplit_lifecycle_signatures

            resumed_conflicts = prefix_conflicts + resumed_suffix_conflicts
            assert KnowledgeStore.conflict_signatures(resumed_conflicts) == (
                KnowledgeStore.conflict_signatures(unsplit_conflicts)
            )
