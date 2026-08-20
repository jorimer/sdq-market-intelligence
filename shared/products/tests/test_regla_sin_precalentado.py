"""REGLA ESTRUCTURAL: la plataforma no pre-calienta informes. Se generan cuando alguien los pide.

**El caso que la motivó (2026-08-20).** El pre-calentado se había dado por eliminado y volvió
a correr: generó informes que nadie pidió y gastó IA sola el día del sync. Nunca se había
eliminado del código — solo se había apagado el toggle de la consola, y el toggle no gobernaba
ninguno de los tres caminos que lo disparaban:

1. *La agenda sembrada.* ``seed_default_schedules`` crea agenda ACTIVA para toda operación con
   cadencia > 0 que no tenga fila. Respeta la fila existente, sí — pero apagar el pre-calentado
   BORRANDO su fila hacía que el arranque siguiente la recreara encendida.
2. *La cascada por evento.* ``shared/products/events.py`` lo disparaba tras cada ``*.updated``.
   La cascada no mira la agenda: el toggle apagado no la frenaba.
3. *La lista ``triggers`` de otra operación.* Cualquier sync que se declare aguas arriba lo
   revive por la puerta de atrás, sin tocar el paquete de productos.

Por eso la decisión fue ELIMINARLO —motor, operación y disparadores—, no apagarlo: un apagado
vive en la base de datos y cualquier deploy, seed o cascada lo revierte sin que nadie lo note.

**Por qué un test y no una nota.** La nota ya estaba: el módulo del warm decía "operación de
consola desacoplada" mientras un suscriptor lo disparaba solo. Lo que sostiene la decisión es
que el nombre no pueda volver al código sin que un test lo diga.

**La regla**, con tres redes:

1. El módulo del motor (``shared/products/prewarm.py``) no existe.
2. Ninguna operación registrada pre-calienta: ni por nombre, ni declarada aguas abajo en el
   ``triggers`` de otra.
3. Ningún archivo de producción nombra al warm en código vivo (los docstrings pueden contar la
   historia; el código, no). Cubre el disparo directo, el indirecto vía constante y el
   ``triggers=[…]``.

Si algún día se decide volver a pre-calentar, que sea borrando este archivo a propósito — no
por descuido.
"""
import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: El nombre que tenía la operación eliminada, y el del módulo que la ejecutaba.
OP = "prewarm-report-cache"
MODULO = "shared/products/prewarm.py"

#: Símbolos del motor eliminado. Un import de estos no compilaría, pero el nombre reaparece
#: primero en un string o en un comentario de quien lo está reponiendo.
SIMBOLOS = ("prewarm_report_cache", "prewarm-report-cache")

#: Paquetes de producción barridos. Los tests quedan afuera: nombran al warm para probar que
#: no está, que es justo lo que hace este archivo.
PAQUETES = ("shared", "modules", "app")


def _archivos_de_produccion():
    for paquete in PAQUETES:
        for ruta in (RAIZ / paquete).rglob("*.py"):
            rel = ruta.relative_to(RAIZ).as_posix()
            if "/tests/" in rel or rel.rsplit("/", 1)[-1].startswith("test_"):
                continue
            yield rel, ruta


def _codigo_vivo(arbol: ast.AST) -> list:
    """Los string literales del módulo MENOS los docstrings: contar la historia del warm en
    prosa es legítimo y deseable; tener su nombre en código es un camino de vuelta."""
    docstrings = set()
    for nodo in ast.walk(arbol):
        cuerpo = getattr(nodo, "body", None)
        if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) \
                and cuerpo and isinstance(cuerpo[0], ast.Expr) \
                and isinstance(cuerpo[0].value, ast.Constant) \
                and isinstance(cuerpo[0].value.value, str):
            docstrings.add(id(cuerpo[0].value))
    return [n for n in ast.walk(arbol)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def test_el_motor_de_precalentado_no_existe():
    """Red 1: sin módulo no hay qué disparar, ni desde la consola ni desde un script."""
    assert not (RAIZ / MODULO).exists(), (
        f"{MODULO} volvió: el pre-calentado se eliminó el 2026-08-20 porque generaba informes "
        "que nadie pidió. Si hay una decisión nueva de repetirlo, borrá este test a propósito.")


def test_ninguna_operacion_precalienta():
    """Red 2: no está registrada, ni la revive el ``triggers`` de otra (la puerta de atrás)."""
    import app.main  # noqa: F401 — importa todos los módulos: el registro queda completo
    from shared.operations.service import OPERATIONS

    assert OP not in OPERATIONS, (
        f"{OP} volvió al registro de operaciones: el arranque le sembraría agenda y volvería "
        "a correr sola.")
    aguas_arriba = [n for n, op in OPERATIONS.items() if OP in (op.triggers or [])]
    assert aguas_arriba == [], (
        f"{aguas_arriba} declaran {OP} aguas abajo: lo revivirían por cascada.")


def test_ningun_archivo_de_produccion_nombra_el_precalentado():
    """Red 3: el nombre no aparece en código vivo en ningún paquete de producción.

    No busca la forma ``trigger("…")`` a propósito: una constante intermedia o un helper nuevo
    la esquivarían. El nombre mismo es la superficie que se vigila.
    """
    hallazgos = []
    for rel, ruta in _archivos_de_produccion():
        texto = ruta.read_text(encoding="utf-8")
        if not any(s in texto for s in SIMBOLOS):
            continue  # atajo: ni lo menciona
        try:
            arbol = ast.parse(texto)
        except SyntaxError:  # pragma: no cover — un archivo roto ya falla en otro lado
            continue
        for nodo in _codigo_vivo(arbol):
            if any(s in nodo.value for s in SIMBOLOS):
                hallazgos.append(f"{rel}:{nodo.lineno}")
        for nodo in ast.walk(arbol):
            nombres = []
            if isinstance(nodo, ast.Name):
                nombres = [nodo.id]
            elif isinstance(nodo, ast.Attribute):
                nombres = [nodo.attr]
            elif isinstance(nodo, (ast.Import, ast.ImportFrom)):
                nombres = [a.name for a in nodo.names] + [getattr(nodo, "module", "") or ""]
            if any(s in (n or "") for n in nombres for s in SIMBOLOS):
                hallazgos.append(f"{rel}:{nodo.lineno}")
    assert not hallazgos, (
        f"código vivo vuelve a nombrar el pre-calentado en {sorted(set(hallazgos))}. Se eliminó "
        "el 2026-08-20: los informes se generan cuando alguien los descarga.")
