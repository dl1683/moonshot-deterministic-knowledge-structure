"""Tests for dks.extract — claim extraction from unstructured text."""
from dks import (
    ClaimCore,
    ExtractionResult,
    Extractor,
    KnowledgeStore,
    LLMExtractor,
    Provenance,
    RegexExtractor,
    TransactionTime,
    ValidTime,
)
from datetime import datetime, timezone
import json


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


class TestRegexExtractor:
    def test_protocol_compliance(self) -> None:
        """RegexExtractor must satisfy the Extractor protocol."""
        extractor = RegexExtractor()
        assert isinstance(extractor, Extractor)

    def test_extract_date_pattern(self) -> None:
        """Extract dates from text using named groups."""
        extractor = RegexExtractor()
        extractor.register_pattern(
            "date_mention",
            r"(?P<entity>\w+) was born on (?P<date>\d{4}-\d{2}-\d{2})",
            ["entity", "date"],
        )

        result = extractor.extract("Alice was born on 1990-03-15")
        assert len(result.claims) == 1
        assert result.claims[0].claim_type == "date_mention"
        assert "entity" in result.claims[0].slots
        assert "date" in result.claims[0].slots

    def test_extract_multiple_matches(self) -> None:
        """Extract multiple claims from text with multiple matches."""
        extractor = RegexExtractor()
        extractor.register_pattern(
            "residence",
            r"(?P<subject>\w+) lives in (?P<city>\w+)",
            ["subject", "city"],
        )

        text = "Alice lives in London. Bob lives in Paris."
        result = extractor.extract(text)
        assert len(result.claims) == 2

    def test_extract_with_type_filter(self) -> None:
        """Type filter should restrict which patterns are applied."""
        extractor = RegexExtractor()
        extractor.register_pattern("residence", r"(?P<s>\w+) lives in (?P<c>\w+)", ["s", "c"])
        extractor.register_pattern("role", r"(?P<s>\w+) is a (?P<r>\w+)", ["s", "r"])

        result = extractor.extract(
            "Alice lives in London. Alice is a CEO.",
            claim_types=["role"],
        )
        assert len(result.claims) == 1
        assert result.claims[0].claim_type == "role"

    def test_empty_text_returns_empty(self) -> None:
        extractor = RegexExtractor()
        extractor.register_pattern("fact", r"(?P<s>\w+)", ["s"])
        result = extractor.extract("")
        assert len(result.claims) == 0

    def test_extraction_result_preserves_raw_text(self) -> None:
        extractor = RegexExtractor()
        result = extractor.extract("Hello world")
        assert result.raw_text == "Hello world"

    def test_provenance_tracks_source(self) -> None:
        extractor = RegexExtractor()
        extractor.register_pattern("fact", r"(?P<subject>\w+) exists", ["subject"])
        result = extractor.extract("Alpha exists")
        assert len(result.provenance) == 1
        assert result.provenance[0].source.startswith("regex:")


class TestLLMExtractor:
    def test_protocol_compliance(self) -> None:
        """LLMExtractor must satisfy the Extractor protocol."""
        extractor = LLMExtractor(llm_fn=lambda x: "[]")
        assert isinstance(extractor, Extractor)

    def test_extract_with_mock_llm(self) -> None:
        """Extract claims using a mock LLM response."""
        mock_response = json.dumps([
            {"claim_type": "residence", "slots": {"subject": "Alice", "city": "London"}},
            {"claim_type": "role", "slots": {"subject": "Bob", "title": "CEO"}},
        ])

        extractor = LLMExtractor(
            llm_fn=lambda x: mock_response,
            model_id="test-model",
        )
        result = extractor.extract("Alice lives in London. Bob is CEO.")
        assert len(result.claims) == 2
        assert result.claims[0].claim_type == "residence"
        assert result.claims[1].claim_type == "role"

    def test_malformed_llm_response(self) -> None:
        """Malformed LLM output should not crash — returns empty result with error."""
        extractor = LLMExtractor(llm_fn=lambda x: "not json at all")
        result = extractor.extract("Some text")
        assert len(result.claims) == 0
        assert "error" in result.metadata

    def test_provenance_tracks_model(self) -> None:
        mock_response = json.dumps([{"claim_type": "fact", "slots": {"s": "v"}}])
        extractor = LLMExtractor(llm_fn=lambda x: mock_response, model_id="qwen3-0.6b")
        result = extractor.extract("text")
        assert "qwen3-0.6b" in result.provenance[0].source


class TestCommitmentBoundary:
    def test_extraction_to_commitment(self) -> None:
        """Claims from extraction become deterministic after commitment."""
        extractor = RegexExtractor()
        extractor.register_pattern("fact", r"(?P<subject>\w+) is (?P<value>\w+)", ["subject", "value"])

        result = extractor.extract("Alpha is important")
        assert len(result.claims) >= 1

        # Commit to store — this crosses the commitment boundary
        store = KnowledgeStore()
        for claim in result.claims:
            store.assert_revision(
                core=claim,
                assertion="Alpha is important",
                valid_time=ValidTime(start=dt(2024), end=None),
                transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024)),
                provenance=Provenance(source="test"),
                confidence_bp=8000,
                status="asserted",
            )

        # After commitment, the data is deterministic
        assert len(store.cores) >= 1
        assert len(store.revisions) >= 1

    def test_same_text_same_claims_after_commit(self) -> None:
        """Same extraction → same core_ids (deterministic after canonicalization)."""
        extractor = RegexExtractor()
        extractor.register_pattern("fact", r"(?P<subject>\w+) exists", ["subject"])

        result1 = extractor.extract("Alpha exists")
        result2 = extractor.extract("Alpha exists")

        assert result1.claims[0].core_id == result2.claims[0].core_id
