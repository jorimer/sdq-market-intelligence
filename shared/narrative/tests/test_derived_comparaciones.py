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


# ── Posiciones por dimensión (transversal) ────────────────────────────────────
#
# El input del veto de superlativos. Sólo lo inyectaba pensiones, así que el patrón 8 de
# `numeric_guard` era letra muerta en banca y seguros.

from shared.narrative.derived import posiciones_por_dimension  # noqa: E402

_PANEL = [
    {"id": "bpd", "name": "Banco Popular", "dimensiones": {"Solidez": 100.0, "Liquidez": 71.5}},
    {"id": "bdi", "name": "BDI", "dimensiones": {"Solidez": 98.0, "Liquidez": 88.0}},
    {"id": "bhd", "name": "BHD", "dimensiones": {"Solidez": 95.0, "Liquidez": 80.0}},
]


def test_lider_y_no_lider_en_el_mismo_panel():
    """El caso real: #1 en solidez pero rezagado en liquidez. Colapsar ambas en una sola
    afirmación fue el bug."""
    pos = posiciones_por_dimension("bpd", _PANEL)
    assert pos["Solidez"]["es_lider"] is True and pos["Solidez"]["rank"] == 1
    assert pos["Liquidez"]["es_lider"] is False
    assert pos["Liquidez"]["rank"] == 3
    assert pos["Liquidez"]["lider"] == "BDI"


def test_entidad_sin_score_en_la_dimension_no_produce_posicion():
    """Mejor callar que afirmar una posición que no se puede computar."""
    panel = [{"id": "a", "name": "A", "dimensiones": {"X": None}},
             {"id": "b", "name": "B", "dimensiones": {"X": 10.0}}]
    assert posiciones_por_dimension("a", panel) == {}


def test_panel_vacio_o_invalido_es_seguro():
    assert posiciones_por_dimension("x", []) == {}
    assert posiciones_por_dimension("x", [{"id": "y", "name": "Y"}]) == {}


def test_empate_comparte_el_mejor_puesto():
    """Ranking de COMPETICIÓN. Con orden simple, dos entidades con el mismo score quedaban
    1.ª y 2.ª arbitrariamente: el informe mostró "2.º" para un banco con puntaje MÁXIMO,
    contradiciendo su propio percentil 100 y la prosa que decía que superaba a todo su grupo."""
    panel = [
        {"id": "a", "name": "A", "dimensiones": {"Solidez": 100.0}},
        {"id": "b", "name": "B", "dimensiones": {"Solidez": 100.0}},
        {"id": "c", "name": "C", "dimensiones": {"Solidez": 90.0}},
    ]
    for quien in ("a", "b"):
        pos = posiciones_por_dimension(quien, panel)["Solidez"]
        assert pos["rank"] == 1, quien
        assert pos["es_lider"] is True, quien
        assert pos["empatados_en_su_puesto"] == 2


def test_empate_no_genera_falso_positivo_en_el_guard():
    """Si el empatado en el tope quedara `es_lider: False`, el guardrail vetaría como falso
    un superlativo que SÍ es cierto — el falso positivo que hay que evitar."""
    from shared.narrative.numeric_guard import deterministic_unsupported

    panel = [{"id": "a", "name": "A", "dimensiones": {"Solidez": 100.0}},
             {"id": "b", "name": "B", "dimensiones": {"Solidez": 100.0}}]
    ctx = {"posiciones_dimension": posiciones_por_dimension("a", panel)}
    assert deterministic_unsupported(ctx, "Registra la solvencia más alta del sistema.") == []


def test_el_puesto_salta_tras_un_empate():
    """Competición estándar: 1, 1, 3 — no 1, 1, 2."""
    panel = [
        {"id": "a", "name": "A", "dimensiones": {"X": 10.0}},
        {"id": "b", "name": "B", "dimensiones": {"X": 10.0}},
        {"id": "c", "name": "C", "dimensiones": {"X": 5.0}},
    ]
    assert posiciones_por_dimension("c", panel)["X"]["rank"] == 3


# ── La UNIDAD viaja con la brecha ──────────────────────────────────────
#
# `_lectura` decía siempre "puntos porcentuales". Al empezar a comparar el HHI —un ÍNDICE de
# 0 a 10.000— la brecha salía enunciada como «412.30 puntos porcentuales por encima del
# promedio del sistema»: cifra correcta, unidad imposible. Misma familia que el sujeto que no
# viaja con el número.

def test_un_indice_no_se_enuncia_en_puntos_porcentuales():
    from shared.narrative.derived import comparaciones_vs_referencia as cmp_

    (c,) = cmp_({"hhi": 2091.68}, {"hhi": {"promedio del sistema": 1680.0}},
                unidades={"hhi": "índice"})
    assert c["unidad_brecha"] == "puntos del índice"
    assert "puntos porcentuales" not in c["lectura"]
    assert "411.68 puntos del índice" in c["lectura"]


def test_sin_unidades_declaradas_se_comporta_como_antes():
    """Compat: seguros y pensiones llaman sin `unidades` y son todos porcentajes."""
    from shared.narrative.derived import comparaciones_vs_referencia as cmp_

    (c,) = cmp_({"npl": 1.67}, {"npl": {"promedio de pares": 1.5}})
    assert c["unidad_brecha"] == "puntos porcentuales"
    assert "0.17 puntos porcentuales" in c["lectura"]


def test_el_piso_de_ruido_se_ajusta_a_la_escala_de_la_unidad():
    """0.1 punto de HHI es ruido de redondeo, no una diferencia: forzar un lado ahí sería el
    mismo error que el test de materialidad ya cierra para porcentajes."""
    from shared.narrative.derived import comparaciones_vs_referencia as cmp_

    (ruido,) = cmp_({"hhi": 1680.05}, {"hhi": {"promedio del sistema": 1680.0}},
                    unidades={"hhi": "índice"})
    assert ruido["direccion"] == "en línea"
    (real,) = cmp_({"hhi": 1750.0}, {"hhi": {"promedio del sistema": 1680.0}},
                   unidades={"hhi": "índice"})
    assert real["direccion"] == "por encima"
    # El mismo delta de 0.05 en PORCENTAJE tampoco es material, pero 70 pp sí lo es: los dos
    # pisos son distintos y eso es justamente el punto.
    (pct,) = cmp_({"x": 10.05}, {"x": {"promedio del sistema": 10.0}})
    assert pct["direccion"] == "en línea"


def test_la_brecha_sigue_llamandose_brecha_pp_para_el_guard():
    """Contrato con `numeric_guard._gap_index` y con la instrucción del cerebro: el nombre del
    campo no se toca aunque la unidad no sea pp — la unidad viaja al lado."""
    from shared.narrative.derived import comparaciones_vs_referencia as cmp_

    (c,) = cmp_({"hhi": 2091.68}, {"hhi": {"promedio del sistema": 1680.0}},
                unidades={"hhi": "índice"})
    assert c["brecha_pp"] == 411.68
