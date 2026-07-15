"""Regresión del Hallazgo 4 del piloto P4-P6 (A.5 de la spec del gate de honestidad): una
pregunta compuesta con coma+"y" ("…crecimiento, y cuáles son sus motores…") se quedaba como UNA
sola sub-pregunta; _aggregate_state tomaba el mejor estado (real) y anclaba la cláusula ENTERA,
produciendo headers "100% dato real" junto a brechas en el cuerpo.

Heurística CONSERVADORA: se parte en coma+"y"/"e" SOLO si la parte posterior encabeza con un
interrogativo (segunda pregunta), nunca en una enumeración ("A, B y C" / coma de Oxford
"A, B, y C" → tras ", y" viene un sustantivo). Ante interrogativo ambiguo sin acento, no parte."""
from shared.research.decompose import _split_compound_and, split_question


# ─── DEBE partir: dos asks distintos (coma+"y" + interrogativo que encabeza) ──
DEBE_PARTIR = [
    "cuál es la perspectiva de crecimiento económico de RD para 2026, y cuáles son sus "
    "principales motores sectoriales",
    "cómo está la solidez del banco, y qué riesgo de liquidez enfrenta",
    "cuál es la inflación proyectada, y cómo se compara con la región",
    "qué tan expuesto está el turismo, y cuánto aporta al PIB",
]


def test_compound_questions_are_split():
    for q in DEBE_PARTIR:
        parts = split_question(q)
        assert len(parts) >= 2, f"no partió (debía): {q!r} → {parts}"


def test_split_keeps_both_asks_intact():
    parts = split_question(DEBE_PARTIR[0])
    assert any("crecimiento" in p.lower() for p in parts)
    assert any("motores sectoriales" in p.lower() for p in parts)


# ─── NO debe partir: enumeración legítima dentro de una sola cláusula ──
NO_DEBE_PARTIR = [
    "el desempeño de turismo, minería y construcción",
    "primas, siniestralidad y solvencia de las aseguradoras",
    "exportaciones, importaciones y balanza comercial",
    "rentabilidad, cotizantes y fondos de las AFP",
]


def test_enumerations_are_not_split():
    for q in NO_DEBE_PARTIR:
        parts = split_question(q)
        assert len(parts) == 1, f"partió una enumeración (no debía): {q!r} → {parts}"


def test_oxford_comma_enumeration_not_split():
    # coma de Oxford: tras ", y" viene un sustantivo, no un interrogativo → no parte.
    for q in ("turismo, minería, y construcción como sectores clave",
              "exportaciones, importaciones, y balanza del comercio exterior"):
        parts = _split_compound_and(q)
        assert parts == [q], f"partió Oxford (no debía): {q!r} → {parts}"


# ─── salvaguarda por acento: 'qué' parte, 'que' relativo no ──
def test_accent_distinguishes_question_from_relative():
    # 'y qué' (acentuado, interrogativo) → parte.
    assert len(_split_compound_and("cuál es la solidez del banco, y qué mora tiene")) == 2
    # 'y que' (sin acento, relativo) → NO parte (conservador ante la ambigüedad).
    assert _split_compound_and("el sector bancario, y que sigue creciendo este año") == \
        ["el sector bancario, y que sigue creciendo este año"]


def test_mixed_enumeration_then_question():
    # enumeración seguida de una segunda pregunta real: solo corta en el interrogativo.
    q = "el aporte de turismo, minería y construcción, y cuánto crece el PIB"
    parts = _split_compound_and(q)
    assert len(parts) == 2
    assert "turismo, minería y construcción" in parts[0]
    assert parts[1].startswith("cuánto")


# ─── el corte real cierra la brecha de honestidad (estado por cláusula) ──
def test_split_enables_per_clause_state(monkeypatch):
    # una cláusula con dato real y otra sin evidencia deben quedar SEPARADAS: sin el split la
    # cláusula entera anclaba 'real' (el bug); con él, la segunda queda como brecha.
    import shared.research.decompose as decompose_mod

    class _Hit(dict):
        pass

    def fake_retrieve(query, top_k=4, *, db=None, min_score=0.0, min_score_by_kind=None):
        if "crecimiento" in query.lower():
            return [{"text": "PIB real", "source": "BCRD", "kind": "registry", "score": 20.0,
                     "ref": "", "meta": {"sector_key": "macro", "state": "real"}}]
        return []   # la segunda cláusula (motores sectoriales) no tiene evidencia → brecha

    monkeypatch.setattr(decompose_mod, "retrieve", fake_retrieve)
    subs = decompose_mod.decompose(
        "cuál es el crecimiento del PIB, y cuáles son los motores sectoriales", db=None)
    assert len(subs) == 2
    states = {("real" if s.state == "real" else "gap") for s in subs}
    assert states == {"real", "gap"}   # una anclada, una brecha — ya no contamina la otra
