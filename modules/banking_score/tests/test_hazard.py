"""Tests del modelo de riesgo en tiempo discreto.

Lo que protegen: que las salidas que NO son quiebras censuren en vez de contar como evento o
como supervivencia eterna, y que el modelo se niegue a graduar sobre etiquetas inferidas por
más alto que le dé el AUC.
"""
from datetime import date

from modules.banking_score.validation import hazard as hz
from modules.banking_score.validation import terminaciones as tm


def _serie(nombre, n_trim, *, mora=2.0, cob=150.0, apa=12.0, act=1000.0, dep=800.0,
           fin=date(2026, 3, 1)):
    out = {}
    for k in range(n_trim):
        total = fin.year * 12 + (fin.month - 1) - 3 * k
        d = date(total // 12, total % 12 + 1, 1)
        out[d] = {"entidad_nombre": nombre, "tipo_entidad": "Bancos Múltiples",
                  "morosidad_pct": mora, "cobertura_pct": cob, "apalancamiento_pct": apa,
                  "activos_totales": act, "depositos_totales": dep}
    return out


def _term(nombre, fecha, naturaleza, causa=None):
    return tm.Terminacion("C", nombre, "Bancos Múltiples", fecha, naturaleza, ("x",),
                          False, 40, 2.0, 10.0, causa, "fuente" if causa else None)


def test_una_fusion_censura_no_cuenta_como_evento():
    """Contar una fusión como quiebra sesga hacia un lado; como superviviente eterna, hacia
    el otro. Censurar es no afirmar ninguna de las dos."""
    panel = {"A": _serie("Fusionada", 20, fin=date(2014, 9, 1))}
    t = [_term("Fusionada", date(2014, 9, 1), "sana_al_salir", "fusion")]
    _, y, _ = hz.construir_panel_riesgo(panel, t, date(2026, 4, 1))
    assert sum(y) == 0, "una fusión no aporta eventos"
    assert len(y) > 0, "pero sí aporta períodos en riesgo previos"


def test_un_renombre_tampoco_es_un_evento():
    panel = {"A": _serie("Vieja", 20, fin=date(2020, 6, 1))}
    t = [_term("Vieja", date(2020, 6, 1), "sana_al_salir", "renombre")]
    _, y, _ = hz.construir_panel_riesgo(panel, t, date(2026, 4, 1))
    assert sum(y) == 0


def test_una_quiebra_marca_evento_solo_en_su_ultimo_periodo():
    """El resto de sus trimestres son 'estuvo en riesgo y no quebró todavía' — que es
    exactamente la información que el clasificador de horizonte fijo tiraba."""
    panel = {"A": _serie("Quebrada", 20, fin=date(2003, 6, 1))}
    t = [_term("Quebrada", date(2003, 6, 1), "insolvencia", "quiebra")]
    _, y, _ = hz.construir_panel_riesgo(panel, t, date(2026, 4, 1))
    assert sum(y) == 1 and len(y) > 5


def test_una_entidad_viva_aporta_riesgo_sin_evento():
    panel = {"A": _serie("Viva", 20)}
    _, y, _ = hz.construir_panel_riesgo(panel, [], date(2026, 4, 1))
    assert sum(y) == 0 and len(y) > 5


def test_no_evaluable_sin_curar_no_entra():
    """No se sabe qué fue: no aporta evento ni supervivencia."""
    panel = {"A": _serie("Dudosa", 20, fin=date(1992, 9, 1))}
    t = [_term("Dudosa", date(1992, 9, 1), "no_evaluable")]
    _, y, _ = hz.construir_panel_riesgo(panel, t, date(2026, 4, 1))
    assert len(y) == 0


def test_solo_curadas_excluye_lo_no_confirmado():
    panel = {"A": _serie("Curada", 20, fin=date(2003, 6, 1)),
             "B": _serie("Sin curar", 20, fin=date(2005, 6, 1))}
    t = [_term("Curada", date(2003, 6, 1), "insolvencia", "quiebra"),
         _term("Sin curar", date(2005, 6, 1), "insolvencia")]
    _, _, g = hz.construir_panel_riesgo(panel, t, date(2026, 4, 1), solo_curadas=True)
    assert set(g) == {"Curada"}


def test_pocos_eventos_no_gradua():
    panel = {f"E{i}": _serie(f"E{i}", 20) for i in range(5)}
    r = hz.ajustar(panel, [], date(2026, 4, 1))
    assert r.gradua is False and "eventos" in (r.motivo or "")


def test_sobre_etiquetas_inferidas_NUNCA_gradua():
    """Aunque el AUC dé alto: la etiqueta inferida se construye con las mismas variables que
    después predicen, así que el AUC está inflado. Es diagnóstico, no validación — el mismo
    estándar con que `deal_scoring` trata sus labels retrospectivos."""
    import inspect
    src = inspect.getsource(hz.ajustar)
    assert "if not solo_curadas:" in src and "gradua = False" in src


def test_el_umbral_de_graduacion_es_el_de_la_casa():
    from modules.deal_scoring.validation.learning_curve import GRADUATION_AUC_FLOOR as piso
    assert hz.GRADUATION_AUC_FLOOR == piso, (
        "un segundo umbral de graduación en el repo es un segundo estándar")


def test_la_trayectoria_se_auto_referencia_a_la_historia_del_banco():
    """`z_propio` pregunta "¿está alto PARA ESTE BANCO?" en vez de "¿supera el piso de su
    tipo?". Con eso los pisos por tipo —constantes puestas a mano— dejan de ser parámetros
    libres."""
    fin = date(2026, 3, 1)
    serie = _serie("B", 16, fin=fin)
    trim = sorted(d for d in serie if d.month in hz.MES_TRIMESTRAL)
    # una entidad plana no tiene desviación de su propia historia
    fx = hz._trayectoria(serie, trim[-1], trim)
    assert abs(fx["morosidad_pct__z_propio"]) < 1e-6
    # la misma mora, ahora anómala para ESE banco
    serie[trim[-1]] = {**serie[trim[-1]], "morosidad_pct": 9.0}
    fx2 = hz._trayectoria(serie, trim[-1], trim)
    assert fx2["morosidad_pct__z_propio"] > 1.0


def test_sin_historia_propia_no_hay_trayectoria():
    """Se excluye la observación en vez de rellenar la historia que no existe."""
    fin = date(2026, 3, 1)
    serie = _serie("B", 3, fin=fin)
    trim = sorted(d for d in serie if d.month in hz.MES_TRIMESTRAL)
    assert hz._trayectoria(serie, trim[-1], trim) is None


def test_la_persistencia_cuenta_trimestres_consecutivos_empeorando():
    fin = date(2026, 3, 1)
    serie = _serie("B", 16, fin=fin)
    trim = sorted(d for d in serie if d.month in hz.MES_TRIMESTRAL)
    for i, d in enumerate(trim):
        serie[d] = {**serie[d], "morosidad_pct": 2.0 + 0.3 * i}   # empeora siempre
    fx = hz._trayectoria(serie, trim[-1], trim)
    assert fx["morosidad_pct__persistencia"] >= 4
