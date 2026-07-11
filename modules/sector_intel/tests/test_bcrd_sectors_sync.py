"""Tests for the BCRD value-added sector connector + sync (Eje 3 Gate A).

All offline: the pure builder is fed synthetic maps, and the sync runs against a
fixture-mode client (the committed ``bcrd_sectors.json``). No network.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.bcrd_sectors import (
    BCRDSectorsClient,
    BCRDSectorsError,
    SECTORS,
    TOTAL_LABEL,
    VAR_GROWTH,
    VAR_SIZE,
    _annual_by_sector,
    _complete_year_columns,
    _norm,
    build_sector_records,
)
from modules.sector_intel.models.models import (  # noqa: F401 — register tables
    Sector,
    SectorVariable,
)
from modules.sector_intel.sectors_sync import bcrd_sectores_sync

LABELS = [label for _slug, label, _name in SECTORS]  # all 17 leaf labels


def _nominal(year_values):
    """Build a full nominal map (all 17 leaves + Valor Agregado = their sum).

    ``year_values``: ``{label: {year: value}}`` covering every leaf. The
    builder is fail-closed, so a partial map would (correctly) raise.
    """
    nominal = {_norm(lbl): dict(year_values[lbl]) for lbl in LABELS}
    years = {y for d in year_values.values() for y in d}
    nominal[_norm(TOTAL_LABEL)] = {
        y: sum(year_values[lbl].get(y, 0.0) for lbl in LABELS) for y in years
    }
    return nominal


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


# ── Pure builder ──────────────────────────────────────────────────
def test_size_is_share_of_value_added():
    vals = {lbl: {2024: 10.0} for lbl in LABELS}
    vals[LABELS[0]][2024] = 40.0   # Agropecuario
    vals[LABELS[4]][2024] = 60.0   # Construcción
    va = 40.0 + 60.0 + 10.0 * (len(LABELS) - 2)  # = 250
    recs = build_sector_records(_nominal(vals), {}, url=None)
    sizes = {r.dimension: r.value for r in recs if r.series == VAR_SIZE and r.period == "2024"}
    assert sizes["agropecuario"] == pytest.approx(100.0 * 40.0 / va)
    assert sizes["construccion"] == pytest.approx(100.0 * 60.0 / va)
    assert sum(v for v in sizes.values() if v is not None) == pytest.approx(100.0)


def test_growth_is_real_yoy_and_none_without_prior_year():
    nominal = _nominal({lbl: {2023: 10.0, 2024: 10.0} for lbl in LABELS})
    real = {_norm(lbl): {2023: 100.0, 2024: 100.0} for lbl in LABELS}
    real[_norm(LABELS[0])] = {2023: 100.0, 2024: 110.0}  # Agropecuario +10% real
    recs = build_sector_records(nominal, real, url=None)
    g = {r.period: r.value for r in recs if r.series == VAR_GROWTH and r.dimension == "agropecuario"}
    assert g["2023"] is None          # no prior year → not fabricated
    assert g["2024"] == pytest.approx(10.0)


def test_missing_value_added_raises():
    with pytest.raises(BCRDSectorsError):
        build_sector_records({_norm(LABELS[0]): {2024: 1.0}}, {}, url=None)


def test_partition_deviation_fails_closed():
    # Value Added inflated beyond the leaf sum → must raise, not persist skewed shares.
    nominal = _nominal({lbl: {2024: 10.0} for lbl in LABELS})  # leaf sum = 170
    nominal[_norm(TOTAL_LABEL)][2024] = 200.0                  # claims 200 → −15%
    with pytest.raises(BCRDSectorsError):
        build_sector_records(nominal, {}, url=None)


def test_missing_leaf_fails_closed():
    # A renamed/removed leaf breaks the partition → fail closed (anti double-count).
    nominal = _nominal({lbl: {2024: 10.0} for lbl in LABELS})
    del nominal[_norm(LABELS[3])]
    with pytest.raises(BCRDSectorsError):
        build_sector_records(nominal, {}, url=None)


# ── Vintage híbrido: retropolado (2007+) como historia + vigente (2018+) ───────
# El retropolado es una partición más GRUESA de 16 actividades: no desagrega
# 'Servicios profesionales' (lo mantiene dentro de 'Otras Actividades de Servicios
# de Mercado'). Se usa para los años previos al primer año del archivo vigente.
_SP_LABEL = "Servicios profesionales"
HIST_LABELS = [lbl for lbl in LABELS if lbl != _SP_LABEL]  # 16-activity retropolado


def _hist(year_values):
    """16-activity historical (retropolado) nominal map (no 'Servicios profesionales')
    + Valor Agregado = sum of the 16."""
    nominal = {_norm(lbl): dict(year_values[lbl]) for lbl in HIST_LABELS}
    years = {y for d in year_values.values() for y in d}
    nominal[_norm(TOTAL_LABEL)] = {
        y: sum(year_values[lbl].get(y, 0.0) for lbl in HIST_LABELS) for y in years
    }
    return nominal


def test_historical_extends_panel_and_growth_stays_within_vintage():
    # Current vigente: 2024-2025 (17 leaves). Historical retropolado: 2022-2025 (16).
    cur_nom = _nominal({lbl: {2024: 10.0, 2025: 10.0} for lbl in LABELS})
    cur_real = {_norm(lbl): {2024: 100.0, 2025: 100.0} for lbl in LABELS}
    cur_real[_norm(LABELS[0])] = {2024: 100.0, 2025: 110.0}  # Agropecuario +10% en 2025
    hist_nom = _hist({lbl: {2022: 10.0, 2023: 10.0, 2024: 10.0, 2025: 10.0} for lbl in HIST_LABELS})
    hist_real = {_norm(lbl): {2022: 90.0, 2023: 95.0, 2024: 100.0, 2025: 110.0} for lbl in HIST_LABELS}

    recs = build_sector_records(cur_nom, cur_real, historical=(hist_nom, hist_real), url=None)
    g = {r.period: r.value for r in recs
         if r.series == VAR_GROWTH and r.dimension == "agropecuario"}
    assert set(g) == {"2022", "2023", "2024", "2025"}          # panel extendido 11→4 años
    assert g["2022"] is None                                    # sin año previo → no fabricado
    assert g["2023"] == pytest.approx(5.56, abs=0.01)           # 95/90 (histórico)
    assert g["2024"] == pytest.approx(5.26, abs=0.01)           # 100/95 (histórico: current no tiene 2023)
    assert g["2025"] == pytest.approx(10.0)                     # 110/100 (vigente)
    # size presente en todos los años para un slug limpio
    sizes = {r.period: r.value for r in recs
             if r.series == VAR_SIZE and r.dimension == "agropecuario"}
    assert all(sizes[p] is not None for p in ("2022", "2023", "2024", "2025"))


def test_seam_growth_never_crosses_vintages_for_redefined_slug():
    # 'otros_servicios' (residual) tiene niveles DISTINTOS entre vintages (el retro lo
    # combina con servicios profesionales). Su crecimiento en el año-costura debe salir
    # del vintage histórico (360/330), NUNCA current/historical (200/330 = salto espurio).
    cur_nom = _nominal({lbl: {2024: 10.0, 2025: 10.0} for lbl in LABELS})
    cur_real = {_norm(lbl): {2024: 100.0, 2025: 100.0} for lbl in LABELS}
    cur_real[_norm("Otras Actividades de Servicios de Mercado")] = {2024: 200.0, 2025: 220.0}
    hist_nom = _hist({lbl: {2023: 10.0, 2024: 10.0, 2025: 10.0} for lbl in HIST_LABELS})
    hist_real = {_norm(lbl): {2023: 100.0, 2024: 100.0, 2025: 100.0} for lbl in HIST_LABELS}
    hist_real[_norm("Otras Actividades de Servicios de Mercado")] = {2023: 330.0, 2024: 360.0, 2025: 396.0}

    recs = build_sector_records(cur_nom, cur_real, historical=(hist_nom, hist_real), url=None)
    g = {r.period: r.value for r in recs
         if r.series == VAR_GROWTH and r.dimension == "otros_servicios"}
    assert g["2024"] == pytest.approx(9.09, abs=0.01)   # 360/330 histórico, NO 200/330 (−39%)
    assert g["2025"] == pytest.approx(10.0)             # 220/200 vigente (split)


def test_servicios_profesionales_has_no_pre_seam_history():
    # El retropolado no tiene esa rama → sin historia previa a la costura (hueco honesto,
    # nunca inventado); su serie arranca en el primer año del vigente.
    cur_nom = _nominal({lbl: {2024: 10.0, 2025: 10.0} for lbl in LABELS})
    cur_real = {_norm(lbl): {2024: 100.0, 2025: 110.0} for lbl in LABELS}
    hist_nom = _hist({lbl: {2022: 10.0, 2023: 10.0, 2024: 10.0, 2025: 10.0} for lbl in HIST_LABELS})
    hist_real = {_norm(lbl): {2022: 90.0, 2023: 95.0, 2024: 100.0, 2025: 110.0} for lbl in HIST_LABELS}

    recs = build_sector_records(cur_nom, cur_real, historical=(hist_nom, hist_real), url=None)
    sizes = {r.period: r.value for r in recs
             if r.series == VAR_SIZE and r.dimension == "servicios_profesionales"}
    assert sizes["2022"] is None and sizes["2023"] is None   # sin historia previa
    assert sizes["2024"] is not None and sizes["2025"] is not None
    g = {r.period: r.value for r in recs
         if r.series == VAR_GROWTH and r.dimension == "servicios_profesionales"}
    assert g["2022"] is None and g["2023"] is None and g["2024"] is None  # sin par comparable
    assert g["2025"] == pytest.approx(10.0)                  # 110/100 vigente


def test_historical_partition_guard_runs_per_vintage():
    # El guard anti-doble-conteo también corre sobre el vintage histórico: una VA
    # histórica inflada debe fallar cerrado, no persistir shares distorsionados.
    cur_nom = _nominal({lbl: {2024: 10.0} for lbl in LABELS})
    hist_nom = _hist({lbl: {2022: 10.0} for lbl in HIST_LABELS})   # Σ16 = 160
    hist_nom[_norm(TOTAL_LABEL)][2022] = 200.0                     # reclama 200 → −20%
    with pytest.raises(BCRDSectorsError):
        build_sector_records(cur_nom, {}, historical=(hist_nom, {}), url=None)


def test_annual_by_sector_takes_first_block_only():
    # The workbook stacks blocks (level, then growth/incidence) repeating sectors.
    # Only the first block (before the first repeated "Valor Agregado") is the
    # quantity we want; summing across blocks corrupts the real YoY growth.
    header = ("VALOR AGREGADO POR ACTIVIDAD ECONOMICA", 2024, None, None, None, 2025, None, None, None)
    rows = [
        header,
        ("Construcción", 10, 10, 10, 10, 20, 20, 20, 20),   # block 1: 2024=40, 2025=80
        ("Comercio", 5, 5, 5, 5, 5, 5, 5, 5),               #          2024=20, 2025=20
        (TOTAL_LABEL, 15, 15, 15, 15, 25, 25, 25, 25),      # closes block 1: 2024=60
        ("Construcción", 99, 99, 99, 99, 99, 99, 99, 99),   # block 2 — must be IGNORED
        (TOTAL_LABEL, 99, 99, 99, 99, 99, 99, 99, 99),
    ]
    out = _annual_by_sector(rows, _complete_year_columns(header))
    assert out[_norm("Construcción")] == {2024: 40.0, 2025: 80.0}   # not 40+396
    assert out[_norm(TOTAL_LABEL)] == {2024: 60.0, 2025: 100.0}     # first block only


def test_annual_by_sector_single_block_unaffected():
    # No second "Valor Agregado": first-occurrence guard alone must keep it correct.
    header = ("VALOR AGREGADO POR ACTIVIDAD ECONOMICA", 2024, None, None, None)
    rows = [
        header,
        ("Construcción", 10, 10, 10, 10),     # 2024 = 40
        (TOTAL_LABEL, 15, 15, 15, 15),        # 2024 = 60
    ]
    out = _annual_by_sector(rows, _complete_year_columns(header))
    assert out[_norm("Construcción")] == {2024: 40.0}
    assert out[_norm(TOTAL_LABEL)] == {2024: 60.0}


def test_norm_is_accent_and_case_insensitive():
    # A BCRD rename to different casing/accents must still match the same slug.
    assert _norm("CONSTRUCCION") == _norm("Construcción")
    assert _norm("Servicios Profesionales") == _norm("Servicios profesionales")


# ── Fixture-mode client (offline) ─────────────────────────────────
def test_fixture_client_returns_full_catalog():
    recs = BCRDSectorsClient(mode="fixture").fetch()
    assert recs, "fixture vacío — ¿se generó bcrd_sectors.json?"
    sectors = {r.dimension for r in recs}
    assert len(sectors) == len(SECTORS) == 17
    # for the latest year, sizes sum to ~100%
    latest = max(r.period for r in recs)
    sizes = [r.value for r in recs if r.series == VAR_SIZE and r.period == latest and r.value is not None]
    assert sum(sizes) == pytest.approx(100.0, abs=0.5)


# ── Sync (offline via fixture monkeypatch) ────────────────────────
def test_sync_persists_and_is_idempotent(db, monkeypatch):
    # Route the "live" fetch to the committed fixture so the test stays offline.
    monkeypatch.setattr(BCRDSectorsClient, "_fetch_live", BCRDSectorsClient._fetch_fixture)

    first = bcrd_sectores_sync(db)
    assert first["errors"] == []
    assert first["synced"] > 0
    assert first["sectors_seeded"] == 17
    assert set(first["variables"]) == {VAR_SIZE, VAR_GROWTH}
    n1 = db.query(SectorVariable).count()
    assert n1 == first["synced"]

    # second run upserts in place — no duplicate rows, same count, no re-seed.
    second = bcrd_sectores_sync(db)
    assert second["sectors_seeded"] == 0
    n2 = db.query(SectorVariable).count()
    assert n2 == n1

    # a known row is stamped with provenance
    row = (
        db.query(SectorVariable)
        .filter_by(sector_code="turismo", variable=VAR_SIZE)
        .first()
    )
    assert row is not None
    assert row.source == "BCRD"
    assert row.dimension == "sector"
