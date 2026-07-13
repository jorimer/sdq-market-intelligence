"""Audited-statement PDF extractor (AI-powered).

Ported from the proven ingestion pipeline in the sibling repo
``financial-analysis-agent`` (``backend/app/ingestion/audited_statement_extractor.py``)
and adapted to this project's settings/Anthropic client. We keep the battle-tested
prompts and the single-call → JSON-repair → split-call fallback, but drop the NIIF
catalog matching and the heavy pandas/chardet document parser: here we only need the
balance sheet + income statement line items, extracted as structured JSON.

Used by ``fiduciaria_pdf_client`` to read fiduciary and public-trust audited PDFs
(scanned-with-OCR-text-layer or native digital) into figures the scoring needs.

Synchronous by design — the ingestion job runs in a sync (Celery) context.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from shared.config.settings import settings

logger = logging.getLogger(__name__)


# ─── Prompts (ported verbatim — proven on DR audited statements) ──────────

AUDITED_SYSTEM_PROMPT = """You are an expert CPA/CFA financial analyst specializing in audited financial statements from the Dominican Republic and Latin America. You work with NIIF/IFRS standards and regulatory catalogs (Superintendencia de Bancos).

Your task is to extract ALL financial data from audited annual financial statements (and trust/fideicomiso statements). These typically include:
1. Balance General / Estado de Situacion Financiera (Balance Sheet)
2. Estado de Resultados / Estado de Resultados Integrales (Income Statement)
3. Estado de Flujos de Efectivo (Cash Flow Statement)
4. Estado de Cambios en el Patrimonio (Statement of Changes in Equity)

You MUST:
- Extract EVERY line item with its exact amount
- Preserve the original account names exactly as written
- Identify both current period and prior period amounts when present
- Detect the entity name, reporting period, and currency
- Classify each account into its correct financial statement
- Maintain the hierarchical structure (parent accounts, subtotals, totals)
- For a trust (fideicomiso), "Patrimonio fideicomitido" is the equity section.

CRITICAL — Balance Sheet vs Cash Flow disambiguation:
Lines starting with "(Aumento)", "(Disminución)", "Aumento", "Disminución" → belong
to flujo_efectivo (these are CHANGES, not balances). Lines like "Efectivo al inicio/
final del ejercicio" → flujo_efectivo, NOT balance_general. When uncertain, prefer CF
if the label contains a change-keyword.

Return ONLY valid JSON. No explanatory text before or after the JSON object."""

EXTRACT_ALL_STATEMENTS_PROMPT = """Analyze the following text extracted from an audited annual financial statement PDF and extract ALL financial data.

TEXT FROM PDF:
{extracted_text}

Extract and return a JSON object with this EXACT structure:
{{
  "company_info": {{
    "name": "Entity/trust name as found in the document",
    "period_end": "YYYY-MM-DD (end date of the reporting period)",
    "prior_period_end": "YYYY-MM-DD (prior period end date, if comparative) or null",
    "currency": "DOP|USD|EUR",
    "currency_unit": "units|thousands|millions"
  }},
  "balance_general": [
    {{
      "original_text": "Exact account name from document",
      "category": "assets|liabilities|equity",
      "subcategory": "current_assets|non_current_assets|current_liabilities|non_current_liabilities|equity",
      "amount_current": 1234567.89,
      "amount_prior": 1100000.00,
      "is_total": false,
      "is_subtotal": false
    }}
  ],
  "estado_resultados": [
    {{
      "original_text": "Exact account name",
      "category": "revenue|cogs|opex|other_income|other_expense|tax|net_income",
      "amount_current": 500000.00,
      "amount_prior": 450000.00,
      "is_total": false,
      "is_subtotal": false
    }}
  ]
}}

IMPORTANT RULES:
- Use null for amounts that are not present or cannot be determined
- Negative amounts as negative numbers; amounts in parentheses () = negative
- Include ALL line items, even subtotals and totals (mark them with is_total/is_subtotal)
- Mark the grand totals: "Total activos" (is_total, assets), "Total pasivos"
  (is_total, liabilities), "Total patrimonio"/"Total patrimonio fideicomitido"
  (is_total, equity), "Total ingresos" (is_total, revenue), and the net result
  (category net_income, is_total)
- If amounts are in thousands/millions, note it in currency_unit but keep values as shown"""

EXTRACT_PHASE1_PROMPT = """Analyze the following text from an audited financial statement PDF.
Extract ONLY the company_info and the Balance General (Balance Sheet / Estado de situación financiera).

TEXT FROM PDF:
{extracted_text}

Return a JSON object: {{"company_info": {{"name": "...", "period_end": "YYYY-MM-DD", "prior_period_end": "YYYY-MM-DD or null", "currency": "DOP", "currency_unit": "units"}}, "balance_general": [{{"original_text": "...", "category": "assets|liabilities|equity", "subcategory": "...", "amount_current": 0, "amount_prior": 0, "is_total": false, "is_subtotal": false}}]}}

Rules: null for missing amounts; () = negative; include ALL line items including the grand totals (Total activos / Total pasivos / Total patrimonio)."""

EXTRACT_PHASE2_PROMPT = """Analyze the following text from an audited financial statement PDF.
Extract ONLY the Estado de Resultados (Income Statement).

TEXT FROM PDF:
{extracted_text}

Return a JSON object: {{"estado_resultados": [{{"original_text": "...", "category": "revenue|cogs|opex|other_income|other_expense|tax|net_income", "amount_current": 0, "amount_prior": 0, "is_total": false, "is_subtotal": false}}]}}

Rules: null for missing amounts; () = negative; include ALL line items including Total ingresos, Total gastos operacionales and the net result."""

# Vision path: the attached page images ARE the statement (scanned/image-only PDF).
# Same JSON contract as the text prompt; Claude reads the figures directly from the
# images (far more reliable on scanned tables than Tesseract OCR text).
VISION_EXTRACT_PROMPT = """The attached images are the scanned pages of an audited financial statement (balance general + estado de resultados). Read the figures directly from the images and extract ALL financial data.

Return ONLY a JSON object with this EXACT structure:
{
  "company_info": {"name": "Entity/trust name as shown", "period_end": "YYYY-MM-DD", "prior_period_end": "YYYY-MM-DD or null", "currency": "DOP|USD|EUR", "currency_unit": "units|thousands|millions"},
  "balance_general": [{"original_text": "Exact account name", "category": "assets|liabilities|equity", "subcategory": "current_assets|non_current_assets|current_liabilities|non_current_liabilities|equity", "amount_current": 0, "amount_prior": 0, "is_total": false, "is_subtotal": false}],
  "estado_resultados": [{"original_text": "Exact account name", "category": "revenue|cogs|opex|other_income|other_expense|tax|net_income", "amount_current": 0, "amount_prior": 0, "is_total": false, "is_subtotal": false}]
}

IMPORTANT RULES:
- Read numbers carefully from the scan; amounts in parentheses () are negative; null when a value is absent.
- Include ALL line items, and ALWAYS mark the grand totals: "Total activos"/"Total de activos" (is_total, assets), "Total pasivos" (is_total, liabilities), "Total patrimonio" (is_total, equity), and the net result (category net_income, is_total). The grand totals are the most important — do not omit Total activos.
- If amounts are in thousands/millions, set currency_unit accordingly but keep values exactly as shown.
- Return ONLY the JSON object, no prose."""


# Below this many extracted chars/page the PDF is treated as an image-only scan.
_TEXT_LAYER_MIN_CHARS = 200
# Vision rendering caps: enough pages to cover the core statements, downscaled to
# Anthropic's optimal long edge to keep the payload/token cost in check.
MAX_VISION_PAGES = 20
_VISION_MAX_EDGE = 1568


def _pdfplumber_text(file_path: str) -> Tuple[str, int]:  # pragma: no cover - pdfplumber I/O
    """Raw pdfplumber text + page count (no OCR). Shared by the digital-text check."""
    import pdfplumber

    parts: List[str] = []
    with pdfplumber.open(file_path) as pdf:
        n_pages = len(pdf.pages)
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt:
                parts.append(txt)
    return "\n".join(parts), n_pages


def _has_text_layer(text: str, n_pages: int) -> bool:
    """A digital / OCR-text-layer PDF clears a per-page char floor; below it = image scan."""
    return len(text.strip()) >= _TEXT_LAYER_MIN_CHARS * max(min(n_pages, 3), 1)


def pdf_render_available() -> bool:
    """True if PDF→image rendering (pdf2image + poppler) is available for the vision path."""
    try:
        import pdf2image  # noqa: F401
    except ImportError:
        return False
    return True


def render_pdf_images(file_path: str, max_pages: int = MAX_VISION_PAGES,
                      dpi: int = 150) -> List[str]:  # pragma: no cover - poppler/PIL I/O
    """Render the first pages of a PDF to base64 PNGs, downscaled to Anthropic's optimal
    long edge — the input to the Claude-vision extraction path for scanned statements."""
    import base64
    import io

    from pdf2image import convert_from_path

    images = convert_from_path(file_path, dpi=dpi, fmt="png", first_page=1, last_page=max_pages)
    out: List[str] = []
    for im in images:
        w, h = im.size
        scale = min(1.0, _VISION_MAX_EDGE / max(w, h))
        if scale < 1.0:
            im = im.resize((max(int(w * scale), 1), max(int(h * scale), 1)))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        out.append(base64.standard_b64encode(buf.getvalue()).decode())
    return out


def extract_pdf_text(file_path: str, max_chars: int = 180_000) -> str:  # pragma: no cover - pdfplumber I/O
    """Extract text from a PDF. Tries pdfplumber (digital / OCR-text-layer scans);
    if the result is too sparse (image-only scan), falls back to Tesseract OCR.
    Truncates very long docs to stay within Claude's context window."""
    text, n_pages = _pdfplumber_text(file_path)

    # Image-only scan (no text layer) → OCR fallback.
    if not _has_text_layer(text, n_pages):
        from shared.pdf.ocr import ocr_available, ocr_pdf_text

        if ocr_available():
            logger.info("[AuditedPdf] PDF sin capa de texto (%d chars/%d pág) → OCR", len(text), n_pages)
            try:
                ocr_text = ocr_pdf_text(file_path)
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
            except Exception as e:  # noqa: BLE001 — OCR best-effort; keep whatever pdfplumber got
                logger.warning("[AuditedPdf] OCR falló: %s", e)
        else:
            logger.warning("[AuditedPdf] PDF sin texto y OCR no disponible (sin tesseract)")

    if len(text) > max_chars:
        logger.warning("[AuditedPdf] texto truncado de %d a %d chars", len(text), max_chars)
        text = text[:max_chars]
    return text


class AuditedPdfExtractor:
    """Extract structured balance sheet + income statement from an audited PDF.

    Two-phase strategy: one high-token call for both statements; on truncation,
    repair the JSON, then fall back to two focused calls.
    """

    MAX_TOKENS_SINGLE = 16384
    MAX_TOKENS_SPLIT = 8192

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError(
                "Se requiere ANTHROPIC_API_KEY para extraer estados de PDF con IA."
            )
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model or settings.ANTHROPIC_MODEL

    # ─── Public API ──────────────────────────────────────────────

    def extract_statements(self, file_path: str) -> Dict[str, Any]:  # pragma: no cover - I/O + AI
        """Return {company_info, balance_general[], estado_resultados[]} for a PDF.

        Digital / OCR-text-layer PDFs → the proven text path. Image-only scans (e.g.
        SIPEN's AFP statements, some SIB fiduciary PDFs) → OCR→Claude, which reads the
        regulatory grand totals reliably (the missing figures were a label-mapping bug,
        not OCR quality — see fiduciaria_pdf_client). Claude VISION on the page images is
        kept only as a fallback for the rare scan too poor for OCR (no image-token cost
        on the common path)."""
        text, n_pages = _pdfplumber_text(file_path)
        if _has_text_layer(text, n_pages):
            return self._extract_with_fallback(text[:180_000])

        # Scanned: OCR→Claude is the default (cheap; reads the totals fine).
        ocr_text = extract_pdf_text(file_path)
        if ocr_text and len(ocr_text.strip()) >= 400:
            return self._extract_with_fallback(ocr_text)

        # Vision fallback only when OCR yields too little to parse.
        if pdf_render_available():
            try:
                images = render_pdf_images(file_path)
                if images:
                    logger.info("[AuditedPdf] OCR pobre (%d chars) → visión Claude (%d imgs)",
                                len(ocr_text or ""), len(images))
                    return self._extract_from_images(images)
            except Exception as e:  # noqa: BLE001 — keep whatever OCR we have
                logger.warning("[AuditedPdf] visión de respaldo falló: %s", e)

        if ocr_text and len(ocr_text.strip()) >= 100:
            return self._extract_with_fallback(ocr_text)
        raise ValueError(
            "No se pudo extraer texto suficiente del PDF (puede estar vacío, dañado o protegido)."
        )

    def _extract_from_images(self, images_b64: List[str]) -> Dict[str, Any]:  # pragma: no cover - network
        """Claude-vision extraction: send the page images + the JSON contract, parse/repair."""
        blocks: List[Dict[str, Any]] = [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": b64}}
            for b64 in images_b64
        ]
        blocks.append({"type": "text", "text": VISION_EXTRACT_PROMPT})
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.MAX_TOKENS_SINGLE,
                temperature=0.1,
                system=AUDITED_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": blocks}],
            )
        except self._anthropic.APIError as e:
            raise RuntimeError(f"Error de la API de Claude (visión): {e}") from e
        text = response.content[0].text
        if response.stop_reason == "end_turn":
            return self._parse_json_response(text)
        logger.warning("[AuditedPdf] visión truncada (stop=%s), reparando JSON…", response.stop_reason)
        repaired = self._repair_truncated_json(text)
        if repaired and (repaired.get("balance_general") or repaired.get("estado_resultados")):
            return repaired
        return self._parse_json_response(text)

    # ─── Extraction with fallback ────────────────────────────────

    def _extract_with_fallback(self, text: str) -> Dict[str, Any]:  # pragma: no cover - AI calls
        try:
            resp, stop = self._call_claude(
                AUDITED_SYSTEM_PROMPT,
                EXTRACT_ALL_STATEMENTS_PROMPT.format(extracted_text=text),
                max_tokens=self.MAX_TOKENS_SINGLE,
            )
            if stop == "end_turn":
                return self._parse_json_response(resp)
            logger.warning("[AuditedPdf] respuesta truncada (stop=%s), reparando JSON…", stop)
            repaired = self._repair_truncated_json(resp)
            if repaired and repaired.get("balance_general") and repaired.get("estado_resultados"):
                return repaired
        except Exception as e:  # noqa: BLE001 — fall through to split strategy
            logger.warning("[AuditedPdf] extracción de una llamada falló: %s", e)

        # Split into two focused calls
        logger.info("[AuditedPdf] fase 2: extracción dividida (2 llamadas)")
        resp1, _ = self._call_claude(
            AUDITED_SYSTEM_PROMPT,
            EXTRACT_PHASE1_PROMPT.format(extracted_text=text),
            max_tokens=self.MAX_TOKENS_SPLIT,
        )
        parsed1 = self._parse_json_response(resp1)
        resp2, _ = self._call_claude(
            AUDITED_SYSTEM_PROMPT,
            EXTRACT_PHASE2_PROMPT.format(extracted_text=text),
            max_tokens=self.MAX_TOKENS_SPLIT,
        )
        parsed2 = self._parse_json_response(resp2)
        return {
            "company_info": parsed1.get("company_info", {}),
            "balance_general": parsed1.get("balance_general", []),
            "estado_resultados": parsed2.get("estado_resultados", []),
        }

    def _call_claude(self, system_prompt: str, user_prompt: str, max_tokens: int) -> Tuple[str, str]:  # pragma: no cover - network
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0.1,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = response.content[0].text
            return text, response.stop_reason
        except self._anthropic.APIError as e:
            raise RuntimeError(f"Error de la API de Claude: {e}") from e

    # ─── JSON parsing / repair (ported) ──────────────────────────

    @staticmethod
    def _parse_json_response(response_text: str) -> Dict[str, Any]:
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass
        code_block = re.search(r"```(?:json)?\s*\n(.*?)```", response_text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass
        start, end = response_text.find("{"), response_text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(response_text[start:end])
            except json.JSONDecodeError:
                pass
        raise ValueError(
            f"No se pudo parsear JSON de la respuesta de Claude ({len(response_text)} chars)."
        )

    @staticmethod
    def _repair_truncated_json(text: str) -> Optional[Dict[str, Any]]:
        """Repair JSON truncated mid-stream: cut the incomplete tail, close brackets."""
        start = text.find("{")
        if start == -1:
            return None
        json_text = text[start:]
        # Drop a final line that ends inside an unterminated string
        lines = json_text.split("\n")
        good: List[str] = []
        for line in lines:
            stripped = line.rstrip().rstrip(",")
            good.append(line)
            if stripped.count('"') % 2 != 0:
                good.pop()
                break
        json_text = "\n".join(good)
        for trim in (0, 50, 100, 200, 500, 1000, 2000):
            candidate = json_text if trim == 0 else json_text[:-trim]
            if not candidate.strip():
                continue
            # don't end mid-string
            in_str = False
            esc = False
            for ch in candidate:
                if esc:
                    esc = False
                    continue
                if ch == "\\":
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
            if in_str:
                lq = candidate.rfind('"')
                if lq > 0:
                    candidate = candidate[: lq + 1]
            candidate = candidate.rstrip().rstrip(",")
            candidate += "]" * max(candidate.count("[") - candidate.count("]"), 0)
            candidate += "}" * max(candidate.count("{") - candidate.count("}"), 0)
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue
        return None
