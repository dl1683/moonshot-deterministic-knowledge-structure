from datetime import datetime, timezone

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    Provenance,
    RelationEdge,
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
        result = merged.merge(replica)
        merged = result.merged
        conflicts.extend(result.conflicts)
    return merged, tuple(conflicts)


def test_revision_winner_selection_is_deterministic() -> None:
    store = KnowledgeStore()
    core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    asserted_a = store.assert_revision(
        core=core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_a"),
        confidence_bp=7600,
        status="asserted",
    )
    asserted_b = store.assert_revision(
        core=core,
        assertion="Ada lives in Paris",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_b"),
        confidence_bp=7600,
        status="asserted",
    )

    assert store.query_as_of(core.core_id, valid_at=dt(2024, 1, 5), tx_id=9) is None

    tie_winner = store.query_as_of(core.core_id, valid_at=dt(2024, 1, 5), tx_id=10)
    assert tie_winner is not None
    assert tie_winner.revision_id == min(asserted_a.revision_id, asserted_b.revision_id)

    store.assert_revision(
        core=core,
        assertion="Ada residence claim retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=11, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_retraction"),
        confidence_bp=7600,
        status="retracted",
    )
    assert store.query_as_of(core.core_id, valid_at=dt(2024, 1, 5), tx_id=11) is None

    asserted_after_retraction = store.assert_revision(
        core=core,
        assertion="Ada lives in Rome",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=12, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_c"),
        confidence_bp=7600,
        status="asserted",
    )
    winner_after_reassert = store.query_as_of(
        core.core_id, valid_at=dt(2024, 1, 5), tx_id=12
    )
    assert winner_after_reassert is not None
    assert winner_after_reassert.revision_id == asserted_after_retraction.revision_id


def test_merge_checkpoint_replay_equivalence_matches_unsplit() -> None:
    core_residence = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    core_fact = ClaimCore(claim_type="fact", slots={"subject": "London"})
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    replica_residence = KnowledgeStore()
    replica_residence.assert_revision(
        core=core_residence,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=20, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8100,
        status="asserted",
    )

    replica_fact = KnowledgeStore()
    replica_fact.assert_revision(
        core=core_fact,
        assertion="London is in the UK",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=21, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_fact"),
        confidence_bp=8100,
        status="asserted",
    )

    replica_relation = KnowledgeStore()
    relation_residence_revision = replica_relation.assert_revision(
        core=core_residence,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=20, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8100,
        status="asserted",
    )
    relation_fact_revision = replica_relation.assert_revision(
        core=core_fact,
        assertion="London is in the UK",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=21, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_fact"),
        confidence_bp=8100,
        status="asserted",
    )
    relation = replica_relation.attach_relation(
        relation_type="supports",
        from_revision_id=relation_residence_revision.revision_id,
        to_revision_id=relation_fact_revision.revision_id,
        transaction_time=TransactionTime(tx_id=22, recorded_at=dt(2024, 1, 3)),
    )

    replica_competing = KnowledgeStore()
    replica_competing.assert_revision(
        core=core_residence,
        assertion="Ada lives in Paris",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=20, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_competing"),
        confidence_bp=8100,
        status="asserted",
    )

    replay_sequence = [replica_residence, replica_fact, replica_relation, replica_competing]

    unsplit_merged, unsplit_conflicts = merge_replicas(replay_sequence)
    unsplit_conflict_signatures = KnowledgeStore.conflict_signatures(unsplit_conflicts)
    assert KnowledgeStore.conflict_code_counts(unsplit_conflicts) == (
        (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 1),
    )
    assert len(unsplit_conflict_signatures) == 1
    assert unsplit_conflict_signatures[0][0] == ConflictCode.COMPETING_REVISION_SAME_SLOT.value
    assert unsplit_conflict_signatures[0][1] == core_residence.core_id
    assert unsplit_merged.query_relations_as_of(tx_id=22) == (relation,)
    assert unsplit_merged.pending_relation_ids() == ()

    for split_index in range(1, len(replay_sequence)):
        prefix_merged, prefix_conflicts = merge_replicas(replay_sequence[:split_index])
        resumed_merged, resumed_suffix_conflicts = merge_replicas(
            replay_sequence[split_index:],
            start=prefix_merged.checkpoint(),
        )
        resumed_signatures = KnowledgeStore.conflict_signatures(
            prefix_conflicts + resumed_suffix_conflicts
        )

        assert resumed_signatures == unsplit_conflict_signatures
        assert resumed_merged.revision_state_signatures() == unsplit_merged.revision_state_signatures()
        assert resumed_merged.relation_state_signatures() == unsplit_merged.relation_state_signatures()
        assert resumed_merged.pending_relation_ids() == unsplit_merged.pending_relation_ids()
        assert resumed_merged.query_relations_as_of(tx_id=22) == (relation,)


def test_orphan_relation_promotes_to_active_after_missing_endpoint_arrives() -> None:
    core_subject = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    core_location = ClaimCore(claim_type="location", slots={"subject": "London"})
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)

    anchor_replica = KnowledgeStore()
    subject_revision = anchor_replica.assert_revision(
        core=core_subject,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=30, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="anchor_subject"),
        confidence_bp=8200,
        status="asserted",
    )

    endpoint_replica = KnowledgeStore()
    missing_endpoint_revision = endpoint_replica.assert_revision(
        core=core_location,
        assertion="London is in the UK",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=32, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="endpoint_location"),
        confidence_bp=8200,
        status="asserted",
    )

    orphan_replica = KnowledgeStore()
    orphan_replica.assert_revision(
        core=core_subject,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=30, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="anchor_subject"),
        confidence_bp=8200,
        status="asserted",
    )
    orphan_relation = RelationEdge(
        relation_type="supports",
        from_revision_id=subject_revision.revision_id,
        to_revision_id=missing_endpoint_revision.revision_id,
        transaction_time=TransactionTime(tx_id=31, recorded_at=dt(2024, 1, 3)),
    )
    orphan_replica.relations[orphan_relation.relation_id] = orphan_relation

    merged = KnowledgeStore()
    merged = merged.merge(anchor_replica).merged

    orphan_result = merged.merge(orphan_replica)
    merged = orphan_result.merged

    assert KnowledgeStore.conflict_code_counts(orphan_result.conflicts) == (
        (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 1),
    )
    assert merged.pending_relation_ids() == (orphan_relation.relation_id,)
    assert merged.query_pending_relations_as_of(tx_id=31) == (orphan_relation,)
    assert merged.query_relations_as_of(tx_id=31) == ()

    promotion_result = merged.merge(endpoint_replica)
    merged = promotion_result.merged

    assert promotion_result.conflicts == ()
    assert merged.pending_relation_ids() == ()
    assert merged.query_pending_relations_as_of(tx_id=40) == ()
    assert merged.query_relations_as_of(tx_id=40) == (orphan_relation,)
    assert merged.query_relations_as_of(
        tx_id=40,
        valid_at=dt(2024, 1, 5),
        active_only=True,
    ) == (orphan_relation,)
