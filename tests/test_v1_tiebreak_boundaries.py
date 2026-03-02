from datetime import datetime, timezone

import pytest

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


def _relation_ids(bucket: tuple) -> tuple[str, ...]:
    return tuple(relation.relation_id for relation in bucket)


def _build_tiebreak_boundary_scenario() -> dict[str, object]:
    store = KnowledgeStore()

    valid_at_before_boundary = dt(2024, 5, 31)
    valid_at_boundary = dt(2024, 6, 1)

    valid_open = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_before_boundary = ValidTime(start=dt(2024, 1, 1), end=valid_at_boundary)
    valid_from_boundary = ValidTime(start=valid_at_boundary, end=None)

    core_anchor = ClaimCore(claim_type="document", slots={"id": "tiebreak-anchor"})
    core_tie = ClaimCore(claim_type="residence", slots={"subject": "tiebreak-tie"})
    core_retracted = ClaimCore(
        claim_type="residence",
        slots={"subject": "tiebreak-retracted"},
    )
    core_boundary = ClaimCore(claim_type="fact", slots={"id": "tiebreak-boundary"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="anchor revision",
        valid_time=valid_open,
        transaction_time=TransactionTime(tx_id=9, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_anchor"),
        confidence_bp=9000,
        status="asserted",
    )

    tie_revision_a = store.assert_revision(
        core=core_tie,
        assertion="tie candidate a",
        valid_time=valid_open,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
        provenance=Provenance(source="source_tie_a"),
        confidence_bp=8200,
        status="asserted",
    )
    tie_revision_b = store.assert_revision(
        core=core_tie,
        assertion="tie candidate b",
        valid_time=valid_open,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
        provenance=Provenance(source="source_tie_b"),
        confidence_bp=8200,
        status="asserted",
    )
    tie_winner = min(
        (tie_revision_a, tie_revision_b),
        key=lambda revision: revision.revision_id,
    )
    tie_loser = (
        tie_revision_b
        if tie_winner.revision_id == tie_revision_a.revision_id
        else tie_revision_a
    )

    retracted_asserted = store.assert_revision(
        core=core_retracted,
        assertion="retracted candidate asserted",
        valid_time=valid_open,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
        provenance=Provenance(source="source_retracted_asserted"),
        confidence_bp=8200,
        status="asserted",
    )
    retracted_winner = store.assert_revision(
        core=core_retracted,
        assertion="retracted candidate retracted",
        valid_time=valid_open,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
        provenance=Provenance(source="source_retracted_winner"),
        confidence_bp=8200,
        status="retracted",
    )

    boundary_old = store.assert_revision(
        core=core_boundary,
        assertion="boundary old winner",
        valid_time=valid_before_boundary,
        transaction_time=TransactionTime(tx_id=9, recorded_at=dt(2024, 1, 10)),
        provenance=Provenance(source="source_boundary_old"),
        confidence_bp=8100,
        status="asserted",
    )
    boundary_new = store.assert_revision(
        core=core_boundary,
        assertion="boundary new winner",
        valid_time=valid_from_boundary,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
        provenance=Provenance(source="source_boundary_new"),
        confidence_bp=8100,
        status="asserted",
    )

    active_tie = store.attach_relation(
        relation_type="supports",
        from_revision_id=tie_winner.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=tie_loser.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=retracted_asserted.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
    )
    active_boundary = store.attach_relation(
        relation_type="derived_from",
        from_revision_id=boundary_new.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=11, recorded_at=dt(2024, 1, 12)),
    )

    orphan_replica = KnowledgeStore()
    pending_tie = RelationEdge(
        relation_type="depends_on",
        from_revision_id=tie_winner.revision_id,
        to_revision_id="missing-tiebreak-winner-endpoint",
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
    )
    pending_loser = RelationEdge(
        relation_type="supports",
        from_revision_id=tie_loser.revision_id,
        to_revision_id="missing-tiebreak-loser-endpoint",
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
    )
    pending_retracted = RelationEdge(
        relation_type="supports",
        from_revision_id=retracted_asserted.revision_id,
        to_revision_id="missing-tiebreak-retracted-endpoint",
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
    )
    pending_boundary = RelationEdge(
        relation_type="depends_on",
        from_revision_id=boundary_new.revision_id,
        to_revision_id="missing-tiebreak-boundary-endpoint",
        transaction_time=TransactionTime(tx_id=11, recorded_at=dt(2024, 1, 12)),
    )
    orphan_replica.relations[pending_tie.relation_id] = pending_tie
    orphan_replica.relations[pending_loser.relation_id] = pending_loser
    orphan_replica.relations[pending_retracted.relation_id] = pending_retracted
    orphan_replica.relations[pending_boundary.relation_id] = pending_boundary
    store = store.merge(orphan_replica).merged

    return {
        "store": store,
        "core_tie": core_tie,
        "core_retracted": core_retracted,
        "core_boundary": core_boundary,
        "tie_winner": tie_winner,
        "tie_loser": tie_loser,
        "retracted_winner": retracted_winner,
        "boundary_old": boundary_old,
        "boundary_new": boundary_new,
        "active_tie": active_tie,
        "active_boundary": active_boundary,
        "pending_tie": pending_tie,
        "pending_boundary": pending_boundary,
        "valid_at_before_boundary": valid_at_before_boundary,
        "valid_at_boundary": valid_at_boundary,
    }


def _build_merge_conflict_boundary_stream() -> tuple[tuple[int, MergeResult], ...]:
    return (
        (
            10,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(
                    MergeConflict(
                        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
                        entity_id="entity-b",
                        details="missing endpoint b",
                    ),
                    MergeConflict(
                        code=ConflictCode.CORE_ID_COLLISION,
                        entity_id="entity-z",
                        details="core collision z",
                    ),
                ),
            ),
        ),
        (
            10,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(
                    MergeConflict(
                        code=ConflictCode.CORE_ID_COLLISION,
                        entity_id="entity-z",
                        details="core collision z",
                    ),
                    MergeConflict(
                        code=ConflictCode.CORE_ID_COLLISION,
                        entity_id="entity-a",
                        details="core collision a",
                    ),
                ),
            ),
        ),
        (
            11,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(
                    MergeConflict(
                        code=ConflictCode.REVISION_ID_COLLISION,
                        entity_id="entity-r",
                        details="revision collision r",
                    ),
                    MergeConflict(
                        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
                        entity_id="entity-b",
                        details="missing endpoint b",
                    ),
                ),
            ),
        ),
        (
            12,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(),
            ),
        ),
    )


def test_query_as_of_tiebreak_boundary_matrix() -> None:
    scenario = _build_tiebreak_boundary_scenario()
    store = scenario["store"]
    tie_winner = scenario["tie_winner"]
    tie_loser = scenario["tie_loser"]

    assert tie_winner.revision_id < tie_loser.revision_id

    query_cases = (
        (
            scenario["core_tie"].core_id,
            scenario["valid_at_boundary"],
            9,
            None,
        ),
        (
            scenario["core_tie"].core_id,
            scenario["valid_at_boundary"],
            10,
            scenario["tie_winner"],
        ),
        (
            scenario["core_retracted"].core_id,
            scenario["valid_at_boundary"],
            10,
            None,
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_before_boundary"],
            9,
            scenario["boundary_old"],
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_before_boundary"],
            10,
            scenario["boundary_old"],
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_boundary"],
            9,
            None,
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_boundary"],
            10,
            scenario["boundary_new"],
        ),
    )
    for core_id, valid_at, tx_id, expected in query_cases:
        assert store.query_as_of(core_id, valid_at=valid_at, tx_id=tx_id) == expected


def test_revision_lifecycle_as_of_and_window_tiebreak_boundary_matrix() -> None:
    scenario = _build_tiebreak_boundary_scenario()
    store = scenario["store"]

    as_of_cases = (
        (
            scenario["core_tie"].core_id,
            scenario["valid_at_boundary"],
            10,
            (scenario["tie_winner"],),
            (),
        ),
        (
            scenario["core_retracted"].core_id,
            scenario["valid_at_boundary"],
            10,
            (),
            (scenario["retracted_winner"],),
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_before_boundary"],
            10,
            (scenario["boundary_old"],),
            (),
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_boundary"],
            10,
            (scenario["boundary_new"],),
            (),
        ),
    )
    for core_id, valid_at, tx_id, expected_active, expected_retracted in as_of_cases:
        projection = store.query_revision_lifecycle_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            core_id=core_id,
        )
        assert projection.active == expected_active
        assert projection.retracted == expected_retracted

    window_cases = (
        (
            scenario["core_tie"].core_id,
            scenario["valid_at_boundary"],
            10,
            10,
            (scenario["tie_winner"],),
            (),
        ),
        (
            scenario["core_retracted"].core_id,
            scenario["valid_at_boundary"],
            10,
            10,
            (),
            (scenario["retracted_winner"],),
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_before_boundary"],
            10,
            10,
            (),
            (),
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_boundary"],
            10,
            10,
            (scenario["boundary_new"],),
            (),
        ),
        (
            scenario["core_boundary"].core_id,
            scenario["valid_at_boundary"],
            11,
            11,
            (),
            (),
        ),
    )
    for (
        core_id,
        valid_at,
        tx_start,
        tx_end,
        expected_active,
        expected_retracted,
    ) in window_cases:
        projection = store.query_revision_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            core_id=core_id,
        )
        assert projection.active == expected_active
        assert projection.retracted == expected_retracted


def test_relation_lifecycle_and_resolution_as_of_window_tiebreak_boundary_matrix() -> None:
    scenario = _build_tiebreak_boundary_scenario()
    store = scenario["store"]

    lifecycle_as_of_cases = (
        (
            10,
            scenario["tie_winner"].revision_id,
            (scenario["active_tie"],),
            (scenario["pending_tie"],),
        ),
        (
            11,
            scenario["tie_winner"].revision_id,
            (scenario["active_tie"],),
            (scenario["pending_tie"],),
        ),
        (
            10,
            scenario["boundary_new"].revision_id,
            (),
            (),
        ),
        (
            11,
            scenario["boundary_new"].revision_id,
            (scenario["active_boundary"],),
            (scenario["pending_boundary"],),
        ),
    )
    for tx_id, revision_id, expected_active, expected_pending in lifecycle_as_of_cases:
        projection = store.query_relation_lifecycle_as_of(
            tx_id=tx_id,
            valid_at=scenario["valid_at_boundary"],
            revision_id=revision_id,
        )
        assert projection.active == expected_active
        assert projection.pending == expected_pending
        assert _relation_ids(projection.active) == tuple(sorted(_relation_ids(projection.active)))
        assert _relation_ids(projection.pending) == tuple(sorted(_relation_ids(projection.pending)))

    lifecycle_window_cases = (
        (
            10,
            10,
            scenario["tie_winner"].revision_id,
            (scenario["active_tie"],),
            (scenario["pending_tie"],),
        ),
        (
            11,
            11,
            scenario["tie_winner"].revision_id,
            (),
            (),
        ),
        (
            11,
            11,
            scenario["boundary_new"].revision_id,
            (scenario["active_boundary"],),
            (scenario["pending_boundary"],),
        ),
    )
    for tx_start, tx_end, revision_id, expected_active, expected_pending in lifecycle_window_cases:
        projection = store.query_relation_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=scenario["valid_at_boundary"],
            revision_id=revision_id,
        )
        assert projection.active == expected_active
        assert projection.pending == expected_pending

    resolution_as_of_cases = (
        (
            10,
            scenario["core_tie"].core_id,
            (scenario["active_tie"],),
            (scenario["pending_tie"],),
        ),
        (
            11,
            scenario["core_tie"].core_id,
            (scenario["active_tie"],),
            (scenario["pending_tie"],),
        ),
        (
            11,
            scenario["core_retracted"].core_id,
            (),
            (),
        ),
        (
            10,
            scenario["core_boundary"].core_id,
            (),
            (),
        ),
        (
            11,
            scenario["core_boundary"].core_id,
            (scenario["active_boundary"],),
            (scenario["pending_boundary"],),
        ),
    )
    for tx_id, core_id, expected_active, expected_pending in resolution_as_of_cases:
        projection = store.query_relation_resolution_as_of(
            tx_id=tx_id,
            valid_at=scenario["valid_at_boundary"],
            core_id=core_id,
        )
        assert projection.active == expected_active
        assert projection.pending == expected_pending

    resolution_window_cases = (
        (
            10,
            10,
            scenario["core_tie"].core_id,
            (scenario["active_tie"],),
            (scenario["pending_tie"],),
        ),
        (
            11,
            11,
            scenario["core_tie"].core_id,
            (),
            (),
        ),
        (
            10,
            11,
            scenario["core_retracted"].core_id,
            (),
            (),
        ),
        (
            11,
            11,
            scenario["core_boundary"].core_id,
            (scenario["active_boundary"],),
            (scenario["pending_boundary"],),
        ),
    )
    for tx_start, tx_end, core_id, expected_active, expected_pending in resolution_window_cases:
        projection = store.query_relation_resolution_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=scenario["valid_at_boundary"],
            core_id=core_id,
        )
        assert projection.active == expected_active
        assert projection.pending == expected_pending


def test_lifecycle_and_resolution_window_surfaces_reject_inverted_ranges() -> None:
    scenario = _build_tiebreak_boundary_scenario()
    store = scenario["store"]

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_revision_lifecycle_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=scenario["valid_at_boundary"],
        )

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_relation_lifecycle_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=scenario["valid_at_boundary"],
            revision_id=scenario["tie_winner"].revision_id,
        )

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_relation_resolution_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=scenario["valid_at_boundary"],
            core_id=scenario["core_tie"].core_id,
        )


def test_merge_conflict_projection_tiebreak_boundary_matrix() -> None:
    stream = _build_merge_conflict_boundary_stream()
    swapped_same_tx_stream = (stream[1], stream[0], stream[2], stream[3])

    for tx_id in (9, 10, 11, 12):
        projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            stream,
            tx_id=tx_id,
        )
        expected = MergeResult.stream_conflict_summary(
            merge_result
            for merge_result_tx_id, merge_result in stream
            if merge_result_tx_id <= tx_id
        )
        assert projection.summary == expected
        signature_keys = tuple(
            (code, entity_id, details)
            for code, entity_id, details, _count in projection.signature_counts
        )
        assert signature_keys == tuple(sorted(signature_keys))
        code_keys = tuple(code for code, _count in projection.code_counts)
        assert code_keys == tuple(sorted(code_keys))

    for tx_start, tx_end in ((9, 9), (10, 10), (10, 11), (11, 11), (12, 12), (9, 12)):
        projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        expected = MergeResult.stream_conflict_summary(
            merge_result
            for merge_result_tx_id, merge_result in stream
            if tx_start <= merge_result_tx_id <= tx_end
        )
        assert projection.summary == expected

    assert KnowledgeStore.query_merge_conflict_projection_as_of(
        stream,
        tx_id=10,
    ) == KnowledgeStore.query_merge_conflict_projection_as_of(
        swapped_same_tx_stream,
        tx_id=10,
    )
    assert KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        stream,
        tx_start=10,
        tx_end=10,
    ) == KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        swapped_same_tx_stream,
        tx_start=10,
        tx_end=10,
    )


def test_merge_conflict_projection_window_rejects_inverted_range() -> None:
    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            _build_merge_conflict_boundary_stream(),
            tx_start=13,
            tx_end=12,
        )
