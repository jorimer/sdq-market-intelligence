"""Tests del núcleo del Data Registry: normalización, constructores y agregación."""
from shared.registry.builders import (
    axis_variable_weights,
    nested_breakdown_signals,
    pattern_a_signals,
    pattern_b_signals,
)
from shared.registry.signals import (
    GAP,
    REAL,
    RUBRIC,
    AxisRegistry,
    DataRegistry,
    VariableSignal,
    normalize_state,
)


# ─── normalize_state: los dos dialectos → tres estados canónicos ───────
def test_normalize_state_dialects():
    assert normalize_state("live") == REAL
    assert normalize_state("real") == REAL
    assert normalize_state("rubric") == RUBRIC
    assert normalize_state("rúbrica") == RUBRIC
    assert normalize_state("brecha") == GAP
    assert normalize_state("gap") == GAP


def test_normalize_state_unknown_is_gap_not_real():
    # Regla dura §4: desconocido/ausente NUNCA se asume real por omisión.
    assert normalize_state(None) == GAP
    assert normalize_state("") == GAP
    assert normalize_state("loquesea") == GAP


# ─── pesos desde doctrina ──────────────────────────────────────────────
def test_axis_variable_weights_from_doctrine():
    w = axis_variable_weights("sectoral")
    # macro: peso 0.25, 1 variable → 0.25
    assert w["macro_exposure"] == (("macro", 0.25))
    # regulation: peso 0.15, 2 variables → 0.075 c/u
    assert w["regulatory_quality"][0] == "regulation"
    assert abs(w["regulatory_quality"][1] - 0.075) < 1e-6


def test_axis_variable_weights_missing_axis():
    assert axis_variable_weights("no-existe-este-eje") == {}


# ─── Patrón A (panel) ──────────────────────────────────────────────────
def _panel():
    dataset = {
        "s1": {"sector_size": 12.0, "regulatory_quality": 48.0, "ease_of_business": 50.0},
        "s2": {"sector_size": 8.0, "regulatory_quality": 48.0},  # ease_of_business ausente
    }
    sources = {
        "s1": {"sector_size": "live", "regulatory_quality": "live", "ease_of_business": "rubric"},
        "s2": {"sector_size": "live", "regulatory_quality": "live"},  # ease_of_business ausente
    }
    return dataset, sources


def test_pattern_a_states_and_fractions():
    dataset, sources = _panel()
    sigs = {s.key: s for s in pattern_a_signals(
        axis="sectoral", dataset=dataset, sources=sources,
        source_label="BCRD", cadence="annual")}

    assert sigs["sector_size"].state == REAL
    assert sigs["sector_size"].real_fraction == 1.0
    assert sigs["sector_size"].source == "BCRD"

    # ease_of_business: rúbrica en s1, ausente en s2 → RUBRIC (hay rúbrica, no dato)
    assert sigs["ease_of_business"].state == RUBRIC
    assert sigs["ease_of_business"].real_fraction == 0.0
    assert sigs["ease_of_business"].source == ""  # rúbrica no cita fuente


def test_pattern_a_partial_real_is_declared():
    # dato real en 1/2 sujetos → REAL pero con la parcialidad declarada en la nota.
    dataset = {"s1": {"profitability": 12.0}, "s2": {}}
    sources = {"s1": {"profitability": "live"}, "s2": {}}
    sig = {s.key: s for s in pattern_a_signals(
        axis="sectoral", dataset=dataset, sources=sources,
        source_label="ENAE", cadence="annual")}["profitability"]
    assert sig.state == REAL
    assert sig.real_fraction == 0.5
    assert "parcial" in sig.note


def test_pattern_a_declares_gap_not_fills():
    # §4 round-trip: una variable con brecha conocida a propósito se DECLARA, no se rellena.
    dataset = {"s1": {}, "s2": {}}
    sources = {"s1": {"secret_var": "brecha"}, "s2": {}}
    sig = {s.key: s for s in pattern_a_signals(
        axis="sectoral", dataset=dataset, sources=sources,
        source_label="X", cadence="annual")}["secret_var"]
    assert sig.state == GAP
    assert sig.real_fraction == 0.0
    assert "brecha" in sig.note.lower()


# ─── Patrón B (índice sujeto único) ───────────────────────────────────
def test_pattern_b_from_breakdown_list():
    breakdown = [
        {"dimension": "acceso", "provenance": "real", "weight": 0.5, "value": 70.0},
        {"dimension": "calidad", "provenance": "brecha", "weight": 0.5},
    ]
    sigs = {s.dimension: s for s in pattern_b_signals(
        breakdown=breakdown, source_label="INDOTEL", cadence="quarterly")}
    assert sigs["acceso"].state == REAL
    assert sigs["acceso"].real_fraction == 1.0
    assert sigs["calidad"].state == GAP
    assert sigs["calidad"].real_fraction == 0.0


def test_pattern_b_present_flag_maps_to_state():
    breakdown = {"d1": {"present": True, "weight": 1.0}}
    sig = pattern_b_signals(breakdown=breakdown, source_label="S", cadence="annual")[0]
    assert sig.state == REAL


# ─── breakdown anidado (IAI) ──────────────────────────────────────────
def test_nested_breakdown_signals():
    breakdown = {
        "sector": {"weight": 0.15, "variables": {
            "sector_size": {"source": "live", "value": 12.0},
            "sector_growth": {"source": "live", "value": 3.1}}},
        "business": {"weight": 0.25, "variables": {
            "ease_of_business": {"source": "rubric", "value": 50.0}}},
    }
    sigs = {s.key: s for s in nested_breakdown_signals(
        breakdown=breakdown, axis="sectoral", source_label="BCRD", cadence="annual")}
    assert sigs["sector_size"].state == REAL
    assert sigs["ease_of_business"].state == RUBRIC
    # peso desde doctrina (sector: 0.15/2 = 0.075)
    assert abs(sigs["sector_size"].weight - 0.075) < 1e-6


# ─── Agregación / cobertura ───────────────────────────────────────────
def test_axis_coverage_real_weighted():
    sigs = (
        VariableSignal(key="a", label="a", state=REAL, weight=0.6, real_fraction=1.0),
        VariableSignal(key="b", label="b", state=RUBRIC, weight=0.4),
    )
    axis = AxisRegistry(sector_key="x", display_name="X", source="S",
                        implemented=True, signals=sigs)
    # 0.6*1.0 anclado / 0.6+0.4 = 0.6
    assert axis.coverage_real == 0.6
    assert axis.state_counts == {REAL: 1, RUBRIC: 1, GAP: 0}


def test_axis_coverage_partial_real_credit():
    sigs = (VariableSignal(key="a", label="a", state=REAL, weight=1.0, real_fraction=0.5),)
    axis = AxisRegistry(sector_key="x", display_name="X", source="S",
                        implemented=True, signals=sigs)
    assert axis.coverage_real == 0.5  # crédito parcial, no total


def test_registry_summary():
    axes = (
        AxisRegistry(sector_key="x", display_name="X", source="S", implemented=True,
                     signals=(VariableSignal(key="a", label="a", state=REAL, weight=1.0),)),
        AxisRegistry(sector_key="y", display_name="Y", source="S", implemented=False),
    )
    reg = DataRegistry(generated_at="2026-07-11T00:00:00Z", axes=axes)
    summ = reg.summary
    assert summ["axes_total"] == 2
    assert summ["axes_implemented"] == 1
    assert summ["by_state"][REAL] == 1


# ── Solo se promedia lo comparable ────────────────────────────────────────────────────────

def _eje(key, kind, real_fraction, n=2):
    """Eje sintético con *n* señales reales de la fracción dada."""
    from shared.registry.signals import REAL, AxisRegistry, VariableSignal
    sig = tuple(VariableSignal(key=f"v{i}", label=f"v{i}", state=REAL, dimension="d",
                               weight=1.0, source="s", cadence="annual", value=None,
                               real_fraction=real_fraction) for i in range(n))
    return AxisRegistry(sector_key=key, display_name=key, source="s", implemented=True,
                        signals=sig, coverage_kind=kind)


def test_un_eje_con_otra_semantica_no_entra_al_promedio():
    """`coverage_real` responde una pregunta distinta según el eje: en un índice es «qué
    fracción del peso está anclada a dato real»; en el eje de leyes es «cuántos indicadores
    de la LEY medimos». Promediarlas da un número que no significa nada — el eje de leyes,
    con 5 de 90, hundía el promedio de la plataforma sin que ningún índice hubiera perdido
    un solo dato real.
    """
    from shared.registry.signals import (COVERAGE_INDEX, COVERAGE_INSTRUMENT, DataRegistry)

    solo_indices = DataRegistry(generated_at="t", axes=(
        _eje("a", COVERAGE_INDEX, 1.0), _eje("b", COVERAGE_INDEX, 0.5)))
    con_instrumento = DataRegistry(generated_at="t", axes=(
        _eje("a", COVERAGE_INDEX, 1.0), _eje("b", COVERAGE_INDEX, 0.5),
        _eje("law", COVERAGE_INSTRUMENT, 0.056)))

    assert (con_instrumento.summary["coverage_real_mean"]
            == solo_indices.summary["coverage_real_mean"]), \
        "agregar un eje de otra semántica movió el promedio de los índices"
    assert con_instrumento.summary["coverage_real_mean_sobre_ejes"] == 2


def test_pero_el_eje_de_otra_semantica_NO_desaparece_del_resumen():
    """Omitirlo sería peor que promediarlo mal: se iría del resumen sin aviso. Va aparte,
    marcado y con su cobertura — que es exactamente lo que la doctrina manda hacer con lo
    que no es comparable."""
    from shared.registry.signals import (COVERAGE_INDEX, COVERAGE_INSTRUMENT, DataRegistry)

    reg = DataRegistry(generated_at="t", axes=(
        _eje("a", COVERAGE_INDEX, 1.0), _eje("law", COVERAGE_INSTRUMENT, 0.056)))
    otros = reg.summary["coverage_no_comparable"]
    assert [o["sector_key"] for o in otros] == ["law"]
    assert otros[0]["coverage_kind"] == COVERAGE_INSTRUMENT
    assert otros[0]["coverage"] == 0.056


def test_por_defecto_un_eje_es_comparable_y_nada_cambia_para_los_existentes():
    """El campo se agregó con default: ningún eje ya escrito cambia de significado."""
    from shared.registry.signals import COVERAGE_INDEX, AxisRegistry
    assert AxisRegistry(sector_key="x", display_name="x", source="s",
                        implemented=True).coverage_kind == COVERAGE_INDEX


def test_un_coverage_kind_desconocido_no_saca_al_eje_del_promedio_en_silencio(monkeypatch):
    """Un typo en la declaración volvería incomparable a un eje sin que nadie se entere.
    Se ignora el valor y se avisa: el default es el comportamiento de siempre."""
    from shared.products.registry import CatalogEntry
    from shared.registry.service import _axis_registry
    from shared.registry.signals import COVERAGE_INDEX, REAL, VariableSignal

    class _Falso:
        def variable_signals(self):
            return {"period": None, "coverage_kind": "typo_de_alguien",
                    "signals": [VariableSignal(key="v", label="v", state=REAL, dimension="d",
                                               weight=1.0, source="s", cadence="annual",
                                               value=None, real_fraction=1.0)]}

    import shared.registry.service as svc
    monkeypatch.setattr(svc, "is_implemented", lambda k: True)
    monkeypatch.setattr(svc, "get_product", lambda k, db: _Falso())
    entry = CatalogEntry("falso", "Falso", "falso_mod", "s")
    assert _axis_registry(None, entry).coverage_kind == COVERAGE_INDEX
