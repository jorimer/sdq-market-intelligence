"""Tests del generador de procedencia — la prosa que reemplaza a la escrita a mano.

Lo que se protege: que la frase que ve el cliente sea DERIVADA del estado real del
registro (y por tanto no pueda divergir de él), que el matiz nacional-vs-por-sujeto no se
pierda, y que ante la ausencia de señal el generador calle en vez de afirmar.
"""
from shared.registry.provenance import (
    coverage_sentence,
    limits_sentence,
    partial_coverage_sentence,
    provenance_paragraph,
    scope_sentence,
)
from shared.registry.signals import (
    GAP,
    NATIONAL,
    PER_SUBJECT,
    REAL,
    RUBRIC,
    AxisRegistry,
    VariableSignal,
)


def _sig(key, state=REAL, weight=0.2, scope=PER_SUBJECT, real_fraction=1.0,
         label=None, note=""):
    return VariableSignal(key=key, label=label or key, state=state, weight=weight,
                          scope=scope, real_fraction=real_fraction, note=note)


def _axis(*signals):
    return AxisRegistry(sector_key="sector_intel", display_name="IAI", source="varios",
                        implemented=True, signals=tuple(signals))


# ─── La propiedad central: la frase sigue al estado ───────────────────


def test_the_sentence_follows_the_state_not_the_prose():
    """El mismo eje, con la variable subida a real, cambia la frase SOLO."""
    before = _axis(_sig("a", REAL, 0.5), _sig("b", RUBRIC, 0.5, label="facilidad"))
    after = _axis(_sig("a", REAL, 0.5), _sig("b", REAL, 0.5, label="facilidad"))
    assert "facilidad" in limits_sentence(before)
    assert limits_sentence(after) == ""          # nada que declarar: nada se declara
    assert coverage_sentence(before) != coverage_sentence(after)


def test_coverage_is_weight_based():
    axis = _axis(_sig("a", REAL, 0.75), _sig("b", RUBRIC, 0.25))
    assert "75%" in coverage_sentence(axis)


def test_no_signals_means_silence_not_claims():
    """Sin señal por-variable no se afirma nada — silencio honesto."""
    empty = AxisRegistry(sector_key="x", display_name="", source="", implemented=True)
    assert provenance_paragraph(empty) == ""
    assert provenance_paragraph(None) == ""


def test_degraded_axis_speaks_only_at_aggregate_level():
    axis = AxisRegistry(sector_key="x", display_name="", source="", implemented=True,
                        degraded=True, signals=(_sig("_axis", REAL, 1.0),))
    text = provenance_paragraph(axis)
    assert text == coverage_sentence(axis)       # nada por-variable


# ─── El matiz nacional (la corrección que motivó el campo) ────────────


def test_national_scope_is_declared_not_hidden():
    """Dato real de alcance país: se dice que no explica diferencias entre casos."""
    axis = _axis(
        _sig("skills", REAL, 0.2, NATIONAL, label="nivel de competencias"),
        _sig("growth", REAL, 0.8, label="crecimiento del sector"),
    )
    text = scope_sentence(axis)
    assert "nivel de competencias" in text
    assert "nivel del índice" in text
    assert "crecimiento del sector" in text      # y nombra lo que SÍ diferencia


def test_no_national_variables_no_scope_sentence():
    axis = _axis(_sig("a", REAL), _sig("b", REAL))
    assert scope_sentence(axis) == ""


def test_rubric_national_does_not_enter_scope_sentence():
    """El alcance solo se declara sobre lo REAL — lo de rúbrica ya lo declara limits."""
    axis = _axis(_sig("a", RUBRIC, scope=NATIONAL), _sig("b", REAL))
    assert scope_sentence(axis) == ""


# ─── Límites y parcialidad ────────────────────────────────────────────


def test_rubric_and_gap_are_both_declared():
    axis = _axis(
        _sig("a", RUBRIC, label="facilidad de operar"),
        _sig("b", GAP, label="intensidad de carbono"),
        _sig("c", REAL),
    )
    text = limits_sentence(axis)
    assert "facilidad de operar" in text and "supuesto neutral" in text
    assert "intensidad de carbono" in text and "brecha" in text


def test_partial_coverage_names_the_fraction():
    axis = _axis(_sig("prof", REAL, real_fraction=0.47, label="rentabilidad"))
    text = partial_coverage_sentence(axis)
    assert "rentabilidad" in text and "47%" in text


def test_full_paragraph_composes_without_empty_fragments():
    axis = _axis(
        _sig("growth", REAL, 0.5, label="crecimiento"),
        _sig("skills", REAL, 0.3, NATIONAL, label="competencias"),
        _sig("ease", RUBRIC, 0.2, label="facilidad de operar"),
    )
    text = provenance_paragraph(axis)
    for fragment in ("del peso", "competencias", "facilidad de operar"):
        assert fragment in text
    assert "  " not in text                       # sin dobles espacios por huecos


# ─── El gate léxico no puede vetar al generador (viven en capas distintas) ──


def test_generated_prose_uses_the_vocabulary_the_gate_forbids_in_curated_prose():
    """Sanidad del diseño: "dato real"/"supuesto" SON el vocabulario del generador —
    el gate los prohíbe solo en la prosa curada, donde serían afirmación estática."""
    axis = _axis(_sig("a", REAL, 0.6), _sig("b", RUBRIC, 0.4))
    text = provenance_paragraph(axis)
    assert "dato real" in text


def test_el_titular_de_procedencia_habla_en_los_terminos_del_eje():
    """«El X% del peso de este índice se sostiene en dato real» es falso en el eje de
    evaluación de leyes: ese eje no arma un índice, mide cuántas metas de una ley tienen
    dato. La frase sale en la Metodología del informe y en el payload de calidad de la API
    paga, así que describía mal el producto que el cliente compra."""
    from shared.registry.provenance import coverage_sentence
    from shared.registry.signals import (COVERAGE_INDEX, COVERAGE_INSTRUMENT, REAL,
                                         AxisRegistry, VariableSignal)

    sig = (VariableSignal(key="v", label="v", state=REAL, dimension="d", weight=1.0,
                          source="s", cadence="annual", value=None, real_fraction=1.0),)

    def _eje(kind):
        return AxisRegistry(sector_key="x", display_name="x", source="s", implemented=True,
                            signals=sig, coverage_kind=kind)

    indice = coverage_sentence(_eje(COVERAGE_INDEX))
    instrumento = coverage_sentence(_eje(COVERAGE_INSTRUMENT))
    assert "peso de este índice" in indice
    assert "peso de este índice" not in instrumento
    assert "el propio instrumento se fijó" in instrumento
    # Y avisa que no se compara con la de un índice: sin eso, un cliente pone las dos
    # cifras en la misma tabla.
    assert "no es comparable" in instrumento
