"""Tests for the DGA customs connector (chapter-level trade). Offline.

The pure scraping/parsing logic is exercised with synthetic HTML and an in-memory
workbook — no network. The flow-building maps a parsed chapter table to trade
flows in USD millions stamped with the DGA source.
"""
import io

import openpyxl

from shared.data.dga_client import (
    _is_data_cruda,
    _parse_period,
    discover_dc_files,
    parse_chapter_xlsx,
)
from modules.trade_intel.dga_sync import _flows_for


def test_parse_period_from_varied_filenames():
    cases = {
        "exportaciones-por-capítulo-enero-marzo-2026-dc.xlsx": "2026-Q1",
        "exportaciones_por_capitulo_abril_-junio_2023-data-cruda.xlsx": "2023-Q2",
        "importaciones_por_capitulo_julio_septiembre_2024dc.xlsx": "2024-Q3",
        "exportaciones_por_capitulo_octubre_diciembre_2025dc.xlsx": "2025-Q4",
    }
    for name, expected in cases.items():
        assert _parse_period(name.lower()) == expected
    assert _parse_period("brochure-carta-compromiso.pdf") is None


def test_is_data_cruda_distinguishes_raw_from_summary():
    assert _is_data_cruda("exportaciones_por_capitulo_enero_marzo_2025dc.xlsx")
    assert _is_data_cruda("exportaciones_por_capitulo_abril_-junio_2023-data-cruda.xlsx")
    assert _is_data_cruda("exportaciones_por_capitulo_julio_septiembre_2025dc-v2.xlsx")
    assert not _is_data_cruda("exportaciones-por-capítulo-enero-marzo-2026-excel.xlsx")  # summary
    assert not _is_data_cruda("exportaciones_por_capitulo_enero_marzo_2026-dc.pdf")      # pdf


def test_discover_prefers_v2_and_filters_direction():
    html = """
      <a href="/media/aaa111/exportaciones_por_capitulo_julio_septiembre_2025dc.xlsx">x</a>
      <a href="/media/bbb222/exportaciones_por_capitulo_julio_septiembre_2025dc-v2.xlsx">x</a>
      <a href="/media/ccc333/importaciones_por_capitulo_enero_marzo_2025dc.xlsx">x</a>
      <a href="/media/ddd444/exportaciones-por-capítulo-enero-marzo-2026-excel.xlsx">x</a>
    """
    exp = discover_dc_files(html, "export")
    assert set(exp) == {"2025-Q3"}                      # the summary (excel) is excluded
    assert "bbb222" in exp["2025-Q3"]                   # v2 wins over the plain dc
    assert exp["2025-Q3"].startswith("https://www.aduanas.gob.do/media/")
    imp = discover_dc_files(html, "import")
    assert set(imp) == {"2025-Q1"}                      # export files filtered out


def _workbook_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sample_xlsx():
    return _workbook_bytes([
        ("DIRECCIÓN GENERAL DE ADUANAS", None, None),
        ("Exportaciones Según Capítulo", None, None),
        ("Código Capítulo", "Capítulo Descripción", "Valor FOB US$"),
        ("01", "Animales vivos.", 22756.0192),
        ("71", "Perlas finas, piedras preciosas.", 880_000_000.0),
        ("Total", "TOTAL GENERAL", 880_022_756.0),   # total row → skipped
        (None, None, None),
    ])


def test_parse_chapter_xlsx_reads_chapters_and_skips_total():
    rows = parse_chapter_xlsx(_sample_xlsx())
    assert len(rows) == 2                               # total + blank excluded
    assert ("01", "Animales vivos.", 22756.0192) in rows
    assert rows[1][0] == "71"


def test_flows_for_maps_to_millions_with_source():
    flows = _flows_for(_sample_xlsx(), "export", "2026-Q1")
    assert len(flows) == 2
    perlas = next(f for f in flows if f["product"].startswith("Perlas"))
    assert perlas["value"] == 880.0                     # 880_000_000 USD → 880 M
    assert perlas["direction"] == "export"
    assert perlas["period"] == "2026-Q1"
    assert perlas["source"] == "DGA"
    assert perlas["partner"] is None
