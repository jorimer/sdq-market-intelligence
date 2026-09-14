"""Fase 8: lo que entró este mes al marco de la ley, vía JurisAI.

Lo que se protege es la NEGATIVA: «no se promulgó nada que afecte este marco» solo sale si el
emisor declara el vacío concluyente. Sin eso la sección dice que no se puede afirmar, y si la
fuente no responde dice que no se consultó. Ninguna de las tres cosas pasa por el modelo.
"""
import asyncio
from datetime import date

import pytest

from modules.law_intel import novedades as nv
from shared.products.tiers import ProductTier


def _resp(resultados=(), concluyente=False, truncado=False):
    return {"resultados": list(resultados), "truncado": truncado,
            "alcance": {"vacio_es_concluyente": concluyente, "huecos": []}}


# ── La prosa ──────────────────────────────────────────────────────────────────

def test_un_mes_con_novedades_las_LISTA_con_su_fecha_de_ingreso():
    r = _resp([{"tipo": "decreto", "numero": "210-26", "titulo": "Que reglamenta.",
                "fecha_de_ingesta": "2026-08-14"}])
    texto = nv.texto_de_novedades(r, desde=date(2026, 8, 1), norma="Ley 1-12")
    assert texto.startswith("En agosto de 2026 entraron a la base normativa 1 norma que citan la Ley 1-12:")
    assert "- Decreto 210-26 — Que reglamenta (ingresó el 2026-08-14)" in texto


def test_un_mes_VACIO_y_concluyente_publica_la_negativa_con_esa_palabra():
    texto = nv.texto_de_novedades(_resp(concluyente=True), desde=date(2026, 8, 1), norma="Ley 1-12")
    assert "ninguna norma" in texto and "esto es concluyente" in texto


def test_un_mes_VACIO_NO_concluyente_dice_que_no_se_puede_afirmar():
    texto = nv.texto_de_novedades(_resp(concluyente=False), desde=date(2026, 8, 1), norma="Ley 1-12")
    assert "no se puede afirmar" in texto
    assert "concluyente" not in texto and "ninguna norma" not in texto


def test_sin_respuesta_de_la_fuente_no_se_afirma_nada():
    texto = nv.texto_de_novedades(None, desde=date(2026, 8, 1), norma="Ley 1-12")
    assert "No se pudo consultar" in texto and "ninguna norma" not in texto


def test_una_lista_recortada_se_DECLARA():
    r = _resp([{"tipo": "ley", "numero": "1-26", "fecha_de_ingesta": "2026-08-02"}], truncado=True)
    assert "recortada" in nv.texto_de_novedades(r, desde=date(2026, 8, 1), norma="Ley 1-12")


# ── La consulta ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("norma, ref", [("Ley 1-12", "ley:1-12"), ("Ley No. 167-21", "ley:167-21"),
                                        ("Decreto 134-14", "decreto:134-14"), ("END 2030", None)])
def test_la_referencia_sale_de_la_norma_o_no_se_inventa(norma, ref):
    assert nv.referencia_de_norma(norma) == ref


@pytest.mark.parametrize("hoy, ventana", [
    (date(2026, 9, 14), (date(2026, 8, 1), date(2026, 8, 31))),
    (date(2026, 3, 1), (date(2026, 2, 1), date(2026, 2, 28))),
    (date(2026, 1, 5), (date(2025, 12, 1), date(2025, 12, 31))),
])
def test_la_ventana_es_el_ultimo_mes_CERRADO(hoy, ventana):
    assert nv.ventana_del_mes_cerrado(hoy) == ventana


def test_la_consulta_pide_por_INGESTA_con_la_cita_de_la_ley(monkeypatch):
    from shared.data import jurisai_client as jc
    from shared.settings import service as st

    vistos = {}

    def fake(base, clave, **kw):
        vistos.update(kw)
        return _resp(concluyente=True)

    monkeypatch.setattr(jc, "novedades", fake)
    monkeypatch.setattr(st, "get_sector_api_base_url", lambda db, p: "https://x")
    monkeypatch.setattr(st, "get_sector_api_key", lambda db, p: "k")
    texto, _ = nv.consultar_novedades(object(), norma="Ley 1-12", hoy=date(2026, 9, 14))
    assert vistos == {"desde": "2026-08-01", "hasta": "2026-08-31", "cita_a": "ley:1-12"}
    assert "concluyente" in texto


def test_si_jurisai_falla_la_seccion_lo_DICE_y_no_lanza(monkeypatch):
    from shared.data import jurisai_client as jc
    from shared.settings import service as st

    def revienta(*a, **k):
        raise jc.JurisAIUnavailable("502")

    monkeypatch.setattr(jc, "novedades", revienta)
    monkeypatch.setattr(st, "get_sector_api_base_url", lambda db, p: "https://x")
    monkeypatch.setattr(st, "get_sector_api_key", lambda db, p: "k")
    texto, resp = nv.consultar_novedades(object(), norma="Ley 1-12", hoy=date(2026, 9, 14))
    assert resp is None and "No se pudo consultar" in texto


# ── El producto ───────────────────────────────────────────────────────────────

def test_la_narrativa_deja_el_MARCADOR_sin_llamar_al_modelo_y_lo_vivo_lo_reemplaza(monkeypatch):
    from shared.narrative import claude_engine as ce
    from shared.products.contract import ProductSnapshot

    from modules.law_intel import products as lp

    pedidas = []

    async def fake(**kw):
        pedidas.append(kw["context"].get("seccion_pedida"))
        return ce.NarrativeResult(text="x")

    monkeypatch.setattr(ce.narrative_engine, "generate", fake)
    p = lp.LawProduct(db=object()) if hasattr(lp, "LawProduct") else None
    if p is None:
        cls = next(v for k, v in vars(lp).items() if k.endswith("Product") and isinstance(v, type))
        p = cls(db=object())
    snap = ProductSnapshot(tier=ProductTier.insight, period="2025",
                           payload={"contexto": {}, "sin_dato": [], "instrumento": {"norma": "Ley 1-12"}})
    narr = asyncio.run(p.narratives(ProductTier.insight, snap))
    assert narr[nv.SECCION_NOVEDADES] == nv.MARCADOR_NOVEDADES
    assert lp._SECTION_TITLES[nv.SECCION_NOVEDADES] not in pedidas, "la sección se le pidió al modelo"

    monkeypatch.setattr(lp, "consultar_novedades", lambda db, norma: ("TEXTO VIVO de " + norma, None))
    completo = p.completar_en_vivo(ProductTier.insight, snap, narr)
    assert completo[nv.SECCION_NOVEDADES] == "TEXTO VIVO de Ley 1-12"


def test_la_seccion_tiene_TITULO_y_MUESTRA_curada():
    from modules.law_intel import products as lp

    assert lp._SECTION_TITLES.get(nv.SECCION_NOVEDADES)
    assert lp._SAMPLE_NARRATIVES.get(nv.SECCION_NOVEDADES)


def test_una_seccion_SIN_MODELO_esta_declarada_y_no_tiene_plantilla():
    """La excepción del test de plantillas no puede crecer en silencio: cada sección declarada sin
    modelo tiene que estar en el manifiesto y NO tener plantilla."""
    from modules.law_intel.products import SECCIONES_SIN_MODELO, _SECTION_TEMPLATES, law_manifest

    en_el_manifiesto = {s for nivel in law_manifest().levels.values() for s in nivel.sections}
    assert set(SECCIONES_SIN_MODELO) == {nv.SECCION_NOVEDADES}
    assert set(SECCIONES_SIN_MODELO) <= en_el_manifiesto
    assert not set(SECCIONES_SIN_MODELO) & set(_SECTION_TEMPLATES)
