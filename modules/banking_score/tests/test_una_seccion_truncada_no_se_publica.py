"""Un texto CORTADO no es un texto terminado, y no llega al PDF.

**El boletín que salió partido a la mitad.** El 2026-09-06 se generó un boletín regional real
y el PDF de distribución terminaba así: «La construcción industrial (4 186 un». Cortado a
mitad de palabra. Además faltaba El Salvador, que sí había llegado al contexto con sus 22
series: era el último en orden ISO3 y el texto se acabó antes de llegar a él.

Nada falló. El motor SÍ distinguía «cortado» de «terminado» —la API lo declara en
`stop_reason` y viaja en `NarrativeResult.truncated`— pero el ensamblador hacía
`narratives[section] = result.text` y tiraba la señal. Quedaba un `logger.warning` que nadie
lee antes de que el PDF salga.

La causa de fondo: §2 se narraba con UNA llamada para TODOS los países, con presupuesto fijo.
La plantilla pedía «máximo 900 palabras» para recorrer nueve sistemas —100 por país— y el
contenido real fueron 2.181. Cada país nuevo acercaba el corte, así que el defecto empeoraba
solo: lo activamos nosotros al sumar Chile y recuperar las siete plazas de SECMCA.
"""
import asyncio

import pytest

from modules.banking_score.reports.narrative import (
    NarrativaTruncada,
    _exigir_texto_entero,
    _exigir_un_cuerpo_POR_PAIS,
    encabezado_de_pais,
)


class _Resultado:
    def __init__(self, text="texto", truncated=False):
        self.text = text
        self.truncated = truncated


def test_un_texto_terminado_pasa():
    _exigir_texto_entero("boletin_sistemas", _Resultado())


def test_un_texto_CORTADO_no_pasa():
    """Publicarlo imprime una frase a medias en un documento que se distribuye."""
    with pytest.raises(NarrativaTruncada, match="truncado, no terminado"):
        _exigir_texto_entero("boletin_sistemas", _Resultado(truncated=True))


def test_el_mensaje_NOMBRA_la_seccion():
    """Sin el nombre, quien mira el error no sabe qué sección partir ni cuál subir de modo."""
    with pytest.raises(NarrativaTruncada, match="boletin_armonizado"):
        _exigir_texto_entero("boletin_armonizado", _Resultado(truncated=True))


# ── Que no falte ningún país ──────────────────────────────────────
_BLOQUES = [{"iso3": "CHL", "pais": "Chile"}, {"iso3": "PAN", "pais": "Panamá"},
            {"iso3": "SLV", "pais": "El Salvador"}]


def test_estan_los_tres_paises():
    _exigir_un_cuerpo_POR_PAIS(_BLOQUES, ["cuerpo", "cuerpo", "cuerpo"])


def test_un_pais_que_NO_se_nombro_hace_fallar():
    """Es el caso real: El Salvador llegó al contexto y no salió en la prosa."""
    textos = ["Chile — corte julio 2026…", "Panamá — corte julio 2026…", ""]
    with pytest.raises(NarrativaTruncada, match="El Salvador"):
        _exigir_un_cuerpo_POR_PAIS(_BLOQUES, textos)


def test_un_cuerpo_en_BLANCO_tampoco_cuenta():
    """Un país «presente» con texto vacío es un país ausente con mejor disfraz."""
    with pytest.raises(NarrativaTruncada, match="El Salvador"):
        _exigir_un_cuerpo_POR_PAIS(_BLOQUES, ["Chile…", "Panamá…", "   \n  "])


# ── El encabezado se COMPUTA ──────────────────────────────────────
def test_el_encabezado_lo_ponemos_NOSOTROS():
    """El corte, la fuente y la norma son datos del bloque: no se delegan a quien puede
    copiarlos mal. Y así el nombre del país no depende de cómo el modelo decida abreviarlo."""
    e = encabezado_de_pais({
        "iso3": "CHL", "pais": "Chile", "corte_mas_reciente": "2026-07-31",
        "norma_contable": ["CMF Chile — Basilea III (LGB Título VII, arts. 66 y ss.)",
                           "CMF Chile — Compendio de Normas Contables 2022"],
        "series": [{"fuente": "CMF Chile"}]})
    assert e.startswith("Chile — corte julio 2026")
    assert "CMF Chile" in e and "Basilea III" in e and "Compendio" in e
    # La fuente no se repite tres veces: las normas vienen prefijadas por su emisor.
    assert e.count("CMF Chile") == 1


def test_el_encabezado_NOMBRA_al_pais_aunque_el_modelo_lo_abrevie():
    """El caso real: el modelo escribió «RD» y el guard viejo, que exigía el nombre literal,
    tumbó un boletín entero. El nombre lo pone el documento, no la prosa."""
    e = encabezado_de_pais({
        "iso3": "DOM", "pais": "República Dominicana", "corte_mas_reciente": "2026-07-31",
        "norma_contable": ["EMFA armonizado"], "series": [{"fuente": "SECMCA"}]})
    assert e == "República Dominicana — corte julio 2026 (SECMCA; EMFA armonizado)"


def test_un_bloque_sin_corte_no_inventa_una_fecha():
    e = encabezado_de_pais({"iso3": "XXX", "pais": "Sin corte", "series": []})
    assert e == "Sin corte"


# ── §2 se genera país por país ────────────────────────────────────
def test_hay_una_llamada_por_PAIS_y_no_una_sola_para_todos(monkeypatch):
    """El arreglo de raíz. Mientras la sección comparta un presupuesto, agregar un país
    puede volver a tirar a otro por la borda sin que nada falle."""
    from modules.banking_score.reports import narrative as n

    llamadas = []

    class _Motor:
        async def generate(self, context, template, mode, **kw):
            llamadas.append((template, context.get("pais")))
            return _Resultado(text=f"{context.get('pais')} — corte julio 2026. Cuerpo.")

    monkeypatch.setattr(n, "narrative_engine", _Motor())
    ctx = {"bloques_por_pais": _BLOQUES, "regla": "cada país dentro de su sistema"}
    texto = asyncio.run(n._narrar_pais_por_pais(ctx, "deep"))

    assert len(llamadas) == 3, f"se hicieron {len(llamadas)} llamadas para 3 países"
    assert {p for _t, p in llamadas} == {"Chile", "Panamá", "El Salvador"}
    assert {t for t, _p in llamadas} == {"boletin_sistema_pais"}
    # Cada país queda nombrado por SU encabezado, que ponemos nosotros.
    for b in _BLOQUES:
        assert b["pais"] in texto


def test_si_UN_pais_se_trunca_no_se_publica_el_resto(monkeypatch):
    """Un país cortado no se disimula entregando los otros ocho."""
    from modules.banking_score.reports import narrative as n

    class _Motor:
        async def generate(self, context, template, mode, **kw):
            corta = context.get("pais") == "Panamá"
            return _Resultado(text=f"{context.get('pais')} — texto", truncated=corta)

    monkeypatch.setattr(n, "narrative_engine", _Motor())
    with pytest.raises(NarrativaTruncada, match="PAN"):
        asyncio.run(n._narrar_pais_por_pais({"bloques_por_pais": _BLOQUES}, "deep"))


def test_la_plantilla_por_pais_existe_y_solo_pide_context():
    """El formateo pasa ÚNICAMENTE `context`: cualquier otro marcador revienta con KeyError
    en tiempo de generación, que es el peor momento para enterarse."""
    import re

    from shared.narrative.claude_engine import THIN_TEMPLATES

    plantilla = THIN_TEMPLATES["boletin_sistema_pais"]
    assert set(re.findall(r"\{(\w+)\}", plantilla)) == {"context"}
