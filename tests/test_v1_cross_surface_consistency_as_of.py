from datetime import datetime, timezone

from dks import ClaimCore, KnowledgeStore, Provenance, TransactionTime, ValidTime


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _assert_revision_ordering(revisions: tuple) -> None:
    revision_ids = tuple(revision.revision_id for revision in revisions)
    assert revision_ids == tuple(sorted(revision_ids))


def _assert_relation_ordering(relations: tuple) -> None:
    relation_ids = tuple(relation.relation_id for relation in relations)
    assert relation_ids == tuple(sorted(relation_ids))


def _winner_set_by_core(
    store: KnowledgeStore,
    *,
    core_ids: tuple[str, ...],
    tx_id: int,
    valid_at: datetime,
) -> dict[str, object]:
    winners: dict[str, object] = {}
    for core_id in core_ids:
        winner = store.query_as_of(
            core_id,
            tx_id=tx_id,
            valid_at=valid_at,
        )
        if winner is not None:
            winners[core_id] = winner
    return winners


def _cross_surface_as_of_consistency_scenario() -> tuple[
    KnowledgeStore,
    datetime,
    int,
    tuple[str, ...],
    str,
    str,
]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_as_of = 6

    core_subject = ClaimCore(claim_type="residence", slots={"subject": "ada lovelace"})
    core_evidence = ClaimCore(claim_type="document", slots={"id": "archive-evidence"})
    core_context = ClaimCore(claim_type="fact", slots={"id": "context"})
    core_retracted = ClaimCore(claim_type="residence", slots={"subject": "grace hopper"})

    evidence_winner = store.assert_revision(
        core=core_evidence,
        assertion="Archive confirms London residence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_evidence"),
        confidence_bp=9000,
        status="asserted",
    )
    context_winner = store.assert_revision(
        core=core_context,
        assertion="Context record for Ada",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_context"),
        confidence_bp=9000,
        status="asserted",
    )
    subject_revision_a = store.assert_revision(
        core=core_subject,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_subject_a"),
        confidence_bp=8300,
        status="asserted",
    )
    subject_revision_b = store.assert_revision(
        core=core_subject,
        assertion="Ada lives in Paris",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_subject_b"),
        confidence_bp=8300,
        status="asserted",
    )
    subject_winner = (
        subject_revision_a
        if subject_revision_a.revision_id < subject_revision_b.revision_id
        else subject_revision_b
    )
    subject_loser = (
        subject_revision_b
        if subject_winner.revision_id == subject_revision_a.revision_id
        else subject_revision_a
    )

    retracted_asserted = store.assert_revision(
        core=core_retracted,
        assertion="Grace lives in New York",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_retracted_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="Grace residence claim retracted",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_retracted_retraction"),
        confidence_bp=8300,
        status="retracted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=subject_winner.revision_id,
        to_revision_id=evidence_winner.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=context_winner.revision_id,
        to_revision_id=subject_winner.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=context_winner.revision_id,
        to_revision_id=evidence_winner.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=subject_loser.revision_id,
        to_revision_id=evidence_winner.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=retracted_asserted.revision_id,
        to_revision_id=evidence_winner.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )

    return (
        store,
        valid_at,
        tx_as_of,
        (
            core_subject.core_id,
            core_evidence.core_id,
            core_context.core_id,
            core_retracted.core_id,
        ),
        core_subject.core_id,
        core_retracted.core_id,
    )


def test_query_as_of_winners_match_unfiltered_as_of_projection_active_buckets() -> None:
    (
        store,
        valid_at,
        tx_as_of,
        core_ids,
        _subject_core_id,
        _retracted_core_id,
    ) = _cross_surface_as_of_consistency_scenario()

    winners_by_core = _winner_set_by_core(
        store,
        core_ids=core_ids,
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    winner_revision_ids = {winner.revision_id for winner in winners_by_core.values()}

    revision_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    relation_resolution_projection = store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    relation_lifecycle_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )

    _assert_revision_ordering(revision_projection.active)
    _assert_relation_ordering(relation_resolution_projection.active)
    _assert_relation_ordering(relation_lifecycle_projection.active)

    expected_active_revisions = tuple(
        sorted(winners_by_core.values(), key=lambda revision: revision.revision_id)
    )
    assert revision_projection.active == expected_active_revisions

    expected_active_relations = tuple(
        relation
        for relation in store.query_relations_as_of(tx_id=tx_as_of)
        if relation.from_revision_id in winner_revision_ids
        and relation.to_revision_id in winner_revision_ids
    )
    assert relation_resolution_projection.active == expected_active_relations
    assert relation_lifecycle_projection.active == expected_active_relations
    assert relation_resolution_projection.active == relation_lifecycle_projection.active


def test_query_as_of_winners_match_filtered_as_of_projection_active_buckets() -> None:
    (
        store,
        valid_at,
        tx_as_of,
        core_ids,
        subject_core_id,
        retracted_core_id,
    ) = _cross_surface_as_of_consistency_scenario()

    winners_by_core = _winner_set_by_core(
        store,
        core_ids=core_ids,
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    winner_revision_ids = {winner.revision_id for winner in winners_by_core.values()}

    subject_winner = store.query_as_of(
        subject_core_id,
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert subject_winner is not None
    assert winners_by_core[subject_core_id].revision_id == subject_winner.revision_id
    assert store.query_as_of(retracted_core_id, tx_id=tx_as_of, valid_at=valid_at) is None

    subject_revision_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    _assert_revision_ordering(subject_revision_projection.active)
    assert subject_revision_projection.active == (subject_winner,)
    assert subject_revision_projection.retracted == ()

    subject_resolution_projection = store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    subject_lifecycle_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        revision_id=subject_winner.revision_id,
    )
    _assert_relation_ordering(subject_resolution_projection.active)
    _assert_relation_ordering(subject_lifecycle_projection.active)

    expected_subject_active_relations = tuple(
        relation
        for relation in store.query_relations_as_of(
            tx_id=tx_as_of,
            revision_id=subject_winner.revision_id,
        )
        if relation.from_revision_id in winner_revision_ids
        and relation.to_revision_id in winner_revision_ids
    )
    assert subject_resolution_projection.active == expected_subject_active_relations
    assert subject_lifecycle_projection.active == expected_subject_active_relations

    retracted_revision_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=retracted_core_id,
    )
    assert retracted_revision_projection.active == ()
    assert len(retracted_revision_projection.retracted) == 1
    retracted_resolution_projection = store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=retracted_core_id,
    )
    assert retracted_resolution_projection.active == ()
    assert retracted_resolution_projection.pending == ()
