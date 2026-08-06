"""El chequeo de dirección alcanza a SEGUROS y PENSIONES.

`numeric_guard` tenía el detector desde #631, pero fuera de banca estaba CIEGO: reconstruía
los pares (valor, referencia) desde `_BENCH_KEY`, que es el mapeo de indicadores BANCARIOS.
Ahora los ejes inyectan `comparaciones` YA RESUELTAS y el detector las lee tal cual — la
misma cura sirve de red, sin que el guard tenga que conocer el vocabulario de cada eje.
"""
from modules.insurance_intel.ai_context import insurance_entity_context, insurance_peer_context
from modules.pension_intel.ai_context import pension_entity_context
from shared.narrative.numeric_guard import deterministic_direction_errors


def _dim(key, label, score):
    return {"key": key, "label": label, "score": score, "weight": 0.2,
            "raw": score, "provenance": "real", "present": True}


def _panel(label_scores, mios):
    """Sujeto + 4 pares, para que la mediana del panel sea representativa."""
    rating = {"slug": "yo", "name": "Entidad", "period": "2026-03", "overall_score": 70,
              "band": "Adecuada", "coverage": 1.0,
              "dimensions": [_dim(k, lab, sc) for k, (lab, sc) in mios.items()]}
    peers = [rating] + [
        {"slug": f"p{i}", "name": f"Par {i}", "overall_score": 60,
         "dimensions": [_dim(k, lab, vs[i]) for k, (lab, vs) in label_scores.items()]}
        for i in range(4)
    ]
    return rating, peers


_MIOS = {"solvencia": ("Solvencia", 80.0), "escala": ("Escala", 40.0)}
_PARES = {"solvencia": ("Solvencia", [50.0, 55.0, 60.0, 65.0]),
          "escala": ("Escala", [70.0, 75.0, 80.0, 85.0])}


def test_seguros_inyecta_las_comparaciones():
    rating, peers = _panel(_PARES, _MIOS)
    comps = insurance_entity_context(rating, peers)["comparaciones"]
    por = {c["indicador"]: c for c in comps}
    assert por["Solvencia"]["direccion"] == "por encima"
    assert por["Escala"]["direccion"] == "por debajo"


def test_pensiones_inyecta_las_comparaciones():
    rating, peers = _panel(_PARES, _MIOS)
    comps = pension_entity_context(rating, peers)["comparaciones"]
    assert {c["indicador"] for c in comps} == {"Solvencia", "Escala"}


def test_el_detector_atrapa_la_direccion_invertida_en_seguros():
    """Antes esto pasaba sin ser visto: el guard no reconocía indicadores de seguros."""
    rating, peers = _panel(_PARES, _MIOS)
    ctx = insurance_entity_context(rating, peers)
    txt = "La Solvencia de 80 se ubica por debajo de la mediana del panel (60)."
    assert any("Solvencia" in f for f in deterministic_direction_errors(ctx, txt))


def test_la_direccion_correcta_no_se_marca():
    rating, peers = _panel(_PARES, _MIOS)
    ctx = insurance_entity_context(rating, peers)
    txt = "La Solvencia de 80 supera la mediana del panel (60)."
    assert deterministic_direction_errors(ctx, txt) == []


def test_panel_chico_no_produce_comparaciones():
    """Con menos de 3 pares la mediana no representa: mejor callar que comparar mal."""
    rating = {"slug": "yo", "name": "E", "overall_score": 70, "coverage": 1.0,
              "dimensions": [_dim("solvencia", "Solvencia", 80.0)]}
    peers = [rating, {"slug": "p", "name": "P", "overall_score": 60,
                      "dimensions": [_dim("solvencia", "Solvencia", 50.0)]}]
    assert insurance_entity_context(rating, peers)["comparaciones"] == []


def test_el_posicionamiento_de_pares_tambien_las_lleva():
    rating, peers = _panel(_PARES, _MIOS)
    ctx = insurance_peer_context("Entidad", rating, peers)
    assert ctx["comparaciones"]
