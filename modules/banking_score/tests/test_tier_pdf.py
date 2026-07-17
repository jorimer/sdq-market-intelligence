"""Tests de la extensión NO-ROTURA de generate_pdf_report (productización por niveles).

La regresión de los 7 reportes base vive en test_reports.py (llaman sin params nuevos).
Aquí se prueba que los params opt-in (sections/tier/watermark/sample/band_distribution/
peer_block) funcionan y que `_order_narratives` filtra/ordena sin perder contenido.
"""
import os

import pytest

from modules.banking_score.reports.pdf_generator import (
    _order_narratives,
    generate_pdf_report,
)


def _result():
    return {
        "overall_score": 82.0, "rating_tier": "SDQ-AA-",
        "sub_components": {"solidez": 80, "calidad": 78, "eficiencia": 70,
                           "liquidez": 75, "diversificacion": 60},
        "indicators": {"solvencia": {"raw": 16.8, "score": 90, "available": True}},
    }


# ── No-rotura: la llamada actual (sin params nuevos) sigue intacta ──

@pytest.mark.asyncio
async def test_default_call_unchanged(tmp_path):
    path = await generate_pdf_report(
        "full_rating", "Banco Test", _result(), "2024-Q4",
        narratives={"executive_summary": "Resumen."}, output_dir=str(tmp_path))
    assert os.path.exists(path) and path.endswith(".pdf")


# ── Pulse: tabla de banda + watermark, sin scoring de entidad ──

@pytest.mark.asyncio
async def test_pulse_band_distribution_and_watermark(tmp_path):
    system = {"overall_score": 0, "rating_tier": "Sistema", "sub_components": {}, "indicators": {}}
    path = await generate_pdf_report(
        "sector_outlook", "Sistema Bancario RD", system, "2024-Q4",
        narratives={"system_overview": "El sistema se mantiene sólido."},
        output_dir=str(tmp_path), tier="pulse", watermark="Vista abierta · SDQMIP",
        band_distribution={"Fuerte": 8, "Adecuado": 5, "Vigilancia": 2})
    assert os.path.exists(path)
    assert os.path.getsize(path) > 3000


# ── Insight/Deep Dive: bloque de pares + muestra ──

@pytest.mark.asyncio
async def test_insight_peer_block_and_sample(tmp_path):
    path = await generate_pdf_report(
        "full_rating", "Banco Demo, S.A.", _result(), "2024-Q4",
        narratives={"executive_summary": "Resumen.", "recommendation": "Aprobar."},
        output_dir=str(tmp_path), tier="insight", sample=True,
        peer_block={"metric_label": "Activos", "cr5": 72.5, "cr10": 88.1, "hhi": 1450})
    assert os.path.exists(path)


# ── _order_narratives: filtra/ordena y preserva extras ──

def test_order_narratives_default_is_identity():
    n = {"a": "1", "b": "2"}
    assert _order_narratives(n, None) == n


def test_order_narratives_orders_by_sections():
    n = {"b": "2", "a": "1", "c": "3"}
    ordered = _order_narratives(n, ["a", "b"])
    assert list(ordered)[:2] == ["a", "b"]
    # No pierde la sección extra no listada.
    assert ordered["c"] == "3"


def test_order_narratives_skips_absent_sections():
    n = {"a": "1"}
    assert list(_order_narratives(n, ["a", "missing"])) == ["a"]


# ─── Regresiones de template en producción (2026-07-17) ────────────────────────

def test_standard_section_titles_merged_in_spanish():
    # Bug real: "std_methodology"/"std_sources" caían al fallback key.title() →
    # "Std Methodology"/"Std Sources" en inglés en el índice del PDF.
    from modules.banking_score.reports.pdf_generator import NARRATIVE_SECTION_TITLES
    assert NARRATIVE_SECTION_TITLES["std_methodology"] == "Metodología y fuentes"
    assert NARRATIVE_SECTION_TITLES["std_sources"] == "Fuentes y referencias"
    assert NARRATIVE_SECTION_TITLES["std_glossary"] == "Glosario"


@pytest.mark.asyncio
async def test_tier_label_translated_in_title(tmp_path, monkeypatch):
    # Bug real: la portada imprimía el tier crudo ("· deep_dive") sin mapear.
    import shared.products.render as render_mod
    captured = {}
    real_build = render_mod.build_branded_pdf

    def _spy(**kwargs):
        captured.update(kwargs)
        return real_build(**kwargs)

    monkeypatch.setattr(render_mod, "build_branded_pdf", _spy)
    await generate_pdf_report(
        "full_rating", "Banco Test", _result(), "2024-Q4",
        narratives={"executive_summary": "Resumen."},
        output_dir=str(tmp_path), tier="deep_dive")
    assert "Deep Dive" in captured["title"]
    assert "deep_dive" not in captured["title"]
