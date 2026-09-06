"""Tres defectos de un boletín REAL, y de dónde salieron.

El boletín regional del 2026-09-06, 16 páginas y listo para distribuir, tenía esto:

1. **Tres convenciones de miles conviviendo**: 76 cifras con coma («21,594»), 8 con punto
   («6.823.5») y 4 con espacio («2 891.62»). La del punto además es ilegible bajo la
   convención de casa —punto decimal—: «6.823.5» se lee como seis coma ochocientos veintitrés.
2. **Una razón contada como múltiplo**: «La cobertura de cartera vencida … es de 136.48 veces
   el uno». Son 136,48 POR CIENTO, o sea 1,36 veces. «136,48 veces» se lee como 13.648%.
3. **Un descargo sobre calificaciones que el documento no emite**: el boletín es divulgación
   gratuita y no califica a nadie, y su pie hablaba de «las calificaciones expresadas en este
   informe».

El segundo es el interesante: `_semantica_indicadores` YA servía la unidad de cada indicador
—el registro declara `"unit": "%"` para cobertura— pero solo al contexto de ENTIDAD. El de
SISTEMA servía los promedios pelados, así que el modelo tuvo que adivinar si 136,48 era un
porcentaje o un múltiplo. El mecanismo existía y a ese motor le faltaba.
"""
from shared.narrative.sanitize import normalize_number_format


# ── 1. El formato del número ──────────────────────────────────────
def test_el_punto_de_miles_se_corrige():
    """«6.823.5» es ilegible con punto decimal: parece seis coma ochocientos veintitrés."""
    texto, cambios = normalize_number_format("saldo de 6.823.5 unidades")
    assert texto == "saldo de 6,823.5 unidades"
    assert cambios and "miles" in cambios[0]


def test_un_miles_de_TRES_dígitos_finales_NO_se_toca():
    """«12.345.678» es un miles-miles de otra convención. Reescribirlo cambiaría la magnitud
    por mil, que es peor que la inconsistencia que arregla."""
    texto, cambios = normalize_number_format("12.345.678 pesos")
    assert texto == "12.345.678 pesos"
    assert cambios == []


def test_la_coma_de_miles_legitima_sobrevive():
    """La convención de casa. Tocarla sería romper 76 cifras para arreglar 8."""
    texto, cambios = normalize_number_format("21,594 unidades y 1,176 puntos")
    assert texto == "21,594 unidades y 1,176 puntos"
    assert cambios == []


def test_el_miles_con_ESPACIO_se_MARCA_pero_no_se_reescribe():
    """Un espacio entre dígitos también aparece en prosa legítima («en 2026 100 entidades»):
    sustituirlo automáticamente inventaría una cifra. Se declara y se deja."""
    texto, cambios = normalize_number_format("un HHI de 2 891.62 puntos")
    assert texto == "un HHI de 2 891.62 puntos"
    assert any("ESPACIO" in c for c in cambios)


def test_la_coma_decimal_sigue_pasando_a_punto():
    """La regla que ya existía no se rompe al agregar la nueva."""
    texto, _ = normalize_number_format("una tasa de 18,6% en julio")
    assert "18.6%" in texto


# ── 2. La unidad viaja con el número, también en el sistema ───────
def test_el_contexto_de_SISTEMA_declara_la_unidad_de_cada_promedio():
    """Sin esto el modelo adivina si 136,48 es un porcentaje o un múltiplo — y adivinó mal."""
    from modules.banking_score.reports.narrative import _semantica_del_sistema

    sem = _semantica_del_sistema({"cobertura_provisiones_avg": 136.48,
                                  "morosidad_avg": 1.99})
    assert sem["cobertura_provisiones"]["unidad"] == "%"
    assert sem["morosidad"]["unidad"] == "%"
    assert sem["cobertura_provisiones"]["mide"], "sin «qué mide» la unidad sola no alcanza"


def test_la_semantica_LLEGA_al_contexto_del_boletin():
    """Que la función exista no sirve si el contexto no la usa: era exactamente el defecto."""
    from modules.banking_score.reports.narrative import _build_system_context

    ctx = _build_system_context(
        "boletin_regional", "Sistema", "2025-12-31",
        {"sector_averages": {"cobertura_provisiones_avg": 136.48}})
    assert "semantica_indicadores" in ctx, (
        "el contexto de sistema sirve los promedios pelados: el modelo tiene que adivinar "
        "la unidad, y una cobertura de 136,48% se narró como «136,48 veces el uno»")
    assert ctx["semantica_indicadores"]["cobertura_provisiones"]["unidad"] == "%"


# ── 3. El descargo dice lo que el documento hace ──────────────────
def test_un_documento_que_NO_califica_no_se_descarga_de_calificaciones():
    from modules.banking_score.reports.pdf_generator import (
        DISCLAIMER_ES, DISCLAIMER_SIN_CALIFICACION_ES)

    assert "calificaciones y opiniones" in DISCLAIMER_ES
    assert "no contiene calificaciones" in DISCLAIMER_SIN_CALIFICACION_ES
    assert "Las calificaciones y opiniones expresadas" not in DISCLAIMER_SIN_CALIFICACION_ES


def test_el_pie_se_elige_por_PRESENCIA_de_calificacion():
    """Por presencia y no por lista de tipos: una lista es lo que alguien olvida actualizar,
    y a este repo ya le costó cuatro registros perdidos de a uno."""
    import inspect

    from modules.banking_score.reports import pdf_generator as g

    fuente = inspect.getsource(g.generate_pdf_report) if hasattr(g, "generate_pdf_report") \
        else inspect.getsource(g)
    assert "califica=bool(scoring_result.get(\"overall_score\"))" in fuente, (
        "el pie no se está eligiendo por la presencia de una calificación")
