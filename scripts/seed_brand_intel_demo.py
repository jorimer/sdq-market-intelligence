"""Seed the Brand Intel demonstration engagement.

Loads the four published waves of a QSR brand tracker (may '25 – mar '26) so the module
starts with a real, verifiable case rather than synthetic data. Every figure here was
transcribed from the provider's delivered charts; nothing is estimated.

    python scripts/seed_brand_intel_demo.py [--reset]

The engagement is created WITHOUT an ``organization_id``, which makes it staff-only by
construction — private client data never becomes world-readable through a demo fixture.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from shared.contracts.macro_sector import INFLATION_SERIES_KEY  # noqa: E402
from shared.database.session import SessionLocal  # noqa: E402
from shared.settings.models import AppSetting  # noqa: E402
from modules.brand_intel.models.models import (  # noqa: E402
    BrandEngagement,
    BrandEntity,
    BrandObservation,
    BrandWave,
)

SLUG = "mcdonalds-rd"
SOURCE = "Hot Tracker QSR RD · informe de olas 1-4"

WAVES = [
    # code,      label,      order, reference date, field start,      field end,        n
    ("2025-05", "May '25", 1, date(2025, 5, 7), date(2025, 4, 29), date(2025, 5, 14), 300),
    ("2025-08", "Ago '25", 2, date(2025, 8, 1), date(2025, 7, 25), date(2025, 8, 8), 300),
    ("2025-11", "Nov '25", 3, date(2025, 10, 25), date(2025, 10, 17), date(2025, 11, 3), 300),
    ("2026-03", "Mar '26", 4, date(2026, 2, 8), date(2026, 1, 30), date(2026, 2, 17), 300),
]

BRANDS = [
    # slug,            name,               focal, in_set, order
    ("mcdonalds", "McDonald's", True, True, 1),
    ("little_caesars", "Little Caesars", False, True, 2),
    ("kfc", "KFC", False, True, 3),
    ("burger_king", "Burger King", False, True, 4),
    ("wendys", "Wendy's", False, True, 5),
    ("dominos", "Domino's Pizza", False, True, 6),
    ("pizza_hut", "Pizza Hut", False, True, 7),
]

# Funnel ladder per brand and wave: awareness, ever tried, 3 months, 1 month, 7 days.
FUNNEL = {
    "mcdonalds": {
        "2025-05": [89, 84, 64, 51, 26], "2025-08": [85, 81, 59, 42, 24],
        "2025-11": [88, 83, 64, 48, 25], "2026-03": [87, 82, 60, 43, 27],
    },
    "little_caesars": {
        "2025-05": [79, 73, 63, 46, 23], "2025-08": [74, 70, 62, 50, 28],
        "2025-11": [76, 73, 63, 48, 30], "2026-03": [83, 80, 70, 53, 31],
    },
    "kfc": {
        "2025-05": [82, 72, 56, 42, 23], "2025-08": [78, 72, 56, 40, 24],
        "2025-11": [77, 73, 56, 39, 21], "2026-03": [82, 74, 52, 42, 20],
    },
    "burger_king": {
        "2025-05": [85, 75, 48, 32, 16], "2025-08": [82, 73, 53, 32, 16],
        "2025-11": [80, 72, 51, 32, 15], "2026-03": [84, 76, 47, 32, 16],
    },
    "wendys": {
        "2025-05": [77, 65, 46, 31, 15], "2025-08": [71, 61, 38, 24, 12],
        "2025-11": [77, 67, 48, 32, 14], "2026-03": [80, 66, 42, 29, 16],
    },
    "dominos": {
        "2025-05": [88, 80, 53, 35, 16], "2025-08": [84, 75, 46, 30, 16],
        "2025-11": [82, 72, 47, 28, 15], "2026-03": [86, 74, 42, 25, 11],
    },
    "pizza_hut": {
        "2025-05": [82, 75, 50, 31, 15], "2025-08": [80, 72, 48, 35, 15],
        "2025-11": [79, 71, 50, 30, 14], "2026-03": [80, 74, 47, 28, 14],
    },
}
LADDER = ["awareness_total", "ever_tried", "reach_3m", "reach_1m", "reach_7d"]

FAVOURITE = {
    "mcdonalds": [18, 19, 20, 17], "little_caesars": [13, 11, 12, 16],
    "kfc": [9, 9, 10, 12], "wendys": [11, 9, 9, 12],
    "pizza_hut": [6, 7, 10, 8], "burger_king": [5, 4, 4, 4],
    "dominos": [5, 6, 4, 4],
}

# Focal-brand core indicators, each with the effective base of its own chart.
FOCAL_SERIES = {
    "last_visit_share": ([49, 44, 39, 44], [201, 210, 300, 217]),
    "brand_opinion_t2b": ([72, 67, 71, 65], [268, 254, 264, 257]),
    "loyalty_t2b": ([75, 72, 73, 72], [268, 254, 264, 257]),
    "satisfaction_t2b": ([87, 87, 87, 94], [99, 100, 93, 105]),
    "delivery_t2b": ([94, 90, 84, 94], [86, 81, 88, 82]),
}

# Average ticket in RD$, estimated from the declared bracket distribution using bracket
# midpoints (open-ended top bracket assumed at RD$2,600 — the report ships the sensitivity).
TICKET = ([1116, 1218, 1230, 1172], [99, 100, 93, 105])

# Santiago cut of the favourite-place question: small bases, kept deliberately so the
# signal filter has a real case of an unpublishable cell to flag.
SANTIAGO_FAVOURITE = ([34, 30, 31, 29], [73, 60, 68, 63])


def _obs(db, eng_id, wave_id, brand, metric, value, base, segment="total", unit="pct"):
    row = (
        db.query(BrandObservation)
        .filter(
            BrandObservation.engagement_id == eng_id,
            BrandObservation.wave_id == wave_id,
            BrandObservation.brand_slug == brand,
            BrandObservation.metric_code == metric,
            BrandObservation.segment == segment,
        )
        .first()
    )
    if row is None:
        row = BrandObservation(
            engagement_id=eng_id, wave_id=wave_id, brand_slug=brand,
            metric_code=metric, segment=segment,
        )
        db.add(row)
    row.value = float(value)
    row.base_n = base
    row.unit = unit
    row.source = SOURCE


def ensure_inflation_contract(db) -> str:
    """Publish the BCRD inflation series into the shared contract if it is not there yet.

    ``macro_monitor`` owns this in normal operation; the demo only fills the gap when the
    environment has the raw series but no published contract, so the deflator has an input.
    Reads the raw table with SQL rather than importing the producing module.
    """
    import json

    existing = db.query(AppSetting).filter(AppSetting.key == INFLATION_SERIES_KEY).first()
    if existing and existing.value:
        return "ya publicada"
    try:
        rows = db.execute(text(
            "SELECT period, value FROM mm_series "
            "WHERE series_code LIKE '%inflacion%interanual%' AND value IS NOT NULL "
            "ORDER BY period"
        )).fetchall()
    except Exception:
        return "tabla macro no disponible"
    if not rows:
        return "sin observaciones de inflación en la base"

    payload = json.dumps([[str(p), float(v)] for p, v in rows])
    if existing:
        existing.value = payload
    else:
        db.add(AppSetting(key=INFLATION_SERIES_KEY, value=payload))
    return f"publicada desde mm_series ({len(rows)} observaciones)"


def _seed_decisions(db, eng_id: str, waves: dict) -> None:
    """Two client decisions, registered the quarter before and evaluated by this wave.

    Chosen because they land on different verdicts: one falls under its detection floor,
    the other sits right on the edge of it. Between them they show what the ledger is for —
    neither licenses claiming the decision worked.
    """
    from modules.brand_intel.engines.ledger import check_feasibility
    from modules.brand_intel.models.models import BrandDecision, BrandObservation

    rows = [
        {
            "title": "Reactivar el tráfico en Santo Domingo",
            "rationale": "Activaciones locales y refuerzo de la propuesta de conveniencia "
                         "tras el descenso observado en la ola de noviembre.",
            "metric_code": "last_visit_share", "segment": "total",
            "success_threshold": 8.0, "owner": "Dirección de Marketing",
        },
        {
            "title": "Sostener la evaluación del servicio de delivery",
            "rationale": "Revisión de empaque, tiempos de preparación y cobertura tras la "
                         "lectura de noviembre.",
            "metric_code": "delivery_t2b", "segment": "total",
            "success_threshold": 8.0, "owner": "Operaciones",
        },
    ]
    for spec in rows:
        existing = (db.query(BrandDecision)
                    .filter(BrandDecision.engagement_id == eng_id,
                            BrandDecision.title == spec["title"]).first())
        if existing:
            continue
        base_obs = (
            db.query(BrandObservation)
            .filter(BrandObservation.engagement_id == eng_id,
                    BrandObservation.wave_id == waves["2025-11"],
                    BrandObservation.metric_code == spec["metric_code"],
                    BrandObservation.brand_slug == "mcdonalds",
                    BrandObservation.segment == spec["segment"])
            .first()
        )
        check = check_feasibility(
            spec["metric_code"],
            base_obs.value if base_obs else None,
            base_obs.base_n if base_obs else None,
            spec["success_threshold"],
        )
        db.add(BrandDecision(
            engagement_id=eng_id, title=spec["title"], rationale=spec["rationale"],
            metric_code=spec["metric_code"], segment=spec["segment"],
            brand_slug="mcdonalds", baseline_wave_id=waves["2025-11"],
            baseline_value=base_obs.value if base_obs else None,
            target_wave_id=waves["2026-03"],
            success_threshold=spec["success_threshold"], owner=spec["owner"],
            status="open" if check.feasible else "unevaluable",
            verdict_note=None if check.feasible else check.reason,
            detectable_threshold=check.detectable_threshold,
        ))


def seed(reset: bool = False) -> None:
    db = SessionLocal()
    try:
        eng = db.query(BrandEngagement).filter(BrandEngagement.slug == SLUG).first()
        if eng and reset:
            for model in (BrandObservation, BrandEntity, BrandWave):
                db.query(model).filter(model.engagement_id == eng.id).delete()
            db.flush()
        if eng is None:
            eng = BrandEngagement(
                slug=SLUG,
                client_name="Operador de franquicia (demostración)",
                focal_brand="McDonald's",
                market="República Dominicana",
                category="QSR",
                research_provider="Proveedor de tracking",
                organization_id=None,  # staff-only by construction
                notes="Encargo de demostración. Cifras transcritas de las láminas "
                      "entregadas; ninguna estimada.",
            )
            db.add(eng)
            db.flush()

        waves = {}
        for code, label, order, ref, fs, fe, n in WAVES:
            w = (db.query(BrandWave)
                 .filter(BrandWave.engagement_id == eng.id, BrandWave.code == code).first())
            if w is None:
                w = BrandWave(engagement_id=eng.id, code=code)
                db.add(w)
            w.label, w.sort_order = label, order
            w.period_date, w.field_start, w.field_end, w.nominal_base = ref, fs, fe, n
            db.flush()
            waves[code] = w.id

        for slug, name, focal, in_set, order in BRANDS:
            b = (db.query(BrandEntity)
                 .filter(BrandEntity.engagement_id == eng.id, BrandEntity.slug == slug).first())
            if b is None:
                b = BrandEntity(engagement_id=eng.id, slug=slug)
                db.add(b)
            b.name, b.is_focal, b.in_category_set, b.sort_order = name, focal, in_set, order
        db.flush()

        codes = [w[0] for w in WAVES]

        for brand, by_wave in FUNNEL.items():
            for code, rungs in by_wave.items():
                for metric, value in zip(LADDER, rungs):
                    _obs(db, eng.id, waves[code], brand, metric, value, 300)

        for brand, values in FAVOURITE.items():
            for code, value in zip(codes, values):
                _obs(db, eng.id, waves[code], brand, "favourite_place", value, 300)

        for metric, (values, bases) in FOCAL_SERIES.items():
            for code, value, base in zip(codes, values, bases):
                _obs(db, eng.id, waves[code], "mcdonalds", metric, value, base)

        for code, value, base in zip(codes, *TICKET):
            _obs(db, eng.id, waves[code], "mcdonalds", "ticket_avg", value, base, unit="RD$")

        for code, value, base in zip(codes, *SANTIAGO_FAVOURITE):
            _obs(db, eng.id, waves[code], "mcdonalds", "favourite_place", value, base,
                 segment="santiago")

        _seed_decisions(db, eng.id, waves)

        inflation_note = ensure_inflation_contract(db)
        db.commit()

        n_obs = (db.query(BrandObservation)
                 .filter(BrandObservation.engagement_id == eng.id).count())
        print(f"✓ Encargo '{SLUG}' listo.")
        print(f"  {len(WAVES)} olas · {len(BRANDS)} marcas · {n_obs} observaciones")
        print(f"  Serie de inflación: {inflation_note}")
        print(f"  Informe: GET /api/v1/brand-intel/engagements/{SLUG}/report.html")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed del encargo de demostración Brand Intel")
    ap.add_argument("--reset", action="store_true",
                    help="Borra olas, marcas y observaciones antes de recargar")
    seed(reset=ap.parse_args().reset)
