"""El motor de Research tiene que VER el cruce socio × capítulo.

El 2026-08-13 un informe a medida respondió que el desglose de importaciones desde China
"excede lo que los motores disponibles pueden responder", e INFIRIÓ la composición ("bienes de
consumo masivo, insumos industriales… son categorías plausibles"). El dato existía a una
llamada de Comtrade; después se ingirió y se expuso, y el motor SEGUÍA sin verlo porque
`_trade_summary` sólo leía `payload["score"]`.
"""
from shared.research.data_pull import _trade_summary

_PAYLOAD = {
    "score": {"resilience_score": 67.3, "import_dependency": 0.7},
    "socios_por_capitulo": {
        "China": {
            "period": "2025", "total_usd_mm": 5988.0, "n_capitulos": 94,
            "capitulos_top": [{"capitulo": "85", "usd_mm": 1040.0, "pct": 17.4},
                              {"capitulo": "84", "usd_mm": 946.0, "pct": 15.8}],
            "truncado": 92, "fuente": "UN Comtrade",
        }
    },
}


def _textos(payload):
    return " ".join(e.text for e in _trade_summary("RD", payload, "2026-Q2", "trade"))


def test_el_desglose_por_socio_llega_como_evidencia():
    t = _textos(_PAYLOAD)
    assert "China" in t and "5,988" in t.replace(".", ",") or "5988" in t.replace(",", "")
    assert "cap. 85" in t and "94 capítulos" in t


def test_el_sujeto_viaja_con_el_numero():
    """Cada línea nombra al socio: sin eso el modelo reatribuye la cifra al total del país,
    que es exactamente el error que produjo «cuatro compañías concentran el 87,1%»."""
    for e in _trade_summary("RD", _PAYLOAD, "2026-Q2", "trade"):
        if "cap. 85" in e.text:
            assert "China" in e.text
            break
    else:
        raise AssertionError("no se emitió la evidencia de capítulos")


def test_el_recorte_no_es_silencioso():
    """Un top-N sin avisar se lee como si fuera la corriente entera."""
    assert "92 capítulos más no listados" in _textos(_PAYLOAD)


def test_sin_el_cruce_el_motor_no_inventa_nada():
    """Sin el dato, ninguna evidencia habla de composición por bien: la brecha queda visible
    y el modelo tiene que declararla en vez de inferir 'categorías plausibles'."""
    solo_score = {"score": _PAYLOAD["score"]}
    t = _textos(solo_score)
    assert "cap." not in t and "China" not in t
    assert "resiliencia" in t          # lo que sí hay se sigue sirviendo


def test_un_socio_sin_capitulos_no_emite_linea_vacia():
    p = {"score": _PAYLOAD["score"],
         "socios_por_capitulo": {"Vietnam": {"period": "2025", "capitulos_top": []}}}
    assert "Vietnam" not in _textos(p)
