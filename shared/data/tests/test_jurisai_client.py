"""JurisAI — el cliente que decide si se puede acusar a alguien de incumplir.

Los tests protegen las tres cosas que, si fallan, producen una afirmación falsa contra el
órgano evaluado: el rango obligatorio, la lectura del alcance, y que un 401 nunca se
traduzca a «no existe».
"""
import pytest

from shared.data.jurisai_client import (
    JurisAIUnavailable, buscar, normas, vacio_es_concluyente,
)

BASE = "https://jurisai.example/api/v1"


def test_sin_rango_de_fechas_se_niega_a_consultar():
    """El emisor lo declaró: sin `desde` y `hasta` el alcance se calcula desde 1900 y
    `vacio_es_concluyente` sale siempre false. Consultar así devolvería una lista vacía que
    NO autoriza a escribir «no se dictó» — y ese matiz se pierde en cuanto el parámetro es
    opcional."""
    for kw in ({"desde": "", "hasta": "2026-01-01"}, {"desde": "2012-01-25", "hasta": ""}):
        with pytest.raises(JurisAIUnavailable, match="concluyente"):
            buscar(BASE, "jrs_x_y", **kw)


def test_un_tipo_fuera_del_conjunto_no_se_manda():
    """Un tipo inventado devuelve vacío, y ese vacío se lee como «no se dictó». Falla acá
    en vez de producir una acusación."""
    with pytest.raises(JurisAIUnavailable, match="tipo"):
        buscar(BASE, "jrs_x_y", desde="2012-01-25", hasta="2026-01-01", tipo="ordenanza")


def test_el_alcance_manda_sobre_la_lista_vacia():
    """La única puerta entre `sin_registro_publico` —que no acusa— e `incumplida`, que sí.
    Se lee del alcance declarado por el emisor y jamás se asume."""
    concluyente = {"alcance": {"vacio_es_concluyente": True}, "resultados": []}
    con_hueco = {"alcance": {"vacio_es_concluyente": False, "huecos": ["1997-2001"]},
                 "resultados": []}
    assert vacio_es_concluyente(concluyente) is True
    assert vacio_es_concluyente(con_hueco) is False
    # Sin el bloque de alcance tampoco se asume: ausencia no es permiso.
    assert vacio_es_concluyente({"resultados": []}) is False
    assert normas(concluyente) == []


def test_una_credencial_rechazada_NO_es_una_norma_inexistente(monkeypatch):
    """El error más caro posible: que un 401 se traduzca a «la norma no se dictó» y el
    informe acuse al Estado de incumplir por culpa de nuestra clave."""
    import urllib.error

    from shared.data import jurisai_client as j

    def _falla(*a, **k):
        raise urllib.error.HTTPError(BASE, 401, "Unauthorized", None, None)

    monkeypatch.setattr(j.urllib.request, "urlopen", _falla)
    with pytest.raises(j.JurisAICredencial):
        buscar(BASE, "jrs_mala", desde="2012-01-25", hasta="2026-01-01")


def test_la_clave_viaja_con_el_prefijo_Bearer(monkeypatch):
    """Sin `Bearer ` delante el emisor devuelve 401 `credencial_ausente`, que se leería como
    clave equivocada y mandaría a pedir otra."""
    from shared.data import jurisai_client as j

    vistos = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"alcance":{"vacio_es_concluyente":true},"resultados":[]}'

    def _ok(req, timeout=0):
        vistos["auth"] = req.headers.get("Authorization")
        vistos["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(j.urllib.request, "urlopen", _ok)
    buscar(BASE, "jrs_ab_cd", desde="2012-01-25", hasta="2012-07-23",
           cita_a="ley:1-12", tipo="decreto")
    assert vistos["auth"] == "Bearer jrs_ab_cd"
    assert "cita_a=ley%3A1-12" in vistos["url"] and "tipo=decreto" in vistos["url"]
