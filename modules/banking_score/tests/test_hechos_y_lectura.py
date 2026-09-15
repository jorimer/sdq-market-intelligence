"""HECHOS Y LECTURA: el código escribe toda cifra y toda relación; el modelo, solo la lectura.

**Por qué.** El Deep Dive 2025 de Banco Múltiple Santa Cruz se regeneró cinco veces el
2026-09-15 y cada vuelta sacó un error nuevo en una frase con número —el sujeto del score, un
«duplica» sobre 1,9 veces, «el 75 %» de una mitad central, y al final «63.49, apenas por encima
de donde empezó el año (64.15)»—. Cada guard cazaba la forma anterior. El dueño lo dijo: así no
es un producto estable. La cura es de diseño, no otro guard:

* las frases con cifras las escribe `hechos_y_lectura` desde el dato servido, con la relación
  resuelta en código;
* el modelo recibe un contexto SIN números —solo direcciones, rótulos y veredictos ya
  resueltos— y su texto no puede llevar dígitos (`shared.narrative.lectura_sin_cifras`).

Los tests piden la sección a la RUTA del producto: el defecto vivió siempre en lo que llega al
documento, no en una función aislada.
"""
import asyncio
import json
import re
from types import SimpleNamespace

from modules.banking_score.reports import anio_por_trimestres as apt
from modules.banking_score.reports.revision_anual import _camino


def _puntos():
    return [{"period_end": c, "score": s, "resiliencia": r, "banda_resiliencia": "Adecuada"}
            for c, s, r in (("2024-12-31", 64.15, 63.96), ("2025-03-31", 67.09, 65.20),
                            ("2025-06-30", 63.59, 63.67), ("2025-09-30", 63.43, 63.71),
                            ("2025-12-31", 63.49, 63.63))]


def _dentro():
    """El año de Santa Cruz tal como lo sirvió producción (cifras del v5)."""
    puntos = _puntos()
    tramos = apt._tramos(puntos)
    return {
        "anio": 2025, "entidad": "Banco Múltiple Santa Cruz",
        "serie": [{"corte": p["period_end"], "score_global": p["score"],
                   "resiliencia": p["resiliencia"], "banda": "Adecuada",
                   "es_linea_base": i == 0} for i, p in enumerate(puntos)],
        "linea_base": "2024-12-31", "cortes_faltantes": [],
        "tramos": tramos,
        "tramo_que_mas_movio": {**apt._tramo_que_mas_movio(tramos),
                                "rotulo": "atípico frente a su historia y frente al sistema",
                                "se_destaca": True},
        "contexto_de_los_tramos": [
            {"tramo": "primer trimestre", "cambio_de_la_entidad": 2.94,
             "frente_a_su_historia": "atípico", "frente_al_sistema": "atípico",
             "rotulo": "atípico frente a su historia y frente al sistema", "se_destaca": True,
             "rango_historico_del_mismo_trimestre": {"minimo": -4.43, "maximo": 1.9,
                                                     "n_anios": 5},
             "sistema_en_el_mismo_trimestre": {
                 "mediana_del_cambio_del_resto": 0.12,
                 "la_mitad_central_del_resto_va_desde": -1.16,
                 "la_mitad_central_del_resto_va_hasta": 1.31,
                 "pct_del_resto_dentro_de_la_mitad_central": 50,
                 "n_entidades_del_resto": 42, "universo_del_resto": "instituciones"}},
            {"tramo": "segundo trimestre", "cambio_de_la_entidad": -3.5,
             "frente_a_su_historia": "atípico", "frente_al_sistema": "atípico",
             "rotulo": "atípico frente a su historia y frente al sistema", "se_destaca": True,
             "rango_historico_del_mismo_trimestre": {"minimo": -2.75, "maximo": 9.41,
                                                     "n_anios": 5}},
            {"tramo": "tercer trimestre", "cambio_de_la_entidad": -0.16,
             "frente_a_su_historia": "ordinario", "frente_al_sistema": "ordinario",
             "rotulo": "ordinario", "se_destaca": False},
            {"tramo": "cuarto trimestre", "cambio_de_la_entidad": 0.06,
             "frente_a_su_historia": "historia insuficiente",
             "frente_al_sistema": "sin referencia suficiente del sistema",
             "rotulo": "sin referencia para juzgarlo", "se_destaca": False},
        ],
        "tramos_por_dimension": [
            {"dimension": "eficiencia", "por_tramo": [
                {"tramo": "primer trimestre", "cambio": 12.61},
                {"tramo": "segundo trimestre", "cambio": -14.64},
                {"tramo": "tercer trimestre", "cambio": 0.2}]},
            {"dimension": "liquidez", "por_tramo": [{"tramo": "primer trimestre",
                                                     "cambio": 0.1}]},
        ],
        "camino": _camino(puntos),
        "cambios_de_banda": [],
        "balance": [
            {"indicador": "morosidad", "unidad": "%", "apertura": 2.08, "cierre": 2.97,
             "cambio": 0.89, "score_apertura": 70.0, "score_cierre": 61.1,
             "cambio_de_score": -8.9, "nivel_de_referencia": None,
             "contra_la_referencia": None, "sentido_de_la_escala": "lower",
             "veredicto": "desfavorable",
             "veredicto_por_que": "en este indicador un valor más bajo es mejor"},
            {"indicador": "solvencia", "unidad": "%", "apertura": 12.84, "cierre": 12.51,
             "cambio": -0.33, "score_apertura": 60.0, "score_cierre": 58.0,
             "cambio_de_score": -2.0, "nivel_de_referencia": 10.0,
             "contra_la_referencia": "por encima", "sentido_de_la_escala": "higher",
             "veredicto": "desfavorable",
             "veredicto_por_que": "en este indicador un valor más alto es mejor"},
            {"indicador": "patrimonio_activos", "unidad": "%", "apertura": 10.92,
             "cierre": 10.86, "cambio": -0.06, "veredicto": "estable",
             "veredicto_por_que": "el movimiento no es material"},
            # ÓPTIMO INTERMEDIO. Su `nivel_de_referencia` no es un nivel de nadie: el v6 de
            # Santa Cruz publicó «Cierra por encima del nivel de referencia del modelo,
            # -35.00 %» para la exposición inmobiliaria y «5.00 %» para la cartera sobre
            # depósitos, que cerró en 72.81 %. Y el motivo arrastró el nombre de una clave
            # del contexto a un documento de cliente.
            {"indicador": "exposicion_re", "unidad": "%", "apertura": 9.54, "cierre": 11.63,
             "cambio": 2.09, "score_apertura": 79.69, "score_cierre": 81.09,
             "cambio_de_score": 1.40, "nivel_de_referencia": -35.0,
             "contra_la_referencia": "por encima", "sentido_de_la_escala": "target",
             "veredicto": "no_aplica",
             "veredicto_por_que": ("indicador de óptimo intermedio: la vara es el óptimo, no "
                                   "el promedio — leé 'posicion_vs_optimo'")},
        ],
        "morosidad_estresada": {
            "apertura": {"disponible": True, "morosidad_estresada_de_la_entidad_pct": 6.8412,
                         "veces_la_mediana_del_resto": 1.53,
                         "mediana_estresada_del_resto_del_sistema_pct": 4.48},
            "cierre": {
                "disponible": True, "puntua_en_el_score": False,
                "morosidad_convencional_publicada_de_la_entidad_pct": 2.97,
                "morosidad_estresada_de_la_entidad_pct": 9.06,
                "componentes_de_la_estresada_de_la_entidad": [
                    {"componente": "cartera vencida", "pct_de_la_cartera_de_la_entidad": 2.34},
                    {"componente": "castigos de los últimos 12 meses",
                     "pct_de_la_cartera_de_la_entidad": 3.67}],
                "lo_que_la_mora_convencional_no_ve_pp": 6.72,
                "mayor_componente_fuera_de_la_vencida": "castigos de los últimos 12 meses",
                "mediana_estresada_del_resto_del_sistema_pct": 4.78,
                "n_entidades_del_resto_del_sistema": 42,
                "diferencia_con_la_mediana_del_resto_pp": 4.28,
                "veces_la_mediana_del_resto": 1.9,
                "posicion_frente_a_la_mediana_del_resto": "por encima"},
            "cambio_de_la_estresada_de_la_entidad_en_el_anio_pp": 2.2188,
        },
    }


def _mapa():
    def _fila(sector, peso, atribucion, mora, mora_r, brecha, tasa=None, tasa_r=None,
              spread=None, cob=None, cob_r=None, gar=None, gar_r=None, deuda=None,
              material=True):
        return {"sector": sector, "deuda": deuda or peso * 1e9,
                "peso_en_su_cartera_pct": peso, "mora_pct": mora,
                "mora_del_resto_del_sector_pct": mora_r, "brecha_de_mora_pp": brecha,
                "tasa_promedio_ponderada_pct": tasa, "tasa_del_resto_del_sector_pct": tasa_r,
                "spread_de_tasa_pp": spread,
                "cobertura_de_provision_sobre_vencida_pct": cob,
                "cobertura_del_resto_del_sector_pct": cob_r,
                "garantia_sobre_deuda_pct": gar, "garantia_del_resto_del_sector_pct": gar_r,
                "dolarizacion_de_la_deuda_pct": 55.6, "atribucion": atribucion,
                "material": material}
    sectores = [
        _fila("Y - CONSUMO DE BIENES Y SERVICIOS", 31.98, "idiosincratico_peor", 8.37, 4.18,
              4.19, 31.92, 27.02, 4.9, 83.21, 99.98, 10.0, 12.0),
        _fila("G - COMERCIO AL POR MAYOR Y AL POR MENOR", 23.81, "compartido_con_el_sector",
              0.8, 1.65, -0.85, 12.15, 14.28, -2.13),
        _fila("Z - COMPRA Y REMODELACIÓN DE VIVIENDAS", 11.66, "compartido_con_el_sector",
              0.36, 0.74, -0.38),
        _fila("A - AGRICULTURA, GANADERÍA, CAZA Y SILVICULTURA", 4.10, "idiosincratico_mejor",
              0.37, 1.71, -1.34),
        # EXPOSICIÓN NO MATERIAL: el v6 narró «Pesca (0.00 % de su cartera, mora -2.00 pp
        # frente al resto)». Una celda que la propia tabla marca como ruido no es un hallazgo.
        _fila("B - PESCA", 0.0, "idiosincratico_mejor", 0.0, 2.0, -2.0, deuda=500.0,
              material=False),
    ]
    return {
        "entidad": "Banco Múltiple Santa Cruz", "corte": "2025-12-31",
        "sectores": sectores,
        "resumen": {"sectores_con_deterioro_propio": 1,
                    "peso_en_su_cartera_de_los_sectores_con_deterioro_propio_pct": 31.98,
                    "sectores_con_mejor_desempeno_que_su_sector": 1,
                    "peso_en_su_cartera_de_los_sectores_con_mejor_desempeno_que_su_sector_pct":
                        4.1,
                    "sectores_alineados_con_su_sector": 2,
                    "peso_en_su_cartera_de_los_sectores_alineados_con_su_sector_pct": 35.47},
        "concentracion_por_sector": {
            "de_cuantos": 4,
            "top2": {"pct": 55.79, "miembros": ["Y - CONSUMO DE BIENES Y SERVICIOS",
                                                "G - COMERCIO AL POR MAYOR Y AL POR MENOR"]},
            "top3": {"pct": 67.46, "miembros": []}},
        "provincias": [
            {"provincia": "DISTRITO NACIONAL", "peso_en_su_cartera_pct": 78.06,
             "peso_de_la_provincia_en_el_pais_pct": 54.3, "sobre_representacion_pp": 23.76,
             "mora_pct": 3.06, "mora_del_resto_del_pais_en_la_provincia_pct": 1.36,
             "brecha_de_mora_pp": 1.7},
            {"provincia": "SANTIAGO", "peso_en_su_cartera_pct": 13.94,
             "peso_de_la_provincia_en_el_pais_pct": 9.37, "sobre_representacion_pp": 4.57,
             "mora_pct": 2.21, "mora_del_resto_del_pais_en_la_provincia_pct": 2.12,
             "brecha_de_mora_pp": 0.09},
        ],
    }


# ── 1 · Los HECHOS los escribe el código, con la relación resuelta ────────────

def test_el_cierre_contra_la_linea_base_lo_escribe_el_codigo():
    """LITERAL del v5: «63.49, apenas por encima de donde empezó el año (64.15)». Es por debajo."""
    from modules.banking_score.reports.hechos_y_lectura import hechos_del_anio

    hechos = hechos_del_anio(_dentro())
    assert "cerró 2025 en 63.49, 0.66 puntos por debajo de la línea base (64.15" in hechos
    assert "por encima de la línea base" not in hechos


def test_cada_trimestre_con_su_movimiento_su_rotulo_y_sus_referencias():
    from modules.banking_score.reports.hechos_y_lectura import hechos_del_anio

    hechos = hechos_del_anio(_dentro())
    assert "**Segundo trimestre**: de 67.09 a 63.59 (-3.50 puntos, a la baja)" in hechos
    assert "atípico frente a su historia y frente al sistema" in hechos
    assert "entre -2.75 y +9.41 puntos" in hechos
    # La MITAD central, no «el 75 %».
    assert "la mitad central del resto de las instituciones de crédito (42) se movió entre " \
           "-1.16 y +1.31 puntos" in hechos
    assert "52.6 % del movimiento del año" in hechos
    # El punto más bajo no fue el cierre, y se dice cuánto recuperó.
    assert "El punto más bajo fue 63.43, al cierre del tercer trimestre" in hechos


def test_el_balance_trae_su_veredicto_escrito_y_no_deducido():
    from modules.banking_score.reports.hechos_y_lectura import hechos_del_anio

    hechos = hechos_del_anio(_dentro())
    assert "de 2.08 % a 2.97 % (+0.89 pp): deterioro" in hechos
    assert "nivel de referencia del modelo, 10.00 %" in hechos
    assert "Sin movimiento material: Patrimonio / activos." in hechos


def test_las_dos_moras_con_el_multiplo_servido():
    from modules.banking_score.reports.hechos_y_lectura import hechos_del_anio

    hechos = hechos_del_anio(_dentro())
    assert "la morosidad estresada que publica la SIB es 9.06 %" in hechos
    assert "1.90 veces esa mediana" in hechos
    assert "subió 2.22 puntos porcentuales en el año" in hechos
    assert "La morosidad estresada no entra al score." in hechos


def test_el_mapa_escribe_cada_brecha_con_su_signo_y_su_poblacion():
    from modules.banking_score.reports.hechos_y_lectura import hechos_del_mapa

    hechos = hechos_del_mapa(_mapa())
    assert ("**Consumo de bienes y servicios** (31.98 % de su cartera): mora de 8.37 % "
            "contra 4.18 % del resto del sistema en el mismo sector (+4.19 pp)") in hechos
    assert "reúnen el 55.79 % de su cartera" in hechos
    assert "**Distrito Nacional**: 78.06 % de su cartera contra 54.30 % del crédito del país" \
        in hechos
    assert "Agricultura, ganadería, caza y silvicultura" in hechos


def test_un_optimo_intermedio_no_publica_un_nivel_de_referencia_que_no_lo_es():
    """v6 de Santa Cruz: «Cierra por encima del nivel de referencia del modelo, -35.00 %».

    En un indicador de óptimo intermedio la vara es el óptimo, no ese nivel: publicarlo da una
    referencia que nadie puede usar —y una negativa, en un porcentaje de cartera—. Se omite."""
    from modules.banking_score.reports.hechos_y_lectura import hechos_del_anio

    hechos = hechos_del_anio(_dentro())
    assert "Exposición inmobiliaria" in hechos, "la fixture tiene que llegar al texto"
    assert "-35.00" not in hechos
    assert "nivel de referencia del modelo, -" not in hechos


def test_el_texto_no_nombra_una_clave_del_contexto():
    """El motivo del óptimo intermedio arrastraba «leé 'posicion_vs_optimo'» a un documento de
    cliente: vocabulario del sistema, el defecto que el banco ya había objetado."""
    from modules.banking_score.reports.hechos_y_lectura import hechos_del_anio

    hechos = hechos_del_anio(_dentro())
    assert "posicion_vs_optimo" not in hechos
    assert "leé" not in hechos


def test_un_sector_sin_exposicion_material_no_se_narra():
    from modules.banking_score.reports.hechos_y_lectura import hechos_del_mapa

    hechos = hechos_del_mapa(_mapa())
    assert "Pesca" not in hechos
    assert "Agricultura, ganadería, caza y silvicultura" in hechos, "los materiales siguen"


# ── 2 · El modelo lee un contexto SIN números ────────────────────────────────

def test_el_contexto_de_la_lectura_del_anio_no_trae_digitos():
    from modules.banking_score.reports.hechos_y_lectura import contexto_de_la_lectura_del_anio

    ctx = contexto_de_la_lectura_del_anio(_dentro(), "Banco Múltiple Santa Cruz")
    assert not re.search(r"\d", json.dumps(ctx, ensure_ascii=False)), ctx
    assert ctx["cierre_frente_a_la_linea_base"] == "por debajo"
    assert ctx["morosidad_estresada"]["multiplo_de_la_mediana_del_resto"] == "menos del doble"


def test_el_contexto_de_la_lectura_del_mapa_no_trae_digitos():
    from modules.banking_score.reports.hechos_y_lectura import contexto_de_la_lectura_del_mapa

    ctx = contexto_de_la_lectura_del_mapa(_mapa(), "Banco Múltiple Santa Cruz")
    assert not re.search(r"\d", json.dumps(ctx, ensure_ascii=False)), ctx


# ── 3 · Por la RUTA del producto ─────────────────────────────────────────────

def _narrar(monkeypatch, texto_del_modelo):
    from modules.banking_score.products import BankingProduct
    from shared.narrative import claude_engine
    from shared.products import ProductSnapshot, ProductTier

    vistos = []

    async def _fake_generate(*, context, template, mode, axis, audience):
        vistos.append((template, context))
        return SimpleNamespace(text=texto_del_modelo, model_used="test-model")

    monkeypatch.setattr(claude_engine.narrative_engine, "generate", _fake_generate)
    snapshot = ProductSnapshot(tier=ProductTier.deep_dive, period="2025",
                               payload={"anio_por_trimestres": _dentro(),
                                        "mapa_sectorial": _mapa()},
                               entity_name="Banco Múltiple Santa Cruz")
    salida = asyncio.run(BankingProduct().narratives(ProductTier.deep_dive, snapshot))
    return salida, vistos


def test_la_ruta_publica_los_hechos_y_la_lectura(monkeypatch):
    salida, _ = _narrar(monkeypatch, "El año se rompió en el segundo trimestre.")
    anio = salida["anio_por_trimestres"]
    assert "0.66 puntos por debajo de la línea base" in anio
    assert "El año se rompió en el segundo trimestre." in anio
    mapa = salida["mapa_sectorial"]
    assert "(+4.19 pp)" in mapa and "El año se rompió en el segundo trimestre." in mapa


def test_la_ruta_le_da_al_modelo_contextos_sin_numeros_y_con_la_regla(monkeypatch):
    from shared.narrative.lectura_sin_cifras import CLAVE

    _, vistos = _narrar(monkeypatch, "Lectura.")
    assert len(vistos) == 2
    for template, ctx in vistos:
        assert ctx.get(CLAVE) is True, template
        assert not re.search(r"\d", json.dumps(ctx, ensure_ascii=False)), (template, ctx)


def test_los_titulos_del_modelo_no_llegan_al_documento(monkeypatch):
    """La estructura es del código. El v5 abrió con «Año 2025: Lectura Intraanual»."""
    salida, _ = _narrar(monkeypatch, "## Año por dentro: lectura\n\nEl año se rompió.")
    assert "Lectura Intraanual" not in salida["anio_por_trimestres"]
    assert "## Año por dentro" not in salida["anio_por_trimestres"]
    assert "El año se rompió." in salida["anio_por_trimestres"]
