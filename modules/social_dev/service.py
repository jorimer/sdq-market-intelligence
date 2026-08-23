"""Social Development — index computation, persistence and events."""
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.social_dev.events import publish_social_updated
from modules.social_dev.models.models import DevelopmentScore, SocialIndicator
from modules.social_dev.scoring.development import (
    compute_development,
    distribution_stats,
)
from shared.data.encft_employment import LICENSE as _ONE_LICENSE
from shared.data.minerd_coverage import LICENSE as _MINERD_LICENSE
from shared.data.sisdom_common import LICENSE as _MEPYD_LICENSE
from shared.data.siuben_client import LICENSE as _SIUBEN_LICENSE

logger = logging.getLogger("sdq.social_dev.service")

MODEL_VERSION = "1.0"


def compute_and_persist(
    db: Session, period: str, dataset: Dict[str, Dict[str, float]]
) -> Dict[str, Any]:
    """Compute the development index for every entity in *dataset*, persist, publish.

    *dataset* is ``{entity_key: {indicator: value}}`` (regions/groups as the peer
    set, so distribution — not just the mean — is reported).
    """
    if not dataset:
        raise ValueError("Se requiere 'dataset' con al menos una entidad.")

    results: List[Dict[str, Any]] = []
    for entity_key in dataset:
        dev = compute_development(entity_key, dataset)
        row = (
            db.query(DevelopmentScore)
            .filter_by(entity_key=entity_key, period=period)
            .first()
        )
        if row is None:
            row = DevelopmentScore(entity_key=entity_key, period=period)
            db.add(row)
        row.development_score = dev["development_score"]
        row.band = dev["band"]
        row.breakdown = dev["dimensions"]
        row.model_version = MODEL_VERSION
        results.append({
            "entity_key": entity_key,
            "development_score": dev["development_score"],
            "band": dev["band"],
        })

    db.commit()
    distribution = distribution_stats([r["development_score"] for r in results])

    payload = {"period": period, "entities": results, "distribution": distribution}
    publish_social_updated(payload)
    logger.info("Social snapshot %s: %d entidades", period, len(results))
    return {
        "period": period,
        "entities": results,
        "distribution": distribution,
        "model_version": MODEL_VERSION,
    }


def get_scores(db: Session, period: Optional[str] = None) -> List[DevelopmentScore]:
    q = db.query(DevelopmentScore)
    if period:
        q = q.filter_by(period=period)
    return q.order_by(DevelopmentScore.development_score.desc().nullslast()).all()


def _period_key(period: Optional[str]) -> tuple:
    """Chronological key; annual ``YYYY`` is canonical (sorts after its quarters)."""
    m = re.match(r"(\d{4})(?:-Q([1-4]))?", period or "")
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)) if m.group(2) else 5)


def get_latest(db: Session, entity_key: str) -> Optional[DevelopmentScore]:
    rows = db.query(DevelopmentScore).filter_by(entity_key=entity_key).all()
    return max(rows, key=lambda s: _period_key(s.period)) if rows else None


# IDM variable sources (Gate C): poverty + net coverage by region (ONE), national
# series applied to every region (WDI health + ONE/BCRD labour + WB Findex financial
# access), education by region (ONE ENHOGAR, AI-extracted). All 8 vars now sourced.
RUBRIC_VARS = ()  # none left: financial_inclusion now WB Findex (latest-available)
# financial_inclusion: latest-available national value (Findex access proxy lags a
# year), so the current IDM period stays live — like the ENHOGAR study's latest use.
FINANCIAL_VAR = "financial_inclusion"
# literacy_rate is by region (ENHOGAR). schooling_years is NATIONAL: ENHOGAR reports
# only literacy by region, not years of schooling, so it comes from the national ONE
# series (años promedio de educación) like income/informality.
EDUCATION_VARS = ("literacy_rate",)
HEALTH_VARS = ("life_expectancy", "child_mortality")
# National annual series applied uniformly to every region; carry a declared rubric
# default (50) when a period lacks the real value. informality_rate = BCRD ENCFT;
# schooling_years = ONE national years of schooling (no regional breakdown exists).
NATIONAL_LIVE_VARS = ("informality_rate",)
POVERTY_VAR = "poverty_rate"
# Net secondary-coverage by development region + period (MINERD), like poverty: real
# regional + temporal education-access signal in the education dimension.
COVERAGE_VAR = "secondary_coverage"
# Escolaridad promedio POR REGIÓN (SISDOM del MEPyD, cuadro 05 3 007). Dejó de ser
# nacional el 2026-08-10: la serie de la ONE daba la MISMA cifra a las diez regiones y
# ahora hay 2,3 años de brecha entre Ozama y Enriquillo. Se resuelve como el ingreso —
# último valor disponible por región y live solo si LAS 10 lo tienen — porque el motor
# normaliza min-max entre regiones y un llenado parcial no es "menos dato": corre el
# extremo y cambia el score de las demás.
SCHOOLING_VAR = "schooling_years"
# Ingreso per cápita POR REGIÓN (SISDOM del MEPyD). Dejó de ser nacional el 2026-08-09:
# antes era el proxy horario de la ONE, la MISMA cifra para las 10 regiones. Se resuelve
# como la educación —último valor disponible por región, y live solo si LAS 10 lo
# tienen— y no como la pobreza, por dos razones:
#
#   * el SISDOM es una publicación anual que puede quedar un año detrás de la serie de
#     pobreza, que es la que fija el período objetivo; atarlo al período haría que la
#     variable DESAPAREZCA del panel el día que la pobreza avance primero;
#   * el motor normaliza min-max ENTRE regiones, así que un llenado parcial no es
#     "menos dato": corre el mínimo o el máximo y cambia el score de las demás. Con
#     nueve regiones la décima no falta, contamina.
INCOME_VAR = "income_per_capita"
HEALTH_ENTITY = "nacional"


def get_social_indicators(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Real per-entity indicators from ``sd_indicators``. Latest period per
    (entity, theme) when *period* is omitted."""
    best: Dict[tuple, tuple] = {}  # (entity, theme) -> (period, value)
    for r in db.query(SocialIndicator).all():
        if period and r.period != period:
            continue
        key = (r.entity_key, r.theme)
        cur = best.get(key)
        if cur is None or _period_key(r.period) > _period_key(cur[0]):
            best[key] = (r.period, r.value)
    out: Dict[str, Dict[str, float]] = {}
    periods = set()
    for (ent, theme), (p, val) in best.items():
        if val is not None:
            out.setdefault(ent, {})[theme] = val
            if p:
                periods.add(p)
    return {"entities": out, "period": max(periods, key=_period_key) if periods else None,
            "has_data": bool(out)}


def _poverty_periods(db: Session) -> List[str]:
    ps = {p for (p,) in db.query(SocialIndicator.period)
          .filter(SocialIndicator.theme == POVERTY_VAR).distinct() if p}
    return sorted(ps, key=_period_key)


def assemble_idm_dataset(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Full IDM dataset per development region for *period*: real (ONE poverty by
    region + WDI national health, applied to all regions + ONE education by region)
    + declared rubric. Single source of truth. Returns ``{period, dataset, sources,
    has_live}`` with a live|rubric provenance map per variable. *period* defaults
    to the latest."""
    from shared.data.one_client import region_catalog
    from shared.doctrine import load_doctrine_raw

    defaults = load_doctrine_raw("social").get("rubric_defaults", {})
    pov_periods = _poverty_periods(db)
    target = period or (pov_periods[-1] if pov_periods else None)
    snap = get_social_indicators(db, period=target)["entities"] if target else {}
    nat = snap.get(HEALTH_ENTITY, {})

    regions = region_catalog()
    # Education is by region from a one-off study (ENHOGAR, AI-extracted), on its
    # own period — take the latest real value per (region, var) regardless of the
    # poverty target. A variable goes live ONLY IF *every* region has it: a partial
    # fill would distort the cross-region min-max (doctrine §rubric_defaults), so
    # an incomplete extraction stays uniform rubric for all rather than half-real.
    latest = get_social_indicators(db)["entities"]
    nat_latest = latest.get(HEALTH_ENTITY, {})  # latest national value per theme
    edu_live = {
        var: all(latest.get(slug, {}).get(var) is not None for slug, _ in regions)
        for var in EDUCATION_VARS
    }
    # Mismo criterio de completitud para el ingreso regional (SISDOM), por la razón
    # explicada en INCOME_VAR: nueve de diez no es "casi", es un min-max distinto.
    income_live = all(latest.get(slug, {}).get(INCOME_VAR) is not None
                      for slug, _ in regions)
    # Ídem escolaridad: pasó de nacional a regional (SISDOM 05 3 007) el 2026-08-10.
    schooling_live = all(latest.get(slug, {}).get(SCHOOLING_VAR) is not None
                         for slug, _ in regions)

    dataset: Dict[str, Dict[str, float]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    for slug, _name in regions:
        merged: Dict[str, float] = {}
        smap: Dict[str, str] = {}
        for var in RUBRIC_VARS:  # none left (all 8 IDM vars sourced)
            merged[var] = float(defaults.get(var, 50))
            smap[var] = "rubric"
        fi = nat_latest.get(FINANCIAL_VAR)  # national (WB Findex), latest-available
        merged[FINANCIAL_VAR] = float(fi) if fi is not None else float(defaults.get(FINANCIAL_VAR, 50))
        smap[FINANCIAL_VAR] = "live" if fi is not None else "rubric"
        for var in EDUCATION_VARS:  # by region (ONE ENHOGAR), live iff complete
            if edu_live[var]:
                merged[var] = float(latest[slug][var])
                smap[var] = "live"
            else:
                merged[var] = float(defaults.get(var, 50))
                smap[var] = "rubric"
        for var in HEALTH_VARS:  # national (WDI), same for all regions
            v = nat.get(var)
            if v is not None:
                merged[var] = float(v)
            smap[var] = "live" if v is not None else "rubric"
        for var in NATIONAL_LIVE_VARS:  # nacional, rubric default if absent
            v = nat.get(var)
            merged[var] = float(v) if v is not None else float(defaults.get(var, 50))
            smap[var] = "live" if v is not None else "rubric"
        if schooling_live:              # por región (SISDOM), live iff las 10 la tienen
            merged[SCHOOLING_VAR] = float(latest[slug][SCHOOLING_VAR])
            smap[SCHOOLING_VAR] = "live"
        else:
            merged[SCHOOLING_VAR] = float(defaults.get(SCHOOLING_VAR, 50))
            smap[SCHOOLING_VAR] = "rubric"
        if income_live:                 # por región (SISDOM), live iff las 10 la tienen
            merged[INCOME_VAR] = float(latest[slug][INCOME_VAR])
            smap[INCOME_VAR] = "live"
        else:
            merged[INCOME_VAR] = float(defaults.get(INCOME_VAR, 50))
            smap[INCOME_VAR] = "rubric"
        pov = snap.get(slug, {}).get(POVERTY_VAR)  # by region (ONE)
        if pov is not None:
            merged[POVERTY_VAR] = float(pov)
        smap[POVERTY_VAR] = "live" if pov is not None else "rubric"
        cov = snap.get(slug, {}).get(COVERAGE_VAR)  # by region + period (ONE)
        if cov is not None:
            merged[COVERAGE_VAR] = float(cov)
        smap[COVERAGE_VAR] = "live" if cov is not None else "rubric"
        dataset[slug] = merged
        sources[slug] = smap
    return {"period": target, "dataset": dataset, "sources": sources, "has_live": bool(snap)}


# ── Series SUB-NACIONALES para la Data API ────────────────────────────────
# Se publican SOLO las series con desagregación geográfica real (región o provincia).
# Las variables nacionales del IDM —salud, informalidad, ingreso, escolaridad, inclusión
# financiera— se aplican por igual a las 10 regiones, así que exponerlas "por región"
# entregaría una CONSTANTE con etiqueta geográfica: no distingue demarcaciones y no
# puede aportar nada a un consumidor que ordena territorios. Servirlas sería servir
# ruido con apariencia de granularidad.
SUBNATIONAL_LEVELS = ("region", "provincia")

_THEME_LABELS = {
    "poverty_rate": "Pobreza monetaria general",
    "poverty_extreme": "Pobreza monetaria extrema",
    "secondary_coverage": "Cobertura neta secundaria",
    "literacy_rate": "Tasa de alfabetización",
    "income_per_capita": "Ingreso familiar mensual por persona",
    "schooling_years": "Escolaridad promedio (15+)",
    "endesa_child_mortality": "Mortalidad infantil (ENDESA)",
}
# Series que NO alimentan el IDM y llevan una advertencia propia. Una serie oficial pero
# vieja es publicable; lo que no es publicable es servirla como si fuera actual.
_SERIES_CAVEATS = {
    "endesa_child_mortality": (
        " Cortes de la encuesta ENDESA, NO una serie anual: el índice de desarrollo usa "
        "la serie anual del Banco Mundial y esta no lo alimenta. Comparte concepto con "
        "ella pero no metodología — una es estimación modelada y esta una encuesta de "
        "hogares; no deben graficarse juntas."),
}
# Una serie servida sin licencia es una serie que el cliente no sabe si puede citar. El
# emisor entra acá el mismo día que empieza a escribir filas sub-nacionales — si no, el
# descriptor sale con ``license: null`` y nadie se entera.
#
# Se IMPORTAN del conector, no se copian. Estaban copiadas palabra por palabra, y una copia
# es una licencia que deja de ser la del emisor en cuanto alguien corrige el original: la de
# Parline decía «uso público con cita» cuando la real es CC BY-NC-SA 4.0, y una copia de esa
# frase habría seguido diciéndolo después del arreglo. Acá el descriptor que se sirve por la
# Data API queda atado a la única declaración que existe.
_SOURCE_LICENSES = {
    "ONE": _ONE_LICENSE,
    "SIUBEN": _SIUBEN_LICENSE,
    "MINERD": _MINERD_LICENSE,
    "MEPyD": _MEPYD_LICENSE,
}


def _series_code(theme: str, entity_key: str) -> str:
    """``'poverty_rate.enriquillo'`` — el sujeto geográfico vive en el código.

    La Data API sirve una serie por código; una serie temática sin su demarcación sería
    ambigua entre 42 sujetos. El punto separa tema y sujeto, y deja el sujeto como hoja
    legible (el guard de nombres del manifiesto lo lee de ahí)."""
    return f"{theme}.{entity_key}"


def split_series_code(code: str) -> tuple:
    """Inversa de :func:`_series_code` → ``(theme, entity_key)``."""
    theme, _sep, entity = str(code or "").rpartition(".")
    return (theme, entity) if theme else (code, "")


def subnational_series(db: Session) -> List[Dict[str, Any]]:
    """Descriptores de cada serie sub-nacional persistida — uno por (tema, demarcación).

    Se derivan del contenido real de ``sd_indicators``: una fuente nueva que empiece a
    escribir con ``disaggregation`` geográfica aparece sola en el catálogo, sin que nadie
    edite la capa API (premisa de auto-extensión de la Data API)."""
    from shared.data.series_nature import infer_nature
    from shared.reference.provinces import NAME_OF as PROVINCE_NAMES

    rows = (
        db.query(SocialIndicator)
        .filter(SocialIndicator.disaggregation.in_(SUBNATIONAL_LEVELS))
        .filter(SocialIndicator.value.isnot(None))
        .all()
    )
    # ``str(...)`` en la frontera: estos modelos usan el estilo legacy de SQLAlchemy,
    # cuyo tipo estático es ``Column[str]`` y no ``str``.
    grouped: Dict[tuple, List[SocialIndicator]] = {}
    for r in rows:
        grouped.setdefault((str(r.theme), str(r.entity_key)), []).append(r)

    region_names = dict(_region_catalog_safe())
    out: List[Dict[str, Any]] = []
    for (theme, entity), obs in sorted(grouped.items()):
        periods = sorted({str(o.period) for o in obs if o.period}, key=_period_key)
        level = str(obs[0].disaggregation or "")
        place = (PROVINCE_NAMES.get(entity) if level == "provincia"
                 else region_names.get(entity)) or entity
        source = str(obs[0].source or "")
        unit = str(obs[0].unit) if obs[0].unit is not None else None
        theme_label = _THEME_LABELS.get(theme)
        if theme_label is None:
            spec = _siuben_spec(theme)
            theme_label = spec.note.rstrip(".") if spec else theme
        out.append({
            "code": _series_code(theme, entity),
            # ``source`` viaja para que la nota nombre al emisor real: el eje ya no tiene
            # uno solo (ONE, MINERD, MEPyD, SIUBEN escriben filas sub-nacionales).
            "label": f"{theme_label} — {place}",
            "unit": unit,
            # Trimestral si el período trae Q (padrón SIUBEN); anual si no.
            "frequency": "quarterly" if any("Q" in (p or "") for p in periods) else "annual",
            "source": source,
            "license": _SOURCE_LICENSES.get(source),
            "period_first": periods[0] if periods else None,
            "period_latest": periods[-1] if periods else None,
            "n_obs": len(obs),
            # La naturaleza sale de la UNIDAD que declaró el emisor, no de una constante.
            # Estaba clavada en "rate" porque hasta hoy todas las series del eje eran
            # porcentajes; el ingreso del SISDOM viene en RD$ y con la constante habría
            # salido como tasa — un consumidor leería su variación en PUNTOS y publicaría
            # "el ingreso subió 2.400 puntos". Es el mismo error de categoría que
            # `series_nature` existe para cerrar.
            "nature": infer_nature(unit=unit, label=theme_label),
            "geo_level": level,
            "curated": True,           # tema elegido y nombrado, no volcado de planilla
            "note": _series_note(theme, level, source),
        })
    return out


def _region_catalog_safe() -> List[tuple]:
    from shared.data.one_client import region_catalog

    return region_catalog()


def _siuben_spec(theme: str):
    from shared.data.siuben_client import theme_spec

    return theme_spec(theme)


#: Emisor → cómo nombrarlo en la nota de la serie. La nota decía "ONE" para todo, que era
#: cierto cuando la ONE era la única fuente sub-nacional del eje y hoy sería atribuirle a
#: un organismo el dato de otro.
_SOURCE_NAMES = {
    "ONE": "la Oficina Nacional de Estadística (ONE)",
    "MINERD": "el Ministerio de Educación (tablero SIIE del MINERD)",
    "MEPyD": "el SISDOM del Ministerio de Economía (VAES/MEPyD)",
}


def _series_note(theme: str, level: str, source: str = "") -> str:
    """La nota carga el UNIVERSO, que es lo que decide si la cifra se puede leer como
    tasa poblacional. Sin esto, un consumidor toma una composición del padrón SIUBEN
    por la tasa de la provincia."""
    spec = _siuben_spec(theme)
    if spec is not None:
        return (f"{spec.note} Universo: padrón de focalización del SIUBEN (hogares "
                "registrados), NO la población general de la demarcación.")
    emisor = _SOURCE_NAMES.get(source)
    quien = f" Publicado por {emisor}." if emisor else ""
    donde = ("Desagregación por provincia (32)." if level == "provincia"
             else "Desagregación por región de desarrollo (10 regiones).")
    return donde + quien + _SERIES_CAVEATS.get(theme, "")


def subnational_observations(
    db: Session, code: str, *, start: Optional[str] = None, end: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Observaciones de UNA serie sub-nacional, ascendentes por período."""
    theme, entity = split_series_code(code)
    if not theme or not entity:
        return []
    rows = (
        db.query(SocialIndicator)
        .filter(SocialIndicator.theme == theme, SocialIndicator.entity_key == entity)
        .filter(SocialIndicator.disaggregation.in_(SUBNATIONAL_LEVELS))
        .all()
    )
    rows.sort(key=lambda r: _period_key(str(r.period)))
    if start:
        rows = [r for r in rows if _period_key(str(r.period)) >= _period_key(start)]
    if end:
        rows = [r for r in rows if _period_key(str(r.period)) <= _period_key(end)]
    if limit:
        rows = rows[-int(limit):]
    return [
        {"period": r.period, "value": r.value, "unit": r.unit, "source": r.source,
         "published_at": r.published_at.isoformat() if r.published_at else None,
         "reason": None if r.value is not None else "sin dato publicado para el período"}
        for r in rows
    ]


def backfill_idm_scores(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Backfill the IDM for every period with real poverty data, then purge any
    score outside that set (the SIB pattern: score_all_periods + prune) — removes
    fixture/seed remnants (e.g. the old SAMPLE_REGIONS snapshot)."""
    set_phase = set_phase or (lambda _m: None)
    periods = _poverty_periods(db)
    if not periods:
        return {"scored_periods": 0, "purged": 0,
                "errors": ["sin dato social; corre one-social-sync primero"]}
    for i, p in enumerate(periods, 1):
        set_phase(f"backfill IDM {p} ({i}/{len(periods)})")
        asm = assemble_idm_dataset(db, period=p)
        compute_and_persist(db, period=p, dataset=asm["dataset"])
    set_phase("purgando scores fuera del backfill (fixture/seed)")
    keep = set(periods)
    stale = db.query(DevelopmentScore).filter(DevelopmentScore.period.notin_(keep)).all()
    purged_periods = sorted({s.period for s in stale})
    db.query(DevelopmentScore).filter(DevelopmentScore.period.notin_(keep)).delete(synchronize_session=False)
    db.commit()
    return {"scored_periods": len(periods), "periods": periods, "latest": periods[-1],
            "purged": len(stale), "purged_periods": purged_periods, "errors": []}
