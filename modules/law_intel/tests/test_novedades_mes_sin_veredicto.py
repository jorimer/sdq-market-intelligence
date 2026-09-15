"""Un mes sin veredicto de JurisAI se DECLARA indeterminado, también cuando trae normas.

**El caso (prod, 2026-09-14).** Agosto de 2026 no era concluyente para JurisAI —sus corridas no
cubrieron el mes completo en todas las fuentes— y trajo cuatro resoluciones que citan la Ley 1-12.
El panel del operador lo leía bien (`law:jurisai` indeterminada). El informe del cliente decía
«En agosto de 2026 entraron a la base normativa 4 normas…» y nada más: una lista que se lee como
TODO lo que entró, sobre un mes cuya cobertura el emisor no garantiza. Si faltaba una norma, el
documento lo afirmaba sin saberlo.

**La regla.** El veredicto del mes se computa UNA vez (`veredicto_del_mes`) y lo leen el texto y la
señal del panel, para que no puedan contradecirse. Un mes sin cobertura concluyente es
`indeterminado` tenga o no normas, y la sección lo dice con esa palabra.
"""
from datetime import date

import pytest

from modules.law_intel import novedades as nv

AGOSTO = date(2026, 8, 1)
NORMAS = [{"tipo": "resolucion", "numero": "339-21", "titulo": "Que aprueba un fideicomiso.",
           "fecha_de_ingesta": "2026-08-20"}]


def _resp(resultados=(), concluyente=False):
    return {"resultados": list(resultados), "truncado": False,
            "alcance": {"vacio_es_concluyente": concluyente, "huecos": []}}


# ── El texto de la sección ────────────────────────────────────────────────────

def test_un_mes_CON_normas_y_sin_cobertura_concluyente_se_declara_indeterminado():
    texto = nv.texto_de_novedades(_resp(NORMAS, concluyente=False), desde=AGOSTO, norma="Ley 1-12")
    assert "- Resolucion 339-21" in texto, "la lista se sigue publicando"
    assert "indeterminado" in texto
    assert "puede no estar completa" in texto


def test_un_mes_CON_normas_y_cobertura_concluyente_no_se_declara_indeterminado():
    texto = nv.texto_de_novedades(_resp(NORMAS, concluyente=True), desde=AGOSTO, norma="Ley 1-12")
    assert "indeterminado" not in texto and "puede no estar completa" not in texto


def test_un_mes_VACIO_sin_cobertura_concluyente_se_declara_indeterminado():
    texto = nv.texto_de_novedades(_resp(concluyente=False), desde=AGOSTO, norma="Ley 1-12")
    assert "indeterminado" in texto
    # La palabra «concluyente» sigue fuera: en este caso solo puede aparecer la negativa firme.
    assert "concluyente" not in texto and "ninguna norma" not in texto


def test_un_mes_VACIO_y_concluyente_publica_la_negativa_sin_indeterminado():
    texto = nv.texto_de_novedades(_resp(concluyente=True), desde=AGOSTO, norma="Ley 1-12")
    assert "esto es concluyente" in texto and "indeterminado" not in texto


# ── El veredicto del mes: una sola lectura ────────────────────────────────────

@pytest.mark.parametrize("respuesta, estado", [
    (_resp(NORMAS, concluyente=True), "completo"),
    (_resp(concluyente=True), "sin_novedades"),
    (_resp(NORMAS, concluyente=False), "indeterminado"),
    (_resp(concluyente=False), "indeterminado"),
    (None, "no_consultado"),
])
def test_el_veredicto_del_mes_distingue_los_cinco_casos_en_cuatro_estados(respuesta, estado):
    assert nv.veredicto_del_mes(respuesta) == estado


# ── La señal del panel lee el MISMO veredicto ─────────────────────────────────

def _senal(monkeypatch, respuesta):
    from modules.law_intel import products as lp

    monkeypatch.setattr(lp, "consultar_novedades", lambda db, norma: ("texto", respuesta))
    cls = next(v for k, v in vars(lp).items() if k.endswith("Product") and isinstance(v, type))
    senales = cls(db=object()).senales_de_fuentes()
    assert len(senales) == 1
    return senales[0]


def test_el_panel_declara_indeterminado_el_mes_con_normas_sin_cobertura(monkeypatch):
    s = _senal(monkeypatch, _resp(NORMAS, concluyente=False))
    assert s.freshness_days is None
    assert "indeterminado" in s.detalle


def test_el_panel_no_declara_indeterminado_un_mes_completo(monkeypatch):
    s = _senal(monkeypatch, _resp(NORMAS, concluyente=True))
    assert s.freshness_days is not None
    assert "indeterminado" not in s.detalle
