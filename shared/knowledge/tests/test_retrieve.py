"""Tests del retrieval léxico: tokenización, BM25, corpus y la regla de brecha (§4)."""
from shared.knowledge import retrieve
from shared.knowledge.corpus import load_corpus_passages
from shared.knowledge.index import LexicalIndex, tokenize
from shared.knowledge.models import KIND_METHODOLOGY, Passage


# ─── tokenización ──────────────────────────────────────────────────────
def test_tokenize_strips_accents_and_stopwords():
    toks = tokenize("La Rúbrica declarada NO es un dato real")
    assert "rubrica" in toks       # sin acento
    assert "declarada" in toks
    assert "dato" in toks and "real" in toks
    assert "la" not in toks and "no" not in toks and "es" not in toks  # stopwords


def test_tokenize_drops_short_tokens():
    assert tokenize("a b cd efg") == ["cd", "efg"]


# ─── índice BM25 sobre pasajes sintéticos ─────────────────────────────
def _idx():
    return LexicalIndex([
        Passage(text="El IRMP mide el riesgo regulatorio y la volatilidad electoral.",
                source="Doc A", kind=KIND_METHODOLOGY),
        Passage(text="El IAI mide el atractivo de inversión sectorial con dato del BCRD.",
                source="Doc B", kind=KIND_METHODOLOGY),
        Passage(text="La resiliencia energética combina capacidad y transición renovable.",
                source="Doc C", kind=KIND_METHODOLOGY),
    ])


def test_search_ranks_relevant_first():
    hits = _idx().search("riesgo regulatorio electoral", top_k=2)
    assert hits
    assert hits[0][0].source == "Doc A"


def test_search_gibberish_returns_empty_gap_not_fill():
    # §4: sin evidencia → vacío (brecha), nunca un relleno de un doc irrelevante.
    assert _idx().search("zzzqqq xkcdplover", top_k=3) == []


def test_index_skips_passages_without_source():
    idx = LexicalIndex([
        Passage(text="pasaje sin lineage", source="", kind=KIND_METHODOLOGY),
        Passage(text="pasaje con lineage regulatorio", source="Doc X", kind=KIND_METHODOLOGY),
    ])
    assert len(idx) == 1  # el sin-source no entra al índice


# ─── corpus real ──────────────────────────────────────────────────────
def test_corpus_loads_and_every_passage_has_lineage():
    passages = load_corpus_passages()
    assert len(passages) > 20
    assert all(p.source for p in passages)      # regla §4 desde el corpus
    assert all(p.text.strip() for p in passages)


# ─── contrato de retrieve() ───────────────────────────────────────────
def test_retrieve_returns_contract_keys():
    # Consulta a la doctrina citable del corpus (rationale de macro_sector · inflación).
    # Antes apuntaba a docs/REPORT_STANDARD.md, retirado del manifest en Hallazgo 7.
    results = retrieve("inflación erosiona el poder de compra consumo comercio", top_k=3)
    assert results
    for r in results:
        assert {"text", "source", "score"} <= set(r)   # contrato preservado
        assert r["source"]
        assert r["score"] > 0


def test_retrieve_empty_query_is_empty():
    assert retrieve("   ", top_k=5) == []


def test_retrieve_no_match_is_gap():
    # Consulta de tópico ausente del corpus propio → brecha honesta, no relleno.
    assert retrieve("recetas de cocina tailandesa con curry", top_k=5) == []
