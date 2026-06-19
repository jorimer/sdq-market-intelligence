"""IDM convergent-validity report: does the IDM rank the 10 development regions
like the PNUD regional HDI (IDHr)? Spearman + bootstrap CI + the side-by-side
ranking, with the largest divergence surfaced honestly.
"""
from typing import Dict, List, Optional

from modules.social_dev.validation.idhr import IDHR, SOURCE
from shared.validation.metrics import spearman_bootstrap_ci


def _latest_idm_scores(db) -> Dict[str, float]:
    """{region_slug: development_score} for the latest persisted period."""
    from modules.social_dev.models.models import DevelopmentScore
    from modules.social_dev.service import _period_key

    rows = db.query(DevelopmentScore).all()
    if not rows:
        return {}
    latest = max((r.period for r in rows), key=_period_key)
    return {r.entity_key: r.development_score for r in rows
            if r.period == latest and r.development_score is not None}


def _desc_ranks(scores: Dict[str, float]) -> Dict[str, int]:
    """Rank 1 = highest score."""
    order = sorted(scores, key=lambda k: -scores[k])
    return {k: i + 1 for i, k in enumerate(order)}


def build_convergent_validity(db) -> Dict:
    """IDM regional ranking vs PNUD IDHr — Spearman ρ + bootstrap CI + pairs."""
    idm = _latest_idm_scores(db)
    common = sorted(set(idm) & set(IDHR))
    if len(common) < 3:
        return {"has_data": False, "n_regions": len(common)}

    xs = [idm[k] for k in common]
    ys = [IDHR[k] for k in common]
    rho, lo, hi = spearman_bootstrap_ci(xs, ys)

    idm_rank = _desc_ranks({k: idm[k] for k in common})
    idhr_rank = _desc_ranks({k: IDHR[k] for k in common})
    pairs = [{
        "region": k,
        "idm_score": round(idm[k], 2),
        "idm_rank": idm_rank[k],
        "idhr": IDHR[k],
        "idhr_rank": idhr_rank[k],
        "rank_diff": idm_rank[k] - idhr_rank[k],
    } for k in common]
    pairs.sort(key=lambda p: p["idhr_rank"])

    top = max(pairs, key=lambda p: abs(p["rank_diff"]))
    return {
        "has_data": True,
        "n_regions": len(common),
        "spearman": None if rho is None else round(rho, 3),
        "spearman_ci": [None if lo is None else round(lo, 2),
                        None if hi is None else round(hi, 2)],
        "pairs": pairs,
        "source": SOURCE,
        "top_divergence": {"region": top["region"], "rank_diff": top["rank_diff"]},
        "disclaimer": (
            "Validez CONVERGENTE (no backtest): un Gate E temporal no aplica al IDM "
            "—índice relativo cross-región cuyas variables nacionales normalizan plano—, "
            "así que se valida contra una medida INDEPENDIENTE de desarrollo: el IDH "
            "regional (IDHr) del PNUD para las mismas 10 regiones. ρ de Spearman alto = "
            "el IDM ordena el desarrollo regional como el índice oficial. N=10 (IC ancho, "
            "honesto). La divergencia mayor suele ser Ozama: el IDHr la encumbra por la "
            "dimensión de ingreso (área metropolitana), que el IDM no captura por región. "
            "El IDHr es ~2010 (último regional oficial citable); los rankings regionales "
            "son estructuralmente estables, por eso la correlación de rango es válida."
        ),
    }
