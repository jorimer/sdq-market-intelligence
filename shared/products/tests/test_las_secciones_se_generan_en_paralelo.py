"""REGLA ESTRUCTURAL: ningún producto genera sus secciones de a una.

**El caso que la motivó (2026-09-01).** `banking_year_review` era el ÚNICO producto del
catálogo que hacía `await narrative_engine.generate(...)` DENTRO del bucle de secciones. Los
otros doce fanean con `asyncio.gather`. La consecuencia no es de estilo: su tiempo de
ensamblado es la SUMA de sus secciones en vez de la más lenta, y por eso cruzaba el techo de
`PRESUPUESTO_DE_ENSAMBLADO_S`. Medido sobre la ventana del 25/8 al 1/9, en el Deep Dive:

    revision_anual          p90 212,3 s
    banking_sector_map      p90  79,8 s
    revision_anual_mercado  p90  55,3 s
    ─────────────────────────────────────
    SUMA (lo que tardaba)   p90 347,4 s   ← por encima del techo de 270 s
    MÁXIMO (faneado)        p90 212,3 s   ← 21 % por debajo

Y no se veía: la telemetría de tiempos AFIRMABA que las secciones corren en paralelo, así que
el diagnóstico buscó una cola larga durante semanas en vez de una suma.

Es la familia «el guard existe en un motor y falta en el otro», que en este repo ya se
repitió ocho veces, y la cura acordada para la reincidencia es un test estructural que lee el
código y exige la regla o una excepción DECLARADA.

**Qué queda afuera del barrido, dicho a propósito:** solo se miran los `products*.py` de los
módulos, que es donde vive el contrato `narratives()`. Un producto que naciera fuera de esa
ruta no se revisaría — por eso el test también comprueba que sigue ENCONTRANDO productos.
"""
import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: Productos que generan de a una con un motivo, y el motivo. Vacío hoy: no es un hueco
#: reservado «por si acaso» sino la puerta declarada. Una entrada acá tiene que decir POR QUÉ
#: la suma de sus secciones cabe en el presupuesto de ensamblado.
SECUENCIALES_DECLARADOS: dict = {}


def _fuentes():
    return sorted(RAIZ.glob("modules/*/products*.py"))


def _narratives(arbol):
    """Las definiciones de `narratives` del archivo (puede haber varias clases)."""
    return [n for n in ast.walk(arbol)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "narratives"]


def _await_dentro_de_bucle(fn) -> bool:
    """¿Hay un `await` en el CUERPO de un `for`?

    Se mira el cuerpo y no el iterador a propósito: `for x in await asyncio.gather(...)` es
    justo el idiom correcto —se arma la lista y se fanea— y marcarlo lo prohibiría.
    """
    for nodo in ast.walk(fn):
        if not isinstance(nodo, (ast.For, ast.AsyncFor, ast.While)):
            continue
        for hijo in nodo.body:
            for sub in ast.walk(hijo):
                if isinstance(sub, ast.Await):
                    return True
    return False


def test_el_barrido_encuentra_productos():
    """Un barrido que no encuentra nada pasa en verde sin haber probado nada."""
    fuentes = _fuentes()
    assert len(fuentes) >= 10, f"solo {len(fuentes)} archivos de producto: el glob se quedó corto"
    con_narrativas = [f for f in fuentes if _narratives(ast.parse(f.read_text(encoding="utf-8")))]
    assert len(con_narrativas) >= 10, (
        f"solo {len(con_narrativas)} definen `narratives`: el barrido no está mirando el "
        "contrato que dice mirar")


@pytest.mark.parametrize("fuente", _fuentes(), ids=lambda p: p.parent.name + "/" + p.name)
def test_ningun_producto_genera_sus_secciones_de_a_una(fuente):
    arbol = ast.parse(fuente.read_text(encoding="utf-8"))
    clave = f"{fuente.parent.name}/{fuente.name}"
    for fn in _narratives(arbol):
        if not _await_dentro_de_bucle(fn):
            continue
        motivo = SECUENCIALES_DECLARADOS.get(clave)
        assert motivo, (
            f"{clave}: `narratives` hace `await` dentro de un bucle, así que su tiempo de "
            "ensamblado es la SUMA de sus secciones y no la más lenta. Faneá con "
            "`asyncio.gather` —el idiom está en `law_intel`— o declaralo en "
            "`SECUENCIALES_DECLARADOS` diciendo por qué esa suma cabe en "
            "`PRESUPUESTO_DE_ENSAMBLADO_S`")


def test_una_excepcion_declarada_tiene_que_seguir_siendo_secuencial():
    """La puerta se cierra de los dos lados: un producto que se declara secuencial y ya no lo
    es deja una excepción muerta, y una excepción muerta es la que alguien reutiliza mañana
    para tapar un caso nuevo sin pensarlo."""
    for clave in SECUENCIALES_DECLARADOS:
        fuente = RAIZ / "modules" / clave
        assert fuente.exists(), f"{clave} declarado como secuencial y no existe"
        arbol = ast.parse(fuente.read_text(encoding="utf-8"))
        assert any(_await_dentro_de_bucle(fn) for fn in _narratives(arbol)), (
            f"{clave} ya no genera de a una: sacá su entrada de SECUENCIALES_DECLARADOS")
