from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    DeterministicStateFingerprint,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _relation_signature(
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


def _transition_bucket_map(
    transition: DeterministicStateFingerprintTransition,
) -> dict[str, tuple]:
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


def _signature_count_sort_key(
    signature_count: tuple[str, str, str, int],
) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _expected_transition_buckets_from_as_of_fingerprints(
    from_fingerprint: DeterministicStateFingerprint,
    to_fingerprint: DeterministicStateFingerprint,
) -> dict[str, tuple]:
    from_revision_active = {
        revision.revision_id: revision
        for revision in from_fingerprint.revision_lifecycle.active
    }
    to_revision_active = {
        revision.revision_id: revision
        for revision in to_fingerprint.revision_lifecycle.active
    }
    from_revision_retracted = {
        revision.revision_id: revision
        for revision in from_fingerprint.revision_lifecycle.retracted
    }
    to_revision_retracted = {
        revision.revision_id: revision
        for revision in to_fingerprint.revision_lifecycle.retracted
    }

    from_resolution_active = {
        relation.relation_id: relation
        for relation in from_fingerprint.relation_resolution.active
    }
    to_resolution_active = {
        relation.relation_id: relation
        for relation in to_fingerprint.relation_resolution.active
    }
    from_resolution_pending = {
        relation.relation_id: relation
        for relation in from_fingerprint.relation_resolution.pending
    }
    to_resolution_pending = {
        relation.relation_id: relation
        for relation in to_fingerprint.relation_resolution.pending
    }

    from_lifecycle_active = {
        relation.relation_id: relation
        for relation in from_fingerprint.relation_lifecycle.active
    }
    to_lifecycle_active = {
        relation.relation_id: relation
        for relation in to_fingerprint.relation_lifecycle.active
    }
    from_lifecycle_pending = {
        relation.relation_id: relation
        for relation in from_fingerprint.relation_lifecycle.pending
    }
    to_lifecycle_pending = {
        relation.relation_id: relation
        for relation in to_fingerprint.relation_lifecycle.pending
    }

    from_signature_active = set(from_fingerprint.relation_lifecycle_signatures.active)
    to_signature_active = set(to_fingerprint.relation_lifecycle_signatures.active)
    from_signature_pending = set(from_fingerprint.relation_lifecycle_signatures.pending)
    to_signature_pending = set(to_fingerprint.relation_lifecycle_signatures.pending)

    from_merge_signature_counts = set(
        from_fingerprint.merge_conflict_projection.signature_counts
    )
    to_merge_signature_counts = set(to_fingerprint.merge_conflict_projection.signature_counts)
    from_merge_code_counts = set(from_fingerprint.merge_conflict_projection.code_counts)
    to_merge_code_counts = set(to_fingerprint.merge_conflict_projection.code_counts)

    return {
        "entered_revision_active": tuple(
            to_revision_active[revision_id]
            for revision_id in sorted(set(to_revision_active) - set(from_revision_active))
        ),
        "exited_revision_active": tuple(
            from_revision_active[revision_id]
            for revision_id in sorted(set(from_revision_active) - set(to_revision_active))
        ),
        "entered_revision_retracted": tuple(
            to_revision_retracted[revision_id]
            for revision_id in sorted(
                set(to_revision_retracted) - set(from_revision_retracted)
            )
        ),
        "exited_revision_retracted": tuple(
            from_revision_retracted[revision_id]
            for revision_id in sorted(
                set(from_revision_retracted) - set(to_revision_retracted)
            )
        ),
        "entered_relation_resolution_active": tuple(
            to_resolution_active[relation_id]
            for relation_id in sorted(set(to_resolution_active) - set(from_resolution_active))
        ),
        "exited_relation_resolution_active": tuple(
            from_resolution_active[relation_id]
            for relation_id in sorted(
                set(from_resolution_active) - set(to_resolution_active)
            )
        ),
        "entered_relation_resolution_pending": tuple(
            to_resolution_pending[relation_id]
            for relation_id in sorted(
                set(to_resolution_pending) - set(from_resolution_pending)
            )
        ),
        "exited_relation_resolution_pending": tuple(
            from_resolution_pending[relation_id]
            for relation_id in sorted(
                set(from_resolution_pending) - set(to_resolution_pending)
            )
        ),
        "entered_relation_lifecycle_active": tuple(
            to_lifecycle_active[relation_id]
            for relation_id in sorted(set(to_lifecycle_active) - set(from_lifecycle_active))
        ),
        "exited_relation_lifecycle_active": tuple(
            from_lifecycle_active[relation_id]
            for relation_id in sorted(set(from_lifecycle_active) - set(to_lifecycle_active))
        ),
        "entered_relation_lifecycle_pending": tuple(
            to_lifecycle_pending[relation_id]
            for relation_id in sorted(set(to_lifecycle_pending) - set(from_lifecycle_pending))
        ),
        "exited_relation_lifecycle_pending": tuple(
            from_lifecycle_pending[relation_id]
            for relation_id in sorted(set(from_lifecycle_pending) - set(to_lifecycle_pending))
        ),
        "entered_relation_lifecycle_signature_active": tuple(
            sorted(to_signature_active - from_signature_active)
        ),
        "exited_relation_lifecycle_signature_active": tuple(
            sorted(from_signature_active - to_signature_active)
        ),
        "entered_relation_lifecycle_signature_pending": tuple(
            sorted(to_signature_pending - from_signature_pending)
        ),
        "exited_relation_lifecycle_signature_pending": tuple(
            sorted(from_signature_pending - to_signature_pending)
        ),
        "entered_merge_conflict_signature_counts": tuple(
            sorted(
                to_merge_signature_counts - from_merge_signature_counts,
                key=_signature_count_sort_key,
            )
        ),
        "exited_merge_conflict_signature_counts": tuple(
            sorted(
                from_merge_signature_counts - to_merge_signature_counts,
                key=_signature_count_sort_key,
            )
        ),
        "entered_merge_conflict_code_counts": tuple(
            sorted(
                to_merge_code_counts - from_merge_code_counts,
                key=_code_count_sort_key,
            )
        ),
        "exited_merge_conflict_code_counts": tuple(
            sorted(
                from_merge_code_counts - to_merge_code_counts,
                key=_code_count_sort_key,
            )
        ),
    }


def _build_state_fingerprint_transition_store() -> tuple[
    KnowledgeStore,
    datetime,
    int,
    int,
    str,
    dict[str, object],
]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_from = 3
    tx_to = 7

    core_anchor = ClaimCore(claim_type="document", slots={"id": "fingerprint-transition-anchor"})
    core_enter_active = ClaimCore(
        claim_type="residence",
        slots={"subject": "fingerprint-transition-enter"},
    )
    core_exit_active = ClaimCore(
        claim_type="residence",
        slots={"subject": "fingerprint-transition-exit"},
    )
    core_reactivate = ClaimCore(
        claim_type="residence",
        slots={"subject": "fingerprint-transition-reactivate"},
    )

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="fingerprint transition anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_fingerprint_transition_anchor"),
        confidence_bp=9200,
        status="asserted",
    )
    exited_active_revision = store.assert_revision(
        core=core_exit_active,
        assertion="fingerprint transition exited core",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_fingerprint_transition_exit_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    exited_retracted_revision = store.assert_revision(
        core=core_exit_active,
        assertion="fingerprint transition exited core",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_fingerprint_transition_exit_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    entered_active_revision = store.assert_revision(
        core=core_enter_active,
        assertion="fingerprint transition entered core",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_fingerprint_transition_enter"),
        confidence_bp=8500,
        status="asserted",
    )
    exited_retracted_prior_revision = store.assert_revision(
        core=core_reactivate,
        assertion="fingerprint transition reactivate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_fingerprint_transition_reactivate_retracted"),
        confidence_bp=8300,
        status="retracted",
    )
    entered_active_from_retracted_revision = store.assert_revision(
        core=core_reactivate,
        assertion="fingerprint transition reactivate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_fingerprint_transition_reactivate_asserted"),
        confidence_bp=8300,
        status="asserted",
    )

    exited_active_relation = store.attach_relation(
        relation_type="derived_from",
        from_revision_id=exited_active_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    entered_active_relation = store.attach_relation(
        relation_type="supports",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    entered_active_from_reactivated_relation = store.attach_relation(
        relation_type="depends_on",
        from_revision_id=entered_active_from_retracted_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )

    orphan_replica = KnowledgeStore()
    exited_pending_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=exited_active_revision.revision_id,
        to_revision_id="missing-fingerprint-transition-exited-pending",
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    entered_pending_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id="missing-fingerprint-transition-entered-pending",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    orphan_replica.relations[exited_pending_relation.relation_id] = exited_pending_relation
    orphan_replica.relations[entered_pending_relation.relation_id] = entered_pending_relation
    store = store.merge(orphan_replica).merged

    return (
        store,
        valid_at,
        tx_from,
        tx_to,
        core_exit_active.core_id,
        {
            "entered_active_revision": entered_active_revision,
            "exited_active_revision": exited_active_revision,
            "entered_retracted_revision": exited_retracted_revision,
            "exited_retracted_revision": exited_retracted_prior_revision,
            "entered_active_from_retracted_revision": entered_active_from_retracted_revision,
            "entered_active_relation": entered_active_relation,
            "exited_active_relation": exited_active_relation,
            "entered_active_from_reactivated_relation": entered_active_from_reactivated_relation,
            "entered_pending_relation": entered_pending_relation,
            "exited_pending_relation": exited_pending_relation,
        },
    )


def test_state_fingerprint_transition_tracks_entered_and_exited_buckets() -> None:
    (
        store,
        valid_at,
        tx_from,
        tx_to,
        _target_core_id,
        artifacts,
    ) = _build_state_fingerprint_transition_store()
    transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    from_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
    )
    to_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
    )

    entered_revision_active = (
        artifacts["entered_active_revision"],
        artifacts["entered_active_from_retracted_revision"],
    )
    entered_relation_active = (
        artifacts["entered_active_relation"],
        artifacts["entered_active_from_reactivated_relation"],
    )

    assert transition.tx_from == tx_from
    assert transition.tx_to == tx_to
    assert transition.from_digest == from_fingerprint.digest
    assert transition.to_digest == to_fingerprint.digest
    assert transition.entered_revision_active == tuple(
        sorted(entered_revision_active, key=lambda revision: revision.revision_id)
    )
    assert transition.exited_revision_active == (artifacts["exited_active_revision"],)
    assert transition.entered_revision_retracted == (artifacts["entered_retracted_revision"],)
    assert transition.exited_revision_retracted == (artifacts["exited_retracted_revision"],)
    assert transition.entered_relation_resolution_active == tuple(
        sorted(entered_relation_active, key=lambda relation: relation.relation_id)
    )
    assert transition.exited_relation_resolution_active == (artifacts["exited_active_relation"],)
    assert transition.entered_relation_resolution_pending == (
        artifacts["entered_pending_relation"],
    )
    assert transition.exited_relation_resolution_pending == ()
    assert transition.entered_relation_lifecycle_active == tuple(
        sorted(entered_relation_active, key=lambda relation: relation.relation_id)
    )
    assert transition.exited_relation_lifecycle_active == (artifacts["exited_active_relation"],)
    assert transition.entered_relation_lifecycle_pending == (
        artifacts["entered_pending_relation"],
    )
    assert transition.exited_relation_lifecycle_pending == ()
    assert transition.entered_relation_lifecycle_signature_active == tuple(
        sorted(
            _relation_signature("active", relation)
            for relation in entered_relation_active
        )
    )
    assert transition.exited_relation_lifecycle_signature_active == (
        _relation_signature("active", artifacts["exited_active_relation"]),
    )
    assert transition.entered_relation_lifecycle_signature_pending == (
        _relation_signature("pending", artifacts["entered_pending_relation"]),
    )
    assert transition.exited_relation_lifecycle_signature_pending == ()
    assert transition.entered_merge_conflict_signature_counts == ()
    assert transition.exited_merge_conflict_signature_counts == ()
    assert transition.entered_merge_conflict_code_counts == ()
    assert transition.exited_merge_conflict_code_counts == ()


def test_state_fingerprint_transition_zero_delta_has_identity_digests_and_empty_buckets() -> None:
    (
        store,
        valid_at,
        tx_from,
        _tx_to,
        _target_core_id,
        _artifacts,
    ) = _build_state_fingerprint_transition_store()

    transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_from,
        valid_at=valid_at,
    )
    fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
    )

    assert transition.from_digest == fingerprint.digest
    assert transition.to_digest == fingerprint.digest
    for bucket in _transition_bucket_map(transition).values():
        assert bucket == ()


def test_state_fingerprint_transition_supports_core_filtering() -> None:
    (
        store,
        valid_at,
        tx_from,
        tx_to,
        target_core_id,
        artifacts,
    ) = _build_state_fingerprint_transition_store()

    filtered_transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
        core_id=target_core_id,
    )
    from_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_from,
        valid_at=valid_at,
        core_id=target_core_id,
    )
    to_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_to,
        valid_at=valid_at,
        core_id=target_core_id,
    )

    assert filtered_transition.from_digest == from_fingerprint.digest
    assert filtered_transition.to_digest == to_fingerprint.digest
    assert filtered_transition.entered_revision_active == ()
    assert filtered_transition.exited_revision_active == (artifacts["exited_active_revision"],)
    assert filtered_transition.entered_revision_retracted == (
        artifacts["entered_retracted_revision"],
    )
    assert filtered_transition.exited_revision_retracted == ()
    assert filtered_transition.entered_relation_resolution_active == ()
    assert filtered_transition.exited_relation_resolution_active == (
        artifacts["exited_active_relation"],
    )
    assert filtered_transition.entered_relation_resolution_pending == ()
    assert filtered_transition.exited_relation_resolution_pending == (
        artifacts["exited_pending_relation"],
    )
    assert filtered_transition.entered_relation_lifecycle_active == ()
    assert filtered_transition.exited_relation_lifecycle_active == (
        artifacts["exited_active_relation"],
    )
    assert filtered_transition.entered_relation_lifecycle_pending == ()
    assert filtered_transition.exited_relation_lifecycle_pending == (
        artifacts["exited_pending_relation"],
    )
    assert filtered_transition.entered_relation_lifecycle_signature_active == ()
    assert filtered_transition.exited_relation_lifecycle_signature_active == (
        _relation_signature("active", artifacts["exited_active_relation"]),
    )
    assert filtered_transition.entered_relation_lifecycle_signature_pending == ()
    assert filtered_transition.exited_relation_lifecycle_signature_pending == (
        _relation_signature("pending", artifacts["exited_pending_relation"]),
    )


def test_state_fingerprint_transition_matches_explicit_as_of_fingerprint_diffs() -> None:
    (
        store,
        valid_at,
        tx_from,
        tx_to,
        target_core_id,
        _artifacts,
    ) = _build_state_fingerprint_transition_store()

    for core_id in (None, target_core_id):
        from_fingerprint = store.query_state_fingerprint_as_of(
            tx_id=tx_from,
            valid_at=valid_at,
            core_id=core_id,
        )
        to_fingerprint = store.query_state_fingerprint_as_of(
            tx_id=tx_to,
            valid_at=valid_at,
            core_id=core_id,
        )
        transition = store.query_state_fingerprint_transition_for_tx_window(
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
            core_id=core_id,
        )

        assert _transition_bucket_map(
            transition
        ) == _expected_transition_buckets_from_as_of_fingerprints(
            from_fingerprint,
            to_fingerprint,
        )
        assert transition.from_digest == from_fingerprint.digest
        assert transition.to_digest == to_fingerprint.digest


def test_state_fingerprint_transition_rejects_inverted_tx_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_to must be greater than or equal to tx_from",
    ):
        KnowledgeStore().query_state_fingerprint_transition_for_tx_window(
            tx_from=9,
            tx_to=8,
            valid_at=dt(2024, 6, 1),
        )
