"""Path selection in AuditedPdfExtractor: digital PDFs → text, scanned → Claude vision.

No network/Claude: the pdfplumber/render helpers and the two extraction methods are
stubbed, so we assert ONLY which path a PDF takes (the routing logic), plus the pure
text-layer threshold. The vision path was added because Tesseract OCR mangled the
"Total activos" line on SIPEN's scanned AFP statements.
"""
import pytest

from shared.pdf import audited_extractor as ape


def _extractor():
    # api_key bypasses the env requirement; the Anthropic client is never called here.
    return ape.AuditedPdfExtractor(api_key="test-key")


def test_has_text_layer_threshold():
    # Floor is 200 chars/page (capped at 3 pages) → 600 for a multi-page PDF.
    assert ape._has_text_layer("x" * 700, 6) is True
    assert ape._has_text_layer("x" * 100, 6) is False
    assert ape._has_text_layer("", 6) is False


def test_scanned_pdf_uses_ocr_by_default(monkeypatch):
    # Scanned PDF with usable OCR → OCR→Claude (the cheap default); vision NOT used.
    ex = _extractor()
    monkeypatch.setattr(ape, "_pdfplumber_text", lambda p: ("", 6))      # no text layer → scan
    monkeypatch.setattr(ape, "extract_pdf_text", lambda p: "TOTAL ACTIVO ... " * 50)  # good OCR
    rendered = {}
    monkeypatch.setattr(ape, "render_pdf_images",
                        lambda *a, **k: rendered.setdefault("rendered", True))  # must NOT render
    monkeypatch.setattr(ex, "_extract_with_fallback", lambda t: {"via": "ocr-text"})
    out = ex.extract_statements("scan.pdf")
    assert out == {"via": "ocr-text"}
    assert "rendered" not in rendered  # vision was never invoked


def test_digital_pdf_routes_to_text(monkeypatch):
    ex = _extractor()
    monkeypatch.setattr(ape, "_pdfplumber_text", lambda p: ("y" * 800, 6))  # rich text layer
    called = {}
    monkeypatch.setattr(ape, "render_pdf_images",
                        lambda *a, **k: called.setdefault("rendered", True))  # must NOT render
    monkeypatch.setattr(ex, "_extract_with_fallback", lambda t: {"via": "text"})
    out = ex.extract_statements("digital.pdf")
    assert out == {"via": "text"}
    assert "rendered" not in called


def test_map_entity_fields_matches_singular_total_activo():
    """SIPEN's AFP balance labels the grand totals 'TOTAL ACTIVO'/'TOTAL PASIVO' (singular).
    The mapper must catch them — and must NOT grab the off-balance managed-fund assets."""
    from modules.banking_score.external.fiduciaria_pdf_client import map_entity_fields

    statements = {
        "balance_general": [
            {"original_text": "TOTAL ACTIVO", "category": "assets",
             "amount_current": 8_572_098_109, "is_total": True},
            # The managed fund (RD$439B, off-balance) — must be ignored, not taken as "assets".
            {"original_text": "Activos de los Fondos Administrados", "category": "assets",
             "amount_current": 439_020_658_625, "is_total": False},
            {"original_text": "TOTAL PASIVO", "category": "liabilities",
             "amount_current": 1_341_276_481, "is_total": True},
            {"original_text": "TOTAL PATRIMONIO", "category": "equity",
             "amount_current": 7_230_821_628, "is_total": True},
        ],
        "estado_resultados": [],
    }
    f = map_entity_fields(statements)
    assert f["activos_totales"] == 8_572_098_109  # singular label matched; fund row ignored
    assert f["pasivos_exigibles"] == 1_341_276_481
    assert f["patrimonio_tecnico"] == 7_230_821_628


def test_poor_ocr_falls_back_to_vision(monkeypatch):
    # Scan whose OCR is too sparse to parse → vision fallback kicks in.
    ex = _extractor()
    monkeypatch.setattr(ape, "_pdfplumber_text", lambda p: ("", 6))
    monkeypatch.setattr(ape, "extract_pdf_text", lambda p: "  ")          # near-empty OCR
    monkeypatch.setattr(ape, "pdf_render_available", lambda: True)
    monkeypatch.setattr(ape, "render_pdf_images", lambda p, **k: ["imgA"])
    monkeypatch.setattr(ex, "_extract_from_images", lambda imgs: {"via": "vision"})
    out = ex.extract_statements("bad-scan.pdf")
    assert out == {"via": "vision"}
