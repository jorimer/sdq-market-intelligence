"""Tests de los summarizers de evidencia por-eje (Mejora #2 del roadmap: dejar de caer a
``_generic_summary`` para los ~11 sectores restantes).

Cada test arma un payload sintético con la forma real de ese motor (mapeada del código) y
verifica que el summarizer saca la cifra clave y NO devuelve la línea genérica de relleno.
"""
import shared.research.data_pull as dp
from shared.registry.signals import REAL

GENERIC_MARK = "el motor devolvió resultado"


def _texts(evs):
    return " || ".join(e.text for e in evs)


def _is_real(evs):
    assert evs, "el summarizer no devolvió evidencia"
    assert all(e.state == REAL and e.kind == "engine" for e in evs)
    assert GENERIC_MARK not in _texts(evs), "cayó al genérico en vez de extraer cifras"


def test_index_family_extracts_score_band_and_dims():
    summ = dp._AXIS_SUMMARY["tourism"]
    payload = {"index": {"itt_score": 62.4, "band": "Fuerte",
                         "dimensions": {"total_demand": {"score": 80.0, "weight": 0.4},
                                        "recovery": {"score": 41.0, "weight": 0.3}},
                         "levels": {"nonresident": 8200000, "hhi": 0.22}}}
    evs = summ("SDQ Tourism Intelligence", payload, "2025", "BCRD·tourism")
    _is_real(evs)
    t = _texts(evs)
    assert "ITT" in t and "62.4/100" in t and "Fuerte" in t
    # dimensión más fuerte y más débil nombradas
    assert "impulsa" in t and "lastra" in t


def test_index_family_tolerates_none_dim_score():
    # energy suele traer una dimensión en brecha (score=None) → se omite, no rompe.
    summ = dp._AXIS_SUMMARY["energy"]
    payload = {"index": {"energy_score": 55.0, "band": "Media",
                         "dimensions": {"capacity_adequacy": {"score": 70.0},
                                        "energy_transition": {"score": None}}}}
    evs = summ("SDQ Energy Intelligence", payload, "2024", "SIE")
    _is_real(evs)
    assert "Dimensión:" in _texts(evs) or "impulsa" in _texts(evs)


def test_trade_summary():
    payload = {"score": {"resilience_score": 48.0, "export_diversification": 33.1,
                         "import_dependency": 0.42, "total_exports": 12000.0,
                         "total_imports": 24000.0}}
    evs = dp._trade_summary("SDQ Trade & Logistics", payload, "2025", "DGA·BCRD")
    _is_real(evs)
    t = _texts(evs)
    assert "resiliencia comercial 48.0/100" in t
    assert "dependencia importadora" in t and "exportaciones 12000" in t


def test_esg_summary_with_rank():
    payload = {"score": {"esg_score": 35.7, "band": "Baja", "period": "2025",
                         "breakdown": {"dimensions": {"physical_risk": {"score": 20.0},
                                                      "governance": {"score": 55.0}}}},
               "rank": 9, "n_countries": 14}
    evs = dp._esg_summary("SDQ ESG & Climate", payload, "2025", "ONE")
    _is_real(evs)
    t = _texts(evs)
    assert "IRC 35.7/100" in t and "Baja" in t
    assert "panel Caribe: 9 de 14" in t


def test_agribusiness_summary():
    payload = {"latest": {"iai_score": 58.0, "iai_band": "Media", "sgps_score": 3.2,
                          "iai_breakdown": {"sector": {"score": 60.0}, "talent": {"score": 40.0}}}}
    evs = dp._agribusiness_summary("SDQ Agribusiness", payload, "2025", "ONE")
    _is_real(evs)
    t = _texts(evs)
    assert "IAI 58.0/100" in t and "SGPS" in t and "Ejes del IAI" in t


def test_structure_summary_driver_and_drag():
    payload = {"structure": {"total_va_growth": 4.9, "concentration_hhi": 0.11,
                             "top_driver": {"sector": "Construcción", "weight": 13.5, "growth": 6.0},
                             "top_drag": {"sector": "Minería", "weight": 1.8, "growth": -3.0}}}
    evs = dp._structure_summary("SDQ Sectoral Structure", payload, "2025", "BCRD")
    _is_real(evs)
    t = _texts(evs)
    assert "Valor Agregado 4.9%" in t
    assert "principal motor Construcción" in t and "principal lastre Minería" in t


def test_structure_drag_none_is_safe():
    payload = {"structure": {"total_va_growth": 4.9,
                             "top_driver": {"sector": "Comercio", "weight": 12.6},
                             "top_drag": None}}
    evs = dp._structure_summary("SDQ Sectoral Structure", payload, "2025", "BCRD")
    _is_real(evs)
    assert "principal motor Comercio" in _texts(evs)


def test_pension_named_form():
    payload = {"rating": {"overall_score": 71.0, "band": "Adecuada",
                          "dimensions": [{"key": "solvencia", "label": "Solvencia", "score": 80.0},
                                         {"key": "costo", "label": "Costo", "score": 45.0}]}}
    evs = dp._pension_summary("AFP Popular", payload, "2026-05", "SIPEN")
    _is_real(evs)
    t = _texts(evs)
    assert "ISA 71.0/100" in t and "Adecuada" in t
    assert "Solvencia" in t and "Costo" in t


def test_pension_pulse_form():
    payload = {"has_data": True, "dispersion": {"average": 7.9, "spread_pp": 2.1, "n_afp": 7}}
    evs = dp._pension_summary("SDQ Pensiones (SIPEN)", payload, "2026-05", "SIPEN")
    _is_real(evs)
    t = _texts(evs)
    assert "rentabilidad promedio del sistema 7.9%" in t and "7 AFP" in t


def test_insurance_pulse_form():
    payload = {"pulse": {"total_premiums_rd": 95000000000.0, "growth_pct": 8.3,
                         "active_insurers": 30, "top4_concentration_pct": 55.0}}
    evs = dp._insurance_summary("SDQ Seguros (SIS)", payload, "2025", "SIS")
    _is_real(evs)
    t = _texts(evs)
    assert "primas del mercado RD$ 95,000,000,000" in t
    assert "concentración top-4 55.0%" in t and "30 aseguradoras" in t


def test_empty_payload_falls_back_to_generic_not_crash():
    # has_data:False / has_score:False → sin cifras → cae al genérico (mantiene ok, no rompe).
    for summ_key, payload in (("pension", {"has_data": False}),
                              ("tourism", {"has_score": False}),
                              ("economic_structure", {"has_data": False})):
        evs = dp._AXIS_SUMMARY[summ_key]("X", payload, "2025", "src")
        assert evs and evs[0].state == REAL  # el genérico mantiene al motor en la síntesis


def test_all_catalog_sectors_have_a_summarizer():
    # los 14 ejes del catálogo deben tener summarizer dedicado (ninguno depende del genérico).
    from shared.products.registry import PRODUCT_CATALOG
    for entry in PRODUCT_CATALOG:
        assert entry.sector_key in dp._AXIS_SUMMARY, f"{entry.sector_key} sin summarizer"


def test_declares_no_data_detects_dead_payload():
    """Hallazgo del piloto: un payload {'has_data': False} contaba como cosecha VIVA
    (evidencia REAL 'has_data False') e inflaba el ledger. Un motor honesto sin dato
    no es evidencia."""
    assert dp._declares_no_data({"has_data": False})
    assert dp._declares_no_data({"has_score": False})
    assert not dp._declares_no_data({"has_data": True, "pulse": {}})
    assert not dp._declares_no_data({"scoring_result": {"overall_score": 78.0}})


def test_generic_summary_ignores_booleans():
    """'has_data' es int para isinstance — no debe salir como cifra en la evidencia."""
    evs = dp._generic_summary("X", {"has_data": True, "flag": False}, "2025", "src")
    t = " ".join(e.text for e in evs)
    assert "has_data" not in t and "flag" not in t
