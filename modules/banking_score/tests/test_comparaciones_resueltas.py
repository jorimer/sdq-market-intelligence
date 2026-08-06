"""La ruta de REPORTES inyecta las comparaciones resueltas — era la que no tenía cura."""
from modules.banking_score.reports.narrative import _build_section_context

_SCORING = {
    "overall_score": 90.69,
    "rating_tier": "SDQ-AA+",
    "sub_components": {"solidez": 100.0, "calidad": 84.0},
    "indicators": {
        "solvencia": {"raw": 16.44, "score": 100.0, "available": True},
        "morosidad": {"raw": 1.67, "score": 83.3, "available": True},
    },
}
_BENCH = {
    "sector_averages": {"car": 16.5, "npl": 1.8},
    "peer_groups": {"large_banks": {"car_avg": 15.8, "npl_avg": 1.5}},
}


def _find(comps, ind, ref):
    return next(c for c in comps if c["indicador"] == ind and c["referencia"] == ref)


def test_seccion_de_panorama_recibe_comparaciones():
    ctx = _build_section_context("executive_summary", "BPD", _SCORING, "2026-03-31", _BENCH)
    comps = ctx["comparaciones"]
    # La clave LEGADA `large_banks` es una constante: su etiqueta lo declara.
    assert _find(comps, "morosidad",
                 "promedio de bancos grandes (referencia declarada)"
                 )["direccion"] == "por encima"
    assert _find(comps, "morosidad", "promedio del sistema")["direccion"] == "por debajo"
    assert _find(comps, "solvencia", "promedio del sistema")["direccion"] == "en línea"


def test_seccion_de_subcomponente_solo_sus_indicadores():
    ctx = _build_section_context("calidad_activos", "BPD", _SCORING, "2026-03-31", _BENCH)
    assert {c["indicador"] for c in ctx["comparaciones"]} == {"morosidad"}


def test_sin_benchmarks_no_hay_comparaciones():
    ctx = _build_section_context("executive_summary", "BPD", _SCORING, "2026-03-31", None)
    assert "comparaciones" not in ctx


def test_etiqueta_de_pares_es_legible():
    """La etiqueta es la que el analista debe usar al nombrar la base."""
    ctx = _build_section_context("executive_summary", "BPD", _SCORING, "2026-03-31", _BENCH)
    etiquetas = {c["referencia"] for c in ctx["comparaciones"]}
    assert "promedio de bancos grandes (referencia declarada)" in etiquetas
    assert not any("large_banks" in e for e in etiquetas)
    # Una referencia DECLARADA debe verse como tal: si no es medida del panel,
    # el informe no puede presentarla como si lo fuera.
    assert any("declarada" in e for e in etiquetas)
