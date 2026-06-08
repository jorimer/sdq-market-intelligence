"""Tests for the cambiarias (EIC) submodel: scoring + EIC ETL mapping."""
from types import SimpleNamespace

from modules.banking_score.scoring.engine import run_scoring
from modules.banking_score.external.sib_data_client import (
    SIBDataClient,
    cambiaria_display_name,
)


def _ns(**kw):
    base = dict(activos_totales=0, patrimonio_tecnico=0, pasivos_exigibles=0,
               activos_liquidos=0, cartera_bruta=0, utilidad_neta=0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_cambiaria_scoring_discriminates():
    healthy = run_scoring(
        _ns(activos_totales=1000, patrimonio_tecnico=300, pasivos_exigibles=700,
            activos_liquidos=600, cartera_bruta=50, utilidad_neta=35),
        entity_type="cambiaria",
    )
    weak = run_scoring(
        _ns(activos_totales=1000, patrimonio_tecnico=30, pasivos_exigibles=970,
            activos_liquidos=80, cartera_bruta=600, utilidad_neta=-20),
        entity_type="cambiaria",
    )
    assert healthy["overall_score"] > weak["overall_score"]
    assert 0 <= weak["overall_score"] <= 100
    assert 0 <= healthy["overall_score"] <= 100
    # Uses the cambiaria indicator set, not the bank one.
    assert "capitalizacion" in healthy["indicators"]
    assert "solvencia" not in healthy["indicators"]
    assert set(healthy["sub_components"]) == {
        "solidez", "calidad", "eficiencia", "liquidez", "diversificacion"}


def test_cambiaria_uses_cambiaria_weight_profile():
    r = run_scoring(_ns(activos_totales=100, patrimonio_tecnico=30), entity_type="cambiaria")
    # cambiaria profile: liquidez weighted 0.20 (vs 0.10 base)
    assert abs(r["weight_profile"]["liquidez"] - 0.20) < 1e-9


def test_eic_mapper_parses_concepts():
    client = SIBDataClient.__new__(SIBDataClient)  # no network init needed
    period_data = {
        "balance": [
            {"conceptoNivel1": "Activos", "conceptoNivel2": "Efectivo y equivalentes de efectivo", "valor": 600},
            {"conceptoNivel1": "Activos", "conceptoNivel2": "Inversiones", "valor": 100},
            {"conceptoNivel1": "Activos", "conceptoNivel2": "Cartera de créditos", "valor": 200},
            {"conceptoNivel1": "Activos", "conceptoNivel2": "Otros activos", "valor": 100},
            {"conceptoNivel1": "Activos", "conceptoNivel2": "TODOS", "valor": 1000},  # must be ignored
            {"conceptoNivel1": "Pasivos", "conceptoNivel2": "Otros pasivos", "valor": 700},
            {"conceptoNivel1": "Patrimonio", "conceptoNivel2": "Patrimonio neto", "valor": 300},
        ],
        "income": [
            {"conceptoNivel1": "Resultado del ejercicio", "conceptoNivel2": "Resultado antes del impuesto", "valor": 50},
            {"conceptoNivel1": "Resultado del ejercicio", "conceptoNivel2": "Impuesto sobre la renta", "valor": -15},
            {"conceptoNivel1": "Resultado del ejercicio", "conceptoNivel2": "TODOS", "valor": 35},
        ],
    }
    m = SIBDataClient._map_eic_to_sdq_fields(client, period_data)
    assert m["activos_totales"] == 1000      # sum of children, not the TODOS row
    assert m["pasivos_exigibles"] == 700
    assert m["patrimonio_tecnico"] == 300
    assert m["activos_liquidos"] == 700      # efectivo + inversiones
    assert m["cartera_bruta"] == 200
    assert m["utilidad_neta"] == 35


def test_cambiaria_display_name():
    assert "Caribe Express" in cambiaria_display_name("CARIBEEXPRESS")
    assert cambiaria_display_name("AGCRPLACIDO") == "Agcrplacido (Agente de Cambio)"
