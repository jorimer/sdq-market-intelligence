"""Early-fragility signals (Eje 2).

Doctrine (§4): an event/threshold is a *signal, not a prediction*.  Two canonical
early-warning reads:

  * **Reinhart-Rogoff** — public-debt/GDP thresholds (debt overhang).
  * **Calvo sudden stop** — a sharp contraction in external flows
    (remittances, FDI, reserves, capital flows).

Pure functions returning structured signals with a severity and the evidence
that triggered them, so every signal is traceable.
"""
from typing import Dict, List, Optional

# Reinhart-Rogoff debt thresholds (public debt / GDP, %).
DEBT_MODERATE = 60.0
DEBT_HIGH = 90.0

# Calvo sudden-stop: period-over-period % contraction in a flow series.
SUDDEN_STOP_PCT = -15.0


def debt_overhang_signal(public_debt_gdp: Optional[float]) -> Optional[Dict]:
    """Reinhart-Rogoff debt signal from the latest public-debt/GDP ratio."""
    if public_debt_gdp is None:
        return None
    if public_debt_gdp >= DEBT_HIGH:
        severity = "alto"
    elif public_debt_gdp >= DEBT_MODERATE:
        severity = "elevado"
    else:
        severity = "bajo"
    return {
        "signal": "debt_overhang",
        "framework": "Reinhart-Rogoff",
        "severity": severity,
        "value": round(public_debt_gdp, 2),
        "thresholds": {"moderate": DEBT_MODERATE, "high": DEBT_HIGH},
    }


def sudden_stop_signal(
    flow_key: str,
    pct_change: Optional[float],
    meta: Optional[Dict[str, str]] = None,
) -> Optional[Dict]:
    """Calvo sudden-stop signal: fire when an external flow contracts sharply YoY.

    *pct_change* es la variación INTERANUAL del flujo, ya sign-correcta (el productor la
    construye como cociente, así que "contracción" es siempre negativa incluso para las
    series negativas del MBP6). Por eso la regla es directa —``pct ≤ −15%``— y no necesita
    volver a razonar el signo aquí. *meta* trae la serie canónica y la etiqueta del flujo
    para que la señal sea citable.
    """
    if pct_change is None:
        return None
    if pct_change > SUDDEN_STOP_PCT:
        return None  # no sharp contraction → no signal
    meta = meta or {}
    label = meta.get("label") or flow_key
    series_code = meta.get("series_code")
    return {
        "signal": "sudden_stop",
        "framework": "Calvo",
        "severity": "alto" if pct_change <= 2 * SUDDEN_STOP_PCT else "elevado",
        "series": flow_key,
        "series_code": series_code,
        "label": label,
        "pct_change": round(pct_change, 2),
        "threshold": SUDDEN_STOP_PCT,
        "basis": "yoy",  # variación interanual, agnóstica de cadencia
        "detail": (f"{label} cae {round(pct_change, 2)}% interanual "
                   f"(umbral {SUDDEN_STOP_PCT:.0f}%)"),
    }


def detect_signals(
    debt_gdp: Optional[float],
    flow_pct_changes: Dict[str, float],
    flow_meta: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict]:
    """Collect all fired signals from the latest macro reads.

    Args:
        debt_gdp: latest public-debt/GDP ratio (for the debt-overhang signal).
        flow_pct_changes: ``{flow_key: yoy_pct}`` para los flujos externos del panel
            (remesas, FDI, reservas, exportaciones, capital) — YoY ya computado y
            sign-correcto; el productor ya descartó los flujos sin YoY, así que aquí
            no hay ``None``.
        flow_meta: ``{flow_key: {series_code, label}}`` para citar cada flujo.
    """
    flow_meta = flow_meta or {}
    signals: List[Dict] = []
    debt = debt_overhang_signal(debt_gdp)
    # Only surface the debt signal when it is actually elevated/high.
    if debt and debt["severity"] != "bajo":
        signals.append(debt)
    for key, pct in flow_pct_changes.items():
        sig = sudden_stop_signal(key, pct, flow_meta.get(key))
        if sig:
            signals.append(sig)
    return signals
