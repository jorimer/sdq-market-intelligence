"""AFP estados financieros → structured figures, reusing the SIB machinery.

Doctrine: don't reinvent. The banking module already has an AI-native audited-PDF
extractor (``AuditedPdfExtractor``) and a statement-field mapper (``map_entity_fields``)
built for the SIB supervised portal. AFP financial statements have the same shape
(balance general + estado de resultados), so we feed them through the SAME extractor:

  * PDF  → ``AuditedPdfExtractor.extract_statements`` (pdfplumber/OCR → Claude → JSON).
  * XLSX → workbook flattened to text → the same extractor's text path.

The extractor interprets the REAL document at runtime (it does not hardcode a layout),
so this works on the first real file without us having to guess its structure.
Missing figures stay ``None`` — never fabricated.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
from typing import Any, Dict, Optional

logger = logging.getLogger("sdq.pension_intel.financials")


def _xlsx_to_text(content: bytes) -> str:
    """Flatten an XLSX workbook to a plain-text rendering for the AI extractor."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    lines: list[str] = []
    try:
        for ws in wb.worksheets:
            lines.append(f"### Hoja: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append(" | ".join(cells))
    finally:
        wb.close()
    return "\n".join(lines)


def extract_financials(content: bytes, filename: str) -> Dict[str, Any]:
    """PDF or XLSX bytes → the extractor's statements dict (company_info + statements).

    Reuses ``modules.banking_score.external.audited_pdf_extractor`` (lazy import so the
    heavy deps load only when an extraction actually runs).
    """
    from modules.banking_score.external.audited_pdf_extractor import AuditedPdfExtractor

    name = (filename or "").lower()
    extractor = AuditedPdfExtractor()
    if name.endswith(".pdf"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(content)
            path = fh.name
        try:
            return extractor.extract_statements(path)
        finally:
            if os.path.exists(path):
                os.remove(path)
    if name.endswith((".xlsx", ".xls")):
        return extractor._extract_with_fallback(_xlsx_to_text(content))  # noqa: SLF001 — documented text path
    raise ValueError("Formato no soportado: sube un PDF o XLSX de estados financieros.")


def _managed_funds(statements: Dict[str, Any]) -> Optional[float]:
    """AUM = 'Activos de los Fondos Administrados' (the AFP's scale), an off-balance line
    in its own statement. Take the ASSETS-side positive amount, never the same-amount
    contra-account (liabilities/equity). The label varies across AFPs ('… Nota 11',
    'CUENTA DE ORDEN (DEBE) - Activos de los Fondos Administrados') but always contains
    'fondos administrad'. Multiple asset matches → the largest (the grand line)."""
    best: Optional[float] = None
    for r in statements.get("balance_general") or []:
        txt = str(r.get("original_text", "")).lower()
        if "fondos administrad" in txt and r.get("category") == "assets":
            v = r.get("amount_current")
            if isinstance(v, (int, float)) and v > 0:
                best = v if best is None else max(best, v)
    return best


def map_afp_financials(statements: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Extracted statements → AFP balance-sheet figures, reusing banking's field mapper.

    ``map_entity_fields`` pulls Total activos / Total pasivos / Total patrimonio (with the
    accounting-identity fallback) and the net result — the ISA solvency dimension. We also
    pull the administered-funds total (AUM) for the ISA's scale/cost dimensions.
    """
    from modules.banking_score.external.fiduciaria_pdf_client import map_entity_fields

    f = map_entity_fields(statements)
    return {
        "patrimonio": f.get("patrimonio_tecnico"),
        "activos_totales": f.get("activos_totales"),
        "pasivos_totales": f.get("pasivos_exigibles"),
        "resultado": f.get("utilidad_neta"),
        "fondos_administrados": _managed_funds(statements),
    }


def statement_period(statements: Dict[str, Any]) -> Optional[str]:
    """Period label ("YYYY-MM") from the extracted company_info.period_end, or None."""
    ci = statements.get("company_info") or {}
    end = ci.get("period_end")
    if isinstance(end, str) and len(end) >= 7 and end[:4].isdigit():
        return end[:7]
    return None
