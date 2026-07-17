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


def test_render_tall_chart_does_not_overflow_page(tmp_path):
    # Regresión: un gráfico con MUCHAS barras (p.ej. la trayectoria WGI de 26 años) generaba
    # una imagen más alta que el marco de página → LayoutError → 500 al descargar el PDF.
    # Ahora se escala por alto y el PDF se genera igual.
    from shared.products.render import render_product_pdf
    tall = {"title": "Trayectoria WGI (0-100)",
            "items": [(str(1996 + i), 40.0 + i) for i in range(26)]}  # 26 barras
    path = render_product_pdf(
        sector_key="macro", display_name="República Dominicana",
        title="Deep Dive Riesgo-País", period="2024-12-31",
        narratives={"gov": "Trayectoria institucional."},
        section_titles={"gov": "Gobernanza"},
        charts=[tall], output_dir=str(tmp_path))
    assert os.path.exists(path) and os.path.getsize(path) > 2000


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


# ─── _dedup_header: encabezado corrido sin repetir el nombre del eje ───────────
# Regresión del bug real de producción: varios ejes país/sector meten el nombre del
# eje tanto en `title` como en `display_name` → el header lo imprimía dos veces.

def test_dedup_header_monetary_policy_case():
    # Caso real Política Monetaria: el segmento repetido se quita, el país queda.
    from shared.products.render import _dedup_header
    out = _dedup_header("Deep Dive · Política Monetaria",
                        "Política Monetaria · República Dominicana")
    assert out == "SDQ·MIP — Deep Dive · Política Monetaria · República Dominicana"


def test_dedup_header_sector_structure_case():
    # Caso real Estructura Sectorial (el eje va al FINAL del display_name).
    from shared.products.render import _dedup_header
    out = _dedup_header("Deep Dive Estructura Sectorial",
                        "Economía Dominicana · Estructura Sectorial")
    assert out == "SDQ·MIP — Deep Dive Estructura Sectorial · Economía Dominicana"


def test_dedup_header_partial_overlap_untouched():
    # Caso real Turismo: solapamiento PARCIAL ("Turismo" ⊂ "Sector Turismo", no literal
    # como segmento completo) → conservador a propósito, no se toca nada.
    from shared.products.render import _dedup_header
    out = _dedup_header("Deep Dive Turismo", "Sector Turismo · República Dominicana")
    assert out == "SDQ·MIP — Deep Dive Turismo · Sector Turismo · República Dominicana"


def test_dedup_header_no_overlap_identical_to_before():
    # Sin solapamiento (Seguros): comportamiento idéntico al formato anterior.
    from shared.products.render import _dedup_header
    out = _dedup_header("Deep Dive Seguros", "Mercado Asegurador Dominicano")
    assert out == "SDQ·MIP — Deep Dive Seguros · Mercado Asegurador Dominicano"
