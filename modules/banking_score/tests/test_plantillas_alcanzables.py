"""REGLA ESTRUCTURAL: toda plantilla que un informe usa tiene que ser ALCANZABLE.

El motor tiene dos rutas y cada una mira su propio diccionario:

  * ruta CEREBRO  → `THIN_TEMPLATES`, y solo se toma si la plantilla está además en
    `_CEREBRO_TEMPLATES` (que es lo que hace que se pase el `axis`);
  * ruta LEGACY   → `TEMPLATES`.

Una plantilla registrada en `THIN_TEMPLATES` pero ausente de `_CEREBRO_TEMPLATES` se manda por
la ruta legacy, donde no existe, y el motor cae al **relleno estático EN SILENCIO**.

Pasó de verdad: el primer anuario generado en producción salió con todas sus tablas correctas
y la sección de análisis diciendo «el análisis cualitativo ampliado se incorpora en la versión
completa del producto». Tardó 0,5 s —una generación real tarda 15-90— y nada lo frenó, porque
el anuario estaba clasificado como boletín de sistema, donde el gate de degradación solo
registra.

Es el mismo modo de falla que dejó al anuario sin endpoint: REGISTRADO PERO INALCANZABLE. Dos
veces en el mismo producto, así que la cura es mecánica y no una lección escrita.
"""
import pytest

from modules.banking_score.reports.narrative import (REPORT_SECTIONS, _CEREBRO_TEMPLATES,
                                                     _SECTION_TO_TEMPLATE)
from shared.narrative.claude_engine import TEMPLATES, THIN_TEMPLATES

#: Secciones que NO se narran con el motor: se generan deterministas o tienen texto propio.
_NO_SE_NARRAN = {"limitations", "early_warning"}


def _plantillas_en_uso():
    """`{plantilla: [secciones que la usan]}` de todos los tipos de informe declarados."""
    out = {}
    for secciones in REPORT_SECTIONS.values():
        for sec in secciones:
            if sec in _NO_SE_NARRAN:
                continue
            out.setdefault(_SECTION_TO_TEMPLATE.get(sec, "banking_summary"), []).append(sec)
    return out


# ── Prueba NEGATIVA ────────────────────────────────────────────────────

def test_hay_plantillas_en_uso_que_revisar():
    """Si el barrido no encuentra nada, la regla de abajo pasa sin haber mirado."""
    assert len(_plantillas_en_uso()) >= 5, sorted(_plantillas_en_uso())


# ── La regla ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("plantilla", sorted(_plantillas_en_uso()))
def test_la_plantilla_es_alcanzable_por_alguna_ruta(plantilla):
    por_cerebro = plantilla in THIN_TEMPLATES and plantilla in _CEREBRO_TEMPLATES
    por_legacy = plantilla in TEMPLATES
    assert por_cerebro or por_legacy, (
        f"'{plantilla}' la usan las secciones {_plantillas_en_uso()[plantilla]} y ninguna ruta "
        "la alcanza: el motor caería al relleno estático EN SILENCIO. Si vive en "
        "THIN_TEMPLATES, agregala a _CEREBRO_TEMPLATES.")


def test_una_plantilla_de_cerebro_NO_declarada_seria_inalcanzable():
    """Fija el mecanismo del defecto, no solo su síntoma: estar en THIN_TEMPLATES no alcanza."""
    ficticia = "plantilla_que_no_existe_en_ninguna_ruta"
    assert ficticia not in TEMPLATES and ficticia not in _CEREBRO_TEMPLATES


def test_el_anuario_llega_por_la_ruta_cerebro():
    """El caso concreto: su plantilla estaba registrada y fuera de la lista."""
    t = _SECTION_TO_TEMPLATE["anuario"]
    assert t in THIN_TEMPLATES and t in _CEREBRO_TEMPLATES


def test_el_anuario_NO_se_entrega_hueco():
    """Un anuario con relleno estático daña más que uno no entregado: es el documento más
    público que la firma produce."""
    from modules.banking_score.api.router_reports import _NO_SE_ENTREGAN_HUECOS

    assert "anuario" in _NO_SE_ENTREGAN_HUECOS
