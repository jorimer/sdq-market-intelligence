"""Mapeo genérico de estados financieros extraídos → campos de scoring.

Transversal (banca, pensiones): opera sobre la forma que emite el extractor de
estados auditados (``shared.pdf.audited_extractor`` — line items con
``original_text``/``amount_current``/``is_total``/``category``) y produce los
campos numéricos que consumen los índices. Vivía en
``modules/banking_score/external/fiduciaria_pdf_client`` y ``pension_intel`` lo
importaba cruzado (deuda del DD); ahora es servicio compartido. Lo específico de
fideicomisos (``map_trust_fields``) sigue en banca.
"""
from typing import Any, Dict, List, Optional

# ─── Line-item helpers ───────────────────────────────────────────────────

def _num(item: Dict[str, Any], key: str = "amount_current") -> Optional[float]:
    v = item.get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _find_total(items: List[Dict[str, Any]], category: str, *label_keywords: str) -> Optional[float]:
    """Find a grand-total amount: prefer is_total rows of *category* whose
    original_text contains any keyword; else any row matching the keywords."""
    kw = [k.lower() for k in label_keywords]

    def matches(it: Dict[str, Any]) -> bool:
        txt = (it.get("original_text") or "").lower()
        return any(k in txt for k in kw)

    # 1) is_total + right category + keyword
    for it in items:
        if it.get("is_total") and (it.get("category") == category) and matches(it):
            v = _num(it)
            if v is not None:
                return v
    # 2) is_total + keyword (any category)
    for it in items:
        if it.get("is_total") and matches(it):
            v = _num(it)
            if v is not None:
                return v
    # 3) keyword only (last resort)
    for it in items:
        if matches(it):
            v = _num(it)
            if v is not None:
                return v
    return None


def _find_equity_result(items: List[Dict[str, Any]], *label_keywords: str) -> Optional[float]:
    """Find the period result inside the equity section (a non-total equity row
    like 'Resultado del período' under Patrimonio fideicomitido)."""
    kw = [k.lower() for k in label_keywords]
    for it in items:
        if it.get("is_total"):
            continue
        if it.get("category") != "equity":
            continue
        txt = (it.get("original_text") or "").lower()
        if any(k in txt for k in kw):
            v = _num(it)
            if v is not None:
                return v
    return None


def _last_income_total(items: List[Dict[str, Any]]) -> Optional[float]:
    """The bottom line of an income statement — last is_total row whose label looks
    like a result (not 'Total ingresos'/'Total gastos', not zero). Fallback for the
    net result when no explicit result label matched."""
    candidate = None
    for it in items:
        if not it.get("is_total"):
            continue
        txt = (it.get("original_text") or "").lower()
        if "ingreso" in txt or "gasto" in txt:  # skip revenue/expense subtotals
            continue
        v = _num(it)
        if v is not None and v != 0:  # skip nil "otro resultado integral" rows
            candidate = v  # keep the last qualifying non-zero total
    return candidate


def _sum_matching(items: List[Dict[str, Any]], *label_keywords: str) -> Optional[float]:
    """Sum non-total line items whose label contains a keyword (e.g. efectivo +
    inversiones for liquid assets). Returns None if nothing matched."""
    kw = [k.lower() for k in label_keywords]
    total = 0.0
    hit = False
    for it in items:
        if it.get("is_total") or it.get("is_subtotal"):
            continue
        txt = (it.get("original_text") or "").lower()
        if any(k in txt for k in kw):
            v = _num(it)
            if v is not None:
                total += v
                hit = True
    return round(total, 2) if hit else None


def map_entity_fields(statements: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Map an extracted fiduciary-entity statement to BankingData-style fields.
    Missing figures stay ``None`` (N/D — never fabricated)."""
    bg = statements.get("balance_general", [])
    er = statements.get("estado_resultados", [])

    # Singular "total activo"/"total pasivo" are SIB-regulatory labels (e.g. SIPEN's AFP
    # statements). They're substrings of the plural forms, so one keyword covers both.
    activos = _find_total(bg, "assets", "total activos", "total de activos", "total activo")
    pasivos = _find_total(bg, "liabilities", "total pasivos", "total de pasivos", "total pasivo")
    patrimonio = _find_total(
        bg, "equity", "total patrimonio", "patrimonio fideicom", "total de patrimonio",
        "patrimonio neto", "patrimonio de los accionistas", "capital contable", "total capital",
    )
    # Fallback by the accounting identity (Activos = Pasivos + Patrimonio) when the
    # equity total isn't labelled in a way we matched.
    if patrimonio is None and activos is not None and pasivos is not None:
        patrimonio = round(activos - pasivos, 2)
    liquidos = _sum_matching(bg, "efectivo", "equivalentes de efectivo", "inversiones", "depósitos a plazo", "depositos a plazo")
    pasivos_circ = _find_total(bg, "liabilities", "total pasivos circulantes", "total pasivos corrientes")

    ingresos = _find_total(er, "revenue", "total ingresos", "total de ingresos", "total ingresos operacionales")
    gastos_op = _find_total(er, "opex", "total gastos operacionales", "total gastos de operaci", "total gastos", "gastos operacionales")
    if gastos_op is not None:
        gastos_op = abs(gastos_op)  # statements show expenses in () → keep magnitude
    comisiones = _sum_matching(er, "comisiones fiduciarias", "comisiones")
    resultado = _find_total(
        er, "net_income", "resultado neto", "utilidad neta", "ganancia neta",
        "excedente", "resultado del ejercicio", "utilidad del ejercicio", "resultado integral",
        "resultado del período", "resultado del periodo", "resultado del año",
        "utilidad del período", "utilidad del periodo", "ganancia del", "beneficio neto",
    )
    if resultado is None or resultado == 0:
        fallback = _last_income_total(er)  # bottom line of the income statement
        if fallback:
            resultado = fallback

    return {
        "activos_totales": activos,
        "pasivos_exigibles": pasivos,
        "pasivos_cp": pasivos_circ,
        "patrimonio_tecnico": patrimonio,
        "activos_liquidos": liquidos,
        "ingresos_operacionales": ingresos,
        "gastos_operacionales": gastos_op,
        "comisiones_fiduciarias": comisiones,
        "utilidad_neta": resultado,
    }
