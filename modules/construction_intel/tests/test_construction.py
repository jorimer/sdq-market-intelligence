"""Tests del conector MIVHED + scoring ICC + servicio (Eje Construcción).

Parser contra CSV inline (estructura real MIVHED: banner + header transaccional),
scoring puro y el compute_and_persist/backfill sobre DB en memoria. Nunca toca la red.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.mivhed_client import parse_licenses
from modules.construction_intel.models.models import ConstructionScore
from modules.construction_intel.scoring.momentum import compute_construction_index
from modules.construction_intel.service import compute_and_persist, get_latest


# Banner rows (2) + real header + per-permit rows (date is MM/DD/YYYY).
_CSV = (
    ",,,,,,,,,\n"
    "Licencias Emitidas 2022-2026,,,,,,,,,\n"
    "Fecha de Emisión,Mes,Año,Provincia,Municipio,Barrio/Sector,"
    "Número de Licencia,Tipologia,Metros Cuadrados,Inversión Total\n"
    "01/15/2024,ENERO,2024,SANTO DOMINGO,SDO,X,P1,APARTAMENTOS,100.5,1000000\n"
    "02/10/2024,FEBRERO,2024,SANTIAGO,STG,Y,P2,VIVIENDAS,50,500000\n"
    "01/20/2025,ENERO,2025,SANTO DOMINGO,SDO,Z,P3,COMERCIAL Y OFICINAS,200,2000000\n"
)


def test_parse_licenses_aggregates_per_year():
    out = parse_licenses(_CSV)
    assert set(out) == {2024, 2025}
    assert out[2024]["permits"] == 2
    assert out[2024]["sqm"] == pytest.approx(150.5)
    assert out[2024]["investment"] == pytest.approx(1_500_000)   # 1000000 + 500000
    assert out[2024]["months"] == 2
    assert out[2024]["by_typology"] == {"APARTAMENTOS": 1, "VIVIENDAS": 1}
    assert out[2024]["by_province"] == {"SANTO DOMINGO": 1, "SANTIAGO": 1}
    assert out[2025]["permits"] == 1 and out[2025]["months"] == 1


def test_parse_licenses_typology_detail_sqm_and_investment():
    # m² y valor tasado (inversión) POR tipología, no solo el conteo de permisos.
    out = parse_licenses(_CSV)
    assert out[2024]["by_typology_detail"] == {
        "APARTAMENTOS": {"permits": 1, "sqm": pytest.approx(100.5),
                         "investment": pytest.approx(1_000_000)},
        "VIVIENDAS": {"permits": 1, "sqm": pytest.approx(50.0),
                      "investment": pytest.approx(500_000)},
    }
    assert out[2025]["by_typology_detail"]["COMERCIAL Y OFICINAS"] == {
        "permits": 1, "sqm": pytest.approx(200.0), "investment": pytest.approx(2_000_000)}
    # el conteo por tipología (que alimenta el HHI) se preserva intacto
    assert out[2024]["by_typology"] == {"APARTAMENTOS": 1, "VIVIENDAS": 1}


def test_parse_licenses_typology_detail_matches_row_totals():
    # QA estilo ONE: varias filas de una misma tipología se suman a un triple conocido
    # (licencias, m², valor tasado) — el mismo cruce que valida "Comercial y oficinas".
    csv = (
        ",,,,,,,,,\n"
        "Licencias Emitidas 2022-2026,,,,,,,,,\n"
        "Fecha de Emisión,Mes,Año,Provincia,Municipio,Barrio/Sector,"
        "Número de Licencia,Tipologia,Metros Cuadrados,Inversión Total\n"
        "01/10/2025,ENERO,2025,SANTO DOMINGO,SDO,X,C1,COMERCIAL Y OFICINAS,143086,2127690356\n"
        "02/10/2025,FEBRERO,2025,SANTIAGO,STG,Y,C2,COMERCIAL Y OFICINAS,200000,3000000000\n"
        "03/10/2025,MARZO,2025,SANTO DOMINGO,SDO,Z,A1,APARTAMENTOS,500000,10000000000\n"
    )
    d = parse_licenses(csv)[2025]["by_typology_detail"]
    assert d["COMERCIAL Y OFICINAS"] == {
        "permits": 2, "sqm": pytest.approx(343_086), "investment": pytest.approx(5_127_690_356)}
    assert d["APARTAMENTOS"]["permits"] == 1


def test_index_exposes_typology_breakdown_sorted_by_sqm():
    lic = {2025: {
        "permits": 3, "sqm": 843_086.0, "investment": 15_127_690_356.0, "months": 12,
        "by_typology": {"COMERCIAL Y OFICINAS": 2, "APARTAMENTOS": 1},
        "by_typology_detail": {
            "COMERCIAL Y OFICINAS": {"permits": 2, "sqm": 343_086.0,
                                     "investment": 5_127_690_356.0},
            "APARTAMENTOS": {"permits": 1, "sqm": 500_000.0, "investment": 10_000_000_000.0}},
        "by_province": {"SANTO DOMINGO": 2, "SANTIAGO": 1}}}
    idx = compute_construction_index(lic, _GROWTH, period=2025)
    bd = idx["typology"]["breakdown"]
    # ordenado por m² descendente → apartamentos (500k) antes que comercial (343k)
    assert [r["typology"] for r in bd] == ["APARTAMENTOS", "COMERCIAL Y OFICINAS"]
    # m² y participación por tipología; NO se expone la "inversión" derivada por tipología
    assert bd[1] == {"typology": "COMERCIAL Y OFICINAS", "permits": 2,
                     "sqm": 343_086.0, "sqm_share": round(343_086 / 843_086 * 100, 1)}
    assert "investment" not in bd[1]
    assert bd[0]["sqm_share"] + bd[1]["sqm_share"] == pytest.approx(100.0, abs=0.1)


def test_parse_licenses_no_header():
    assert parse_licenses("garbage,without,a,year,column\n1,2,3,4,5\n") == {}


def _year(sqm, typ, prov, months=12):
    return {"permits": sum(typ.values()), "sqm": sqm, "investment": sqm * 1000.0,
            "months": months, "by_typology": dict(typ), "by_province": dict(prov)}


# 2019-2025 con m² creciendo a 3% desde 2022 y crecimiento BCRD 4% reciente.
_GROWTH = {2019: 5.0, 2020: 5.0, 2021: 5.0, 2022: 4.0, 2023: 4.0, 2024: 4.0, 2025: 4.0}
_LIC = {
    2022: _year(1_000_000, {"A": 50, "B": 50}, {"P": 50, "Q": 50}),
    2023: _year(1_030_000, {"A": 50, "B": 50}, {"P": 50, "Q": 50}),
    2024: _year(1_060_900, {"A": 50, "B": 50}, {"P": 50, "Q": 50}),
    2025: _year(1_092_727, {"A": 50, "B": 50}, {"P": 50, "Q": 50}),  # 3% CAGR vs 2022
}


def test_compute_index_full_coverage():
    idx = compute_construction_index(_LIC, _GROWTH, period=2025)
    assert idx["coverage"] == pytest.approx(1.0, abs=1e-6)  # 4 dims con dato
    assert idx["icc_score"] is not None and idx["band"] is not None
    # producción: 3y geomean ≈ 4% = objetivo → score 100
    assert idx["dimensions"]["production"]["score"] == 100.0
    # pipeline: m² +3%/año = objetivo → score 100
    assert idx["dimensions"]["pipeline"]["score"] == 100.0
    # diversificación perfecta (2 grupos 50/50) → score 100
    assert idx["dimensions"]["typology_diversification"]["score"] == 100.0
    assert idx["dimensions"]["geographic_breadth"]["score"] == 100.0
    assert idx["levels"]["permits"] == 100


def test_pipeline_needs_base_year_partial_coverage():
    # solo 2024-2025 de m² → el pipeline (CAGR 3y) no tiene base 2022 → None
    lic = {2024: _LIC[2024], 2025: _LIC[2025]}
    idx = compute_construction_index(lic, _GROWTH, period=2025)
    assert idx["dimensions"]["pipeline"]["score"] is None
    # producción + 2 diversificación siguen → cobertura 0.65
    assert idx["coverage"] == pytest.approx(0.65, abs=1e-6)
    assert idx["icc_score"] is not None


def test_compute_index_no_data():
    idx = compute_construction_index({}, {})
    assert idx["icc_score"] is None and idx["coverage"] == 0.0


def test_production_contraction_scores_low():
    growth = {2023: -5.0, 2024: -5.0, 2025: -5.0}  # contracción sostenida
    idx = compute_construction_index(_LIC, growth, period=2025)
    assert idx["dimensions"]["production"]["score"] == 0.0  # clamp a 0


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ConstructionScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_partial_year_is_dropped(db):
    # un año en curso (3 meses) no debe ser el período del índice
    lic = dict(_LIC)
    lic[2026] = _year(300_000, {"A": 20}, {"P": 20}, months=3)
    r = compute_and_persist(db, licenses_by_year=lic, growth_by_year=_GROWTH)
    assert r["period"] == "2025"  # 2026 parcial descartado


def test_compute_and_persist_idempotent(db):
    r1 = compute_and_persist(db, licenses_by_year=_LIC, growth_by_year=_GROWTH)
    assert r1["period"] == "2025" and r1["coverage"] == pytest.approx(1.0, abs=1e-6)
    compute_and_persist(db, licenses_by_year=_LIC, growth_by_year=_GROWTH)  # re-run
    assert db.query(ConstructionScore).count() == 1  # idempotente por período
    latest = get_latest(db)
    assert latest.period == "2025" and latest.icc_score is not None
    assert latest.permits == 100
    assert latest.breakdown["dimensions"]["pipeline"]["score"] == 100.0


_ONE_TYP = {"year": 2025, "by_typology": {
    "Comerciales y Oficinas": {"licencias": 149, "construcciones": 113,
                               "sqm": 343086.0, "valor_tasado": 5127690356.0},
    "Edificios de Apartamentos": {"licencias": 781, "construcciones": 1641,
                                  "sqm": 3205538.0, "valor_tasado": 45789879594.0}},
    "totals": {"valor_tasado": 75894662621.0}}


def test_one_typology_persisted_and_surfaced(db):
    # La capa ONE (valor tasado por tipología) inyectada se persiste en el breakdown y el
    # ai_context la expone, atribuida a la ONE y al año que corresponde.
    from modules.construction_intel.ai_context import construction_ai_context
    r = compute_and_persist(db, licenses_by_year=_LIC, growth_by_year=_GROWTH,
                            one_typology=_ONE_TYP)
    assert r["period"] == "2025"
    row = get_latest(db)
    one = row.breakdown["one_typology"]
    assert one["year"] == 2025
    assert one["by_typology"]["Comerciales y Oficinas"]["valor_tasado"] == 5127690356.0
    ctx = construction_ai_context({"one_typology": one, "levels": {}, "dimensions": {},
                                   "typology": {}}, "2025")
    assert ctx["one_valor_tasado_year"] == 2025
    # ordenado por valor tasado desc → apartamentos primero
    assert ctx["one_typology_valor_tasado"][0]["typology"] == "Edificios de Apartamentos"
    co = next(r for r in ctx["one_typology_valor_tasado"]
              if r["typology"] == "Comerciales y Oficinas")
    assert co["valor_tasado_mm_dop"] == 5127.7  # RD$MM


def test_one_typology_absent_is_ok(db):
    # Sin ONE inyectada (y sin red en tests) el ICC se computa y persiste igual; breakdown
    # trae one_typology = None.
    compute_and_persist(db, licenses_by_year=_LIC, growth_by_year=_GROWTH)
    assert get_latest(db).breakdown["one_typology"] is None


def test_backfill_persists_only_full_coverage_years(db):
    from modules.construction_intel.service import backfill_scores, get_scores
    r = backfill_scores(db, licenses_by_year=_LIC, growth_by_year=_GROWTH)
    # 2022-2025 completos, pero el pipeline (CAGR 3y de m²) solo acredita en 2025 (base
    # 2022) → solo 2025 tiene cobertura plena → un punto honesto y comparable.
    assert r["persisted_periods"] == ["2025"] and r["latest"] == "2025"
    assert {s.period for s in get_scores(db)} == {"2025"}
    assert get_scores(db)[0].coverage == pytest.approx(1.0, abs=1e-6)
    backfill_scores(db, licenses_by_year=_LIC, growth_by_year=_GROWTH)  # idempotente
    assert len(get_scores(db)) == 1
