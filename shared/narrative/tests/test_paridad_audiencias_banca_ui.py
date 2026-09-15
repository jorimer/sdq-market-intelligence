"""Las audiencias de banca son las MISMAS en el cerebro y en el selector de la UI.

**Por qué existe (2026-09-15).** Un alto funcionario de Banco Múltiple Santa Cruz pidió sumar
las áreas comerciales como usuarias del informe. Al agregarla apareció que las audiencias de
banca vivían escritas dos veces —`cerebro.AUDIENCE_FRAMES["banking"]` y
`frontend/src/modules/banking-score/audience.ts`— sin nada que las mantuviera iguales. Una
audiencia solo en el backend no se puede elegir; una solo en la UI cae en silencio al default,
y el usuario cree que el informe está escrito para él.

Es la regla de la casa: un tipo nuevo se registra en TODAS sus superficies, o desaparece.
"""
import json
import pathlib
import re

from shared.narrative.cerebro import AUDIENCE_FRAMES

RAIZ = pathlib.Path(__file__).resolve().parents[3]
_AUDIENCE_TS = RAIZ / "frontend/src/modules/banking-score/audience.ts"
_I18N = ("es", "en", "fr")


def _audiencias_de_la_ui() -> list:
    texto = _AUDIENCE_TS.read_text(encoding="utf-8")
    bloque = re.search(r"export const AUDIENCES = \[(.*?)\]", texto, re.S)
    assert bloque, "no se encontró AUDIENCES en audience.ts: el lector quedó ciego"
    return re.findall(r'"(\w+)"', bloque.group(1))


def test_el_backend_y_la_ui_declaran_las_mismas_audiencias_de_banca():
    backend = set(AUDIENCE_FRAMES["banking"])
    ui = set(_audiencias_de_la_ui())
    assert len(ui) >= 4, "el lector de la UI no encontró las audiencias: no probó nada"
    assert backend == ui, {"solo_backend": backend - ui, "solo_ui": ui - backend}


def test_toda_audiencia_de_la_ui_tiene_su_etiqueta_en_los_tres_idiomas():
    ui = _audiencias_de_la_ui()
    for lang in _I18N:
        datos = json.loads((RAIZ / f"frontend/src/shared/i18n/{lang}.json").read_text(
            encoding="utf-8"))
        etiquetas = [v for v in _buscar(datos, "audience") if isinstance(v, dict)
                     and "comite_credito" in v]
        assert etiquetas, f"{lang}: no se encontró el bloque de etiquetas de audiencia"
        faltan = [a for a in ui if a not in etiquetas[0]]
        assert not faltan, f"{lang}: audiencias sin etiqueta {faltan}"


def _buscar(nodo, clave):
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            if k == clave:
                yield v
            yield from _buscar(v, clave)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from _buscar(v, clave)
