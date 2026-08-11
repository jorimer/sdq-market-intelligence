"""Tests for the fiduciarias submodel: scoring + PDF-link classification + mappers."""
from types import SimpleNamespace

from modules.banking_score.scoring.engine import run_scoring
from modules.banking_score.scoring.fideicomiso import compute_health
from modules.banking_score.external import fiduciaria_pdf_client as fc


def _ns(**kw):
    base = dict(
        activos_totales=0, patrimonio_tecnico=0, pasivos_exigibles=0, pasivos_cp=0,
        activos_liquidos=0, ingresos_operacionales=0, gastos_operacionales=0,
        utilidad_neta=0, hhi_ingresos_raw=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_fiduciaria_scoring_discriminates():
    healthy = run_scoring(
        _ns(activos_totales=2000, patrimonio_tecnico=1000, pasivos_exigibles=1000,
            pasivos_cp=500, activos_liquidos=900, ingresos_operacionales=1300,
            gastos_operacionales=900, utilidad_neta=300, hhi_ingresos_raw=0.5),
        entity_type="fiduciaria",
    )
    weak = run_scoring(
        _ns(activos_totales=2000, patrimonio_tecnico=150, pasivos_exigibles=1850,
            pasivos_cp=1800, activos_liquidos=120, ingresos_operacionales=400,
            gastos_operacionales=520, utilidad_neta=-120, hhi_ingresos_raw=0.98),
        entity_type="fiduciaria",
    )
    assert healthy["overall_score"] > weak["overall_score"]
    assert 0 <= weak["overall_score"] <= 100
    # Uses the fiduciaria indicator set, not the bank one.
    assert "capitalizacion" in healthy["indicators"]
    assert "solvencia" not in healthy["indicators"]
    assert set(healthy["sub_components"]) == {
        "solidez", "calidad", "eficiencia", "liquidez", "diversificacion"}


def test_fiduciaria_weight_profile():
    r = run_scoring(_ns(activos_totales=100, patrimonio_tecnico=50), entity_type="fiduciaria")
    # fiduciaria v1.1 profile: eficiencia 0.26, diversificación trimmed to 0.05
    assert abs(r["weight_profile"]["eficiencia"] - 0.26) < 1e-9
    assert abs(r["weight_profile"]["diversificacion"] - 0.05) < 1e-9
    assert abs(sum(r["weight_profile"].values()) - 1.0) < 1e-9


def test_pdf_link_classification_entity_vs_trust():
    # entity statements vs public-trust statements (accent-insensitive)
    assert fc._classify("/media/x/31-de-diciembre-2024.pdf") == ("entity", 2024)
    assert fc._classify("/media/x/eeff-auditados-fiduciaria-reservas-2023.pdf") == ("entity", 2023)
    assert fc._classify("/media/x/rd-vial-31-de-diciembre-2025.pdf") == ("trust", 2025)
    # accented stem as it appears in the portal HTML (entity-encoded) must classify as trust
    assert fc._classify("/media/x/cr&#xe9;ditos-educativos-31-de-diciembre-2025.pdf")[0] == "trust"
    assert fc._classify("/media/x/créditos-educativos-31-de-diciembre-2025.pdf")[0] == "trust"


def test_entity_field_mapper_picks_totals():
    statements = {
        "balance_general": [
            {"original_text": "Efectivo y equivalentes de efectivo", "category": "assets", "amount_current": 200, "is_total": False},
            {"original_text": "Inversiones", "category": "assets", "amount_current": 637, "is_total": False},
            {"original_text": "Total activos", "category": "assets", "amount_current": 2031, "is_total": True},
            {"original_text": "Total pasivos", "category": "liabilities", "amount_current": 1131, "is_total": True},
            {"original_text": "Total patrimonio", "category": "equity", "amount_current": 900, "is_total": True},
        ],
        "estado_resultados": [
            {"original_text": "Comisiones fiduciarias", "category": "revenue", "amount_current": 1310, "is_total": False},
            {"original_text": "Total ingresos", "category": "revenue", "amount_current": 1334, "is_total": True},
            {"original_text": "Total gastos operacionales", "category": "opex", "amount_current": 991, "is_total": True},
            {"original_text": "Resultado neto", "category": "net_income", "amount_current": 300, "is_total": True},
        ],
    }
    m = fc.map_entity_fields(statements)
    assert m["activos_totales"] == 2031
    assert m["pasivos_exigibles"] == 1131
    assert m["patrimonio_tecnico"] == 900
    assert m["activos_liquidos"] == 837            # efectivo + inversiones
    assert m["ingresos_operacionales"] == 1334
    assert m["gastos_operacionales"] == 991        # magnitude, even if shown as ()
    assert m["utilidad_neta"] == 300


def test_entity_mapper_patrimonio_identity_fallback():
    # Statement without a matched equity total → patrimonio = activos - pasivos,
    # and the net result falls back to the last income total.
    statements = {
        "balance_general": [
            {"original_text": "Total activos", "category": "assets", "amount_current": 972, "is_total": True},
            {"original_text": "Total pasivos", "category": "liabilities", "amount_current": 117, "is_total": True},
            {"original_text": "Total capital de los accionistas", "category": "equity", "amount_current": 855, "is_total": True},
        ],
        "estado_resultados": [
            {"original_text": "Total ingresos", "category": "revenue", "amount_current": 420, "is_total": True},
            {"original_text": "Total gastos operacionales", "category": "opex", "amount_current": -310, "is_total": True},
            {"original_text": "Ganancia neta del año", "category": "net_income", "amount_current": 95, "is_total": True},
        ],
    }
    m = fc.map_entity_fields(statements)
    # "Total capital de los accionistas" matched by the broadened keywords
    assert m["patrimonio_tecnico"] == 855
    assert m["gastos_operacionales"] == 310
    assert m["utilidad_neta"] == 95

    # Now drop the equity line entirely → identity fallback (972 - 117 = 855)
    statements["balance_general"] = statements["balance_general"][:2]
    m2 = fc.map_entity_fields(statements)
    assert m2["patrimonio_tecnico"] == 855


def test_trust_field_mapper_picks_patrimonio_fideicomitido():
    statements = {
        "balance_general": [
            {"original_text": "Efectivo en cajas y banco", "category": "assets", "amount_current": 1692, "is_total": False},
            {"original_text": "Total activos", "category": "assets", "amount_current": 99896, "is_total": True},
            {"original_text": "Total pasivos circulantes", "category": "liabilities", "amount_current": 4232, "is_total": True},
            {"original_text": "Total pasivos", "category": "liabilities", "amount_current": 88280, "is_total": True},
            {"original_text": "Total patrimonio fideicomitido", "category": "equity", "amount_current": 11616, "is_total": True},
        ],
        "estado_resultados": [
            {"original_text": "Resultado del período", "category": "net_income", "amount_current": 2472, "is_total": True},
        ],
    }
    m = fc.map_trust_fields(statements)
    assert m["activos_totales"] == 99896
    assert m["patrimonio_fideicomitido"] == 11616
    assert m["pasivos_circulantes"] == 4232
    assert m["resultado_periodo"] == 2472


def test_trust_health_index_is_honest_across_heterogeneous_funds():
    # RD VIAL: operating toll-road concession, leveraged by design, with a surplus.
    rdvial = compute_health(dict(
        activos_totales=99896577400, patrimonio_fideicomitido=11616035572,
        activos_liquidos=13967095104, pasivos_circulantes=4232707081,
        resultado_periodo=2472107396, ingresos_operacionales=12784145851,
    ))
    # FDI: idle land-holding fund — high equity but poor liquidity and a small loss.
    fdi = compute_health(dict(
        activos_totales=19945734433, patrimonio_fideicomitido=19281673995,
        activos_liquidos=52448099, pasivos_circulantes=664060438,
        resultado_periodo=-1371282, ingresos_operacionales=0,
    ))
    assert rdvial["segment"] == "operativo"
    assert fdi["segment"] == "tenedor"
    # The naive bank-style "97% equity = best" ranking is avoided: the operating
    # fund with strong liquidity + surplus outranks the idle holder overall.
    assert rdvial["overall_score"] > fdi["overall_score"]
    # FDI still scores top on solvency alone (no debt) — dimension is honest.
    assert fdi["solvencia_score"] == 100.0
    assert fdi["liquidez_score"] < 20  # almost no liquid assets vs liabilities


def test_trust_health_nd_reweights_and_never_fabricates():
    # Two dimensions available (solvencia + sostenibilidad) → reweights, real band.
    h = compute_health(dict(activos_totales=1000, patrimonio_fideicomitido=600,
                            resultado_periodo=20))  # no liquidos / pasivos_circ
    assert h["liquidez_score"] is None
    assert h["solvencia_score"] is not None
    assert h["overall_score"] is not None
    # Empty input → everything N/D, no fabricated score.
    empty = compute_health({})
    assert empty["overall_score"] is None
    assert empty["health_band"] == "Datos insuficientes"


def test_trust_health_requires_two_dimensions():
    # A single dimension (solvencia=100, common in asset-holding trusts) is NOT a
    # health verdict — must not fake "Sólida". Needs ≥2 dimensions for a band.
    one_dim = compute_health(dict(activos_totales=1000, patrimonio_fideicomitido=1000))
    assert one_dim["solvencia_score"] == 100.0
    assert one_dim["liquidez_score"] is None
    assert one_dim["sostenibilidad_score"] is None
    assert one_dim["overall_score"] is None
    assert one_dim["health_band"] == "Datos insuficientes"


def test_income_hhi_helper():
    from modules.banking_score.fiduciaria_sync import _income_hhi
    # 100% from one source → HHI 1.0; 50/50 → 0.5
    assert _income_hhi(1000, 1000) == 1.0
    assert _income_hhi(500, 1000) == 0.5
    assert _income_hhi(None, 1000) is None
    assert _income_hhi(500, 0) is None


# ─── Orchestration (DB-backed, network/AI stubbed) ───────────────

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from shared.database.base import Base  # noqa: E402
import shared.auth.models  # noqa: E402,F401 — register the users table for FK resolution
from modules.banking_score import fiduciaria_sync as fs  # noqa: E402
from modules.banking_score.models.models import (  # noqa: E402
    Bank, BankType, BankingData, RatingResult,
    Fideicomiso, FideicomisoData, FideicomisoHealthScore,
)

_ENTITY_STMTS = {
    "balance_general": [
        {"original_text": "Efectivo y equivalentes de efectivo", "category": "assets", "amount_current": 199, "is_total": False},
        {"original_text": "Inversiones", "category": "assets", "amount_current": 637, "is_total": False},
        {"original_text": "Total activos", "category": "assets", "amount_current": 2031, "is_total": True},
        {"original_text": "Total pasivos circulantes", "category": "liabilities", "amount_current": 765, "is_total": True},
        {"original_text": "Total pasivos", "category": "liabilities", "amount_current": 884, "is_total": True},
        {"original_text": "Total patrimonio", "category": "equity", "amount_current": 1147, "is_total": True},
    ],
    "estado_resultados": [
        {"original_text": "Comisiones fiduciarias", "category": "revenue", "amount_current": 1310, "is_total": False},
        {"original_text": "Total ingresos", "category": "revenue", "amount_current": 1334, "is_total": True},
        {"original_text": "Total gastos operacionales", "category": "opex", "amount_current": 991, "is_total": True},
        {"original_text": "Resultado neto", "category": "net_income", "amount_current": 320, "is_total": True},
    ],
}
_TRUST_STMTS = {
    "company_info": {"name": "FIDEICOMISO RD VIAL", "period_end": "2025-12-31"},
    "balance_general": [
        {"original_text": "Total activos", "category": "assets", "amount_current": 99896, "is_total": True},
        {"original_text": "Total pasivos circulantes", "category": "liabilities", "amount_current": 4232, "is_total": True},
        {"original_text": "Aportes del fideicomitente", "category": "equity", "amount_current": 9144, "is_total": False},
        {"original_text": "Resultado del período", "category": "equity", "amount_current": 2472, "is_total": False},
        {"original_text": "Total patrimonio fideicomitido", "category": "equity", "amount_current": 11616, "is_total": True},
        {"original_text": "Efectivo y equivalentes de efectivo", "category": "assets", "amount_current": 12034, "is_total": False},
    ],
    "estado_resultados": [
        {"original_text": "Total ingresos operacionales", "category": "revenue", "amount_current": 12784, "is_total": True},
    ],
}


@pytest.fixture()
def Session(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(fs, "SessionLocal", SessionLocal)
    return SessionLocal


def test_run_fiduciaria_sync_persists_entities_trusts_and_scores(Session, monkeypatch):
    # One entity (2024) + one trust — network/AI stubbed.
    monkeypatch.setattr(fs.fc, "FIDUCIARY_ENTITIES", {"fiduciaria-reservas": "Fiduciaria Reservas"})
    monkeypatch.setattr(fs.fc, "discover_pdfs", lambda slug: {
        "entity": [(2024, "https://x/entity.pdf")],
        "trusts": [("RD VIAL", "https://x/rd-vial.pdf")],
    })
    monkeypatch.setattr(fs, "_extract_one", lambda url: _TRUST_STMTS if "rd-vial" in url else _ENTITY_STMTS)

    result = fs.run_fiduciaria_sync(include_trusts=True)
    assert result["entities_ingested"] == 1
    assert result["trusts_ingested"] == 1
    assert result["ratings_written"] >= 1

    db = Session()
    # Entity persisted as a fiduciaria bank, with annual BankingData + a rating.
    bank = db.query(Bank).filter_by(name="Fiduciaria Reservas").first()
    assert bank is not None and bank.bank_type == BankType.fiduciaria
    bd = db.query(BankingData).filter_by(bank_id=bank.id).first()
    assert float(bd.activos_totales) == 2031
    assert bd.hhi_ingresos_raw is not None  # computed from comisiones/ingresos
    rr = db.query(RatingResult).filter_by(bank_id=bank.id).first()
    # Fase 4: las filas nuevas ya NO llevan la notación de letras; llevan los dos ejes.
    assert rr is not None and rr.rating_tier is None
    assert rr.ejecucion_score is not None and rr.resiliencia_score is not None
    # Trust persisted with its own health index (NOT an SDQ tier).
    trust = db.query(Fideicomiso).filter(Fideicomiso.name.like("%RD VIAL%")).first()
    assert trust is not None
    td = db.query(FideicomisoData).filter_by(fideicomiso_id=trust.id).first()
    assert float(td.patrimonio_fideicomitido) == 11616
    hs = db.query(FideicomisoHealthScore).filter_by(fideicomiso_id=trust.id).first()
    assert hs.health_band in {"Sólida", "Estable", "En vigilancia", "Frágil"}
    assert hs.segment == "operativo"
    db.close()


def test_audited_extractor_json_repair_and_parse():
    from shared.pdf.audited_extractor import AuditedPdfExtractor as A
    # Clean JSON inside prose / code fence.
    assert A._parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert A._parse_json_response('garbage {"b": 2} trailing') == {"b": 2}
    # Truncated mid-stream (multi-line, as a real max_tokens cutoff) → repaired
    # into a valid dict keeping the complete items, dropping the partial tail.
    truncated = (
        '{\n  "balance_general": [\n'
        '    {"original_text": "Total activos", "amount_current": 100},\n'
        '    {"original_text": "Inco'
    )
    repaired = A._repair_truncated_json(truncated)
    assert repaired is not None
    assert repaired["balance_general"][0]["amount_current"] == 100
