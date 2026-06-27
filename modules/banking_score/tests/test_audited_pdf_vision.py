"""Path selection in AuditedPdfExtractor: digital PDFs → text, scanned → Claude vision.

No network/Claude: the pdfplumber/render helpers and the two extraction methods are
stubbed, so we assert ONLY which path a PDF takes (the routing logic), plus the pure
text-layer threshold. The vision path was added because Tesseract OCR mangled the
"Total activos" line on SIPEN's scanned AFP statements.
"""
import pytest

from modules.banking_score.external import audited_pdf_extractor as ape


def _extractor():
    # api_key bypasses the env requirement; the Anthropic client is never called here.
    return ape.AuditedPdfExtractor(api_key="test-key")


def test_has_text_layer_threshold():
    # Floor is 200 chars/page (capped at 3 pages) → 600 for a multi-page PDF.
    assert ape._has_text_layer("x" * 700, 6) is True
    assert ape._has_text_layer("x" * 100, 6) is False
    assert ape._has_text_layer("", 6) is False


def test_scanned_pdf_routes_to_vision(monkeypatch):
    ex = _extractor()
    monkeypatch.setattr(ape, "_pdfplumber_text", lambda p: ("", 6))      # no text layer → scan
    monkeypatch.setattr(ape, "pdf_render_available", lambda: True)
    monkeypatch.setattr(ape, "render_pdf_images", lambda p, **k: ["imgA", "imgB"])
    seen = {}

    def fake_vision(imgs):
        seen["vision"] = imgs
        return {"via": "vision"}

    monkeypatch.setattr(ex, "_extract_from_images", fake_vision)
    monkeypatch.setattr(ex, "_extract_with_fallback",
                        lambda t: {"via": "text"})  # must NOT be called
    out = ex.extract_statements("scan.pdf")
    assert out == {"via": "vision"}
    assert seen["vision"] == ["imgA", "imgB"]


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


def test_scanned_pdf_falls_back_to_ocr_when_render_unavailable(monkeypatch):
    ex = _extractor()
    monkeypatch.setattr(ape, "_pdfplumber_text", lambda p: ("", 6))
    monkeypatch.setattr(ape, "pdf_render_available", lambda: False)        # no poppler
    monkeypatch.setattr(ape, "extract_pdf_text", lambda p: "OCR text " * 50)
    monkeypatch.setattr(ex, "_extract_with_fallback", lambda t: {"via": "ocr-text"})
    out = ex.extract_statements("scan.pdf")
    assert out == {"via": "ocr-text"}
