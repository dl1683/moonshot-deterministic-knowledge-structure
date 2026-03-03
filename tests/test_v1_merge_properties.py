"""Property-based tests for merge CRDT properties using Hypothesis.

Tests commutativity, associativity, and idempotency of KnowledgeStore.merge().
"""
import json
from datetime import datetime, timezone

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _store_fingerprint(store: KnowledgeStore) -> str:
    """Canonical JSON fingerprint for deterministic comparison."""
    payload = store.as_canonical_payload()
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


# Strategy: generate a small KnowledgeStore with N claims
@st.composite
def small_stores(draw, min_claims=0, max_claims=4):
    """Generate a small KnowledgeStore with 0-4 claims."""
    store = KnowledgeStore()
    n_claims = draw(st.integers(min_value=min_claims, max_value=max_claims))

    for i in range(n_claims):
        claim_type = draw(st.sampled_from(["fact", "residence", "role", "attribute"]))
        subject = draw(st.sampled_from(["alice", "bob", "carol", "dave"]))
        core = ClaimCore(claim_type=claim_type, slots={"subject": subject})

        assertion_text = draw(st.text(min_size=1, max_size=20, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"),
        )))
        year = draw(st.integers(min_value=2000, max_value=2030))
        end_year = draw(st.one_of(st.none(), st.integers(min_value=year + 1, max_value=2040)))
        tx_id = draw(st.integers(min_value=1, max_value=1000))
        confidence = draw(st.integers(min_value=0, max_value=10000))
        status = draw(st.sampled_from(["asserted", "retracted"]))

        valid_time = ValidTime(
            start=dt(year),
            end=dt(end_year) if end_year is not None else None,
        )
        transaction_time = TransactionTime(tx_id=tx_id, recorded_at=dt(2024))
        provenance = Provenance(source=f"src_{i}")

        store.assert_revision(
            core=core,
            assertion=assertion_text,
            valid_time=valid_time,
            transaction_time=transaction_time,
            provenance=provenance,
            confidence_bp=confidence,
            status=status,
        )

    return store


@given(a=small_stores(), b=small_stores())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_merge_commutativity(a: KnowledgeStore, b: KnowledgeStore) -> None:
    """merge(A, B).merged must equal merge(B, A).merged by canonical payload."""
    result_ab = a.merge(b)
    result_ba = b.merge(a)

    fp_ab = _store_fingerprint(result_ab.merged)
    fp_ba = _store_fingerprint(result_ba.merged)

    assert fp_ab == fp_ba, "Merge is not commutative"


@given(a=small_stores(), b=small_stores(), c=small_stores())
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
def test_merge_associativity(
    a: KnowledgeStore, b: KnowledgeStore, c: KnowledgeStore
) -> None:
    """merge(merge(A,B), C) must equal merge(A, merge(B,C)) by canonical payload."""
    ab = a.merge(b).merged
    ab_c = ab.merge(c).merged

    bc = b.merge(c).merged
    a_bc = a.merge(bc).merged

    fp_ab_c = _store_fingerprint(ab_c)
    fp_a_bc = _store_fingerprint(a_bc)

    assert fp_ab_c == fp_a_bc, "Merge is not associative"


@given(a=small_stores(min_claims=1))
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_merge_idempotency(a: KnowledgeStore) -> None:
    """merge(A, A).merged must equal A by canonical payload."""
    result = a.merge(a)
    merged = result.merged

    fp_original = _store_fingerprint(a)
    fp_merged = _store_fingerprint(merged)

    assert fp_original == fp_merged, "Merge is not idempotent"


@given(a=small_stores())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_merge_with_empty_is_identity(a: KnowledgeStore) -> None:
    """merge(A, empty) must equal A by canonical payload."""
    empty = KnowledgeStore()
    result = a.merge(empty)

    fp_original = _store_fingerprint(a)
    fp_merged = _store_fingerprint(result.merged)

    assert fp_original == fp_merged, "Merge with empty is not identity"


@given(a=small_stores(), b=small_stores())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_merge_produces_superset_of_both_inputs(
    a: KnowledgeStore, b: KnowledgeStore
) -> None:
    """Merged store must contain all cores and revisions from both inputs."""
    result = a.merge(b)
    merged = result.merged

    for core_id in a.cores:
        assert core_id in merged.cores
    for core_id in b.cores:
        assert core_id in merged.cores
    for rev_id in a.revisions:
        assert rev_id in merged.revisions
    for rev_id in b.revisions:
        assert rev_id in merged.revisions
