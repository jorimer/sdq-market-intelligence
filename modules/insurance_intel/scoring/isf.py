"""Índice de Solidez de Aseguradora (ISF) — insurer solidity index.

Mirrors the pension ISA: a 0-100 band index over REAL public SIS data (audited
statements por cía), NOT a credit rating. Five dimensions (weights sum to 1.0),
each scored 0-100 by a HYBRID of an absolute band (0.5) + peer min-max (0.5) so the
score is both anchored and discriminating; the overall is the weighted mean over the
PRESENT dimensions, with ``coverage`` = share of the declared methodology backed by
real data.

    solvencia         0.35  patrimonio / activos                 higher=better
    siniestralidad    0.20  siniestros / primas (loss ratio)     lower ratio=better
    liquidez          0.15  activos líquidos / reservas técnicas  higher=better
    escala            0.15  activos totales (log)                 higher=better
    resultado_tecnico 0.15  (ingresos − gastos) / primas          higher=better

With audited statements ingested, coverage ≈ 1.0 → the ISF emits an ABSOLUTE band
(Sólida/Adecuada/En vigilancia/Frágil) besides ranking. Missing inputs → the
dimension is a declared gap (present=False), never fabricated.
"""
import math
from statistics import pstdev  # noqa: F401  (reserved for future dispersion use)
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# Dimension spec: weight, direction, and absolute anchors (worst→0, best→100).
# Solvencia y liquidez usan los ÍNDICES REGULATORIOS oficiales que publica la SIS
# (Ley 146-02, Art. 164): índice = recurso disponible / mínimo requerido, ≥1 = cumple.
# Los anclajes reflejan el umbral regulatorio 1.0 (cumplimiento) como piso de referencia.
# ``wabs`` = peso de la banda ABSOLUTA vs. min-max entre pares. Solvencia y liquidez son
# ÍNDICES regulatorios (valor absoluto significativo: 1.0 = cumple sin colchón), así que
# pesan más hacia lo absoluto que las dimensiones puramente relativas.
DIMENSIONS = [
    {"key": "solvencia", "label": "Solvencia regulatoria (PTA/margen requerido, Ley 146-02)",
     "weight": 0.35, "direction": "higher", "lo": 0.60, "hi": 3.00, "log": False, "wabs": 0.75},
    {"key": "siniestralidad", "label": "Siniestralidad (loss ratio)", "weight": 0.20,
     "direction": "lower", "lo": 0.85, "hi": 0.25, "log": False},
    {"key": "liquidez", "label": "Liquidez regulatoria (disponible/mínimo, Ley 146-02)",
     "weight": 0.15, "direction": "higher", "lo": 0.50, "hi": 5.00, "log": False, "wabs": 0.65},
    {"key": "escala", "label": "Escala (activos totales)", "weight": 0.15,
     "direction": "higher", "lo": 5e8, "hi": 3.5e10, "log": True},
    {"key": "resultado_tecnico", "label": "Resultado técnico (sobre primas)", "weight": 0.15,
     "direction": "higher", "lo": -0.05, "hi": 0.20, "log": False},
]
_WABS = 0.5  # hybrid weight of the absolute band vs. peer min-max
_MIN_COVERAGE = 0.50
_BANDS = [(75, "Sólida"), (60, "Adecuada"), (45, "En vigilancia"), (0, "Frágil")]


def band_for(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    for threshold, name in _BANDS:
        if score >= threshold:
            return name
    return "Frágil"


def _absolute(raw: float, spec: Dict) -> float:
    lo, hi = spec["lo"], spec["hi"]
    if spec.get("log"):
        raw = math.log10(max(raw, 1.0))
        lo, hi = math.log10(lo), math.log10(hi)
    frac = (raw - lo) / (hi - lo) if hi != lo else 0.5
    return max(0.0, min(1.0, frac)) * 100


def _minmax(raw: float, peers: List[float], direction: str) -> Optional[float]:
    if len(peers) < 2:
        return None
    lo, hi = min(peers), max(peers)
    if hi == lo:
        return 50.0
    frac = (raw - lo) / (hi - lo)
    if direction == "lower":
        frac = 1 - frac
    return max(0.0, min(1.0, frac)) * 100


def _raw_metric(fin: Dict[str, Any], key: str) -> Optional[float]:
    """Derive a dimension's raw ratio from an insurer's financials dict."""
    g = fin.get
    if key == "solvencia":
        return g("indice_solvencia")  # oficial (PTA/MSMR), Ley 146-02 Art. 160-161
    if key == "siniestralidad":
        return (g("siniestros_pagados") / g("primas_suscritas")) if g("primas_suscritas") else None
    if key == "liquidez":
        return g("indice_liquidez")  # oficial (DLGFL/LMR), Ley 146-02 Art. 162
    if key == "escala":
        return g("activos_totales")
    if key == "resultado_tecnico":
        ing, gas, pri = g("ingresos_totales"), g("gastos_totales"), g("primas_suscritas")
        return ((ing - gas) / pri) if (ing is not None and gas is not None and pri) else None
    return None


def score_insurers(financials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure ISF scorer over a list of insurer financials dicts (testable, no DB).

    Each dict has ``slug``, ``name``, ``period`` + the raw figures (patrimonio,
    activos_totales, primas_suscritas, siniestros_pagados, reservas_tecnicas,
    activos_liquidos, ingresos_totales, gastos_totales)."""
    # Peer pools per dimension (for min-max), over insurers where the raw exists.
    raws: Dict[str, Dict[str, Optional[float]]] = {}
    for fin in financials:
        raws[fin["slug"]] = {d["key"]: _raw_metric(fin, d["key"]) for d in DIMENSIONS}
    pools = {d["key"]: [raws[s][d["key"]] for s in raws if raws[s][d["key"]] is not None]
             for d in DIMENSIONS}

    total_weight = sum(d["weight"] for d in DIMENSIONS)
    out: List[Dict[str, Any]] = []
    for fin in financials:
        slug = fin["slug"]
        dims: List[Dict[str, Any]] = []
        num = wsum = 0.0
        for d in DIMENSIONS:
            raw = raws[slug][d["key"]]
            present = raw is not None
            score = None
            if present:
                a = _absolute(raw, d)
                mm = _minmax(raw, pools[d["key"]], d["direction"])
                wabs = d.get("wabs", _WABS)
                score = round(wabs * a + (1 - wabs) * mm, 1) if mm is not None else round(a, 1)
                num += score * d["weight"]
                wsum += d["weight"]
            dims.append({"key": d["key"], "label": d["label"], "weight": d["weight"],
                         "raw": None if raw is None else round(raw, 4),
                         "score": score, "provenance": "real", "present": present})
        coverage = round(wsum / total_weight, 4) if total_weight else 0.0
        overall = round(num / wsum, 1) if wsum and coverage >= _MIN_COVERAGE else None
        out.append({
            "slug": slug, "name": fin.get("name", slug), "period": fin.get("period"),
            "overall_score": overall, "band": band_for(overall) if coverage >= 0.99 else None,
            "coverage": coverage, "dimensions": dims,
            "score_kind": "absolute" if coverage >= 0.99 else "relative",
        })
    out.sort(key=lambda r: (r["overall_score"] is not None, r["overall_score"] or 0), reverse=True)
    return out


def _fallback_key(name: str) -> str:
    """Heuristic canonical key (used only if the official roster is unavailable): first two
    brand tokens (stable head vs. the truncated tail), with a lighter-slug fallback."""
    from shared.data.sis_solvency_client import brand_key
    from modules.insurance_intel.external.audited_excel_extractor import slugify_insurer
    bk = brand_key(name)
    return "_".join(bk.split("_")[:2]) if bk else (slugify_insurer(name) or "sin_nombre")


def _official_index():
    """``{brand_key: (official_name, official_slug)}`` for the authorized-insurer roster."""
    from shared.data.sis_roster_client import official_insurers
    from shared.data.sis_solvency_client import brand_key
    from modules.insurance_intel.external.audited_excel_extractor import slugify_insurer
    idx = {}
    for name in official_insurers():
        idx[brand_key(name)] = (name, slugify_insurer(name))
    return idx


def _match_official(key: str, official: dict):
    """Match an entity's brand key to an official company. exact → prefix (≥5) → unique
    first-token. Returns ``(official_name, official_slug)`` or None."""
    if key in official:
        return official[key]
    for ok, v in official.items():
        short, long = sorted((key, ok), key=len)
        if len(short) >= 5 and long.startswith(short):
            return v
    first = key.split("_")[0]
    if len(first) >= 5:
        hits = [v for ok, v in official.items() if ok.split("_")[0] == first]
        if len(hits) == 1:
            return hits[0]
    return None


def _load_financials(db: Session) -> List[Dict[str, Any]]:
    """Assemble each insurer's latest figures from ``insurance_series``, grouped under the
    OFFICIAL roster identity (``companias-aseguradoras-y-reaseguradoras``): fragmented
    entities (audited sheet-name truncation drifts the slug across years) collapse into the
    authorized company they match, using its official name/slug. Entities that match no
    authorized company (defunct) drop out. Falls back to a heuristic key + latest-year filter
    if the roster is unavailable. Only ``entity_type='aseguradora'``."""
    from shared.data.sis_solvency_client import brand_key
    from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries

    ents = (db.query(InsuranceEntity)
            .filter(InsuranceEntity.entity_type == "aseguradora").all())
    if not ents:
        return []
    official = _official_index()

    # Map each entity slug → canonical (key, name, slug).
    canon: Dict[str, tuple] = {}
    heuristic = not official
    for e in ents:
        if official:
            m = _match_official(brand_key(e.name), official)
            if m:
                canon[e.slug] = (m[1], m[0], m[1])  # key=slug, official name, official slug
        else:
            k = _fallback_key(e.name)
            canon[e.slug] = (k, e.name, e.slug)
    if not canon:
        return []
    # For the heuristic path, the longest name is the display name per key.
    if heuristic:
        best: Dict[str, tuple] = {}
        for e in ents:
            k = canon[e.slug][0]
            if k not in best or len(e.name or "") > len(best[k][1]):
                best[k] = (k, e.name, e.slug)
        canon = {e.slug: best[canon[e.slug][0]] for e in ents if e.slug in canon}

    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.entity_slug.in_(list(canon)),
                    InsuranceSeries.value.isnot(None)).all())
    agg: Dict[str, Dict[str, Any]] = {}
    seen: Dict[tuple, str] = {}
    for r in rows:
        c = canon.get(r.entity_slug)
        if c is None:
            continue
        key, name, slug = c
        d = agg.setdefault(key, {"slug": slug, "name": name})
        sk = (key, r.series_code)
        if sk not in seen or r.period > seen[sk]:
            seen[sk] = r.period
            d[r.series_code] = r.value
            d["period"] = max(d.get("period", ""), r.period)
    if not agg:
        return []
    if heuristic:  # no roster → drop defunct via latest-year filter
        latest = max((str(d.get("period", ""))[:4] for d in agg.values()), default="")
        return [d for d in agg.values() if str(d.get("period", ""))[:4] == latest]
    return list(agg.values())


def compute_isf(db: Session) -> List[Dict[str, Any]]:
    """Compute the ISF per insurer from ingested audited-statement series. Empty until
    the financials sync populates ``insurance_series`` per entity — never fabricated."""
    financials = _load_financials(db)
    return score_insurers(financials) if financials else []
