"""Dirección de las comparaciones RESUELTA en código, no derivada por el modelo.

Bug 2026-08-05/06: dos informes de cliente afirmaron una comparación con el sentido
invertido ("mora de 1.67% por debajo del promedio de pares (1.5%)"; "ICAP de 16.44% por
encima del promedio del sistema (16.5%)") contradiciendo la tabla del propio informe. Las
cifras eran correctas; el modelo erró la RELACIÓN. La cura es la que este módulo ya aplica
a aportes y deltas: servir el resultado para que lo copie.
"""
from shared.narrative.derived import MATERIALIDAD_PP, comparaciones_vs_referencia


def _by(comps, indicador, referencia):
    return next(c for c in comps
                if c["indicador"] == indicador and c["referencia"] == referencia)


def test_caso_real_bpd_ambas_bases():
    """El caso que se escapó: la mora está por DEBAJO del sistema y por ENCIMA de sus pares.
    Confundir las bases fue justamente el bug."""
    comps = comparaciones_vs_referencia(
        {"morosidad": 1.67},
        {"morosidad": {"promedio del sistema": 1.8, "promedio de bancos grandes": 1.5}},
    )
    assert _by(comps, "morosidad", "promedio del sistema")["direccion"] == "por debajo"
    assert _by(comps, "morosidad", "promedio de bancos grandes")["direccion"] == "por encima"


def test_brecha_no_material_no_afirma_direccion():
    """16.44 vs 16.5 difieren 0.06 pp. Forzar un lado ahí es lo que hizo al modelo elegir el
    equivocado, y además no informa nada: la lectura honesta es 'en línea'."""
    comps = comparaciones_vs_referencia(
        {"solvencia": 16.44}, {"solvencia": {"promedio del sistema": 16.5}})
    c = _by(comps, "solvencia", "promedio del sistema")
    assert c["direccion"] == "en línea"
    assert c["brecha_pp"] == -0.06


def test_brecha_material_si_afirma_direccion():
    comps = comparaciones_vs_referencia(
        {"solvencia": 16.44}, {"solvencia": {"promedio de bancos grandes": 15.8}})
    c = _by(comps, "solvencia", "promedio de bancos grandes")
    assert c["direccion"] == "por encima"
    assert c["brecha_pp"] == 0.64


def test_umbral_de_materialidad_es_el_declarado():
    justo_debajo = comparaciones_vs_referencia(
        {"x": 10.0}, {"x": {"ref": 10.0 + MATERIALIDAD_PP / 2}})
    justo_encima = comparaciones_vs_referencia(
        {"x": 10.0}, {"x": {"ref": 10.0 + MATERIALIDAD_PP * 2}})
    assert justo_debajo[0]["direccion"] == "en línea"
    assert justo_encima[0]["direccion"] == "por debajo"


def test_valores_ausentes_o_no_numericos_se_saltan():
    """Best-effort: nunca lanza y nunca inventa un veredicto."""
    assert comparaciones_vs_referencia({}, {}) == []
    assert comparaciones_vs_referencia({"x": None}, {"x": {"ref": 1.0}}) == []
    assert comparaciones_vs_referencia({"x": 1.0}, {"x": {"ref": None}}) == []
    assert comparaciones_vs_referencia({"x": "n/d"}, {"x": {"ref": 1.0}}) == []
    assert comparaciones_vs_referencia({"x": 1.0}, {"x": "no-es-dict"}) == []


def test_indicador_sin_referencia_no_produce_fila():
    comps = comparaciones_vs_referencia({"a": 1.0, "b": 2.0}, {"a": {"ref": 3.0}})
    assert [c["indicador"] for c in comps] == ["a"]
