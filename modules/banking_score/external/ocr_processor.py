"""OCR fallback for image-only scanned PDFs.

Ported/trimmed from the proven ``financial-analysis-agent`` ingestion OCRProcessor.
Some fiduciary audited PDFs on the SIB portal are image-only scans WITHOUT an OCR
text layer, so ``pdfplumber`` returns little/no text. For those we render each page
to an image (pdf2image → poppler) and run Tesseract (Spanish). Heavy deps are
lazy-loaded; missing binary/lib raises a clear error.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

MAX_OCR_PAGES = 40


def _tesseract_path() -> Optional[str]:
    path = shutil.which("tesseract")
    if path:
        return path
    for candidate in ("/usr/bin/tesseract", "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def ocr_available() -> bool:
    """True if tesseract + pytesseract + pdf2image are all available."""
    if _tesseract_path() is None:
        return False
    try:
        import pdf2image  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_pdf_text(file_path: str, language: str = "spa", dpi: int = 300) -> str:  # pragma: no cover - external bins
    """Render the PDF to images and OCR them; return the concatenated text.

    Raises RuntimeError if tesseract is unavailable or rendering/OCR fails.
    """
    tess = _tesseract_path()
    if not tess:
        raise RuntimeError(
            "Tesseract no está instalado (apt-get install tesseract-ocr tesseract-ocr-spa)."
        )
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as e:
        raise RuntimeError(f"Faltan dependencias de OCR: {e}") from e

    pytesseract.pytesseract.tesseract_cmd = tess
    logger.info("[OCR] extrayendo por OCR: %s (lang=%s)", os.path.basename(file_path), language)

    parts: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        images = convert_from_path(
            file_path, dpi=dpi, output_folder=tmp, fmt="png",
            first_page=1, last_page=MAX_OCR_PAGES,
        )
        for img in images:
            parts.append((pytesseract.image_to_string(img, lang=language) or "").strip())
    text = "\n".join(p for p in parts if p)
    logger.info("[OCR] %d páginas, %d chars", len(parts), len(text))
    return text
