"""Extract text from a PDF: pdfplumber for digital/text-layer docs, Tesseract OCR
as a fallback for image-only scans. Self-contained (no module dependencies)."""
from __future__ import annotations

import logging
import shutil
from typing import List

logger = logging.getLogger("sdq.pdf")

# Below this many chars of text layer (scaled by page count, capped) we assume an
# image-only scan and try OCR.
_TEXT_LAYER_MIN_CHARS = 200


def ocr_available() -> bool:
    """True if the Tesseract binary and its Python bindings are importable."""
    if shutil.which("tesseract") is None:
        return False
    try:
        import pdf2image  # noqa: F401
        import pytesseract  # noqa: F401
    except Exception:  # noqa: BLE001 — any import failure means OCR is unavailable
        return False
    return True


def _ocr_pdf_text(file_path: str, language: str = "spa", dpi: int = 300) -> str:  # pragma: no cover - external bins
    """Rasterize each page and OCR it. Best-effort; requires tesseract + poppler."""
    import pdf2image
    import pytesseract

    pages = pdf2image.convert_from_path(file_path, dpi=dpi)
    out: List[str] = []
    for img in pages:
        out.append(pytesseract.image_to_string(img, lang=language))
    return "\n".join(out)


def extract_pdf_text(file_path: str, max_chars: int = 180_000) -> str:  # pragma: no cover - pdfplumber I/O
    """Return the text of a PDF, falling back to OCR for image-only scans.

    Truncates to *max_chars* to stay within an LLM context window.
    """
    import pdfplumber

    parts: List[str] = []
    n_pages = 0
    with pdfplumber.open(file_path) as pdf:
        n_pages = len(pdf.pages)
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt:
                parts.append(txt)
    text = "\n".join(parts)

    if len(text.strip()) < _TEXT_LAYER_MIN_CHARS * max(min(n_pages, 3), 1):
        if ocr_available():
            logger.info("[pdf] sin capa de texto (%d chars/%d pág) → OCR", len(text), n_pages)
            try:
                ocr_text = _ocr_pdf_text(file_path)
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
            except Exception as e:  # noqa: BLE001 — OCR best-effort
                logger.warning("[pdf] OCR falló: %s", e)
        else:
            logger.warning("[pdf] PDF sin texto y OCR no disponible (sin tesseract)")

    if len(text) > max_chars:
        logger.warning("[pdf] texto truncado de %d a %d chars", len(text), max_chars)
        text = text[:max_chars]
    return text
