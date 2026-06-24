"""Tests del renderer PDF genérico (sector-agnóstico)."""
import os


def test_render_basic_pdf(tmp_path):
    from shared.products.render import render_product_pdf
    path = render_product_pdf(
        sector_key="macro", display_name="República Dominicana",
        title="Pulse Macro", period="2024-Q4",
        narratives={"system_overview": "## Panorama\nEl sistema **se mantiene** estable.\n- Punto uno"},
        section_titles={"system_overview": "Panorama del Sistema"},
        tables=[("Factores", [["Factor", "Lectura"], ["Inflación", "estable"]])],
        subtitle="Vista abierta", watermark="Vista abierta · SDQMIP",
        output_dir=str(tmp_path))
    assert os.path.exists(path) and path.endswith(".pdf")
    assert os.path.getsize(path) > 2000


def test_render_sample_overlay(tmp_path):
    from shared.products.render import render_product_pdf
    path = render_product_pdf(
        sector_key="macro", display_name="RD", title="Insight", period="2024-Q4",
        narratives={"executive_summary": "Texto."}, sample=True, output_dir=str(tmp_path))
    assert os.path.exists(path)


def test_render_pdf_text_has_no_glyphs(tmp_path):
    """El renderer limpia glifos/emoji (tofu) y respeta el contenido."""
    try:
        from pypdf import PdfReader
    except ImportError:
        import pytest
        PdfReader = pytest.importorskip("PyPDF2").PdfReader
    from shared.products.render import render_product_pdf
    path = render_product_pdf(
        sector_key="macro", display_name="República Dominicana", title="Pulse", period="2024",
        narratives={"x": "Inflación ✅ controlada ■ y estable"}, output_dir=str(tmp_path))
    text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    assert "✅" not in text and "■" not in text
    assert "controlada" in text
