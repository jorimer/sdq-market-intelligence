"""Índice de Solidez de ARS (ISARS) — health-risk-manager solidity index.

A 0-100 band index over the OFFICIAL regulatory indicators that SISALRIL publishes per ARS
(Portal Estadístico, "Indicadores de Desempeño Financiero"), computed from the BDFINAC
accounts. NOT a credit rating. Four dimensions (hybrid absolute band + peer min-max):

    margen_solvencia       0.35  ind. 405 = inversiones que avalan (6) / margen requerido (7)  ≥1=cumple
    siniestralidad         0.25  ind. 401 = gasto salud (13) / ingreso salud (12)              lower=better
    solvencia_patrimonial  0.20  patrimonio (10) / activo total (15)                            higher=better
    rentabilidad           0.20  ind. 408 (ROA) = beneficio neto (11) / activo total (15)       higher=better

VALIDATED EXACTLY against SISALRIL's published indicators: margen (6/7) == ind. 405, and
ROA (11/15) == ind. 408 for all 17 ARS. Key finding: the real total asset is TIPO 15 (the
documented ``9`` is a partial line); this unlocked ROA and the patrimonial solvency
(patrimonio/activo) that were previously declared gaps. Capital mínimo (403/404) remains a
declared gap (its accounts are inconsistent for some public/self-managed ARS).
"""
import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# Dimensiones = indicadores REGULATORIOS OFICIALES de SISALRIL (Portal Estadístico,
# Indicadores de Desempeño Financiero), computados de las cuentas del BDFINAC. Validado:
# el margen (6/7) coincide EXACTAMENTE con el indicador 405 del portal.
DIMENSIONS = [
    {"key": "margen_solvencia", "label": "Margen de solvencia requerido (SISALRIL ind. 405)",
     "weight": 0.35, "direction": "higher", "lo": 0.8, "hi": 3.0, "log": False},
    {"key": "siniestralidad", "label": "Índice de siniestralidad (SISALRIL ind. 401)",
     "weight": 0.25, "direction": "lower", "lo": 1.0, "hi": 0.6, "log": False},
    {"key": "solvencia_patrimonial", "label": "Solvencia patrimonial (patrimonio/activo)",
     "weight": 0.20, "direction": "higher", "lo": 0.10, "hi": 0.60, "log": False},
    {"key": "rentabilidad", "label": "Rentabilidad sobre activos ROA (SISALRIL ind. 408)",
     "weight": 0.20, "direction": "higher", "lo": -0.01, "hi": 0.06, "log": False},
]
_WABS = 0.5
_MIN_COVERAGE = 0.50
_BANDS = [(75, "Sólida"), (60, "Adecuada"), (45, "En vigilancia"), (0, "Frágil")]

# Mismo techo de banda que el ISF, sobre el margen de solvencia de SISALRIL (ind. 405,
# < 1.0 = incumple). Decisión de producto del dueño, 2026-08-07: quien está bajo el mínimo
# de capital no puede mostrar una banda que se lea como "está bien". Medido en producción:
# ARS Renacer (0.779) y ARS Dr. Yunén (0.764) incumplen.
BAND_CAP_INCUMPLIMIENTO = "En vigilancia"
_BAND_ORDER = [name for _t, name in _BANDS]  # mejor → peor


def band_for(score: Optional[float], margen_incumplido: bool = False) -> Optional[str]:
    """Banda del score, topeada si la ARS incumple el margen de solvencia requerido.

    El tope no toca el ``overall_score``: solo acota la etiqueta cualitativa, que es la que
    un lector lee como afirmación."""
    if score is None:
        return None
    band = next((name for threshold, name in _BANDS if score >= threshold), "Frágil")
    if margen_incumplido and _BAND_ORDER.index(band) < _BAND_ORDER.index(BAND_CAP_INCUMPLIMIENTO):
        return BAND_CAP_INCUMPLIMIENTO
    return band


def _absolute(raw: float, spec: Dict) -> float:
    lo, hi = spec["lo"], spec["hi"]
    if spec.get("log"):
        raw, lo, hi = math.log10(max(raw, 1.0)), math.log10(lo), math.log10(hi)
    frac = (raw - lo) / (hi - lo) if hi != lo else 0.5
    return max(0.0, min(1.0, frac)) * 100


def _minmax(raw: float, peers: List[float], direction: str) -> Optional[float]:
    """Peer min-max con límites robustos (valla de Tukey): un outlier extremo no comprime
    al resto del panel. Ver ``shared.indices.normalization.robust_bounds``."""
    from shared.indices.normalization import robust_bounds

    if len(peers) < 2:
        return None
    lo, hi = robust_bounds(peers)
    if hi == lo:
        return 50.0
    frac = (raw - lo) / (hi - lo)
    if direction == "lower":
        frac = 1 - frac
    return max(0.0, min(1.0, frac)) * 100


def _ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    return (num / den) if (num is not None and den) else None


def _raw_metric(fin: Dict[str, Any], key: str) -> Optional[float]:
    g = fin.get
    if key == "margen_solvencia":
        return _ratio(g("ars.margen_inversiones"), g("ars.margen_requerido"))
    if key == "siniestralidad":
        return _ratio(g("ars.gasto_salud"), g("ars.ingreso_salud"))
    if key == "solvencia_patrimonial":  # patrimonio / activo total (TIPO 10/15)
        return _ratio(g("ars.patrimonio"), g("ars.activo_total"))
    if key == "rentabilidad":  # ROA = beneficio neto / activo total (ind. 408; 11/15)
        return _ratio(g("ars.beneficio_neto"), g("ars.activo_total"))
    return None


def score_ars(financials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure ISARS scorer over a list of ARS financials dicts (testable, no DB)."""
    raws = {f["slug"]: {d["key"]: _raw_metric(f, d["key"]) for d in DIMENSIONS} for f in financials}
    pools = {d["key"]: [raws[s][d["key"]] for s in raws if raws[s][d["key"]] is not None]
             for d in DIMENSIONS}
    total_weight = sum(d["weight"] for d in DIMENSIONS)
    out: List[Dict[str, Any]] = []
    for f in financials:
        slug = f["slug"]
        dims, num, wsum = [], 0.0, 0.0
        for d in DIMENSIONS:
            raw = raws[slug][d["key"]]
            present = raw is not None
            score = None
            if present:
                a = _absolute(raw, d)
                mm = _minmax(raw, pools[d["key"]], d["direction"])
                score = round(_WABS * a + (1 - _WABS) * mm, 1) if mm is not None else round(a, 1)
                num += score * d["weight"]
                wsum += d["weight"]
            dims.append({"key": d["key"], "label": d["label"], "weight": d["weight"],
                         "raw": None if raw is None else round(raw, 4),
                         "score": score, "provenance": "real", "present": present})
        coverage = round(wsum / total_weight, 4) if total_weight else 0.0
        overall = round(num / wsum, 1) if wsum and coverage >= _MIN_COVERAGE else None
        margen = raws[slug].get("margen_solvencia")
        incumple = margen is not None and margen < 1.0
        band = band_for(overall, incumple) if coverage >= 0.99 else None
        out.append({"slug": slug, "name": f.get("name", slug), "period": f.get("period"),
                    "category": f.get("category"),
                    "overall_score": overall, "band": band,
                    "band_capped": bool(band and incumple and band != band_for(overall)),
                    "incumple_margen_solvencia": None if margen is None else incumple,
                    "coverage": coverage, "dimensions": dims,
                    "score_kind": "absolute" if coverage >= 0.99 else "relative"})
    out.sort(key=lambda r: (r["overall_score"] is not None, r["overall_score"] or 0), reverse=True)
    return out


def _load_ars_financials(db: Session) -> List[Dict[str, Any]]:
    """Assemble each ARS's latest per-entity account figures from ``insurance_series``."""
    from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries

    ents = {e.slug: e for e in db.query(InsuranceEntity)
            .filter(InsuranceEntity.entity_type == "ars").all()}
    if not ents:
        return []
    # canon-exento: los slugs de ARS vienen de SISALRIL con códigos estables (ars_001…), no
    # de nombres de hoja de Excel truncados, así que no hay deriva que colapsar.
    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.entity_slug.in_(list(ents)),
                    InsuranceSeries.series_code.like("ars.%"),
                    InsuranceSeries.value.isnot(None)).all())
    latest: Dict[str, Dict[str, Any]] = {}
    seen: Dict[tuple, str] = {}
    for r in rows:
        e = ents[r.entity_slug]
        d = latest.setdefault(r.entity_slug, {"slug": r.entity_slug, "name": e.name,
                                              "category": e.entity_code})
        key = (r.entity_slug, r.series_code)
        if key not in seen or r.period > seen[key]:
            seen[key] = r.period
            d[r.series_code] = r.value
            d["period"] = max(d.get("period", ""), r.period)
    return list(latest.values())


def compute_ars(db: Session) -> List[Dict[str, Any]]:
    """Compute the ISARS per ARS from ingested BDFINAC series. Empty until the ARS sync
    populates ``insurance_series`` — never fabricated."""
    fins = _load_ars_financials(db)
    return score_ars(fins) if fins else []
