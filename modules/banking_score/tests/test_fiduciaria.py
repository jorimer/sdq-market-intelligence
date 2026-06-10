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
    # fiduciaria profile: eficiencia 0.25, diversificación 0.10
    assert abs(r["weight_profile"]["eficiencia"] - 0.25) < 1e-9
    assert abs(r["weight_profile"]["diversificacion"] - 0.10) < 1e-9


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
    assert m["gastos_operacionales"] == 991
    assert m["utilidad_neta"] == 300


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
    # Missing liquidity inputs → that dimension is N/D, overall reweights over the rest.
    h = compute_health(dict(activos_totales=1000, patrimonio_fideicomitido=600,
                            resultado_periodo=20))  # no liquidos / pasivos_circ
    assert h["liquidez_score"] is None
    assert h["solvencia_score"] is not None
    assert h["overall_score"] is not None
    # Empty input → everything N/D, band N/D (not a fabricated score).
    empty = compute_health({})
    assert empty["overall_score"] is None
    assert empty["health_band"] == "N/D"


def test_income_hhi_helper():
    from modules.banking_score.fiduciaria_sync import _income_hhi
    # 100% from one source → HHI 1.0; 50/50 → 0.5
    assert _income_hhi(1000, 1000) == 1.0
    assert _income_hhi(500, 1000) == 0.5
    assert _income_hhi(None, 1000) is None
    assert _income_hhi(500, 0) is None
