"""REGLA ESTRUCTURAL: un conector con filtro geográfico decide QUÉ HACE con el total país.

**El caso que la motivó, que costó dos veces.** Una fuente sub-nacional trae, en el mismo
archivo, la fila del total nacional. El parser filtra por padrón de regiones o provincias,
esa fila no resuelve a ninguna, y se pierde — sin error, sin aviso, a veces con un
`continue`.

Las consecuencias no fueron teóricas. El eje de evaluación de leyes publicó la cobertura
educativa de `cibao_norte` (71,3%) y la escolaridad de `cibao_norte` (9,63) como si fueran
cifras del país, contra metas NACIONALES de una ley. La nacional estaba en el mismo archivo
que ya bajábamos: `TOTAL PAIS` en el tablero del MINERD, `Total` en el cuadro 05 3 007 del
SISDOM. Al revisar el resto aparecieron dos más — `Nacional` en el cuadro de ingreso y en
el de mortalidad infantil.

**Por qué un test y no una lección.** Este repo ya tiene la lección escrita y ya falló dos
veces con ella escrita. Lo que funciona acá es leer el código y exigir la decisión.

**Qué exige, y qué NO.** No exige capturar el total: para el SIUBEN sería un error, porque
su universo es el padrón de hogares focalizados y un «total» de ahí no es una tasa
poblacional. Exige DECIDIR y dejarlo escrito — capturarlo (``COUNTRY_SLUG``) o declarar por
qué no (``SIN_TOTAL_NACIONAL``). Lo que no se admite es que se pierda sin que nadie lo haya
pensado.
"""
import ast
import pathlib

import pytest

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent

#: Resolutores contra un padrón geográfico. Un módulo que llama a uno de estos filtra
#: filas o columnas por demarcación, y por lo tanto puede estar tirando el total del país.
_RESOLUTORES = {"region_slug", "province_slug"}

#: Las dos formas de haber decidido. `COUNTRY_SLUG` = se captura; `SIN_TOTAL_NACIONAL` = se
#: descarta a propósito, con el motivo en el propio valor.
_CAPTURA = "COUNTRY_SLUG"
_DECLARA = "SIN_TOTAL_NACIONAL"


def _modulos_con_filtro_geografico():
    for path in sorted(DATA_DIR.glob("*.py")):
        try:
            arbol = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        llamados = {n.func.id for n in ast.walk(arbol)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        llamados |= {n.func.attr for n in ast.walk(arbol)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        if llamados & _RESOLUTORES:
            yield path.name, arbol


def _nombres_de_modulo(arbol) -> set:
    return {t.id for n in ast.walk(arbol) if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)}


def test_el_detector_encuentra_los_conectores_geograficos():
    """Sin esto, un cambio de nombre en los resolutores volvería decorativa la regla."""
    encontrados = [n for n, _ in _modulos_con_filtro_geografico()]
    assert len(encontrados) >= 4, f"el detector se volvió decorativo: {encontrados}"


@pytest.mark.parametrize("modulo,arbol", list(_modulos_con_filtro_geografico()),
                         ids=lambda x: x if isinstance(x, str) else "")
def test_todo_conector_geografico_decide_que_hace_con_el_total_nacional(modulo, arbol):
    nombres = _nombres_de_modulo(arbol)
    assert nombres & {_CAPTURA, _DECLARA}, (
        f"{modulo} filtra por padrón geográfico y no dice qué hace con la fila del total "
        f"país. Esa fila viene en el mismo archivo y se pierde en el filtro sin aviso: ya "
        f"hizo publicar la cifra de una región como si fuera la del país, dos veces.\n"
        f"  · Si el total sirve, capturalo y definí {_CAPTURA}.\n"
        f"  · Si no sirve, definí {_DECLARA} con el motivo — que es lo que se lee cuando "
        f"alguien pregunte por qué falta."
    )
