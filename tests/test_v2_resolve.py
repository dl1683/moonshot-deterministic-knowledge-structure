"""Tests for dks.resolve — entity resolution."""
from dks import (
    CascadingResolver,
    ClaimCore,
    ExactResolver,
    KnowledgeStore,
    NormalizedResolver,
    Provenance,
    ResolutionDecision,
    Resolver,
    TransactionTime,
    ValidTime,
)
from dks.resolve import ALIAS_CLAIM_TYPE
from datetime import datetime, timezone


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


class TestExactResolver:
    def test_protocol_compliance(self) -> None:
        resolver = ExactResolver()
        assert isinstance(resolver, Resolver)

    def test_exact_match(self) -> None:
        resolver = ExactResolver()
        resolver.register("Tim Cook", "entity:tim_cook")

        decision = resolver.resolve("Tim Cook")
        assert decision is not None
        assert decision.resolved_entity_id == "entity:tim_cook"
        assert decision.confidence_bp == 10000
        assert decision.method == "exact"

    def test_case_insensitive(self) -> None:
        resolver = ExactResolver()
        resolver.register("Tim Cook", "entity:tim_cook")

        decision = resolver.resolve("TIM COOK")
        assert decision is not None
        assert decision.resolved_entity_id == "entity:tim_cook"

    def test_no_match_returns_none(self) -> None:
        resolver = ExactResolver()
        resolver.register("Tim Cook", "entity:tim_cook")

        decision = resolver.resolve("Elon Musk")
        assert decision is None

    def test_candidate_filter(self) -> None:
        resolver = ExactResolver()
        resolver.register("Tim Cook", "entity:tim_cook")

        # Match exists but not in candidates
        decision = resolver.resolve("Tim Cook", candidates=["entity:other"])
        assert decision is None

        # Match is in candidates
        decision = resolver.resolve("Tim Cook", candidates=["entity:tim_cook"])
        assert decision is not None


class TestNormalizedResolver:
    def test_protocol_compliance(self) -> None:
        resolver = NormalizedResolver()
        assert isinstance(resolver, Resolver)

    def test_direct_match(self) -> None:
        resolver = NormalizedResolver()
        resolver.register("Albert Einstein", "entity:einstein")

        decision = resolver.resolve("Albert Einstein")
        assert decision is not None
        assert decision.resolved_entity_id == "entity:einstein"
        assert decision.confidence_bp == 9500

    def test_substring_match(self) -> None:
        resolver = NormalizedResolver()
        resolver.register("Albert Einstein", "entity:einstein")

        decision = resolver.resolve("Einstein")
        assert decision is not None
        assert decision.resolved_entity_id == "entity:einstein"
        assert decision.confidence_bp == 7000
        assert decision.method == "normalized"


class TestCascadingResolver:
    def test_protocol_compliance(self) -> None:
        resolver = CascadingResolver()
        assert isinstance(resolver, Resolver)

    def test_first_match_wins(self) -> None:
        exact = ExactResolver()
        exact.register("Alice", "entity:alice_exact")

        normalized = NormalizedResolver()
        normalized.register("Alice Smith", "entity:alice_normalized")

        cascade = CascadingResolver([exact, normalized])
        decision = cascade.resolve("Alice")
        assert decision is not None
        assert decision.resolved_entity_id == "entity:alice_exact"
        assert decision.method == "exact"

    def test_fallthrough_to_second(self) -> None:
        exact = ExactResolver()
        # No "Einstein" registered in exact

        normalized = NormalizedResolver()
        normalized.register("Albert Einstein", "entity:einstein")

        cascade = CascadingResolver([exact, normalized])
        decision = cascade.resolve("Einstein")
        assert decision is not None
        assert decision.resolved_entity_id == "entity:einstein"
        assert decision.method == "normalized"

    def test_no_match_returns_none(self) -> None:
        exact = ExactResolver()
        normalized = NormalizedResolver()

        cascade = CascadingResolver([exact, normalized])
        decision = cascade.resolve("Unknown Person")
        assert decision is None

    def test_add_resolver(self) -> None:
        cascade = CascadingResolver()
        assert cascade.resolve("anything") is None

        exact = ExactResolver()
        exact.register("test", "entity:test")
        cascade.add_resolver(exact)

        decision = cascade.resolve("test")
        assert decision is not None


class TestResolutionDecisionAsClaim:
    def test_decision_to_alias_claim(self) -> None:
        decision = ResolutionDecision(
            surface_form="Tim Cook",
            resolved_entity_id="entity:tim_cook",
            confidence_bp=10000,
            method="exact",
        )
        claim = decision.as_alias_claim()

        assert claim.claim_type == ALIAS_CLAIM_TYPE
        assert claim.slots["entity"] == "entity:tim_cook"
        assert claim.slots["method"] == "exact"

    def test_alias_claim_committed_to_store(self) -> None:
        """Resolution decisions stored as claims are auditable and queryable."""
        decision = ResolutionDecision(
            surface_form="Einstein",
            resolved_entity_id="entity:einstein",
            confidence_bp=9500,
            method="normalized",
        )
        claim = decision.as_alias_claim()

        store = KnowledgeStore()
        rev = store.assert_revision(
            core=claim,
            assertion="Resolved 'Einstein' to entity:einstein",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="resolver:normalized"),
            confidence_bp=decision.confidence_bp,
            status="asserted",
        )

        # Query the resolution decision
        winner = store.query_as_of(claim.core_id, valid_at=dt(2024, 6, 1), tx_id=1)
        assert winner is not None
        assert winner.revision_id == rev.revision_id

    def test_alias_claim_retractable(self) -> None:
        """Wrong resolution decisions can be retracted."""
        decision = ResolutionDecision(
            surface_form="Cook",
            resolved_entity_id="entity:wrong_cook",
            confidence_bp=7000,
            method="normalized",
        )
        claim = decision.as_alias_claim()

        store = KnowledgeStore()
        store.assert_revision(
            core=claim,
            assertion="Resolved 'Cook' to wrong_cook",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
            provenance=Provenance(source="resolver"),
            confidence_bp=7000,
            status="asserted",
        )

        # Retract the wrong resolution
        store.assert_revision(
            core=claim,
            assertion="Retracted wrong resolution",
            valid_time=ValidTime(start=dt(2024), end=None),
            transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 2, 1)),
            provenance=Provenance(source="manual_review"),
            confidence_bp=10000,
            status="retracted",
        )

        winner = store.query_as_of(claim.core_id, valid_at=dt(2024, 6, 1), tx_id=2)
        assert winner is None  # Retracted
