"""Regression tests for retraction splash bug (P4).

A retraction of [2010,2020) must NOT suppress an asserted revision [2015,2025)
in the overlap zone. Retractions only affect revisions with the exact same
valid_time interval (per FM-009 / INV-T5).
"""
from datetime import datetime, timezone

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_retraction_does_not_splash_to_overlapping_interval() -> None:
    """Core regression: retraction of [2010,2020) must not suppress asserted [2015,2025)."""
    store = KnowledgeStore()
    core = ClaimCore(claim_type="residence", slots={"subject": "Alice"})

    # Assert claim for [2015, 2025) at tx=3
    asserted_rev = store.assert_revision(
        core=core,
        assertion="Alice lives in London",
        valid_time=ValidTime(start=dt(2015, 1, 1), end=dt(2025, 1, 1)),
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 3, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )

    # Retract claim for [2010, 2020) at tx=4 (higher tx, overlapping interval)
    store.assert_revision(
        core=core,
        assertion="Alice residence retracted",
        valid_time=ValidTime(start=dt(2010, 1, 1), end=dt(2020, 1, 1)),
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 4, 1)),
        provenance=Provenance(source="src_retract"),
        confidence_bp=8000,
        status="retracted",
    )

    # Query at valid_at=2017 (in overlap zone) — should return the asserted revision
    winner = store.query_as_of(core.core_id, valid_at=dt(2017, 6, 1), tx_id=4)
    assert winner is not None, (
        "Retraction splash: retraction of [2010,2020) incorrectly suppressed "
        "asserted revision [2015,2025) in the overlap zone"
    )
    assert winner.revision_id == asserted_rev.revision_id


def test_retraction_still_works_for_exact_interval() -> None:
    """Retraction with the exact same interval SHOULD suppress the claim."""
    store = KnowledgeStore()
    core = ClaimCore(claim_type="residence", slots={"subject": "Bob"})

    # Assert claim for [2010, 2020) at tx=1
    store.assert_revision(
        core=core,
        assertion="Bob lives in Paris",
        valid_time=ValidTime(start=dt(2010, 1, 1), end=dt(2020, 1, 1)),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )

    # Retract same interval at tx=2
    store.assert_revision(
        core=core,
        assertion="Bob residence retracted",
        valid_time=ValidTime(start=dt(2010, 1, 1), end=dt(2020, 1, 1)),
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 2, 1)),
        provenance=Provenance(source="src_retract"),
        confidence_bp=8000,
        status="retracted",
    )

    # Query — should return None (retracted for exact interval)
    winner = store.query_as_of(core.core_id, valid_at=dt(2015, 1, 1), tx_id=2)
    assert winner is None, "Retraction of exact interval should suppress the claim"


def test_retraction_does_not_affect_non_overlapping_interval() -> None:
    """Retraction of [2010,2020) must not affect asserted [2025,2030)."""
    store = KnowledgeStore()
    core = ClaimCore(claim_type="residence", slots={"subject": "Carol"})

    # Assert for [2025, 2030) at tx=1
    asserted_rev = store.assert_revision(
        core=core,
        assertion="Carol lives in Tokyo",
        valid_time=ValidTime(start=dt(2025, 1, 1), end=dt(2030, 1, 1)),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )

    # Retract [2010, 2020) at tx=2
    store.assert_revision(
        core=core,
        assertion="Carol retracted",
        valid_time=ValidTime(start=dt(2010, 1, 1), end=dt(2020, 1, 1)),
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 2, 1)),
        provenance=Provenance(source="src_retract"),
        confidence_bp=8000,
        status="retracted",
    )

    # Query at valid_at=2027 — should return the asserted revision
    winner = store.query_as_of(core.core_id, valid_at=dt(2027, 1, 1), tx_id=2)
    assert winner is not None
    assert winner.revision_id == asserted_rev.revision_id


def test_multiple_intervals_retraction_prefers_asserted() -> None:
    """With multiple overlapping intervals, asserted from any interval wins."""
    store = KnowledgeStore()
    core = ClaimCore(claim_type="role", slots={"subject": "Dave"})

    # Assert [2010, 2025) at tx=1
    rev_wide = store.assert_revision(
        core=core,
        assertion="Dave is CEO",
        valid_time=ValidTime(start=dt(2010, 1, 1), end=dt(2025, 1, 1)),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )

    # Retract [2015, 2020) at tx=2
    store.assert_revision(
        core=core,
        assertion="Dave role retracted for sub-period",
        valid_time=ValidTime(start=dt(2015, 1, 1), end=dt(2020, 1, 1)),
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 2, 1)),
        provenance=Provenance(source="src_retract"),
        confidence_bp=8000,
        status="retracted",
    )

    # Assert [2018, 2022) at tx=3
    rev_narrow = store.assert_revision(
        core=core,
        assertion="Dave is CEO confirmed",
        valid_time=ValidTime(start=dt(2018, 1, 1), end=dt(2022, 1, 1)),
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 3, 1)),
        provenance=Provenance(source="src_b"),
        confidence_bp=9000,
        status="asserted",
    )

    # Query at valid_at=2019 — should return an asserted revision (not retracted)
    winner = store.query_as_of(core.core_id, valid_at=dt(2019, 1, 1), tx_id=3)
    assert winner is not None
    assert winner.status == "asserted"
