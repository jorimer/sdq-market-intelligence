"""Trade-resilience backtest report — discrimination on a regional panel, honest.

Assembles the historical resilience panel (24-country LatAm+Caribbean peer set),
two realized-shock outcomes, Gini/AR with a bootstrap CI, and the realized-shock
rate per resilience band. Convention: LOWER resilience = riskier, so a good index
shows the shock rate RISING from "Fuerte" to "Débil".

PRIMARY = export-earnings collapse — the construct the resilience index actually
targets (concentration → vulnerability to export shocks), the way the IRMP leads
with the instability it targets. Same Comtrade source as the index, but NOT
circular: the index reads trade STRUCTURE at T (concentration shares + import
dependency); the outcome is a future LEVEL shock (≥10% earnings drop at T+1/T+2).

SECONDARY (contrast) = external macro shock (WDI current account / reserves /
recession) — fully independent of the index. The panel shows the index does NOT
discriminate it: broad macro distress is dominated by COMMON global shocks (2009,
2015, 2020), not by a country's trade structure. We report that honestly — it
bounds the claim, it doesn't hide a failure.

The product stays RD-only; this peer panel is validation-only (statistical power).
"""
from typing import Dict, List, Optional

from modules.trade_intel.validation.historical import (
    BAND_ORDER,
    build_panel,
    exports_by_year,
)
from modules.trade_intel.validation.outcomes import (
    label_panel_export,
    label_panel_external,
)
from modules.trade_intel.validation.peers import VALIDATION_PEERS
from shared.data import comtrade_client as cc
from shared.validation.control_tamano import medir_control_de_tamano
from shared.validation.metrics import (
    deterioration_rate_by_tier,
    gini_bootstrap_ci,
)


def _metrics_for(labeled: List[Dict]) -> Dict:
    """Gini (+ bootstrap CI), shock-rate-by-band and counts for a labeled panel."""
    scores = [r["resilience_score"] for r in labeled]
    labels = [r["label"] for r in labeled]
    bands = [r["band"] for r in labeled]
    g, lo, hi = gini_bootstrap_ci(scores, labels)
    rows, monotonic = deterioration_rate_by_tier(bands, labels, BAND_ORDER)
    n_events = sum(labels)
    years = sorted({r["year"] for r in labeled})
    return {
        "n_observations": len(labeled),
        "n_events": n_events,
        "event_rate": round(n_events / len(labeled), 3) if labeled else None,
        "years": [years[0], years[-1]] if years else None,
        "gini": None if g is None else round(g, 3),
        "gini_ci": [None if lo is None else round(lo, 3),
                    None if hi is None else round(hi, 3)],
        "distress_by_band": rows,
        "monotonic": monotonic,
    }


def _control(labeled: List[Dict], gini_del_score: Optional[float]) -> Dict:
    """El mismo panel etiquetado, ordenado solo por el tamaño exportador del país."""
    return medir_control_de_tamano(
        [r.get("total_exports") for r in labeled], [r["label"] for r in labeled],
        gini_del_score, variable="total_exports",
        nota_extra="valor total exportado del país en el año base (Comtrade)")


def build_backtest_report(dataset: Optional[Dict] = None) -> Dict:
    """Run the trade-resilience backtest from the committed Comtrade+WDI panel."""
    if dataset is None:
        dataset = cc.load_panel()
    panel = build_panel(dataset)
    wdi = (dataset or {}).get("wdi", {})

    etiquetado_export = label_panel_export(panel, exports_by_year(panel))
    etiquetado_macro = label_panel_external(panel, wdi)
    export_collapse = _metrics_for(etiquetado_export)
    external_macro = _metrics_for(etiquetado_macro)
    # CONTROL POR TAMAÑO, dentro de cada bloque. El desenlace primario es una caída
    # PORCENTUAL de exportaciones, y el país chico tiene más varianza porcentual por
    # construcción: sin medir qué hace el tamaño solo, «el índice ordena el colapso» y «los
    # chicos colapsan más seguido» son indistinguibles.
    export_collapse["control_solo_tamano"] = _control(etiquetado_export,
                                                      export_collapse.get("gini"))
    external_macro["control_solo_tamano"] = _control(etiquetado_macro,
                                                     external_macro.get("gini"))

    panel_countries = sorted({r["iso"] for r in panel})
    meta = (dataset or {}).get("meta", {})
    return {
        "primary_outcome": "export_collapse",
        "n_countries": len(panel_countries),
        "coverage": {
            "panel_size": len(VALIDATION_PEERS),
            "countries_in_panel": panel_countries,
            "missing": [c for c in VALIDATION_PEERS if c not in panel_countries],
            "years": meta.get("years"),
        },
        "export_collapse": export_collapse,  # PRIMARY — construct the index targets
        "external_macro": external_macro,    # SECONDARY — independent contrast (null)
        "disclaimer": (
            "Validación PRELIMINAR y DIRECCIONAL, no grado-Basilea. El outcome "
            "PRIMARIO es el colapso de ingresos de exportación (caída ≥10% interanual "
            "en T+1/T+2) — el constructo que la resiliencia apunta. Usa la misma "
            "fuente Comtrade que el índice, pero NO es circular: el índice lee la "
            "ESTRUCTURA comercial en T (concentración + dependencia importadora) y el "
            "outcome es un shock de NIVEL futuro. Como contraste se muestra un shock "
            "macro externo independiente (cuenta corriente / reservas / recesión, "
            "WDI): el índice NO lo discrimina, porque el distress macro amplio lo "
            "dominan shocks COMUNES globales (2009/2015/2020), no la estructura "
            "comercial de cada país. Convención: menor resiliencia = más vulnerable, "
            "por eso la tasa de shock debe subir de «Fuerte» a «Débil». Metodología "
            "validada en panel amplio LatAm+Caribe; el producto es RD."
        ),
    }
