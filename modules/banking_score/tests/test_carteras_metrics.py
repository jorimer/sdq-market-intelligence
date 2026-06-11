"""Test the single-pass carteras/creditos aggregation (Mayores Deudores, A, vencida, HHI)."""
from datetime import date

from modules.banking_score.external.sib_data_client import SIBDataClient


def test_compute_carteras_metrics_aggregates_mayores_deudores(monkeypatch):
    client = SIBDataClient.__new__(SIBDataClient)  # no network init

    rows = [
        # entidad, tipoCredito, clasificacionEntidad, sectorEconomico, deuda, deudaVencida
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Créditos Comerciales a Mayores Deudores",
         "clasificacionEntidad": "A", "sectorEconomico": "D - INDUSTRIA", "deuda": 600, "deudaVencida": 10},
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Créditos Comerciales a Menores Deudores",
         "clasificacionEntidad": "A", "sectorEconomico": "G - COMERCIO", "deuda": 200, "deudaVencida": 0},
        {"entidad": "BANRESERVAS", "periodo": "2025-12", "tipoCredito": "Créditos Hipotecarios",
         "clasificacionEntidad": "B", "sectorEconomico": "", "deuda": 200, "deudaVencida": 40},
    ]
    monkeypatch.setattr(client, "_quarters_in_range", lambda ps, pe: ["2025-12"])
    monkeypatch.setattr(client, "_fetch_for_all_types", lambda ep, ps, pe: rows)

    out = client._compute_carteras_metrics("2025-12", "2025-12")
    m = out["Banreservas"][date(2025, 12, 31)]
    assert m["total"] == 1000               # all three rows (incl. mortgage w/o sector)
    assert m["mayores"] == 600              # only the Mayores Deudores row
    assert m["cartera_a"] == 800            # the two clasificación-A rows
    assert m["vencida"] == 50               # 10 + 0 + 40
    # HHI only over sectored rows (600 D + 200 G; mortgage has no sector) → (0.75²+0.25²)·10000
    assert abs(m["hhi"] - 6250.0) < 1.0


def test_concentracion_top10_from_mayores_deudores():
    """The scoring indicator picks up suma_top10 = Mayores Deudores."""
    from types import SimpleNamespace
    from modules.banking_score.scoring.engine import calc_concentracion_top10
    d = SimpleNamespace(suma_top10=600, cartera_total=1000, cartera_bruta=1000)
    r = calc_concentracion_top10(d)
    assert r["raw"] == 60.0  # 600/1000 → 60% en mayores deudores
