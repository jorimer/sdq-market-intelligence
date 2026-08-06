"""Los boletines de SISTEMA no se narran con la plantilla POR ENTIDAD.

Hallazgo 2026-08-06 (Wire y DataWatch en prod). `executive_summary` resolvía a
`banking_summary` —plantilla de un banco concreto— y recibía un `scoring_result` en ceros
porque un reporte de sistema no tiene `bank_id`. El modelo se negaba a analizar, con razón,
y esa disculpa quedaba impresa como cuerpo del PDF.

DataWatch era el caso peor: la disculpa convivía con una sección de Tendencias completa y
con cifras reales del MISMO período. Eso no se lee como función pendiente sino como bug en
vivo, que es peor señal que un stub honesto.
"""
import pytest

from modules.banking_score.reports.narrative import (
    _CEREBRO_TEMPLATES,
    _SECTION_TO_TEMPLATE,
    _SYSTEM_REPORT_TYPES,
    REPORT_SECTIONS,
    _build_system_context,
)
from shared.data.sib_client import DEFAULT_BENCHMARKS
from shared.narrative.claude_engine import TEMPLATES


def test_la_plantilla_de_sistema_existe_y_es_ruta_legacy():
    """Como trend_analysis y sector_outlook, que ya funcionan: sin doctrina de entidad."""
    assert "system_summary" in TEMPLATES
    assert "system_summary" not in _CEREBRO_TEMPLATES


@pytest.mark.parametrize("report_type", sorted(_SYSTEM_REPORT_TYPES))
def test_los_boletines_de_sistema_estan_declarados(report_type):
    assert report_type in REPORT_SECTIONS


def test_criteria_no_es_un_boletin_narrado():
    """`criteria` no se narra en absoluto: se genera del motor (criteria_doc)."""
    assert "criteria" not in _SYSTEM_REPORT_TYPES


def test_el_contexto_de_sistema_no_lleva_datos_de_entidad():
    """Pasar el scoring en CEROS era la causa directa del 'no puedo analizar'."""
    ctx = _build_system_context("wire", "Sistema Bancario", "2026-03-31", DEFAULT_BENCHMARKS)
    for prohibido in ("overall_score", "rating_tier", "sub_components", "indicators"):
        assert prohibido not in ctx


def test_el_contexto_de_sistema_lleva_los_benchmarks_que_si_funcionan():
    ctx = _build_system_context("datawatch", "Sistema Bancario", "2026-03-31",
                                DEFAULT_BENCHMARKS)
    assert ctx["promedios_sistema"]["roe"] == 18.5
    assert ctx["grupos_de_pares"]["large_banks"]["roe_avg"] == 20.1
    assert ctx["limites_regulatorios"]["car_minimum"] == 10.0


def test_el_encuadre_prohibe_pedir_la_entidad():
    ctx = _build_system_context("wire", "Sistema Bancario", "2026-03-31", DEFAULT_BENCHMARKS)
    assert "no la pidas" in ctx["encuadre"].lower()


def test_sin_benchmarks_no_revienta():
    ctx = _build_system_context("wire", "Sistema Bancario", "2026-03-31", None)
    assert ctx["tipo_de_boletin"] == "wire"


def test_el_mapeo_por_entidad_sigue_intacto_para_full_rating():
    """El arreglo NO debe cambiar el informe por banco."""
    assert _SECTION_TO_TEMPLATE["executive_summary"] == "banking_summary"
    assert "full_rating" not in _SYSTEM_REPORT_TYPES
