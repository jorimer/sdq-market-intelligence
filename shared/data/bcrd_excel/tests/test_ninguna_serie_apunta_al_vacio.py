"""Ninguna serie del BCRD que el código de producción USA puede venir de un archivo apagado.

**El defecto que este guard existe para no repetir.** El motor de costo de capital se
construyó sobre `bcrd.xls.valores_bc_mn.mas_de_dos_anos` —la curva soberana en pesos, el
insumo de `Ke`— y ese archivo **nunca estuvo en `PERSISTIBLES_VERIFICADOS`**, la lista blanca
de los que el sync escribe. La serie no existe en ninguna base, ni en producción ni en dev.

Nada falló. Los tests de la curva pasaron en verde porque probaban la REGLA DE ESCALA con
números escritos a mano, no que la serie existiera; `ESCALAS_CURADAS` declaró tres entradas
para un archivo que nadie ingiere; y el eje de valuación quedó bloqueado en producción con
readiness 0,30 y el mensaje «sin motor», que se lee como código faltante cuando lo que falta
es el DATO.

Es la reincidencia de una lección ya escrita —un binding a una serie inexistente no falla— y
por eso la cura es estructural y no otra nota: se lee el código con `ast`, se junta todo
literal que empiece con `bcrd.xls.`, y se exige que su archivo esté habilitado.

**Cómo se levanta un fallo de este test.** No agregando el archivo a la lista sin más: la
lista se llama VERIFICADOS y entrar exige haber comprobado la extracción. Si el archivo no
está listo, lo que hay que cambiar es el código que depende de él —o declarar la excepción
acá, con su motivo—.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Set

from shared.data.bcrd_excel.canonical import PERSISTIBLES_VERIFICADOS
from shared.data.bcrd_excel.extract import default_prefix

_RAIZ = Path(__file__).resolve().parents[4]
#: Dónde vive el código que CONSUME series. Los tests quedan fuera a propósito: un test puede
#: nombrar una serie que no existe para probar justamente ese caso.
_ARBOLES = ("modules", "shared", "app")

#: Excepciones DECLARADAS: series nombradas en producción cuyo archivo no está habilitado, con
#: el motivo y qué haría falta. Vacío es el estado sano. Una excepción sin motivo no entra.
#:
EXCEPCIONES: Dict[str, str] = {}



def _archivos_habilitados() -> Set[str]:
    return {default_prefix(f) for f in PERSISTIBLES_VERIFICADOS}


def _literales_de_serie() -> Dict[str, List[str]]:
    """Todo literal `bcrd.xls.…` del código de producción, con dónde aparece.

    Se lee con `ast` y no con una expresión regular: un `bcrd.xls.` dentro de un comentario o
    de un docstring no es una dependencia, y confundirlos haría fallar el guard por texto en
    vez de por código. `ast.walk` además entra en métodos y en comprensiones, que es donde
    una lectura por bloques de primer nivel se pierde la mitad.
    """
    fuera: Dict[str, List[str]] = {}
    for arbol in _ARBOLES:
        for py in (_RAIZ / arbol).rglob("*.py"):
            if "tests" in py.parts or py.name.startswith("test_"):
                continue
            try:
                arbol_ast = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
                continue
            for nodo in ast.walk(arbol_ast):
                if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                    v = nodo.value
                    # El tercer segmento es el SLUG del archivo. Exigirlo no vacío deja
                    # fuera el prefijo pelado `"bcrd.xls."`, que es la constante con que el
                    # motor arma los códigos y no nombra ningún archivo.
                    segmentos = v.split(".")
                    if (v.startswith("bcrd.xls.") and len(segmentos) >= 3
                            and segmentos[2]):
                        fuera.setdefault(v, []).append(
                            f"{py.relative_to(_RAIZ)}:{nodo.lineno}")
    return fuera


def test_TODA_excepcion_trae_su_motivo_y_su_salida() -> None:
    """Una lista blanca sin motivo se vuelve permanente por inercia.

    Cada excepción tiene que decir qué se midió y qué haría falta para levantarla; si no, en
    seis meses nadie recuerda si el archivo estaba roto o si se olvidó habilitarlo.
    """
    for prefijo, motivo in EXCEPCIONES.items():
        assert prefijo.count(".") == 2, (
            f"«{prefijo}» no es un prefijo de ARCHIVO: la excepción se declara por libro, no "
            "por serie")
        assert len(motivo) > 120, f"«{prefijo}» excepcionada sin explicar qué se midió"
        # La SALIDA se busca por vocabulario y no por una frase exacta: el motivo se
        # reescribe cuando se mide de nuevo —ya pasó— y un test atado a una redacción
        # concreta falla por la razón equivocada. Cualquiera de estas formas cuenta como
        # «acá está lo que hay que hacer para levantarla».
        salidas = ("levantarla", "haría falta", "hay que", "habilitar")
        assert any(x in motivo.lower() for x in salidas), (
            f"«{prefijo}» no dice qué hay que hacer para levantarla; se esperaba alguna de "
            f"{salidas}")


def test_el_barrido_ENCUENTRA_series() -> None:
    """Un barrido vacío pasaría todos los tests de abajo sin mirar nada.

    Es la misma trampa que un `@parametrize` vacío: sale verde y no probó nada. Si alguien
    mueve el árbol o cambia el prefijo de los códigos, este test cae primero.
    """
    encontradas = _literales_de_serie()
    assert len(encontradas) >= 3, (
        f"el guard solo encontró {len(encontradas)} literales `bcrd.xls.…` en el código de "
        "producción: o el barrido dejó de funcionar, o el prefijo cambió")


def test_toda_serie_del_BCRD_que_el_codigo_usa_viene_de_un_archivo_HABILITADO() -> None:
    huerfanas: List[str] = []
    habilitados = _archivos_habilitados()
    for serie, lugares in sorted(_literales_de_serie().items()):
        # El prefijo del archivo son los tres primeros segmentos: `bcrd`, `xls`, y el slug.
        prefijo = ".".join(serie.split(".")[:3])
        if prefijo in EXCEPCIONES:
            continue
        if prefijo not in habilitados:
            huerfanas.append(f"  {serie}\n      usada en {', '.join(lugares)}")
    assert not huerfanas, (
        "hay series del BCRD nombradas en el código de producción cuyo archivo NO está en "
        "`PERSISTIBLES_VERIFICADOS`, o sea que NADIE las escribe y valen vacío en toda base:"
        "\n" + "\n".join(huerfanas) + "\n\n"
        "Habilitar el archivo exige haber verificado su extracción — la lista se llama "
        "VERIFICADOS. Si no está listo, cambiá el código que depende de él o declará la "
        "excepción en EXCEPCIONES con su motivo.")


def test_las_ESCALAS_CURADAS_tampoco_corrigen_archivos_apagados() -> None:
    """Una escala curada para un archivo que nadie ingiere es trabajo que no corre.

    Peor: se lee como que el archivo está cubierto. Las tres entradas de `valores_bc_mn`
    existían mientras el archivo estaba apagado, y eso hacía parecer resuelto un problema de
    escala en una serie que no existía.
    """
    from shared.data.bcrd_excel.canonical import ESCALAS_CURADAS
    habilitados = _archivos_habilitados()
    huerfanas = sorted(
        p for p in ESCALAS_CURADAS
        if p.startswith("bcrd.xls.")
        and ".".join(p.split(".")[:3]) not in habilitados
        and ".".join(p.split(".")[:3]) not in EXCEPCIONES)
    assert not huerfanas, (
        "escalas curadas para archivos que no se ingieren: " + ", ".join(huerfanas))
