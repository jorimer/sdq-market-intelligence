"""Generic PDF text extraction (pdfplumber + Tesseract OCR fallback).

Transversal so any module/service can pull text from a PDF without depending on
another feature module. ``banking_score`` has an equivalent extractor that
predates this; consolidating onto this one is a tracked follow-up.
"""
from shared.pdf.extract import extract_pdf_text, ocr_available

__all__ = ["extract_pdf_text", "ocr_available"]
