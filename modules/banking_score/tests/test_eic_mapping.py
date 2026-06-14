"""EIC (cambiarias) mapping: read TODOS-cascade subtotals (no double-count) and keep
monthly periods separate (no quarter-bucket mixing).

Regression for the 2026-06-14 audit: prod cambiaria balances were ~6× inflated because
the old mapper summed conceptoNivel children (subtotal + leaves) AND _group_by_period
merged Oct+Nov+Dec into one Q4 bucket.
"""
from datetime import date

from modules.banking_score.external.sib_data_client import SIBDataClient


def _bal(n1, n2, n3, valor):
    return {"conceptoNivel1": n1, "conceptoNivel2": n2, "conceptoNivel3": n3, "valor": valor}


def test_mapper_reads_todos_subtotal_not_sum_of_children():
    """activos_totales must be the Activos/TODOS subtotal, never the sum of leaves."""
    balance = [
        _bal("Activos", "TODOS", "TODOS", 1000),                       # grand total
        _bal("Activos", "Efectivo y equivalentes de efectivo", "TODOS", 600),  # subtotal
        _bal("Activos", "Efectivo y equivalentes de efectivo", "Caja", 400),   # leaf
        _bal("Activos", "Efectivo y equivalentes de efectivo", "Bancos del país", 200),  # leaf
        _bal("Activos", "Otros activos", "TODOS", 400),                # subtotal
        _bal("Activos", "Otros activos", "Cargos diferidos", 400),     # leaf
        _bal("Patrimonio", "TODOS", "TODOS", 800),
        _bal("Pasivos", "TODOS", "TODOS", 200),
    ]
    income = [
        {"conceptoNivel1": "Resultado del ejercicio", "conceptoNivel2": "TODOS",
         "conceptoNivel3": "TODOS", "conceptoNivel4": "TODOS", "conceptoNivel5": "TODOS", "valor": 50},
    ]
    out = SIBDataClient._map_eic_to_sdq_fields({"balance": balance, "income": income})
    assert out["activos_totales"] == 1000          # NOT 600+400+200+400+400 (the old bug)
    assert out["patrimonio_tecnico"] == 800
    assert out["pasivos_exigibles"] == 200
    assert out["activos_liquidos"] == 600          # Efectivo subtotal, not its leaves summed
    assert out["utilidad_neta"] == 50


def test_mapper_income_falls_back_to_pre_tax_plus_impuesto():
    balance = [_bal("Activos", "TODOS", "TODOS", 10)]
    income = [
        {"conceptoNivel1": "Resultado del ejercicio", "conceptoNivel2": "Resultado antes del impuesto",
         "conceptoNivel3": "TODOS", "conceptoNivel4": "TODOS", "conceptoNivel5": "TODOS", "valor": 70},
        {"conceptoNivel1": "Resultado del ejercicio", "conceptoNivel2": "Impuesto sobre la renta",
         "conceptoNivel3": "TODOS", "conceptoNivel4": "TODOS", "conceptoNivel5": "TODOS", "valor": -20},
    ]
    out = SIBDataClient._map_eic_to_sdq_fields({"balance": balance, "income": income})
    assert out["utilidad_neta"] == 50  # 70 + (-20)


def test_group_by_exact_month_keeps_months_separate():
    """Oct/Nov/Dec must remain three periods (month-end), not one Q4 bucket."""
    c = SIBDataClient.__new__(SIBDataClient)
    recs = {
        "balance": [
            {"periodo": "2025-10", "conceptoNivel1": "Activos", "valor": 1},
            {"periodo": "2025-11", "conceptoNivel1": "Activos", "valor": 2},
            {"periodo": "2025-12", "conceptoNivel1": "Activos", "valor": 3},
        ],
        "income": [],
    }
    grouped = c._group_by_exact_month(recs)
    assert set(grouped.keys()) == {date(2025, 10, 31), date(2025, 11, 30), date(2025, 12, 31)}
    # the closing month carries only its own record
    assert len(grouped[date(2025, 12, 31)]["balance"]) == 1
    assert grouped[date(2025, 12, 31)]["balance"][0]["valor"] == 3


def test_month_end():
    assert SIBDataClient._month_end("2025-12") == date(2025, 12, 31)
    assert SIBDataClient._month_end("2026-02") == date(2026, 2, 28)
    assert SIBDataClient._month_end("2024-02") == date(2024, 2, 29)  # leap
    assert SIBDataClient._month_end("") is None
