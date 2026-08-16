"""Guards ESTRUCTURALES de la numeración fiscal — leen el código con ``ast``.

Dos defectos de este dominio no se arreglan con una lección escrita, porque reaparecen en la
superficie SIGUIENTE (ya pasó con los guards de narrativa: se arreglan en un motor y faltan en
el otro):

1. **Avanzar el contador fuera del asignador.** Cualquier otro lugar que haga ``+= 1`` sobre
   ``current`` reintroduce la pérdida de actualización que el compare-and-swap eliminó — y lo
   hace sin ruido, porque el número sale bien la mayoría de las veces.
2. **Publicar el número sin su tipo.** Un ``B0200000001`` sin decir que es Factura de Consumo
   deja que el lector lo reatribuya; es el mismo modo de falla que hizo publicar «cuatro
   compañías concentran el 87,1%» cuando eran cuatro ramos.

Qué queda AFUERA de estos guards, dicho explícitamente: SQL crudo (``text("UPDATE …")``) y
mutaciones vía ``setattr`` dinámico, que el AST no puede seguir. Si algún día se necesita
alguna de las dos, va con su excepción declarada acá.
"""
import ast
from pathlib import Path

import pytest

# Raíz del repo (…/shared/billing/tests/x.py → …).
REPO = Path(__file__).resolve().parents[3]
PAQUETES = ("shared", "modules", "app")

# Único módulo autorizado a mover el contador de una secuencia fiscal.
ASIGNADOR = "shared/billing/fiscal/sequences.py"

# Modelo cuyo contador se protege, y el atributo que lo lleva.
MODELO = "FiscalSequence"
CONTADOR = "current"

# Claves de número fiscal y el tipo que DEBE viajar con cada una en el mismo diccionario.
NUMERO_Y_SU_TIPO = {
    "fiscal_number": ("fiscal_doc_type", "fiscal_doc_label"),
    "ncf_number": ("ncf_type", "fiscal_doc_type"),
    "encf_number": ("encf_type", "fiscal_doc_type"),
}

# Superficies que exponen un número fiscal y NO son un diccionario de salida (migraciones,
# tests y el propio guard). Se declaran, no se filtran por casualidad.
EXCEPCIONES = {
    "shared/billing/tests/test_regla_numero_fiscal_estructural.py",
}


def _fuentes():
    for paquete in PAQUETES:
        for path in sorted((REPO / paquete).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if "/tests/" in rel and rel not in EXCEPCIONES:
                continue
            if rel in EXCEPCIONES:
                continue
            yield rel, path


def _arbol(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_hay_fuentes_que_auditar():
    """Si el glob deja de encontrar código, los guards de abajo pasan sin proteger nada."""
    rutas = [rel for rel, _ in _fuentes()]
    assert len(rutas) > 100
    assert ASIGNADOR in rutas


# ── Guard 1: el contador solo se mueve dentro del asignador ──────────

def _mutaciones_del_contador(tree: ast.Module) -> list:
    """Líneas que asignan (o incrementan) el atributo ``current``, o que lo pasan como clave
    de un ``.update({FiscalSequence.current: …})``."""
    hallazgos = []

    for node in ast.walk(tree):
        # row.current = … / row.current += …
        objetivos: list = []
        if isinstance(node, ast.Assign):
            objetivos = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            objetivos = [node.target]
        for t in objetivos:
            if isinstance(t, ast.Attribute) and t.attr == CONTADOR:
                hallazgos.append(t.lineno)

        # db.query(...).update({FiscalSequence.current: ...})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "update":
            for arg in node.args:
                if not isinstance(arg, ast.Dict):
                    continue
                for clave in arg.keys:
                    if (isinstance(clave, ast.Attribute) and clave.attr == CONTADOR
                            and isinstance(clave.value, ast.Name) and clave.value.id == MODELO):
                        hallazgos.append(node.lineno)
    return hallazgos


def test_solo_el_asignador_mueve_el_contador_de_la_secuencia():
    """Ningún módulo fuera de ``fiscal/sequences.py`` puede avanzar ``current``.

    Se auditan solo los archivos que MENCIONAN ``FiscalSequence``: así un ``.current`` de
    cualquier otro dominio no produce un falso positivo."""
    culpables = {}
    for rel, path in _fuentes():
        if rel == ASIGNADOR:
            continue
        texto = path.read_text(encoding="utf-8")
        if MODELO not in texto:
            continue
        lineas = _mutaciones_del_contador(ast.parse(texto))
        if lineas:
            culpables[rel] = lineas

    assert not culpables, (
        "El contador de la secuencia fiscal se mueve fuera del asignador "
        f"({ASIGNADOR}), que es donde vive el compare-and-swap: {culpables}. "
        "Un avance por fuera reintroduce dos comprobantes con el mismo número.")


def test_el_asignador_si_mueve_el_contador():
    """Contra-prueba: el guard de arriba pasaría igual si dejara de detectar mutaciones."""
    assert _mutaciones_del_contador(_arbol(REPO / ASIGNADOR)), \
        "el detector no encuentra la mutación ni donde SÍ existe: no está detectando nada"


# ── Guard 2: el número nunca se publica sin su tipo ──────────────────

def _claves_str(d: ast.Dict) -> set:
    return {k.value for k in d.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _numeros_huerfanos(tree: ast.Module) -> list:
    huerfanos = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        claves = _claves_str(node)
        for numero, acompanantes in NUMERO_Y_SU_TIPO.items():
            if numero in claves and not (set(acompanantes) & claves):
                huerfanos.append((node.lineno, numero))
    return huerfanos


def test_el_numero_fiscal_nunca_se_publica_sin_su_tipo():
    """Todo diccionario de salida que lleva un número de comprobante lleva también su tipo.

    Sin el tipo al lado, un '01' es Crédito Fiscal bajo NCF y no existe bajo e-CF: el lector
    (persona o modelo) lo reatribuye al sujeto más cercano."""
    culpables = {}
    for rel, path in _fuentes():
        huerfanos = _numeros_huerfanos(_arbol(path))
        if huerfanos:
            culpables[rel] = huerfanos

    assert not culpables, (
        "Un número de comprobante fiscal se expone sin su tipo: "
        f"{culpables}. Agregá la clave de tipo en el MISMO diccionario.")


@pytest.mark.parametrize("codigo,esperado", [
    ('{"ncf_number": n}', 1),                              # huérfano
    ('{"ncf_number": n, "ncf_type": t}', 0),               # acompañado
    ('{"fiscal_number": n, "fiscal_doc_type": t}', 0),
    ('{"fiscal_number": n}', 1),
])
def test_el_detector_de_huerfanos_distingue_los_dos_casos(codigo, esperado):
    """Contra-prueba del guard 2: si el detector no separara acompañado de huérfano, el test
    de arriba pasaría siempre."""
    assert len(_numeros_huerfanos(ast.parse(codigo))) == esperado
