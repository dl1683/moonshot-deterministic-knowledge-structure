"""Comprehensive tests for SearchEngine via Pipeline interface.

SearchEngine (~2,943 lines, 25+ public methods) has zero direct coverage.
Tests exercise specific SearchEngine behaviors through Pipeline.
"""
import pytest
from datetime import datetime, timezone
from dks import Pipeline, KnowledgeStore, TfidfSearchIndex


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_pipeline(texts=None, sources=None, build_graph=True):
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    pipe = Pipeline(store=store, search_index=index)
    if texts:
        for i, text in enumerate(texts):
            src = sources[i] if sources and i < len(sources) else f"doc{i}.pdf"
            pipe.ingest_text(text, source=src)
        index.rebuild()
        if build_graph:
            pipe.build_graph()
    return pipe


SCI = [
    "Photosynthesis converts sunlight into chemical energy in chloroplasts. "
    "Plants absorb carbon dioxide and release oxygen during the light reactions. "
    "The Calvin cycle fixes carbon into glucose molecules.",
    "Mitochondria generate ATP through oxidative phosphorylation. "
    "The electron transport chain creates a proton gradient across the inner membrane. "
    "Cellular respiration consumes oxygen and produces carbon dioxide.",
    "DNA replication occurs during the S phase of the cell cycle. "
    "Helicase unwinds the double helix and primase synthesizes RNA primers. "
    "DNA polymerase adds nucleotides to the growing strand with high fidelity.",
]
SCI_SRC = ["bio_photo.pdf", "bio_resp.pdf", "bio_dna.pdf"]

HIST = [
    "The French Revolution began in 1789 with the storming of the Bastille. "
    "Feudal privileges were abolished and the Declaration of the Rights of Man adopted.",
    "The Industrial Revolution transformed manufacturing in Britain during the 1760s. "
    "Steam engines powered factories and railways, replacing manual labor.",
]
HIST_SRC = ["hist_french.pdf", "hist_indust.pdf"]


class TestBasicSearch:
    def test_query_returns_ordered_results(self):
        p = _make_pipeline(SCI, SCI_SRC)
        r = p.query("photosynthesis sunlight chloroplasts")
        assert len(r) > 0
        assert "photosynthesis" in r[0].text.lower()

    def test_scores_non_increasing(self):
        p = _make_pipeline(SCI, SCI_SRC)
        r = p.query("oxygen carbon dioxide")
        assert len(r) >= 2
        for i in range(len(r) - 1):
            assert r[i].score >= r[i + 1].score

    def test_valid_at_temporal_filter(self):
        p = _make_pipeline(SCI[:1], SCI_SRC[:1])
        assert isinstance(p.query("photosynthesis", valid_at=dt(2024, 6, 1)), list)

    def test_tx_id_filter(self):
        p = _make_pipeline(SCI[:1], SCI_SRC[:1])
        assert len(p.query("photosynthesis", tx_id=999)) > 0

    def test_query_exact(self):
        p = _make_pipeline(SCI[:1], SCI_SRC[:1])
        cid = p.query("photosynthesis")[0].core_id
        exact = p.query_exact(cid, valid_at=datetime.now(timezone.utc), tx_id=999)
        assert exact is not None and exact.core_id == cid

    def test_query_exact_missing(self):
        p = _make_pipeline(SCI[:1], SCI_SRC[:1])
        assert p.query_exact("bogus", valid_at=datetime.now(timezone.utc), tx_id=999) is None

    def test_query_multi_groups_by_source(self):
        p = _make_pipeline(SCI, SCI_SRC)
        g = p.query_multi("carbon dioxide oxygen")
        assert isinstance(g, dict) and len(g) >= 1

    def test_query_with_context(self):
        p = _make_pipeline(SCI, SCI_SRC)
        assert len(p.query_with_context("ATP phosphorylation")) > 0

    def test_expand_context(self):
        p = _make_pipeline(SCI, SCI_SRC)
        r = p.query("Calvin cycle")
        assert isinstance(p.expand_context(r[0], window=1), list)

    def test_empty_store(self):
        assert _make_pipeline().query("anything") == []

    def test_single_chunk(self):
        p = _make_pipeline(["The mitochondria is the powerhouse of the cell."])
        assert len(p.query("powerhouse cell")) == 1


class TestEntityLinking:
    def test_link_entities_dict(self):
        links = _make_pipeline(SCI, SCI_SRC).link_entities()
        assert {"total_entities", "total_links", "top_entities"} <= links.keys()

    def test_shared_terms_found(self):
        assert _make_pipeline(SCI[:2], SCI_SRC[:2]).link_entities(min_shared_entities=1)["total_entities"] > 0

    def test_stricter_threshold(self):
        p = _make_pipeline(SCI, SCI_SRC)
        assert p.link_entities(min_shared_entities=5)["total_links"] <= p.link_entities(min_shared_entities=1)["total_links"]

    def test_requires_graph(self):
        p = _make_pipeline(SCI[:1], SCI_SRC[:1], build_graph=False)
        with pytest.raises(ValueError, match="Graph not built"):
            p.link_entities()


class TestReasoning:
    def test_reason_result_shape(self):
        r = _make_pipeline(SCI, SCI_SRC).reason("photosynthesis")
        assert r.question == "photosynthesis" and hasattr(r, "trace") and hasattr(r, "results")

    def test_zero_hops(self):
        r = _make_pipeline(SCI, SCI_SRC).reason("photosynthesis", hops=0)
        assert len(r.trace) == 1 and r.trace[0]["hop"] == 0

    def test_multi_hop_expands(self):
        p = _make_pipeline(SCI, SCI_SRC)
        assert len(p.reason("photosynthesis", hops=2).results) >= len(p.reason("photosynthesis", hops=0).results)

    def test_discover(self):
        assert isinstance(_make_pipeline(SCI, SCI_SRC).discover("electron transport"), list)

    def test_coverage(self):
        c = _make_pipeline(SCI, SCI_SRC).coverage("photosynthesis")
        assert c.topic == "photosynthesis" and hasattr(c, "subtopics")

    def test_evidence_chain(self):
        ch = _make_pipeline(SCI, SCI_SRC).evidence_chain("photosynthesis produces oxygen")
        assert ch.claim == "photosynthesis produces oxygen" and ch.total_evidence >= 1

    def test_query_deep(self):
        p = _make_pipeline(SCI + HIST, SCI_SRC + HIST_SRC)
        d = p.query_deep("How do photosynthesis and respiration relate?")
        assert len(d.subqueries) >= 1

    def test_synthesize(self):
        s = _make_pipeline(SCI, SCI_SRC).synthesize("energy production in cells")
        assert isinstance(s.themes, list) and hasattr(s, "source_summaries")

    def test_ask(self):
        a = _make_pipeline(SCI, SCI_SRC).ask("What is photosynthesis?")
        assert hasattr(a, "results") and hasattr(a, "question")


class TestAnswerExtraction:
    def test_extract_answer(self):
        ea = _make_pipeline(SCI, SCI_SRC).extract_answer("What does photosynthesis convert?")
        assert "answer_sentences" in ea and len(ea["answer_sentences"]) >= 1

    def test_extract_with_precomputed(self):
        p = _make_pipeline(SCI, SCI_SRC)
        ea = p.extract_answer("What does photosynthesis convert?", results=p.query("photosynthesis"))
        assert len(ea["answer_sentences"]) >= 1

    def test_answer_strategy(self):
        a = _make_pipeline(SCI, SCI_SRC).answer("Where does the Calvin cycle fix carbon?")
        assert "strategy" in a and "answer_sentences" in a

    def test_confidence(self):
        c = _make_pipeline(SCI, SCI_SRC).confidence("Photosynthesis converts sunlight into chemical energy")
        assert 0 <= c["confidence_bp"] <= 10000 and "assessment" in c


class TestQueryIntelligence:
    def test_classify_factual(self):
        assert _make_pipeline(SCI[:1], SCI_SRC[:1])._classify_query("What is photosynthesis?") == "factual"

    def test_classify_comparison(self):
        assert _make_pipeline(SCI[:1], SCI_SRC[:1])._classify_query("Compare photosynthesis and respiration") == "comparison"

    def test_decompose_conjunction(self):
        parts = _make_pipeline(SCI[:1], SCI_SRC[:1])._decompose_question(
            "What is photosynthesis and how does cellular respiration work?")
        assert len(parts) >= 2

    def test_decompose_comparison(self):
        parts = _make_pipeline(SCI[:1], SCI_SRC[:1])._decompose_question("Compare cats and dogs")
        assert any("vs" in p for p in parts)

    def test_decompose_max_parts(self):
        assert len(_make_pipeline(SCI[:1], SCI_SRC[:1])._decompose_question("What is A and B and C?", max_parts=2)) <= 2


class TestAnalysis:
    def test_contradictions(self):
        texts = ["Photosynthesis releases oxygen.", "Photosynthesis does not release oxygen."]
        c = _make_pipeline(texts, ["a.pdf", "b.pdf"]).contradictions("photosynthesis oxygen")
        assert isinstance(c, list)
        for item in c:
            assert "confidence_bp" in item

    def test_deduplicate(self):
        texts = [
            "Photosynthesis converts sunlight into chemical energy in chloroplasts.",
            "Photosynthesis converts sunlight to chemical energy within chloroplasts.",
            "DNA replication occurs during S phase of the cell cycle.",
        ]
        assert isinstance(_make_pipeline(texts).deduplicate(), list)

    def test_timeline(self):
        tl = _make_pipeline(HIST, HIST_SRC).timeline("revolution")
        assert isinstance(tl, list)
        if tl:
            assert "text" in tl[0] and "tx_id" in tl[0]

    def test_timeline_diff(self):
        d = _make_pipeline(HIST, HIST_SRC).timeline_diff("revolution", tx_id_a=0, tx_id_b=999)
        assert {"only_in_a", "only_in_b", "summary"} <= d.keys()


class TestProvenanceCitation:
    def test_provenance_of(self):
        p = _make_pipeline(SCI[:1], SCI_SRC[:1])
        prov = p.provenance_of(p.query("photosynthesis")[0])
        assert prov["source"] == "bio_photo.pdf" and "core_id" in prov

    def test_cite(self):
        p = _make_pipeline(SCI[:1], SCI_SRC[:1])
        assert "bio_photo" in p.cite(p.query("photosynthesis")[0])

    def test_cite_results(self):
        p = _make_pipeline(SCI, SCI_SRC)
        r = p.query("carbon dioxide")
        assert len(p.cite_results(r)) == len(r)

    def test_query_by_source(self):
        assert len(_make_pipeline(SCI, SCI_SRC).query_by_source("bio_photo.pdf")) >= 1

    def test_explain(self):
        p = _make_pipeline(SCI, SCI_SRC)
        r = p.query("photosynthesis sunlight")
        ex = p.explain("photosynthesis sunlight", result=r[0])
        assert "matching_terms" in ex and "photosynthesis" in ex["matching_terms"]


class TestCrossDocument:
    def test_multi_source_finds_history(self):
        p = _make_pipeline(SCI + HIST, SCI_SRC + HIST_SRC)
        assert any("hist" in s for s in p.query_multi("revolution").keys())

    def test_evidence_chain_multi(self):
        ch = _make_pipeline(SCI[:2], SCI_SRC[:2]).evidence_chain("oxygen and carbon dioxide")
        assert len(ch.sources) >= 1


class TestEdgeCases:
    def test_nonexistent_term(self):
        assert isinstance(_make_pipeline(SCI, SCI_SRC).query("xylophone basketball"), list)

    def test_reason_empty_store(self):
        p = _make_pipeline()
        p.build_graph()
        assert len(p.reason("anything", hops=1).results) == 0

    def test_single_source_link_entities(self):
        assert isinstance(_make_pipeline(SCI[:1], SCI_SRC[:1]).link_entities(), dict)

    def test_timeline_no_matches(self):
        assert _make_pipeline(SCI[:1], SCI_SRC[:1]).timeline("xylophone") == []

    def test_confidence_unsupported(self):
        c = _make_pipeline(SCI[:1], SCI_SRC[:1]).confidence("The moon is made of cheese")
        assert isinstance(c, dict) and c["evidence_count"] >= 0
