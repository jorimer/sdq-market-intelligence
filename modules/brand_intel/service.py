"""Brand Intel service — loads per-engagement data and drives the engines.

The engines are pure functions over plain structures; this layer is the only one that
touches the database. Every query filters by ``engagement_id``: that is the isolation
boundary for private client data, and it is enforced here rather than trusted to callers.

Nothing in this module fabricates a value. Where an input is missing the output carries
``None`` and a stated reason, which is what lets the report distinguish "no movement" from
"no measurement".
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.brand_intel.engines import attribution as attr
from modules.brand_intel.engines import category as cat
from modules.brand_intel.engines import deflate as defl
from modules.brand_intel.engines import scenarios as scn
from modules.brand_intel.engines import vigilance as vig
from modules.brand_intel.engines import forecast as fc
from modules.brand_intel.engines import funnel as fn
from modules.brand_intel.engines import ledger as ldg
from modules.brand_intel.engines import significance as sig
from modules.brand_intel.engines.metrics import (
    FUNNEL_LADDER,
    TRACKER_VOCABULARY,
    MetricDef,
    Vocabulary,
    core_metrics,
    get_metric,
    label_for,
)
from modules.brand_intel.models.models import (
    BrandClient,
    BrandDecision,
    BrandEngagement,
    BrandEntity,
    BrandMetric,
    BrandExtraction,
    BrandExtractionCell,
    BrandForecast,
    BrandObservation,
    BrandObservationReading,
    BrandWave,
)

logger = logging.getLogger("sdq.brand_intel")

#: Los tipos que `MetricDef.kind` admite. Solo `proportion` habilita banda.
_METRIC_KINDS = {"proportion", "index", "currency", "count"}

REACH_METRIC = "reach_7d"
ATTITUDE_METRIC = "favourite_place"
TICKET_METRIC = "ticket_avg"


# ── loading ───────────────────────────────────────────────────────────

def get_engagement(db: Session, slug: str) -> Optional[BrandEngagement]:
    return (
        db.query(BrandEngagement)
        .filter(BrandEngagement.slug == slug, BrandEngagement.is_active.is_(True))
        .first()
    )


def list_engagements(db: Session, organization_id: Optional[str] = None) -> List[BrandEngagement]:
    """Engagements visible to an organization. ``None`` = platform staff, sees all."""
    q = db.query(BrandEngagement).filter(BrandEngagement.is_active.is_(True))
    if organization_id is not None:
        q = q.filter(BrandEngagement.organization_id == organization_id)
    return q.order_by(BrandEngagement.client_name).all()


def can_access(engagement: BrandEngagement, organization_id: Optional[str],
               is_staff: bool) -> bool:
    """Private client data: staff always, otherwise only the owning organization."""
    if is_staff:
        return True
    if engagement.organization_id is None:
        return False
    return bool(engagement.organization_id == organization_id)


def waves(db: Session, engagement_id: str) -> List[BrandWave]:
    return (
        db.query(BrandWave)
        .filter(BrandWave.engagement_id == engagement_id)
        .order_by(BrandWave.sort_order)
        .all()
    )


def data_waves(db: Session, engagement_id: str) -> List[BrandWave]:
    """Waves that actually carry observations, chronological.

    ``waves()`` returns every wave including future ones created to hold a frozen
    forecast. Analysis must run on the waves that have data: otherwise a projection wave
    silently becomes "the latest wave" and every reading points at an empty column.
    """
    with_data = {
        r[0]
        for r in db.query(BrandObservation.wave_id)
        .filter(BrandObservation.engagement_id == engagement_id)
        .distinct()
        .all()
    }
    return [w for w in waves(db, engagement_id) if w.id in with_data]


def brands(db: Session, engagement_id: str) -> List[BrandEntity]:
    return (
        db.query(BrandEntity)
        .filter(BrandEntity.engagement_id == engagement_id)
        .order_by(BrandEntity.sort_order, BrandEntity.name)
        .all()
    )


#: Every table that hangs off an engagement. Deleting the engagement without emptying
#: these leaves a client's private rows alive with no owner — and `engagement_id` is the
#: only thing that gates access to them, so orphans are unreachable *and* undeletable
#: through the API. Listed children-first: that is also the safe write order.
_OWNED_BY_ENGAGEMENT = (
    BrandExtractionCell,
    BrandExtraction,
    BrandObservationReading,
    BrandForecast,
    BrandDecision,
    BrandObservation,
    BrandMetric,
    BrandEntity,
    BrandWave,
)


def delete_engagement(db: Session, engagement: BrandEngagement) -> Dict[str, int]:
    """Erase an engagement and everything that belongs to it.

    Irreversible on purpose: the alternative on the table was `is_active`, and the owner
    chose deletion for an engagement created by a broken build. What must not happen is a
    *partial* deletion, so the count of every table is returned — a caller that sees rows
    it did not expect knows the model grew a child this function does not know about.
    """
    removed: Dict[str, int] = {}
    for model in _OWNED_BY_ENGAGEMENT:
        removed[model.__tablename__] = (
            db.query(model)
            .filter(model.engagement_id == engagement.id)
            .delete(synchronize_session=False)
        )
    slug = str(engagement.slug)
    db.delete(engagement)
    db.commit()
    logger.info("Encargo brand_intel '%s' eliminado: %s", slug, removed)
    return removed


def client_code(name: str) -> str:
    """Un código legible desde el nombre. Se propone; se puede editar antes de crear."""
    decomposed = unicodedata.normalize("NFD", name or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    code = re.sub(r"[^A-Z0-9]+", "-", stripped.upper()).strip("-")
    return (code or "CLIENTE")[:40]


def clients(db: Session, organization_id: Optional[str] = None) -> List[BrandClient]:
    """Clientes visibles. ``None`` = staff de la plataforma, ve todos.

    Filtra por la organización del cliente solo para no ofrecer a un usuario clientes que
    nunca podrá abrir; el permiso real sigue resolviéndose sobre el encargo.
    """
    q = db.query(BrandClient).filter(BrandClient.is_active.is_(True))
    if organization_id is not None:
        q = q.filter(BrandClient.organization_id == organization_id)
    return q.order_by(BrandClient.name).all()


def get_client(db: Session, code_or_id: str) -> Optional[BrandClient]:
    return (
        db.query(BrandClient)
        .filter(BrandClient.is_active.is_(True))
        .filter((BrandClient.code == code_or_id) | (BrandClient.id == code_or_id))
        .first()
    )


def engagement_counts_by_client(
    db: Session, organization_id: Optional[str] = None
) -> Dict[str, int]:
    """Cuántos estudios cuelgan de cada cliente, para el selector."""
    q = db.query(BrandEngagement).filter(BrandEngagement.is_active.is_(True))
    if organization_id is not None:
        q = q.filter(BrandEngagement.organization_id == organization_id)
    out: Dict[str, int] = {}
    for e in q.all():
        if e.client_id:
            out[str(e.client_id)] = out.get(str(e.client_id), 0) + 1
    return out


def has_own_metrics(db: Session, engagement_id: str) -> bool:
    """Whether this engagement declares its own vocabulary — i.e. is not a tracker."""
    return db.query(BrandMetric).filter(
        BrandMetric.engagement_id == engagement_id).first() is not None


def vocabulary_for(db: Session, engagement_id: str) -> Vocabulary:
    """The metric vocabulary this engagement is read and scored against.

    An engagement that declares its own metrics is a study that is not a brand tracker;
    one that declares none falls back to the tracker vocabulary, which is what keeps this
    invisible to everything already loaded.
    """
    rows = (
        db.query(BrandMetric)
        .filter(BrandMetric.engagement_id == engagement_id)
        .order_by(BrandMetric.sort_order, BrandMetric.code)
        .all()
    )
    if not rows:
        return TRACKER_VOCABULARY
    ladder = [str(r.code) for r in sorted(
        (r for r in rows if r.funnel_order is not None),
        key=lambda r: int(r.funnel_order or 0),
    )]
    return Vocabulary(
        metrics=tuple(
            MetricDef(
                code=str(r.code), label=str(r.label), kind=str(r.kind),
                is_core=bool(r.is_core), higher_is_better=bool(r.higher_is_better),
                category_denominator=bool(r.category_denominator),
                description=str(r.description or ""),
            )
            for r in rows
        ),
        ladder=tuple(ladder),
    )


def brand_slug(name: str) -> str:
    """Fold a printed brand name into a stable key.

    Must agree with the workbook's own slugs, because an engagement can be populated
    from either source and the two must not produce a second entity for one brand.
    The template's own example is ``mcdonalds`` for "McDonald's", which is why the
    apostrophe is dropped rather than treated as a separator: it sits inside a word, and
    splitting there yields ``mcdonald-s`` — a second entity for a brand already loaded.
    """
    decomposed = unicodedata.normalize("NFD", name or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    unquoted = re.sub(r"['‘’ʼ`´]", "", stripped)
    slug = re.sub(r"[^a-z0-9]+", "-", unquoted.lower()).strip("-")
    return slug[:60]


def adopt_structure(
    db: Session,
    engagement: BrandEngagement,
    waves_in: Sequence[Dict[str, Any]],
    brands_in: Sequence[Dict[str, Any]],
    metrics_in: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """Create the engagement's waves and brands from a reviewed proposal.

    Upserts by natural key, so re-adopting after adding one brand does not duplicate the
    others and never orphans observations already tied to an existing wave or brand.
    Chronological order is derived from the wave code rather than trusted from the
    caller: ``sort_order`` drives every series in the module, and a wrong one silently
    reverses trends.
    """
    created_w = updated_w = created_b = updated_b = 0
    warnings: List[str] = []

    for item in sorted(waves_in, key=lambda w: str(w.get("code") or "")):
        code = (item.get("code") or "").strip()
        if not code:
            continue
        known_wave = (
            db.query(BrandWave)
            .filter(BrandWave.engagement_id == engagement.id, BrandWave.code == code)
            .first()
        )
        wave = known_wave or BrandWave(engagement_id=engagement.id, code=code)
        # Provisional: the column is NOT NULL, and the real chronology is recomputed
        # over the full set once every wave in this call exists.
        if wave.sort_order is None:
            wave.sort_order = 0
        wave.label = (item.get("label") or code).strip()[:40]
        period = item.get("period_date")
        if isinstance(period, str) and period:
            period = date.fromisoformat(period)
        if period is not None:
            wave.period_date = period
        if item.get("nominal_base") is not None:
            wave.nominal_base = int(item["nominal_base"])
        if wave.period_date is None:
            warnings.append(f"Ola '{wave.label}' sin fecha de referencia: "
                            "no podrá deflactarse.")
        if known_wave:
            updated_w += 1
        else:
            db.add(wave)
            created_w += 1

    focal_seen = False
    for order, item in enumerate(brands_in, start=1):
        name = (item.get("name") or "").strip()
        slug = (item.get("slug") or brand_slug(name)).strip()
        if not slug:
            continue
        known_brand = (
            db.query(BrandEntity)
            .filter(BrandEntity.engagement_id == engagement.id, BrandEntity.slug == slug)
            .first()
        )
        brand = known_brand or BrandEntity(engagement_id=engagement.id, slug=slug)
        brand.name = name or slug
        is_focal = bool(item.get("is_focal"))
        brand.is_focal = is_focal
        brand.in_category_set = bool(item.get("in_category_set", True))
        brand.sort_order = order
        focal_seen = focal_seen or is_focal
        if known_brand:
            updated_b += 1
        else:
            db.add(brand)
            created_b += 1

    created_m = updated_m = 0
    for order, item in enumerate(metrics_in, start=1):
        code = (item.get("code") or "").strip()
        if not code:
            continue
        known = (
            db.query(BrandMetric)
            .filter(BrandMetric.engagement_id == engagement.id, BrandMetric.code == code)
            .first()
        )
        metric = known or BrandMetric(engagement_id=engagement.id, code=code)
        metric.label = (item.get("label") or code).strip()[:160]
        # An unrecognised kind must not silently become a proportion: that is the one
        # value that unlocks confidence bands, and inventing precision is the failure
        # this whole vocabulary exists to prevent.
        kind = str(item.get("kind") or "").strip()
        metric.kind = kind if kind in _METRIC_KINDS else "count"
        if kind and kind not in _METRIC_KINDS:
            warnings.append(f"Métrica '{code}': tipo '{kind}' desconocido; se guarda como "
                            "conteo, que no admite banda de confianza.")
        metric.is_core = bool(item.get("is_core"))
        metric.higher_is_better = bool(item.get("higher_is_better", True))
        metric.category_denominator = bool(item.get("category_denominator"))
        metric.funnel_order = item.get("funnel_order")
        metric.description = item.get("description") or None
        metric.sort_order = order
        if known:
            updated_m += 1
        else:
            db.add(metric)
            created_m += 1

    db.flush()

    # Chronology is recomputed over the whole set, not just the rows in this call: a
    # wave adopted later can fall between two that already exist.
    for i, w in enumerate(sorted(waves(db, str(engagement.id)),
                                 key=lambda x: str(x.code)), start=1):
        w.sort_order = i

    if brands_in and not focal_seen:
        warnings.append("Ninguna marca quedó marcada como focal: las secciones que "
                        "comparan la marca del cliente contra la categoría no se "
                        "podrán calcular.")
    db.commit()
    return {
        "waves_created": created_w, "waves_updated": updated_w,
        "brands_created": created_b, "brands_updated": updated_b,
        "metrics_created": created_m, "metrics_updated": updated_m,
        "warnings": warnings,
    }


def _cells(
    db: Session, engagement_id: str, metric_code: str, segment: str = "total"
) -> List[cat.Cell]:
    """Observations for one metric, flattened to engine cells keyed by wave code."""
    wave_code = {w.id: w.code for w in waves(db, engagement_id)}
    rows = (
        db.query(BrandObservation)
        .filter(
            BrandObservation.engagement_id == engagement_id,
            BrandObservation.metric_code == metric_code,
            BrandObservation.segment == segment,
        )
        .all()
    )
    out = []
    for r in rows:
        code = wave_code.get(r.wave_id)
        if code:
            out.append(cat.Cell(code, r.brand_slug, r.value, r.base_n))
    return out


def _series_for(
    db: Session, engagement_id: str, metric_code: str, brand_slug: Optional[str],
    segment: str = "total",
) -> List[Dict[str, Any]]:
    """Chronological series of one metric/brand/segment, with bases."""
    ws = data_waves(db, engagement_id)
    cells = {(c.wave): c for c in _cells(db, engagement_id, metric_code, segment)
             if c.brand == brand_slug}
    return [
        {
            "wave": w.code, "label": w.label,
            "value": cells[w.code].value if w.code in cells else None,
            "base_n": cells[w.code].base_n if w.code in cells else None,
        }
        for w in ws
    ]


# ── S1 · category and competitive position ────────────────────────────

def category_analysis(db: Session, engagement_id: str) -> Dict[str, Any]:
    """Category size, share by brand, share shift and the attitude/behaviour divergence."""
    ws = data_waves(db, engagement_id)
    # Coercionados a `str` en el origen: en tiempo de ejecución ya lo son, y arrastrarlos
    # como `Column[str]` obliga a silenciar el tipado en cada sitio que los usa.
    wave_codes: List[str] = [str(w.code) for w in ws]
    labels: Dict[str, str] = {str(w.code): str(w.label) for w in ws}
    ents = brands(db, engagement_id)
    in_set: List[str] = [str(b.slug) for b in ents if b.in_category_set]
    focal = next((str(b.slug) for b in ents if b.is_focal), None)
    names: Dict[str, str] = {str(b.slug): str(b.name) for b in ents}

    reach = _cells(db, engagement_id, REACH_METRIC)
    if not reach:
        return {
            "available": False,
            "reason": f"Sin observaciones de '{label_for(REACH_METRIC)}': "
                      "no puede construirse el denominador de categoría.",
        }

    # El denominador se juzga OLA POR OLA, no sobre el encargo entero. Una versión
    # anterior comprobaba que hubiera ≥2 marcas medidas en total y daba por buena una ola
    # con una sola: su share salía 100% y la categoría "crecía" 226% cuando en la ola
    # siguiente entraban las demás. Eso llegó impreso al informe de un cliente.
    sizes = cat.category_size(reach, in_set)
    con_denominador = [w for w in wave_codes if sizes.get(w) is not None]
    if not con_denominador:
        medidas = {c.brand for c in reach if c.brand and c.brand in set(in_set)}
        quien = next((b.name for b in ents if b.slug in medidas), "una sola marca")
        return {
            "available": False,
            "reason": f"Ninguna ola tiene '{label_for(REACH_METRIC)}' en al menos "
                      f"{cat.MIN_DENOMINATOR_BRANDS} marcas del set (solo {quien}): con un "
                      "único miembro el denominador no es una categoría y el share "
                      "saldría 100%.",
        }

    points = cat.share_by_brand(reach, in_set)
    shift = cat.share_shift(points, wave_codes)

    # El crecimiento se mide entre las olas QUE TIENEN denominador, y sobre las marcas
    # presentes en todas ellas. Dos razones distintas: una ola sin denominador no puede
    # ser extremo de la comparación, y si el conjunto de marcas cambia entre olas lo que
    # varía es la cobertura del estudio, no el tamaño de la categoría.
    comparables, comunes = cat.comparable_size(reach, con_denominador, in_set)
    growth = cat.category_growth(comparables, con_denominador) if comparables else None
    nombres = names
    sin_denominador = [w for w in wave_codes if sizes.get(w) is None]

    if growth is not None:
        entre = f"{labels.get(con_denominador[0])} → {labels.get(con_denominador[-1])}"
        growth_basis = (
            f"Medido entre {entre}, sobre las {len(comunes)} marcas con alcance en todas "
            f"esas olas ({', '.join(nombres.get(b, b) for b in comunes)})."
        )
        if sin_denominador:
            fuera = ", ".join(labels.get(w, w) for w in sin_denominador)
            growth_basis += (f" {fuera} queda(n) fuera de la comparación por no medir "
                             f"alcance en al menos {cat.MIN_DENOMINATOR_BRANDS} marcas.")
    else:
        growth_basis = (
            "No se puede medir el crecimiento: no hay dos olas con al menos "
            f"{cat.MIN_DENOMINATOR_BRANDS} marcas comunes con alcance. Cualquier cifra "
            "reflejaría cambios de cobertura del estudio, no de la categoría."
        )

    attitude = _cells(db, engagement_id, ATTITUDE_METRIC)
    divergence, reading = [], None
    if focal and attitude:
        divergence = cat.attitude_vs_behaviour(attitude, points, focal, wave_codes)
        reading = cat.divergence_reading(divergence)

    share_by_wave: Dict[str, Dict[str, float]] = {}
    for p in points:
        share_by_wave.setdefault(p.brand, {})[p.wave] = p.share

    return {
        "available": True,
        "waves": [{"code": c, "label": labels.get(c, c)} for c in wave_codes],
        "category_size": [{"wave": c, "value": sizes.get(c)} for c in wave_codes],
        "category_growth_pct": growth,
        "growth_basis": growth_basis,
        "waves_without_denominator": [
            {"wave": c, "label": labels.get(c, c)} for c in sin_denominador
        ],
        "share": [
            {
                "brand": slug,
                "name": names.get(slug, slug),
                "is_focal": slug == focal,
                "series": [{"wave": c, "share": by_wave.get(c)} for c in wave_codes],
            }
            for slug, by_wave in sorted(
                share_by_wave.items(),
                key=lambda kv: kv[1].get(wave_codes[-1], 0) if wave_codes else 0,
                reverse=True,
            )
        ],
        "share_shift": [{**row, "name": names.get(row["brand"], row["brand"])}
                        for row in shift],
        "divergence": [
            {"wave": d.wave, "label": labels.get(d.wave, d.wave),
             "attitude": d.attitude, "behaviour": d.behaviour}
            for d in divergence
        ],
        "divergence_reading": reading,
        "focal": focal,
        "denominator_note": (
            "Share del alcance declarado dentro del set medido, no share de mercado: "
            "excluye independientes, comercio informal y cadenas fuera del estudio."
        ),
    }


def macro_context(db: Session) -> Dict[str, Any]:
    """The macro environment for the period, read through the cross-module contract.

    Never imports ``macro_monitor``. With no published contract the reading degrades to
    "unknown" — not to "neutral", which would let absent data pass for a benign environment.
    """
    from shared.contracts import load_macro_contract

    try:
        payload = load_macro_contract(db) or {}
    except Exception as exc:  # noqa: BLE001 — macro context is optional, never fatal
        logger.warning("Contrato macro no disponible: %s", exc)
        payload = {}

    factors: List[Dict[str, Any]] = payload.get("factors") or []
    period = payload.get("period")

    env = attr.read_environment(factors)
    return {
        "available": env.known,
        "period": period,
        "stance": env.stance,
        "index": env.index,
        "adverse": env.adverse,
        "favourable": env.favourable,
        "neutral": env.neutral,
        "drivers": env.drivers,
        "note": env.note,
        "factors": factors,
        "_env": env,
    }


def attribution_analysis(db: Session, engagement_id: str) -> Dict[str, Any]:
    """S3 — every core indicator's movement split between category and brand, in context.

    Runs on the last wave transition. Reach-type metrics ride the category and get a real
    decomposition; attitudinal ones do not scale with category size, so attributing part of
    their movement to it would be a category error dressed as arithmetic.
    """
    ca = category_analysis(db, engagement_id)
    if not ca.get("available"):
        return {"available": False, "reason": ca.get("reason")}
    focal = ca.get("focal")
    wave_codes = [w["code"] for w in ca["waves"]]
    labels = {w["code"]: w["label"] for w in ca["waves"]}
    if not focal or len(wave_codes) < 2:
        return {"available": False, "reason": "Se requieren dos olas y una marca focal."}

    prev, curr = wave_codes[-2], wave_codes[-1]
    sizes = {row["wave"]: row["value"] for row in ca["category_size"]}
    s_prev, s_curr = sizes.get(prev), sizes.get(curr)
    cat_delta_pct = ((s_curr / s_prev - 1) * 100.0) if s_prev and s_curr else None

    macro = macro_context(db)
    env = macro["_env"]

    rows: List[Dict[str, Any]] = []
    for m in core_metrics():
        series = {r["wave"]: r["value"]
                  for r in _series_for(db, engagement_id, m.code, focal)}
        item = attr.decompose_indicator(
            m.code, m.label, prev, curr,
            series.get(prev), series.get(curr), cat_delta_pct,
            is_share_like=m.category_denominator,
        )
        if item.delta is None:
            continue
        reading = attr.cycle_reading(item.brand_effect, env, m.higher_is_better)
        rows.append({
            "metric_code": item.metric_code, "label": item.label,
            "delta": item.delta, "category_effect": item.category_effect,
            "brand_effect": item.brand_effect, "verdict": item.verdict,
            "note": item.note, "cycle_reading": reading["reading"],
            "cycle_text": reading["text"],
        })

    return {
        "available": bool(rows),
        "reason": None if rows else "Sin indicadores núcleo con dos observaciones.",
        "wave_from": prev, "wave_to": curr,
        "wave_from_label": labels.get(prev), "wave_to_label": labels.get(curr),
        "category_delta_pct": cat_delta_pct,
        "environment": {k: v for k, v in macro.items() if k != "_env"},
        "rows": rows,
        "note": (
            "Descomposición contable, no causal: separa el movimiento que explica el "
            "tamaño de la categoría del residual atribuible a la marca. La lectura de "
            "entorno es cualitativa y NO ajusta ninguna cifra."
        ),
    }


# ── S1 · funnel ───────────────────────────────────────────────────────

def funnel_analysis(
    db: Session, engagement_id: str, wave_code: Optional[str] = None
) -> Dict[str, Any]:
    """Step conversion for every brand in the latest (or given) wave with data."""
    ws = data_waves(db, engagement_id)
    if not ws:
        return {"available": False,
                "reason": "Ninguna ola del encargo tiene observaciones todavía."}
    target = next((w for w in ws if w.code == wave_code), ws[-1])
    ents = brands(db, engagement_id)
    focal = next((b.slug for b in ents if b.is_focal), None)
    names = {b.slug: b.name for b in ents}

    rungs_by_brand: Dict[str, Dict[str, Optional[float]]] = {}
    for metric in FUNNEL_LADDER:
        for c in _cells(db, engagement_id, metric):
            if c.wave == target.code and c.brand:
                rungs_by_brand.setdefault(c.brand, {})[metric] = c.value

    if not rungs_by_brand:
        return {"available": False,
                "reason": f"Sin métricas de embudo en la ola {target.label}."}

    funnels = [fn.build_funnel(slug, rungs) for slug, rungs in rungs_by_brand.items()]
    focal_funnel = next((f for f in funnels if f.brand == focal), None)
    weakest = fn.weakest_step(focal_funnel, funnels) if focal_funnel else None
    if weakest:
        weakest["leader_name"] = names.get(str(weakest["leader"]), weakest["leader"])

    return {
        "available": True,
        "wave": {"code": target.code, "label": target.label},
        "funnels": [
            {
                "brand": f.brand,
                "name": names.get(f.brand, f.brand),
                "is_focal": f.brand == focal,
                "rungs": [{"metric": m, "label": label_for(m), "value": f.rungs.get(m)}
                          for m in FUNNEL_LADDER],
                "steps": [{"label": s.label, "conversion": s.conversion} for s in f.steps],
                "end_to_end": f.end_to_end,
            }
            for f in sorted(funnels, key=lambda x: (x.end_to_end or 0), reverse=True)
        ],
        "weakest_step": weakest,
    }


# ── S2 · deflated ticket ──────────────────────────────────────────────

def ticket_analysis(db: Session, engagement_id: str) -> Dict[str, Any]:
    """The focal brand's average ticket, nominal and in constant pesos."""
    from shared.contracts import load_inflation_series

    ws = data_waves(db, engagement_id)
    ents = brands(db, engagement_id)
    focal = next((b.slug for b in ents if b.is_focal), None)
    if not focal:
        return {"available": False, "reason": "El encargo no declara marca focal."}

    series = _series_for(db, engagement_id, TICKET_METRIC, focal)
    nominal = {r["wave"]: r["value"] for r in series if r["value"] is not None}
    if len(nominal) < 2:
        return {"available": False,
                "reason": f"Se requieren al menos dos observaciones de "
                          f"'{label_for(TICKET_METRIC)}'."}

    wave_dates = {w.code: w.period_date for w in ws if w.period_date}
    missing = [c for c in nominal if c not in wave_dates]
    if missing:
        return {"available": False,
                "reason": f"Olas sin fecha de referencia: {', '.join(missing)}. "
                          "Sin fecha no puede deflactarse."}

    inflation = load_inflation_series(db)
    base_wave = next(iter([w.code for w in ws if w.code in nominal]), None)
    if not inflation:
        return {
            "available": True, "deflated": False,
            "reason": "Sin serie de inflación en la plataforma: el dato queda NOMINAL.",
            "base_wave": base_wave,
            "series": [{"wave": r["wave"], "label": r["label"],
                        "nominal": r["value"], "real": None} for r in series],
        }

    real = defl.real_series(nominal, wave_dates, inflation, base_wave)
    base_d = wave_dates.get(base_wave)
    last_code = [r["wave"] for r in series if r["value"] is not None][-1]
    detail = defl.price_level_factor(inflation, base_d, wave_dates[last_code])

    reals: List[Tuple[str, float]] = []
    for c in nominal:
        rv = real.get(c)
        if rv is not None:
            reals.append((c, rv))
    peak_code, peak_val = max(reals, key=lambda kv: kv[1]) if reals else (None, None)
    last_real = real.get(last_code)
    from_peak = ((last_real / peak_val - 1) * 100.0
                 if peak_val and last_real and peak_code != last_code else None)

    return {
        "available": True,
        "deflated": True,
        "base_wave": base_wave,
        "series": [
            {"wave": r["wave"], "label": r["label"],
             "nominal": r["value"], "real": real.get(r["wave"])}
            for r in series
        ],
        "peak_wave": peak_code,
        "change_from_peak_pct": from_peak,
        "deflator_note": detail.note,
        "coverage": detail.coverage,
    }


# ── S4 · forecasting ──────────────────────────────────────────────────

def _expected_base(db: Session, engagement_id: str, metric: str,
                   brand: Optional[str], segment: str) -> Optional[int]:
    """Most recent non-null base for the cell — the best estimate of the next wave's."""
    series = _series_for(db, engagement_id, metric, brand, segment)
    bases = [r["base_n"] for r in series if r["base_n"]]
    return bases[-1] if bases else None


def issue_forecasts(
    db: Session, engagement_id: str, target_wave_code: str, segment: str = "total"
) -> Dict[str, Any]:
    """Freeze a forecast for each core metric of the focal brand. Idempotent per wave."""
    ws = waves(db, engagement_id)
    codes = [w.code for w in ws]
    target = next((w for w in ws if w.code == target_wave_code), None)
    if target is None:
        return {"issued": [], "skipped": [],
                "error": f"Ola objetivo '{target_wave_code}' no existe en el encargo."}

    ents = brands(db, engagement_id)
    focal = next((b.slug for b in ents if b.is_focal), None)
    if not focal:
        return {"issued": [], "skipped": [], "error": "El encargo no declara marca focal."}

    history_codes = [c for c in codes if c != target_wave_code
                     and codes.index(c) < codes.index(target_wave_code)]
    issued, skipped = [], []

    # ONE rule for every series, chosen on the pooled backtest rather than per series.
    # Picking a rule per series would fit a winner on the two or three predictions each
    # one affords — the overfitting this engine exists to avoid. Pooling across the core
    # metrics multiplies the evidence behind the choice and keeps the report explainable:
    # a single named rule, not six.
    bt = rule_backtest(db, engagement_id, segment)
    chosen_rule = bt["winner"] if bt.get("available") else None

    for m in core_metrics():
        series = _series_for(db, engagement_id, m.code, focal, segment)
        values = [r["value"] for r in series
                  if r["wave"] in history_codes and r["value"] is not None]
        base = _expected_base(db, engagement_id, m.code, focal, segment)
        f = fc.issue_forecast(values, base, rule=chosen_rule)
        if f is None:
            skipped.append({"metric": m.code, "label": m.label,
                            "reason": "Historia o base insuficiente para emitir."})
            continue

        existing = (
            db.query(BrandForecast)
            .filter(
                BrandForecast.engagement_id == engagement_id,
                BrandForecast.target_wave_id == target.id,
                BrandForecast.metric_code == m.code,
                BrandForecast.brand_slug == focal,
                BrandForecast.segment == segment,
            )
            .first()
        )
        row = existing or BrandForecast(
            engagement_id=engagement_id, target_wave_id=target.id,
            brand_slug=focal, metric_code=m.code, segment=segment,
        )
        if existing and existing.status == "scored":
            skipped.append({"metric": m.code, "label": m.label,
                            "reason": "Ya puntuado: no se re-emite (no se siembra el pasado)."})
            continue
        row.point, row.lo, row.hi, row.rule = f.point, f.lo, f.hi, f.rule
        row.issued_at_wave_id = history_codes[-1] if history_codes else target.id
        row.status = "pending"
        if not existing:
            db.add(row)
        issued.append({"metric": m.code, "label": m.label, "point": f.point,
                       "lo": f.lo, "hi": f.hi, "rule": f.rule, "basis": f.basis})

    return {"issued": issued, "skipped": skipped, "target_wave": target.code}


def score_pending_forecasts(db: Session, engagement_id: str) -> Dict[str, Any]:
    """Score every pending forecast whose target wave now has data."""
    ws = {w.id: w for w in waves(db, engagement_id)}
    pending = (
        db.query(BrandForecast)
        .filter(BrandForecast.engagement_id == engagement_id,
                BrandForecast.status == "pending")
        .all()
    )
    scored = []
    for f in pending:
        obs = (
            db.query(BrandObservation)
            .filter(
                BrandObservation.engagement_id == engagement_id,
                BrandObservation.wave_id == f.target_wave_id,
                BrandObservation.metric_code == f.metric_code,
                BrandObservation.brand_slug == f.brand_slug,
                BrandObservation.segment == f.segment,
            )
            .first()
        )
        if obs is None:
            continue
        s = fc.score_forecast(f.point, f.lo, f.hi, obs.value)
        f.actual, f.inside_band, f.abs_error, f.status = (
            s.actual, s.inside_band, s.abs_error, "scored"
        )
        wave = ws.get(f.target_wave_id)
        scored.append({
            "metric": f.metric_code, "label": label_for(f.metric_code),
            "wave": wave.label if wave else None,
            "point": f.point, "actual": s.actual,
            "inside_band": s.inside_band, "abs_error": s.abs_error, "note": s.note,
        })
    return {"scored": scored, "n": len(scored)}


def forecast_track_record(db: Session, engagement_id: str) -> Dict[str, Any]:
    """The live record: every scored forecast for this engagement."""
    rows = (
        db.query(BrandForecast)
        .filter(BrandForecast.engagement_id == engagement_id,
                BrandForecast.status == "scored")
        .all()
    )
    if not rows:
        return {"available": False,
                "reason": "Aún no hay pronósticos puntuados: el track record se "
                          "construye a partir de la próxima ola."}
    hits = sum(1 for r in rows if r.inside_band)
    return {
        "available": True,
        "n": len(rows),
        "hit_rate": hits / len(rows) * 100.0,
        "mae": sum(r.abs_error or 0 for r in rows) / len(rows),
        "detail": [
            {"metric": r.metric_code, "label": label_for(r.metric_code),
             "point": r.point, "actual": r.actual, "inside_band": r.inside_band,
             "abs_error": r.abs_error, "rule": r.rule}
            for r in rows
        ],
    }


def rule_backtest(db: Session, engagement_id: str, segment: str = "total") -> Dict[str, Any]:
    """Rank the naive forecast rules on this engagement's own history."""
    ents = brands(db, engagement_id)
    focal = next((b.slug for b in ents if b.is_focal), None)
    if not focal:
        return {"available": False, "reason": "El encargo no declara marca focal."}

    per_rule: Dict[str, List[float]] = {}
    n_series = 0
    for m in core_metrics():
        values = [r["value"] for r in _series_for(db, engagement_id, m.code, focal, segment)
                  if r["value"] is not None]
        if len(values) <= fc.MIN_HISTORY:
            continue
        n_series += 1
        for res in fc.backtest_rules(values):
            if res.mae is not None:
                per_rule.setdefault(res.rule, []).append(res.mae)

    if not per_rule:
        return {"available": False,
                "reason": "Historia insuficiente: se requieren al menos tres olas."}

    scored: List[Dict[str, Any]] = [
        {"rule": k, "mae": sum(v) / len(v), "n_series": len(v)} for k, v in per_rule.items()
    ]
    ranked = sorted(scored, key=lambda r: r["mae"])
    return {
        "available": True,
        "ranking": ranked,
        "winner": ranked[0]["rule"],
        "n_series": n_series,
        "note": (
            "Error absoluto medio en pp, ventana expansiva sin mirar hacia adelante. "
            "Si 'trend' queda última, leer estas series como tendencias induce error "
            "sistemático: son estacionarias con ruido muestral."
        ),
    }


# ── S5 · signal filter and decision ledger ────────────────────────────

def signal_filter(
    db: Session, engagement_id: str, wave_code: Optional[str] = None
) -> Dict[str, Any]:
    """What each indicator would need to move to carry a decision."""
    ws = data_waves(db, engagement_id)
    if not ws:
        return {"available": False,
                "reason": "Ninguna ola del encargo tiene observaciones todavía."}
    target = next((w for w in ws if w.code == wave_code), ws[-1])
    ents = brands(db, engagement_id)
    focal = next((b.slug for b in ents if b.is_focal), None)

    rows = (
        db.query(BrandObservation)
        .filter(BrandObservation.engagement_id == engagement_id,
                BrandObservation.wave_id == target.id,
                BrandObservation.brand_slug == focal)
        .all()
    )
    out = []
    for r in rows:
        m = get_metric(r.metric_code)
        if m is None or not m.supports_bands:
            continue
        row = sig.signal_filter_row(r.metric_code, r.value, r.base_n)
        row.update({"label": m.label, "segment": r.segment})
        out.append(row)
    out.sort(key=lambda r: (r["threshold"] is None, r["threshold"] or 0))
    return {
        "available": True,
        "wave": {"code": target.code, "label": target.label},
        "rows": out,
        "note": (
            "Movimiento mínimo detectable al 95% con la base efectiva de cada celda. "
            "Es una herramienta de priorización: indica qué lecturas pueden sostener "
            "una decisión de presupuesto."
        ),
    }


def evaluate_decisions(db: Session, engagement_id: str) -> Dict[str, Any]:
    """Issue verdicts on every open decision whose evaluation wave has landed."""
    ws = {w.id: w for w in waves(db, engagement_id)}
    rows = (
        db.query(BrandDecision)
        .filter(BrandDecision.engagement_id == engagement_id)
        .all()
    )
    results, verdicts = [], []
    for d in rows:
        base_obs = _decision_obs(db, engagement_id, d, d.baseline_wave_id)
        targ_obs = _decision_obs(db, engagement_id, d, d.target_wave_id) if d.target_wave_id else None
        m = get_metric(d.metric_code)

        v = ldg.evaluate(
            d.metric_code,
            base_obs.value if base_obs else d.baseline_value,
            base_obs.base_n if base_obs else None,
            targ_obs.value if targ_obs else None,
            targ_obs.base_n if targ_obs else None,
            higher_is_better=m.higher_is_better if m else True,
        )
        d.status = v.status
        d.verdict_note = v.note
        d.observed_delta = v.observed_delta
        d.detectable_threshold = v.detectable_threshold
        if base_obs and d.baseline_value is None:
            d.baseline_value = base_obs.value
        verdicts.append(v)

        results.append({
            "id": d.id, "title": d.title, "metric": d.metric_code,
            "label": label_for(d.metric_code), "segment": d.segment,
            "owner": d.owner,
            "baseline_wave": ws[d.baseline_wave_id].label if d.baseline_wave_id in ws else None,
            "target_wave": ws[d.target_wave_id].label if d.target_wave_id in ws else None,
            "baseline_value": d.baseline_value,
            "target_value": targ_obs.value if targ_obs else None,
            "status": v.status, "observed_delta": v.observed_delta,
            "detectable_threshold": v.detectable_threshold, "note": v.note,
        })

    return {"decisions": results, "summary": ldg.summarize(verdicts)}


def _decision_obs(db: Session, engagement_id: str, d: BrandDecision,
                  wave_id: Optional[str]) -> Optional[BrandObservation]:
    if not wave_id:
        return None
    return (
        db.query(BrandObservation)
        .filter(
            BrandObservation.engagement_id == engagement_id,
            BrandObservation.wave_id == wave_id,
            BrandObservation.metric_code == d.metric_code,
            BrandObservation.brand_slug == d.brand_slug,
            BrandObservation.segment == d.segment,
        )
        .first()
    )


# ── S4 · scenarios and sensitivity ────────────────────────────────────

def scenarios_analysis(
    db: Session, engagement_id: str, segment: str = "total"
) -> Dict[str, Any]:
    """S4 — scenarios, rule dispersion, base sensitivity and the stated risks.

    Scenarios qualify how to read the frozen forecast; they never move its numbers. With
    this few waves there is no basis to estimate a macro-to-brand elasticity, and a
    scenario-adjusted point estimate would be fabricated precision.
    """
    ents = brands(db, engagement_id)
    focal = next((b.slug for b in ents if b.is_focal), None)
    if not focal:
        return {"available": False, "reason": "El encargo no declara marca focal."}

    ws = data_waves(db, engagement_id)
    macro = macro_context(db)
    env = macro["_env"]

    disp_objs: List[scn.RuleDispersion] = []
    sensitivities: List[Dict[str, Any]] = []
    for m in core_metrics():
        values = [r["value"] for r in _series_for(db, engagement_id, m.code, focal, segment)
                  if r["value"] is not None]
        if len(values) < 2:
            continue
        base = _expected_base(db, engagement_id, m.code, focal, segment)
        f = fc.issue_forecast(values, base)
        halfwidth = (f.hi - f.lo) / 2.0 if f else None

        d = scn.rule_dispersion(m.code, m.label, values, halfwidth)
        if d:
            disp_objs.append(d)
        if f:
            s = scn.base_sensitivity(f.point, base)
            sensitivities.append({
                "metric_code": m.code, "label": m.label,
                "point": s.point, "expected_base": s.expected_base,
                "rows": s.rows, "note": s.note,
            })

    # Serialised once, at the boundary. The engine's own objects travel through the
    # function; only the response needs them flattened.
    dispersions = [
        {"metric_code": d.metric_code, "label": d.label, "by_rule": d.by_rule,
         "spread": d.spread, "robust": d.robust, "note": d.note}
        for d in disp_objs
    ]
    scenarios = scn.build_scenarios(env)

    return {
        "available": bool(dispersions or scenarios),
        "environment": {k: v for k, v in macro.items() if k != "_env"},
        "scenarios": [
            {"key": s.key, "label": s.label, "assumptions": s.assumptions,
             "band_reading": s.band_reading, "probability_note": s.probability_note,
             "text": s.text}
            for s in scenarios
        ],
        "rule_dispersion": dispersions,
        "base_sensitivity": sensitivities,
        "risks": scn.forecast_risks(disp_objs, len(ws), env),
        "note": (
            "Los escenarios califican cómo leer el pronóstico congelado; no modifican "
            "sus cifras. No se asignan probabilidades: implicarían una distribución "
            "que nadie estimó."
        ),
    }


# ── S5 · vigilance panel and agenda ───────────────────────────────────

def _core_change_assessments(
    db: Session, engagement_id: str, focal: str, segment: str = "total"
) -> List[Dict[str, Any]]:
    """Wave-over-wave verdict for each core indicator, on the last transition."""
    ws = data_waves(db, engagement_id)
    if len(ws) < 2:
        return []
    prev_code, curr_code = ws[-2].code, ws[-1].code

    out: List[Dict[str, Any]] = []
    for m in core_metrics():
        series = {r["wave"]: r for r in _series_for(db, engagement_id, m.code, focal, segment)}
        p, c = series.get(prev_code), series.get(curr_code)
        if not p or not c:
            continue
        a = sig.assess_change(m.code, p["value"], p["base_n"], c["value"], c["base_n"])
        out.append({
            "metric_code": m.code, "label": m.label,
            "delta": a.delta, "threshold": a.threshold, "verdict": a.verdict,
            "note": a.note, "higher_is_better": m.higher_is_better,
        })
    return out


def vigilance_analysis(db: Session, engagement_id: str) -> Dict[str, Any]:
    """S5 — what moved since the last delivery, and the agenda the quarter justifies."""
    ents = brands(db, engagement_id)
    focal = next((b.slug for b in ents if b.is_focal), None)
    if not focal:
        return {"available": False, "reason": "El encargo no declara marca focal."}

    macro = macro_context(db)
    assessments = _core_change_assessments(db, engagement_id, focal)

    scored = (
        db.query(BrandForecast)
        .filter(BrandForecast.engagement_id == engagement_id,
                BrandForecast.status == "scored")
        .all()
    )
    scored_payload = [
        {"metric": f.metric_code, "label": label_for(f.metric_code),
         "point": f.point, "actual": f.actual, "inside_band": f.inside_band,
         "note": ""}
        for f in scored
    ]

    decisions = evaluate_decisions(db, engagement_id)
    category = category_analysis(db, engagement_id)
    funnel = funnel_analysis(db, engagement_id)

    m_sigs = vig.macro_signals(macro.get("factors") or [])
    t_sigs = vig.tracker_signals(assessments)
    f_sigs = vig.forecast_signals(scored_payload)
    d_sigs = vig.decision_signals(decisions.get("decisions") or [])

    agenda = vig.build_agenda(
        f_sigs, t_sigs, d_sigs,
        category.get("divergence_reading") if category.get("available") else None,
        macro.get("note"),
        funnel.get("weakest_step") if funnel.get("available") else None,
    )

    def _pack(sigs):
        return [
            {"source": s.source, "label": s.label, "reading": s.reading,
             "direction": s.direction, "strength": s.strength, "detail": s.detail}
            for s in sigs
        ]

    return {
        "available": True,
        "environment": {k: v for k, v in macro.items() if k != "_env"},
        "signals": {
            "macro": _pack(m_sigs),
            "tracker": _pack(t_sigs),
            "forecast": _pack(f_sigs),
            "decision": _pack(d_sigs),
        },
        "assessments": assessments,
        "agenda": agenda,
        "note": (
            "Solo entran al panel los movimientos que superan —o rozan— el umbral "
            "detectable de su propia base. Lo que queda por debajo no es una señal débil: "
            "es la ausencia de una."
        ),
    }


def check_decision_feasibility(
    db: Session, engagement_id: str, metric_code: str, brand_slug: Optional[str],
    segment: str, baseline_wave_id: str, success_threshold: Optional[float],
) -> Dict[str, Any]:
    """Can this decision ever be evaluated? Run before committing budget to it."""
    obs = (
        db.query(BrandObservation)
        .filter(
            BrandObservation.engagement_id == engagement_id,
            BrandObservation.wave_id == baseline_wave_id,
            BrandObservation.metric_code == metric_code,
            BrandObservation.brand_slug == brand_slug,
            BrandObservation.segment == segment,
        )
        .first()
    )
    check = ldg.check_feasibility(
        metric_code,
        obs.value if obs else None,
        obs.base_n if obs else None,
        success_threshold,
    )
    return {
        "feasible": check.feasible,
        "detectable_threshold": check.detectable_threshold,
        "reason": check.reason,
        "baseline_value": obs.value if obs else None,
        "baseline_base_n": obs.base_n if obs else None,
    }
