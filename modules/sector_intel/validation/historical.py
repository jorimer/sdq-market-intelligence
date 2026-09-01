"""IAI panel for the Gate-E backtest, aggregated to the 10 ENCFT activity branches.

The IAI is computed per BCRD-17 slug, but the employment outcome lives at the
ONE's 10-branch resolution. So each branch's IAI for a period is the size-weighted
mean of its member slugs' persisted ``iai_score`` (weights = ``sector_size`` from
``si_variables``). Point-in-time: reads the IAI already persisted by the snapshot
backfill — it never recomputes with future data. ``sector_growth`` is aggregated
the same way to control the circularity in the report.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.sector_intel.models.models import SectorScore
from shared.reference.sector_variables import SectorVariable
from shared.data.sector_crosswalk import ENCFT_BRANCHES, IED_ACTIVITIES


def _by_slug_period(db: Session, variable: str) -> Dict[tuple, float]:
    """``{(slug, period): value}`` for a sector-dimension variable in si_variables."""
    out: Dict[tuple, float] = {}
    rows = (db.query(SectorVariable)
            .filter(SectorVariable.dimension == "sector",
                    SectorVariable.variable == variable).all())
    for r in rows:
        if r.value is not None and r.period:
            out[(r.sector_code, r.period)] = r.value
    return out


def _weighted(members, period, value_map, size) -> Optional[float]:
    """Size-weighted mean of *members*' *value_map* at *period* (None if no data)."""
    num = den = 0.0
    for slug in members:
        w, v = size.get((slug, period)), value_map.get((slug, period))
        if w is None or v is None or w <= 0:
            continue
        num += v * w
        den += w
    return num / den if den > 0 else None


def composicion_por_periodo(db: Session) -> Dict[str, frozenset]:
    """Qué variables tenía el ÍNDICE en cada período, leído del breakdown PERSISTIDO.

    **Por qué hace falta.** El panel del Gate E cubre 2007→ y la composición del IAI no fue la
    misma todo ese tiempo: cada conector que llegó agregó su variable desde el período en que
    su fuente empieza. El más reciente es el costo del capital, que existe desde 2021 porque
    ahí arranca el desglose sectorial de crédito publicado. Un IC medio sobre los 16 años es,
    entonces, el promedio de VARIOS MODELOS distintos — y presentarlo como el resultado «del
    índice» esconde que el índice de los últimos años no es el de los primeros.

    Se LEE del breakdown y no se declara en una tabla: una lista escrita a mano de qué
    variable entró cuándo se desincroniza el día que llega la siguiente, y el reporte seguiría
    partiendo el panel por una frontera que ya no existe.

    Es la UNIÓN entre sectores, no la intersección: la pregunta es «¿esta variable existía en
    este período?», y una variable de cobertura parcial —`profitability` llega a unos 8 de 17
    slugs— existe en el período aunque no la tengan todos.
    """
    from collections import defaultdict

    por_periodo: Dict[str, set] = defaultdict(set)
    for s in db.query(SectorScore).all():
        for dim in (s.iai_breakdown or {}).values():
            if isinstance(dim, dict):
                por_periodo[str(s.period)].update((dim.get("variables") or {}).keys())
    return {p: frozenset(v) for p, v in por_periodo.items() if v}


def build_iai_panel(db: Session) -> List[Dict]:
    """One row per (branch, period): ``{branch, period, iai_score, sector_growth, sector_size}``.

    Drops a (branch, period) with no member IAI/size data, never fabricated.

    **`sector_size` se emite también acá desde el 2026-09-01.** El panel de IED ya lo traía
    —lo necesita para deflactar la intensidad— y éste no, así que el desenlace de empleo era
    el ÚNICO del eje sin control por tamaño de ninguna clase: no se podía contestar si el IAI
    ordena el crecimiento del empleo por encima de lo que explica cuán grande es la rama. Es
    la misma suma ponderada que la del otro panel, sobre las mismas variables persistidas.
    """
    iai = {(s.sector_code, s.period): s.iai_score
           for s in db.query(SectorScore).all() if s.iai_score is not None}
    size = _by_slug_period(db, "sector_size")
    growth = _by_slug_period(db, "sector_growth")
    periods = sorted({p for (_s, p) in iai})

    panel: List[Dict] = []
    for branch in ENCFT_BRANCHES:
        for period in periods:
            score = _weighted(branch.members, period, iai, size)
            if score is None:
                continue
            tamaño = sum(size.get((slug, period), 0.0) or 0.0 for slug in branch.members)
            panel.append({
                "branch": branch.key,
                "period": period,
                "iai_score": round(score, 3),
                "sector_growth": _weighted(branch.members, period, growth, size),
                "sector_size": round(tamaño, 6) if tamaño else None,
            })
    return panel


def build_iai_panel_ied(db: Session) -> List[Dict]:
    """Panel del IAI agregado a las NUEVE actividades de IED del BCRD.

    Misma agregación ponderada por tamaño que el panel de empleo, contra otra resolución:
    la del desenlace que el índice sí pretende anticipar. Se emite ``sector_size`` además
    del score porque el desenlace primario es una INTENSIDAD (IED por unidad de tamaño) —
    comparar niveles de IED ordenaría sectores por lo grandes que son, no por lo atractivos.
    """
    iai = {(str(s.sector_code), str(s.period)): s.iai_score
           for s in db.query(SectorScore).all() if s.iai_score is not None}
    size = _by_slug_period(db, "sector_size")
    growth = _by_slug_period(db, "sector_growth")
    periods = sorted({p for (_s, p) in iai})

    panel: List[Dict] = []
    for actividad in IED_ACTIVITIES:
        for period in periods:
            score = _weighted(actividad.members, period, iai, size)
            if score is None:
                continue
            tamaño = sum(size.get((slug, period), 0.0) or 0.0 for slug in actividad.members)
            panel.append({
                "branch": actividad.key,
                "period": period,
                "iai_score": round(score, 3),
                "sector_growth": _weighted(actividad.members, period, growth, size),
                "sector_size": round(tamaño, 6) if tamaño else None,
            })
    return panel
