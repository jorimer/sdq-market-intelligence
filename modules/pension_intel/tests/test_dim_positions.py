"""Test del fix A: pension_entity_context expone la posición relativa POR DIMENSIÓN.

Reproduce el caso del Deep Dive de AFP Reservas: #1 GLOBAL pero #2 en escala (lidera
Popular) y #2 en solvencia (lidera Romana). Sin este dato la §1 inventaba 'el mayor del
sistema' / 'solvencia más alta del panel'.
"""
from modules.pension_intel.ai_context import pension_entity_context


def _dim(key, label, score, raw):
    return {"key": key, "label": label, "score": score, "raw": raw,
            "weight": 0.2, "provenance": "real", "present": True}


def _rating(slug, name, overall, escala, solvencia):
    return {
        "slug": slug, "name": name, "overall_score": overall, "period": "2026-05",
        "band": "Adecuada", "score_kind": "absolute", "coverage": 1.0,
        "dimensions": [
            _dim("escala", "Escala (fondos administrados / AUM)", escala, None),
            _dim("solvencia", "Solvencia (patrimonio/activos)", solvencia, None),
        ],
    }


def _panel():
    reservas = _rating("reservas", "AFP Reservas", 73.66, escala=84.73, solvencia=90.73)
    popular = _rating("popular", "AFP Popular", 61.9, escala=98.34, solvencia=63.0)
    romana = _rating("romana", "AFP Romana", 71.7, escala=2.0, solvencia=98.18)
    return reservas, [reservas, popular, romana]


def test_entity_context_exposes_per_dimension_position():
    reservas, peers = _panel()
    ctx = pension_entity_context(reservas, peers)
    pos = ctx["posiciones_dimension"]
    escala = pos["Escala (fondos administrados / AUM)"]
    solv = pos["Solvencia (patrimonio/activos)"]
    # Reservas NO lidera escala (Popular sí) ni solvencia (Romana sí)
    assert escala["es_lider"] is False and escala["rank"] == 2 and escala["lider_afp"] == "AFP Popular"
    assert solv["es_lider"] is False and solv["rank"] == 2 and solv["lider_afp"] == "AFP Romana"
    # y cada dimensión inline lleva su 'posicion'
    dims = {d["dimension"]: d for d in ctx["dimensiones"]}
    assert dims["Escala (fondos administrados / AUM)"]["posicion"]["lider_afp"] == "AFP Popular"
    # la nota instruye contra el superlativo transversal
    assert "no lidera" in ctx["note"].lower() or "es_lider" in ctx["note"]


def test_leader_dimension_marked():
    """La AFP que sí lidera una dimensión queda es_lider=True."""
    reservas, peers = _panel()
    ctx = pension_entity_context(peers[1], peers)  # Popular lidera escala
    assert ctx["posiciones_dimension"]["Escala (fondos administrados / AUM)"]["es_lider"] is True
