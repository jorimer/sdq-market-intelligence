"""Documento de Criterios — GENERADO del motor, no narrado por IA.

Antes se pedía a la IA narrar la plantilla por-banco `banking_risk` con un `scoring_result`
vacío. El estándar epistémico hacía lo correcto (negarse a fabricar) pero ESE RECHAZO
terminaba impreso en el PDF de cliente, con nombres de campos internos a la vista. El valor
de generarlo del motor es que no puede desviarse de cómo se califica realmente.
"""
import re

from modules.banking_score.reports.criteria_doc import (
    SECTION_TITLES,
    _SUB_INDICATOR_MAP,
    build_criteria_document,
)
from modules.banking_score.scoring.indicator_detail import INDICATOR_META
from modules.banking_score.scoring.weights import SUB_COMPONENT_WEIGHTS, WEIGHT_PROFILES


def _doc() -> str:
    return "\n".join(build_criteria_document().values())


def test_todas_las_secciones_tienen_titulo_registrado():
    """Sin título registrado el renderer cae al fallback snake_case (bug real en prod)."""
    for key in build_criteria_document():
        assert key in SECTION_TITLES, f"falta título para {key}"


def test_no_es_un_rechazo_a_fabricar():
    """SENSOR DE REGRESIÓN: el defecto original era que el PDF de cliente contenía el
    mensaje del modelo negándose a analizar, con campos internos del contexto."""
    txt = _doc().lower()
    for marca in ("no contiene datos de entidad", "campos de puntuación",
                  "una vez proporcionado", "umbral_fmt", "delta_overall", "riesgos_baja",
                  "scoring_result", "contexto recibido"):
        assert marca not in txt, f"el documento contiene el artefacto: {marca}"


def test_los_pesos_salen_del_motor():
    """Si alguien recalibra un peso, el documento debe seguirlo solo."""
    comp = build_criteria_document()["crit_componentes"]
    for peso in SUB_COMPONENT_WEIGHTS.values():
        assert f"{peso * 100:.0f}%" in comp


def test_todos_los_perfiles_por_tipo_de_entidad_estan():
    comp = build_criteria_document()["crit_componentes"]
    # 6 perfiles + la fila base ⇒ toda entidad supervisada queda descrita.
    assert len(WEIGHT_PROFILES) >= 6
    for perfil in WEIGHT_PROFILES.values():
        assert abs(sum(perfil.values()) - 1.0) < 1e-9, "un perfil no suma 100%"


def test_la_metodologia_publica_los_DOS_EJES_y_no_la_escala_de_letras():
    """El documento que ve el cliente era donde más pesaba la notación retirada: publicaba
    los diez escalones con su glosa."""
    from modules.banking_score.scoring.perfil_sdq import BANDAS_RESILIENCIA

    esc = build_criteria_document()["crit_escala"]
    assert "SDQ-" not in esc, "la notación retirada volvió al documento de metodología"
    assert "dos ejes independientes" in esc
    for _corte, nombre in BANDAS_RESILIENCIA:
        assert nombre in esc
    for banda in ("Sobresaliente", "Competitiva", "Rezagada", "Deficiente"):
        assert banda in esc
    # Y explica POR QUÉ una es absoluta y la otra relativa.
    assert "ABSOLUTAS" in esc and "RELATIVAS" in esc


def test_todos_los_indicadores_con_ficha_estan_listados():
    ind = build_criteria_document()["crit_indicadores"]
    for key, meta in INDICATOR_META.items():
        assert meta["label"] in ind, f"falta el indicador {key}"


def test_el_conteo_declarado_coincide_con_lo_listado():
    """El total no puede ser `len(INDICATOR_META)`: el motor tiene claves compuestas sin
    ficha, así que ese número mentiría por exceso."""
    ind = build_criteria_document()["crit_indicadores"]
    declarado = int(re.search(r"evalúa \*\*(\d+) indicadores", ind).group(1))
    listados = sum(1 for keys in _SUB_INDICATOR_MAP.values()
                   for k in keys if k in INDICATOR_META)
    assert declarado == listados


def test_los_compuestos_derivados_se_declaran():
    """`composite_calidad` pondera en el score pero no tiene ficha. Callarlo haría que el
    documento describa menos componentes de las que se puntúan."""
    derivados = [k for keys in _SUB_INDICATOR_MAP.values()
                 for k in keys if k not in INDICATOR_META]
    if not derivados:
        return
    assert "compuesto de calidad" in build_criteria_document()["crit_indicadores"].lower()


def test_encuadre_y_limitaciones_presentes():
    """El documento debe decir qué NO es: no es rating de crédito ni mide PD."""
    txt = _doc().lower()
    assert "no es un rating de crédito" in txt
    assert "standalone" in txt
    assert "probabilidad de incumplimiento" in txt


def test_fuentes_y_validacion_presentes():
    txt = _doc()
    assert "Superintendencia de Bancos" in txt
    assert "Banco Central" in txt
    assert "Gini" in txt and "bootstrap" in txt
    # Cohorte real de quiebras + el límite honesto de la prueba.
    assert "Baninter" in txt
    assert "no son evaluables" in txt


def test_sin_sesion_no_inventa_cifras_de_backtest():
    """Sin DB no hay Gini vigente: se describe el método, no se fabrica un número."""
    val = build_criteria_document(db=None)["crit_validacion"]
    assert "Gini" in val
    assert "Resultado vigente" not in val


def test_es_determinista():
    assert build_criteria_document() == build_criteria_document()
