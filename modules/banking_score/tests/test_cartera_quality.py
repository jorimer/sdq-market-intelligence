"""Fase 2 — cartera-quality indicators from real SIB data.

Resurrects four previously-N/D indicators using the dedicated SIB endpoints
discovered live (slugs use hyphens):
  - castigos          ← indicadores/morosidad-estresada (castigos / carteraTotal)
  - exposición RE     ← indicadores/riesgo-credito (mortgage debt / total debt)
  - HHI sectorial     ← carteras/creditos (debt by sectorEconomico)
  - HHI ingresos      ← estados/resultados/eif deep tree (income-source subtotals)
  - migración         ← previous-period category-A portfolio link
"""
from datetime import date
from types import SimpleNamespace

from modules.banking_score.external.sib_data_client import SIBDataClient
from modules.banking_score.scoring.engine import (
    calc_castigos_pct,
    calc_exposicion_re,
    calc_roa,
    calculate_all_indicators,
    _ytd_annualization_factor,
)


_ALL_FIELDS = [
    "patrimonio_tecnico", "apr", "capital_primario", "exposicion_total",
    "capital_tier1", "contingentes", "riesgo_mercado", "provisiones",
    "cartera_vencida_90d", "activos_totales", "cartera_bruta",
    "cartera_categoria_a", "cartera_total", "suma_top10", "hhi_sectorial_raw",
    "castigos", "exposicion_re", "cartera_a_prev", "utilidad_neta",
    "activos_promedio", "patrimonio_promedio", "ingresos_financieros",
    "gastos_financieros", "activos_productivos_avg", "gastos_operacionales",
    "ingresos_operacionales", "caja_valores", "pasivos_cp", "cartera_neta",
    "depositos_totales", "activos_liquidos", "pasivos_exigibles",
    "hhi_ingresos_raw",
    # pre-computed SIB ratios the engine may prefer
    "solvencia_pct", "tier1_pct", "morosidad_pct", "cartera_vigente_pct",
    "cobertura_pct", "margen_pct", "cost_income_pct",
    "castigos_pct", "exposicion_re_pct",
]


def _data(**kw):
    ns = {f: None for f in _ALL_FIELDS}
    ns.update(kw)
    return SimpleNamespace(**ns)


# ── Engine: pre-computed ratios are preferred (unit-safe) ──────────

def test_castigos_prefers_pct_ratio():
    res = calc_castigos_pct(_data(castigos_pct=2.0))
    assert res["raw"] == 2.0
    assert res["score"] == 90.0  # 100 - 2*5


def test_exposicion_re_prefers_pct_ratio():
    res = calc_exposicion_re(_data(exposicion_re_pct=40.0))
    assert res["raw"] == 40.0
    assert res["score"] == 100.0  # centered at 40%


def test_castigos_available_from_pct_alone():
    ind = calculate_all_indicators(_data(castigos_pct=1.0))
    assert ind["castigos_pct"]["available"] is True


def test_exposicion_re_available_from_pct_alone():
    ind = calculate_all_indicators(_data(exposicion_re_pct=35.0))
    assert ind["exposicion_re"]["available"] is True


def test_hhi_sectorial_available_when_raw_present():
    ind = calculate_all_indicators(_data(hhi_sectorial_raw=1800.0))
    assert ind["hhi_sectorial"]["available"] is True


def test_migracion_available_when_prev_and_current_present():
    ind = calculate_all_indicators(_data(cartera_categoria_a=900, cartera_a_prev=1000))
    assert ind["migracion"]["available"] is True
    # -10% change in cat-A → score = 100 - min(100, 10*5) = 50
    assert ind["migracion"]["score"] == 50.0


# ── ETL: income-diversification HHI from the resultados tree ───────

def test_income_hhi_uses_nivel4_subtotals_only():
    rows = [
        # nivel4 subtotals (nivel5 == TODOS) — these count
        {"conceptoNivel4": "Margen financiero neto", "conceptoNivel5": "TODOS", "valor": 600},
        {"conceptoNivel4": "Otros ingresos operacionales", "conceptoNivel5": "TODOS", "valor": 400},
        # child leaf under a nivel4 — must be IGNORED (would double-count)
        {"conceptoNivel4": "Otros ingresos operacionales",
         "conceptoNivel5": "Comisiones por servicios", "valor": 300},
        # negative stream — ignored (not an income source this period)
        {"conceptoNivel4": "Ingresos (gastos) por diferencia de cambio",
         "conceptoNivel5": "TODOS", "valor": -50},
    ]
    # shares 0.6 / 0.4 → (0.36 + 0.16) * 10000 = 5200
    assert SIBDataClient._income_hhi_raw(rows) == 5200.0


def test_income_hhi_none_when_no_income():
    assert SIBDataClient._income_hhi_raw([]) is None
    assert SIBDataClient._income_hhi_raw(
        [{"conceptoNivel4": "Gastos operativos", "conceptoNivel5": "TODOS", "valor": 999}]
    ) is None


# ── ETL: castigos % + RE exposure % from the dedicated endpoints ───

def _client():
    return SIBDataClient(api_key="test-key")


def test_map_computes_castigos_pct_from_morosidad_estresada():
    period_data = {
        "morosidad_estresada": [{"carteraTotal": 1000, "castigos": 25}],
    }
    mapped = _client()._map_to_sdq_fields(period_data)
    assert mapped["castigos_pct"] == 2.5
    assert mapped["castigos"] == 25


def test_map_computes_exposicion_re_pct_from_riesgo_credito():
    period_data = {
        "riesgo_credito": [
            {"tipoCartera": "Créditos Hipotecarios", "deuda": 300},
            {"tipoCartera": "Créditos comerciales", "deuda": 700},
        ],
    }
    mapped = _client()._map_to_sdq_fields(period_data)
    assert mapped["exposicion_re_pct"] == 30.0


def test_map_no_cartera_quality_when_endpoints_empty():
    mapped = _client()._map_to_sdq_fields({})
    assert mapped["castigos_pct"] is None
    assert mapped["exposicion_re_pct"] is None
    assert mapped["hhi_ingresos_raw"] is None


# ── ETL: sector HHI aggregation from carteras/creditos (streamed) ──

def test_quarters_in_range():
    assert _client()._quarters_in_range("2025-01", "2025-12") == [
        "2025-03", "2025-06", "2025-09", "2025-12"]
    assert _client()._quarters_in_range("2025-09", "2025-09") == ["2025-09"]


def test_compute_carteras_hhi_aggregates_by_sector(monkeypatch):
    client = _client()
    rows = [
        {"entidad": "BANRESERVAS", "periodo": "2025-09", "sectorEconomico": "A - X", "deuda": 700},
        {"entidad": "BANRESERVAS", "periodo": "2025-09", "sectorEconomico": "B - Y", "deuda": 300},
        # a TODOS rollup row must be ignored (would inflate)
        {"entidad": "BANRESERVAS", "periodo": "2025-09", "sectorEconomico": "TODOS", "deuda": 1000},
    ]
    monkeypatch.setattr(client, "_fetch_for_all_types", lambda ep, a, b: rows)
    hhi = client._compute_carteras_hhi("2025-09", "2025-09")
    # shares 0.7 / 0.3 → (0.49 + 0.09) * 10000 = 5800
    assert hhi["Banreservas"][date(2025, 9, 30)] == 5800.0


def test_compute_carteras_hhi_pings_progress_each_quarter(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_fetch_for_all_types", lambda ep, a, b: [])
    seen = []
    # 4 quarters in 2024 → 4 heartbeat pings (keeps the sync status fresh)
    client._compute_carteras_hhi("2024-01", "2024-12", on_progress=seen.append)
    assert len(seen) == 4
    assert seen[0].startswith("carteras 2024-03 (1/4)")


# ── ETL: pagination must not silently truncate on a transient page failure ──

def test_get_retries_failed_page_before_truncating(monkeypatch):
    """A transient 504/timeout on a page must be retried, not silently dropped
    (that truncation left deep income rows missing → hhi_ingresos N/D)."""
    client = _client()
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    seq = iter([None, [{"valor": 1}]])  # page fails once, then a short final page
    monkeypatch.setattr(client, "_get_with_retry", lambda *a, **k: next(seq))
    out = client._get("estados/resultados/eif", {"tipoEntidad": "BM"})
    assert out == [{"valor": 1}]  # recovered — not truncated to []


def test_get_stops_after_exhausting_page_retries(monkeypatch):
    """If a page keeps failing past the extra retries, stop (no infinite loop)."""
    client = _client()
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    monkeypatch.setattr(client, "_get_with_retry", lambda *a, **k: None)
    out = client._get("estados/resultados/eif", {"tipoEntidad": "BM"})
    assert out == []


# ── ETL: utilidad_neta must read the pre-tax SUBTOTAL, not a leaf expense ──

def test_map_utilidad_uses_pretax_subtotal_not_leaf():
    period_data = {"income": [
        # a leaf expense under "Resultado antes del impuesto" — must NOT be picked
        {"conceptoNivel1": "Resultado del ejercicio", "conceptoNivel2": "Resultado antes del impuesto",
         "conceptoNivel3": "Otros ingresos (gastos)", "conceptoNivel4": "Otros gastos",
         "conceptoNivel5": "Otros gastos", "valor": -403},
        # the pre-tax SUBTOTAL (cascade TODOS) — must be picked
        {"conceptoNivel1": "Resultado del ejercicio", "conceptoNivel2": "Resultado antes del impuesto",
         "conceptoNivel3": "TODOS", "conceptoNivel4": "TODOS", "valor": 24226},
    ]}
    mapped = _client()._map_to_sdq_fields(period_data)
    assert mapped["utilidad_neta"] == 24226


# ── Engine: ROA/ROE annualized from YTD by the period month ──

def test_ytd_annualization_factor():
    assert _ytd_annualization_factor(SimpleNamespace(period_end=date(2025, 3, 31))) == 4.0
    assert _ytd_annualization_factor(SimpleNamespace(period_end=date(2025, 6, 30))) == 2.0
    assert _ytd_annualization_factor(SimpleNamespace(period_end=date(2025, 12, 31))) == 1.0
    assert _ytd_annualization_factor(SimpleNamespace(period_end=None)) == 1.0


def test_roa_annualized_for_q1():
    # utilidad 6 (YTD Q1) / activos 1000 → 0.6% × 4 = 2.4% annual
    d = _data(utilidad_neta=6, activos_promedio=1000, period_end=date(2025, 3, 31))
    assert calc_roa(d)["raw"] == 2.4
    # Q4 (full year) → no annualization
    d4 = _data(utilidad_neta=24, activos_promedio=1000, period_end=date(2025, 12, 31))
    assert calc_roa(d4)["raw"] == 2.4
