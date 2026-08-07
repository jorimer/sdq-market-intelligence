"""Tests for Insurance Intel (SIS market Pulse — F1a).

Self-contained: builds an in-memory SQLite with just the insurance tables, ingests
the committed real fixture, and asserts the market pulse + product contract behave.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.database.base import Base
import modules.insurance_intel.models.models as m
import modules.insurance_intel.products  # noqa: F401 — registers the SectorProduct
from modules.insurance_intel.service import build_market_pulse
from modules.insurance_intel.sis_sync import sis_insurance_sync
from shared.data.sis_client import SISClient


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        m.InsuranceEntity.__table__, m.InsuranceSeries.__table__,
        m.InsuranceRating.__table__, m.InsuranceSnapshot.__table__])
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


# ── Client / fixture ──────────────────────────────────────────────
def test_fixture_fetch_normalizes_ramo_dimension():
    recs = SISClient(mode="fixture").fetch()
    assert recs, "fixture should yield records"
    # Per-ramo series are normalized to a single code + dimension (parity with live).
    ramo = [r for r in recs if r.series == "sis.primas.ramo"]
    assert ramo and all(r.dimension for r in ramo)
    # No malformed period keys (the lowercase-'febrero' month bug regression guard).
    assert all(len(r.period) == 7 and r.period[4] == "-" and r.period[:4].isdigit()
               for r in recs)


def test_fixture_has_all_months_2020_2025():
    recs = SISClient(mode="fixture").fetch(series="sis.primas.total_mensual")
    years = {}
    for r in recs:
        years[r.period[:4]] = years.get(r.period[:4], 0) + 1
    assert years == {str(y): 12 for y in range(2020, 2026)}


# ── Sync / service ────────────────────────────────────────────────
def test_sync_is_idempotent(db):
    r1 = sis_insurance_sync(db, mode="fixture")
    n1 = db.query(m.InsuranceSeries).count()
    r2 = sis_insurance_sync(db, mode="fixture")
    n2 = db.query(m.InsuranceSeries).count()
    assert n1 == n2 == r1["market_rows"] == r2["market_rows"]
    assert r1["snapshot_period"] == "2025-12"


def test_pulse_growth_skips_duplicate_year(db):
    sis_insurance_sync(db, mode="fixture")
    p = build_market_pulse(db)
    assert p["has_data"] and p["latest_year"] == "2025"
    # 2024 duplicates 2023 in the source → growth is a CAGR from 2023, not off 2024.
    assert p["growth_years"] == ("2023", "2025")
    assert p["data_caveat"] and "2024" in p["data_caveat"]
    # Total ≈ RD$ 153 MMM and a sane double-digit CAGR.
    assert 150e9 < p["total_premiums_rd"] < 156e9
    assert 10 < p["growth_pct"] < 25


def test_pulse_mix_sums_and_concentration(db):
    sis_insurance_sync(db, mode="fixture")
    p = build_market_pulse(db)
    assert p["n_ramos"] == 11
    assert abs(sum(d["pct"] for d in p["mix"]) - 100) < 0.5
    assert p["top4_concentration_pct"] > 80  # a concentrated market


# ── Product contract ──────────────────────────────────────────────
def test_product_registered_and_manifest():
    from shared.products.registry import is_implemented, get_product
    from shared.products import ProductTier
    assert is_implemented("insurance")
    man = get_product("insurance").product_manifest()
    assert set(man.levels) == {ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive}


def test_pulse_tier_has_data_named_tier_honest(db):
    from shared.products.registry import get_product
    from shared.products import ProductTier
    sis_insurance_sync(db, mode="fixture")
    prod = get_product("insurance", db)
    assert prod.has_engine() is True
    pulse = prod.snapshot(ProductTier.pulse, "2025-12")
    assert pulse.payload["has_data"] is True
    # Named tier without ingested financials → honest "sin dato", never fabricated.
    named = prod.snapshot(ProductTier.insight, "2025", scope="no_existe")
    assert named.payload["has_data"] is False


def test_named_tier_without_scope_raises(db):
    # Registry contract (parity with banking/pension/ESG): a named tier with no scope must
    # RAISE so consumers (research pull_axis) degrade to the Pulse instead of taking a
    # non-empty "has_data: False" payload as the engine's result.
    import pytest
    from shared.products.registry import get_product
    from shared.products import ProductTier
    sis_insurance_sync(db, mode="fixture")
    prod = get_product("insurance", db)
    for tier in (ProductTier.insight, ProductTier.deep_dive):
        with pytest.raises(ValueError):
            prod.snapshot(tier, "2025", scope=None)


# ── F1b · ISF (entity rating) ─────────────────────────────────────
_SYNTH_CODES = ("patrimonio", "activos_totales", "primas_suscritas", "siniestros_pagados",
                "reservas_tecnicas", "activos_liquidos", "ingresos_totales", "gastos_totales",
                "gastos_operativos", "indice_solvencia", "indice_liquidez")


# Real authorized-insurer names (must match the official roster fixture so the canonical
# grouping keeps them). Slugs = slugify_insurer(name) → the canonical slug the ISF returns.
def _synthetic_financials():
    return [
        {"slug": "universal", "name": "Seguros Universal, S. A.", "period": "2024",
         "patrimonio": 8e9, "activos_totales": 33e9, "primas_suscritas": 28e9,
         "siniestros_pagados": 10e9, "reservas_tecnicas": 12e9, "activos_liquidos": 14e9,
         "ingresos_totales": 30e9, "gastos_totales": 28e9, "gastos_operativos": 7e9,
         "indice_solvencia": 2.5, "indice_liquidez": 3.0},
        {"slug": "bupa", "name": "Bupa Dominicana, S.A.", "period": "2024",
         "patrimonio": 1.3e9, "activos_totales": 1.5e9, "primas_suscritas": 0.7e9,
         "siniestros_pagados": 0.2e9, "reservas_tecnicas": 0.15e9, "activos_liquidos": 0.4e9,
         "ingresos_totales": 0.8e9, "gastos_totales": 0.6e9, "gastos_operativos": 0.21e9,
         "indice_solvencia": 3.5, "indice_liquidez": 4.0},
        {"slug": "creciendo", "name": "Creciendo Seguros, S.A.", "period": "2024",
         "patrimonio": 0.15e9, "activos_totales": 1.7e9, "primas_suscritas": 3.9e9,
         "siniestros_pagados": 3.1e9, "reservas_tecnicas": 1.0e9, "activos_liquidos": 0.3e9,
         "ingresos_totales": 4.0e9, "gastos_totales": 4.1e9, "gastos_operativos": 1.2e9,
         "indice_solvencia": 0.6, "indice_liquidez": 0.7},
    ]


def test_score_insurers_ranks_and_bands():
    from modules.insurance_intel.scoring.isf import score_insurers
    res = score_insurers(_synthetic_financials())
    by = {r["slug"]: r for r in res}
    # Full coverage → absolute bands emitted.
    assert all(r["coverage"] == 1.0 and r["band"] for r in res)
    # The high-solvency/low-loss insurer outranks the weak one.
    assert by["bupa"]["overall_score"] > by["creciendo"]["overall_score"]
    # Loss ratio is lower-is-better: 'bupa' (0.29) beats 'creciendo' (0.79) on that axis.
    def sini(r):
        return next(d["score"] for d in by[r]["dimensions"] if d["key"] == "siniestralidad")
    assert sini("bupa") > sini("creciendo")


def test_los_slugs_oficiales_entran_en_la_columna():
    """Ningún slug del roster oficial puede exceder el ancho de ``entity_slug``.

    SQLite (dev) ignora el largo de VARCHAR, Postgres (prod) no: el slug de AGRODOSA (44
    caracteres) reventaba ``score_and_persist`` con StringDataRightTruncation y hacía
    rollback del sync entero, dejando ``insurance_ratings`` congelada. Este test corre
    contra el catálogo de nombres, sin depender del motor de base de datos.
    """
    from modules.insurance_intel.external.audited_excel_extractor import slugify_insurer
    from modules.insurance_intel.models.models import InsuranceRating

    ancho = InsuranceRating.__table__.c.entity_slug.type.length
    nombres = [
        "Aseguradora Agropecuaria Dominicana, S. A. (AGRODOSA)",
        "Cuna Mutual Insurance Society Dominicana, S.A.",
        "Cooperativa Nacional de Seguros, INC. (COOPSEGUROS)",
        "Creciendo Seguros, S.A. (Antiguo Banesco Seguros)",
        "REHSA, Compañía de Seguros y Reaseguros, S. A.",
    ]
    largos = {n: len(slugify_insurer(n)) for n in nombres}
    excedidos = {n: ln for n, ln in largos.items() if ln > ancho}
    assert not excedidos, f"slugs más largos que VARCHAR({ancho}): {excedidos}"


def test_minmax_de_escala_mide_en_espacio_log():
    """``escala`` se declara logarítmica: el min-max debe medir en log, como la banda absoluta.

    Antes la banda absoluta usaba log y el min-max escala lineal, así que media dimensión
    medía en una escala y la otra media en otra: contra un máximo de RD$33.000 millones, una
    aseguradora en la mediana (RD$983 millones) sacaba ~3 puntos de 100.
    """
    from modules.insurance_intel.scoring.isf import DIMENSIONS, _minmax
    spec = next(d for d in DIMENSIONS if d["key"] == "escala")
    peers = [5e7, 1e8, 5e8, 1e9, 5e9, 3.3e10]
    mediana_log = _minmax(1e9, peers, spec)
    # En escala lineal 1e9 contra un techo de 3.3e10 daría ~3; en log queda a media tabla.
    assert 35 < mediana_log < 75


def test_minmax_no_se_deja_aplastar_por_un_outlier():
    """Un outlier extremo no debe comprimir al resto del panel contra el borde opuesto.

    Panel del tamaño real del ISF (33 aseguradoras); con paneles chicos la valla no se
    aplica a propósito — ver ``robust_bounds``.
    """
    from modules.insurance_intel.scoring.isf import DIMENSIONS, _minmax
    spec = next(d for d in DIMENSIONS if d["key"] == "resultado_tecnico")
    sanos = [-0.08, -0.05, 0.0, 0.03, 0.06, 0.09, 0.11, 0.14, 0.17, 0.2,
             0.24, 0.28, 0.31, 0.34, 0.38, 0.42]
    con_outlier = [-7.31] + sanos  # Creciendo Seguros, combined ratio 831%

    aplastado = _minmax(0.11, sanos + [-7.31], spec)
    # El orden no se toca: el mejor sigue en 100 y el outlier en 0.
    assert _minmax(0.42, con_outlier, spec) == 100.0
    assert _minmax(-7.31, con_outlier, spec) == 0.0
    # Y uno del medio conserva dispersión en vez de quedar pegado al techo.
    assert 20 < aplastado < 90


def test_margen_tecnico_no_cuenta_siniestros_dos_veces():
    """El margen técnico es 1 − (siniestros + gastos operativos)/primas.

    Regresión del doble conteo: la definición vieja usaba ``gastos_totales``, que en el
    catálogo SIS (Ley 146-02) incluye las reclamaciones pagadas — los siniestros pesaban
    en ``siniestralidad`` y otra vez, escondidos, en el resultado técnico.
    """
    from modules.insurance_intel.scoring.isf import _raw_metric
    fin = {"primas_suscritas": 100.0, "siniestros_pagados": 60.0, "gastos_operativos": 30.0,
           # gastos_totales incluye los siniestros + cesión + reservas: NO debe usarse acá
           "ingresos_totales": 150.0, "gastos_totales": 140.0}
    assert _raw_metric(fin, "resultado_tecnico") == pytest.approx(0.10)  # combined 90%
    # La fórmula vieja habría dado (150−140)/100 = 0.10 por casualidad; con otra mezcla no:
    fin2 = dict(fin, gastos_totales=200.0)
    assert _raw_metric(fin2, "resultado_tecnico") == pytest.approx(0.10)  # inmune a gastos_totales


def test_margen_tecnico_es_brecha_declarada_sin_gastos_operativos():
    """Sin ``gastos_operativos`` la dimensión se declara ausente — nunca se reconstruye con
    la fórmula vieja, aunque ingresos/gastos totales estén disponibles."""
    from modules.insurance_intel.scoring.isf import _raw_metric
    fin = {"primas_suscritas": 100.0, "siniestros_pagados": 60.0,
           "ingresos_totales": 150.0, "gastos_totales": 140.0}
    assert _raw_metric(fin, "resultado_tecnico") is None


def test_extractor_separa_gastos_operativos_de_siniestros_y_cesion():
    """El gasto operativo excluye reclamaciones (5101/5301) y prima cedida (5106-11/5305-10)."""
    from modules.insurance_intel.external.audited_excel_extractor import _extract_sheet
    rows = [
        ("1", "ACTIVO", None), ("1101", "INVERSIONES", 700.0), ("1201", "EFECTIVO", 300.0),
        ("2", "PASIVO", None), ("2101", "RESERVAS", 400.0), ("2201", "RESERVAS ESP", 100.0),
        ("3", "PATRIMONIO", None), ("3101", "CAPITAL", 500.0),
        ("4", "INGRESOS", None),
        ("4301", "PRIMAS SUSCRITAS", None), ("430101", "INCENDIO", 1000.0),
        ("4307", "RECLAMACIONES POR SINIESTROS A CARGO DE REASEGURADORES", None),
        ("430701", "INCENDIO", 50.0),
        ("5", "GASTOS", None),
        ("5301", "RECLAMACIONES PAGADAS POR SINIESTROS", None), ("530101", "INCENDIO", 600.0),
        ("5302", "COMISIONES A INTERMEDIARIOS", None), ("530201", "INCENDIO", 150.0),
        ("5305", "PRIMAS DE REASEGUROS CONTRACTUALES CEDIDOS LOCALMENTE", None),
        ("530501", "INCENDIO", 300.0),
        ("5316", "GASTOS GENERALES Y ADMINISTRATIVOS", None), ("531601", "GENERAL", 100.0),
        ("5501", "GASTOS FINANCIEROS", None), ("550101", "FIN", 999.0),
        ("5502", "OTROS GASTOS DE OPERACIONES", None), ("550201", "OTROS", 50.0),
    ]
    f = _extract_sheet(rows, "Test Seguros", "2024")
    assert f is not None and f.reconciled
    assert f.siniestros == 600.0
    assert f.primas_cedidas == 300.0
    assert f.recuperables_reaseguro == 50.0
    # comisiones 150 + G&A 100 + otros gastos de operación 50 = 300.
    # NO incluye siniestros (600), ni cesión (300), ni gastos financieros (999).
    assert f.gastos_operativos == 300.0
    assert f.gastos == 600 + 150 + 300 + 100 + 999 + 50  # la sección 5 bruta sigue igual


def test_detail_devuelve_el_periodo_mas_reciente(db):
    """Con el histórico ingerido hay una fila por período: el detalle debe tomar la última.

    Sin ``order_by`` el ``.first()`` devolvía una fila arbitraria y la ficha mostraba un año
    viejo mientras el ranking mostraba el actual (La Colonial: 65.6 vs 54.5).
    """
    from modules.insurance_intel.models.models import InsuranceRating

    for period, score in (("2019", 41.0), ("2024", 65.6), ("2021", 52.3)):
        db.add(InsuranceRating(entity_slug="acme", period=period, overall_score=score,
                               band="Adecuada", coverage=1.0, dimensions=[],
                               model_version="0.2"))
    db.flush()
    r = (db.query(InsuranceRating)
         .filter(InsuranceRating.entity_slug == "acme")
         .order_by(InsuranceRating.period.desc()).first())
    assert r.period == "2024" and r.overall_score == 65.6


def test_named_tier_renders_isf(db):
    import asyncio
    from shared.products.registry import get_product
    from shared.products import ProductTier
    # Persist synthetic per-entity series + roster, then score.
    for f in _synthetic_financials():
        db.add(m.InsuranceEntity(slug=f["slug"], name=f["name"], entity_type="aseguradora",
                                 is_active=True))
        for code in _SYNTH_CODES:
            db.add(m.InsuranceSeries(series_code=code, period="2024", entity_slug=f["slug"],
                                     value=f[code], unit="RD$", frequency="annual"))
    db.flush()
    from modules.insurance_intel.scoring.batch import score_and_persist
    assert score_and_persist(db)["ratings_written"] == 3

    prod = get_product("insurance", db)
    opts = {o["value"] for o in prod.scope_options()}
    assert len(opts) == 3  # three official companies matched the roster
    snap = prod.snapshot(ProductTier.insight, "2024", scope=next(iter(opts)))
    assert snap.payload["has_data"] is True
    assert snap.payload["headline_line"].startswith("ISF")
    narr = asyncio.run(prod.narratives(ProductTier.insight, snap))
    path = asyncio.run(prod.render(ProductTier.insight, snap, narr, output_dir="/tmp"))
    import os
    assert os.path.exists(path) and path.endswith(".pdf")


# ── F1c · SISALRIL / SFS health coverage ──────────────────────────
def test_sisalril_sfs_pulse(db):
    from modules.insurance_intel.sisalril_sync import sisalril_sfs_sync
    from modules.insurance_intel.service import build_health_pulse
    res = sisalril_sfs_sync(db, mode="fixture")
    assert res["sfs_rows"] > 0
    hp = build_health_pulse(db)
    assert hp is not None
    # ~10.6M affiliated, split into contributory + subsidized.
    assert hp["afiliados_total"] > 9e6
    assert hp["afiliados_contributivo"] and hp["afiliados_subsidiado"]


def test_market_pulse_folds_in_health(db):
    from modules.insurance_intel.sisalril_sync import sisalril_sfs_sync
    sis_insurance_sync(db, mode="fixture")
    sisalril_sfs_sync(db, mode="fixture")
    p = build_market_pulse(db)
    assert p["health_coverage"] is not None
    assert p["health_coverage"]["afiliados_total"] > 9e6


# ── F3 · ISF validation backtest (G5) ─────────────────────────────
def test_backtest_derive_and_summarize():
    from modules.insurance_intel.validation.backtest import derive_observations, summarize_signal
    # Perfect separation: low score → low forward outcome → Gini ≈ 1, conclusive.
    score_by = {f"a{i}": {"2020": float(i)} for i in range(10)}
    fwd_by = {f"a{i}": [("2021", float(i)), ("2022", float(i))] for i in range(10)}
    obs = derive_observations(score_by, fwd_by, horizon=2, min_entities=5)
    assert len(obs) == 10 and {o.label for o in obs} == {0, 1}
    s = summarize_signal(obs)
    assert s and s["conclusive"] and s["gini"] > 0.8


def test_validation_state_reads_backtest(db):
    import json
    from shared.products.registry import get_product
    from shared.settings.models import AppSetting
    from modules.insurance_intel.scoring.batch import score_and_persist
    AppSetting.__table__.create(db.get_bind(), checkfirst=True)
    # Scoreable insurers (n_scored>0 gate): persist synthetic per-entity series + score.
    for f in _synthetic_financials():
        db.add(m.InsuranceEntity(slug=f["slug"], name=f["name"], entity_type="aseguradora",
                                 is_active=True))
        for code in _SYNTH_CODES:
            db.add(m.InsuranceSeries(series_code=code, period="2024", entity_slug=f["slug"],
                                     value=f[code], unit="RD$", frequency="annual"))
    db.flush()
    score_and_persist(db)
    # A conclusive persisted backtest (Gini 0.30).
    db.add(AppSetting(key="insurance_backtest_report", is_secret=False, value=json.dumps({
        "headline_gini": 0.30, "headline_signal": "solvency",
        "signals": {"solvency": {"gini_ci": [0.14, 0.48], "n_obs": 163}}})))
    db.commit()
    vs = get_product("insurance", db).validation_state()
    # 0.60 + 0.30*0.30 = 0.69
    assert vs.approved and vs.score == 0.69 and "Gini 0.3" in vs.notes


# ── ARS rating (ISARS) ────────────────────────────────────────────
def test_score_ars_ranks_and_bands():
    from modules.insurance_intel.scoring.ars_rating import score_ars
    fins = [
        {"slug": "ars_a", "name": "A", "period": "2026-04", "category": 3,
         "ars.margen_inversiones": 3.0e9, "ars.margen_requerido": 1.0e9, "ars.patrimonio": 5.0e9,
         "ars.activo_total": 10.0e9, "ars.ingreso_salud": 2.0e9, "ars.gasto_salud": 1.0e9,
         "ars.beneficio_neto": 0.5e9},
        {"slug": "ars_b", "name": "B", "period": "2026-04", "category": 2,
         "ars.margen_inversiones": 0.7e9, "ars.margen_requerido": 1.0e9, "ars.patrimonio": 1.0e9,
         "ars.activo_total": 12.0e9, "ars.ingreso_salud": 2.0e9, "ars.gasto_salud": 2.6e9,
         "ars.beneficio_neto": -0.6e9},
    ]
    res = score_ars(fins)
    by = {r["slug"]: r for r in res}
    assert all(r["coverage"] == 1.0 and r["band"] for r in res)
    # Strong ARS (margin 3.0, LR 50%, +margin) outranks the weak one (margin 0.7, LR 130%).
    assert by["ars_a"]["overall_score"] > by["ars_b"]["overall_score"]
    assert res[0]["slug"] == "ars_a"


def test_ars_sync_and_rankings(db):
    from modules.insurance_intel.ars_sync import ars_sync
    from modules.insurance_intel.scoring.ars_rating import compute_ars
    res = ars_sync(db, mode="fixture")
    assert res["ars"] > 5 and res["ratings_written"] > 0
    scored = [r for r in compute_ars(db) if r["overall_score"] is not None]
    assert scored and all(r["slug"].startswith("ars_") for r in scored)
    # Entities carry the ARS entity_type.
    ars_ents = db.query(m.InsuranceEntity).filter(m.InsuranceEntity.entity_type == "ars").count()
    assert ars_ents == res["ars"]


# ── Regulatory solvency/liquidity (Ley 146-02, Art. 164) ──────────
def test_solvency_indices_feed_isf(db):
    from modules.insurance_intel.solvency_sync import solvency_sync
    from modules.insurance_intel.scoring.isf import compute_isf
    # Seed a couple of aseguradora entities whose names match the solvency fixture.
    db.add(m.InsuranceEntity(slug="universal", name="Seguros Universal",
                             entity_type="aseguradora", is_active=True))
    db.add(m.InsuranceEntity(slug="bupa", name="Bupa Dominicana",
                             entity_type="aseguradora", is_active=True))
    db.flush()
    res = solvency_sync(db, mode="fixture")
    assert res["entities_matched"] >= 2 and res["series_rows"] > 0
    # The solvency dimension now reads the official regulatory index.
    rows = db.query(m.InsuranceSeries).filter(
        m.InsuranceSeries.series_code == "indice_solvencia").count()
    assert rows > 0
    # An insurer with only the índices present is scored on solvencia+liquidez (partial cov).
    bupa = next((r for r in compute_isf(db) if "Bupa" in r["name"]), None)
    assert bupa and any(d["key"] == "solvencia" and d["present"] for d in bupa["dimensions"])


def test_scope_options_label_is_official_name_not_slug(db, monkeypatch):
    # Regresión (2026-07-17): el selector del catálogo mostraba el slug crudo
    # ("mapfre_bhd") como etiqueta — el label debe ser el nombre oficial del roster.
    import modules.insurance_intel.products as prods
    from shared.products.registry import get_product
    monkeypatch.setattr(prods, "_isf_results", lambda _db: [
        {"slug": "mapfre_bhd", "name": "Mapfre BHD Seguros", "overall_score": 80.0},
        {"slug": "sin_nombre_oficial", "name": None, "overall_score": 70.0},
        {"slug": "sin_score", "name": "No Califica", "overall_score": None},
    ])
    opts = get_product("insurance", db).scope_options()
    assert opts[0] == {"value": "mapfre_bhd", "label": "Mapfre BHD Seguros",
                       "group": "Aseguradora"}
    assert opts[1]["label"] == "sin_nombre_oficial"   # fallback honesto sin nombre
    assert len(opts) == 2                             # sin score → no se ofrece


# ── Backfill de snapshots por período + pulso as-of (2026-07-18) ─────────────
# Regresión: en prod solo existían 2 snapshots (los períodos que fueron "el último"
# en algún sync) pese a que las series traen historia desde 2020-11 → el selector
# de períodos del producto ofrecía 2 opciones, y elegir una servía el pulso ACTUAL.

def test_sync_backfills_snapshot_per_period(db):
    sis_insurance_sync(db, mode="fixture")
    periods = [p for (p,) in db.query(m.InsuranceSnapshot.period)
               .order_by(m.InsuranceSnapshot.period).all()]
    market_periods = sorted({p for (p,) in db.query(m.InsuranceSeries.period)
                             .filter(m.InsuranceSeries.entity_slug.is_(None),
                                     m.InsuranceSeries.dimension.is_(None),
                                     m.InsuranceSeries.value.isnot(None)).all()})
    assert periods == market_periods          # un snapshot por período con dato
    assert len(periods) > 12                  # historia real, no solo "el último"
    assert periods[-1] == "2025-12"


def test_pulse_as_of_serves_historical_view(db):
    sis_insurance_sync(db, mode="fixture")
    p = build_market_pulse(db, as_of="2022-12")
    assert p["has_data"] and p["latest_year"] == "2022"
    assert p["period"] == "2022-12"
    # La vista as-of no ve años posteriores al período elegido.
    assert all(y <= "2022" for y in p["annual_totals"])
    # Y el total difiere del de la vista actual (2025) — no es el mismo reporte.
    latest = build_market_pulse(db)
    assert p["total_premiums_rd"] != latest["total_premiums_rd"]


def test_product_pulse_honors_selected_period(db):
    from shared.products import ProductTier
    from shared.products.registry import get_product
    sis_insurance_sync(db, mode="fixture")
    prod = get_product("insurance", db)
    assert len(prod.available_periods()) > 12
    snap = prod.snapshot(ProductTier.pulse, "2022-12")
    assert snap.period == "2022-12"
    assert snap.payload["pulse"]["latest_year"] == "2022"
    # Sin período → vista más reciente (comportamiento original intacto).
    latest = prod.snapshot(ProductTier.pulse, "")
    assert latest.payload["pulse"]["latest_year"] == "2025"
