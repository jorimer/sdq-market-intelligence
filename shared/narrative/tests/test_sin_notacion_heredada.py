"""REGLA ESTRUCTURAL: la notación de escalones `SDQ-AAA…D` no vuelve a un texto publicable.

**El caso que la motivó.** El reencuadre a los dos ejes (Ejecución / Resiliencia) se
implementó y se auditó DOS veces. Las dos dieron el resultado por limpio. El 2026-08-13 el
cliente encontró la notación viva en dos documentos entregados:

- Deep Dive §12 (Limitaciones): «La escala SDQ-AAA…D ordena la fortaleza financiera…»
- Criterios §6 (Validación empírica): «…un SDQ-D no puede caer 2 escalones…»

Y el grep de este test destapó tres más que nadie había mirado, en la superficie COMERCIAL:
las narrativas curadas de muestra decían «calificación SDQ-AA- (score 80.3/100)». Un test de
`test_products.py` incluso EXIGÍA el literal, sosteniendo el defecto que debía impedir.

**Por qué se escapó.** Las tres esquinas son texto que NO se re-genera con cada informe:
secciones de cola, caveats de validación y exemplars curados. Auditar los PDF de salida de un
informe reciente no las toca. Por eso la regla se verifica sobre las FUENTES.

**Por qué `ast` y no `grep`.** Los comentarios deben poder discutir la notación vieja —esta
misma docstring lo hace, y la explicación histórica es lo que evita que alguien la
reintroduzca por no saber por qué se fue—. Leyendo el árbol, los comentarios no existen: se
inspecciona solo lo que puede terminar impreso, que son los literales de cadena.

**La regla.** Ningún literal de cadena de `modules/` o `shared/` (fuera de tests) contiene la
notación de escalones. Si un literal la necesita de forma legítima —una migración que mapea
datos históricos, un mensaje que explica la escala retirada— se declara con
`# notacion-heredada-ok: <razón>` en la línea del literal o en la de su sentencia.
"""
import ast
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]

# `SDQ-` seguido de un escalón de la familia de calificadora: AAA…D con signo opcional.
_NOTACION = re.compile(r"\bSDQ-(?:A{1,3}|BBB|BB|B|CCC|CC|C|D)[+-]?(?![\w-])")
_EXENCION = "notacion-heredada-ok:"

# Todo el código de producto. Se excluyen los tests (fijan datos de escenarios históricos) y
# el catálogo de doctrina, que documenta a propósito qué vocabulario se retiró y cuándo.
_EXCLUIDOS = ("/tests/", "/test_", "/__pycache__/", "/shared/doctrine/")

# EXCEPCIÓN DECLARADA, archivo completo: módulos cuyos literales SON la escala retirada.
# Va acá y no como comentario disperso porque la excepción es del archivo entero: leerla en
# un solo lugar es lo que impide que se vuelva un permiso tácito.
_LINAJE = {
    # La columna `rating_tier` sigue existiendo en la base como LINAJE del dato histórico
    # (una acción de rating de 2024 se registró con su escalón). El módulo define esa escala;
    # ninguno de sus literales llega a un documento —lo que se publica son las bandas—, y
    # borrarlo dejaría los registros viejos sin poder leerse.
    "modules/banking_score/scoring/rating_scale.py":
        "define la escala retirada que conserva el linaje de `rating_tier` en la base",
}


def _fuentes():
    for base in ("modules", "shared", "app"):
        for p in sorted((RAIZ / base).rglob("*.py")):
            rel = str(p.relative_to(RAIZ))
            if any(x in "/" + rel for x in _EXCLUIDOS) or rel in _LINAJE:
                continue
            yield p


def _docstrings(arbol: ast.AST) -> set:
    """`id()` de los nodos que son docstring — documentación, no texto publicable."""
    out = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            cuerpo = getattr(nodo, "body", None) or []
            if (cuerpo and isinstance(cuerpo[0], ast.Expr)
                    and isinstance(cuerpo[0].value, ast.Constant)
                    and isinstance(cuerpo[0].value.value, str)):
                out.add(id(cuerpo[0].value))
    return out


def _exento(lineas: list, nodo: ast.Constant) -> bool:
    """¿El literal lleva la exención declarada?

    Se acepta en el propio span del literal o en el BLOQUE de comentarios contiguo que lo
    precede. Recorrer ese bloque —en vez de mirar «la línea de arriba»— importa: un literal
    largo empieza en la línea de su continuación, no en la de la clave, y una ventana fija
    dejaba la exención justo afuera (le pasó al literal que declara la retirada en la API).
    """
    span = "\n".join(lineas[nodo.lineno - 1:(nodo.end_lineno or nodo.lineno)])
    if _EXENCION in span:
        return True
    i = nodo.lineno - 2  # índice 0 de la línea inmediatamente anterior
    while i >= 0:
        cruda = lineas[i].strip()
        if not cruda or cruda.startswith("#"):
            if _EXENCION in cruda:
                return True
            i -= 1
            continue
        # Línea de código que abre la sentencia (p. ej. `"clave": (`): seguí subiendo solo
        # si por encima hay comentarios; cualquier otra cosa corta la búsqueda.
        if cruda.endswith(("(", "[", "{", ":")) and i >= nodo.lineno - 3:
            i -= 1
            continue
        return False
    return False


def test_sin_notacion_heredada():
    """Ningún literal publicable nombra los escalones SDQ-AAA…D."""
    hallazgos = []
    for path in _fuentes():
        texto = path.read_text(encoding="utf-8")
        if not _NOTACION.search(texto):
            continue  # ni en comentarios: nada que revisar en este archivo
        try:
            arbol = ast.parse(texto)
        except SyntaxError:  # pragma: no cover — no debería haberlos
            continue
        lineas = texto.splitlines()
        docs = _docstrings(arbol)
        for nodo in ast.walk(arbol):
            if not (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)):
                continue
            if id(nodo) in docs or not _NOTACION.search(nodo.value):
                continue
            if _exento(lineas, nodo):
                continue
            hallazgos.append(
                f"{path.relative_to(RAIZ)}:{nodo.lineno} → "
                f"{_NOTACION.search(nodo.value).group(0)}")
    assert not hallazgos, (
        "Notación heredada SDQ-AAA…D en texto publicable. El reencuadre a dos ejes "
        "(Ejecución / Resiliencia) la retiró: usá las bandas, o declará "
        f"`# {_EXENCION} <razón>` si el literal la necesita.\n  - "
        + "\n  - ".join(hallazgos))


def test_la_regla_ve_una_reintroduccion(tmp_path):
    """PRUEBA NEGATIVA: sin ella, `hallazgos == []` no distingue «está limpio» de «el
    detector no miró nada» — el modo de falla que ya dejó un guard entero en silencio."""
    modulo = tmp_path / "recaida.py"
    modulo.write_text('TEXTO = "La escala SDQ-AAA…D ordena la fortaleza relativa."\n',
                      encoding="utf-8")
    arbol = ast.parse(modulo.read_text(encoding="utf-8"))
    literales = [n for n in ast.walk(arbol)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in _docstrings(arbol) and _NOTACION.search(n.value)]
    assert len(literales) == 1, "el detector no reconoce una reintroducción evidente"


@pytest.mark.parametrize("texto,esperado", [
    ("SDQ-AAA", True), ("SDQ-AA+", True), ("SDQ-D", True), ("SDQ-BBB-", True),
    ("un SDQ-D no puede caer", True),
    # No debe morder identificadores legítimos que empiezan igual.
    ("SDQ-MIP", False), ("SDQ-Analytics", False), ("SDQ", False), ("sdq_aaa", False),
])
def test_patron_no_muerde_identificadores(texto, esperado):
    assert bool(_NOTACION.search(texto)) is esperado


# ── La misma regla, sobre los DOCUMENTOS-CONTRATO ──────────────────────────────
#
# El test de arriba lee Python. Y la notación sobrevivió meses en un Markdown:
# `DESIGN_SYSTEM.md` §3 siguió documentando «Escala de rating SDQ: SDQ-AAA · SDQ-AA+ …»
# después de que el reencuadre a dos ejes se implementara, se auditara dos veces y se
# limpiara el código — porque nada miraba los documentos. Un diseñador que abre ese archivo
# construye la insignia equivocada, y tiene razón: es el contrato que le dieron.
#
# Solo entran los documentos que dicen QUÉ CONSTRUIR o QUÉ PUBLICAR. Los registros de
# planificación, los specs de la propia retirada y los artefactos fechados nombran la
# notación con todo derecho: son historia, y borrarla ahí destruye el porqué.
_CONTRATOS = (
    "design_handoff_sdqmip/DESIGN_SYSTEM.md",
    "frontend/DESIGN_SYSTEM.md",
    "frontend/CLAUDE.md",
    "CLAUDE.md",
    "docs/REPORT_STANDARD.md",
    "docs/CLAIMS_COMERCIALES.md",
    "docs/comercial/README.md",
)

# En un contrato la notación SOLO puede aparecer para declarar que está retirada. Se exige
# que la mención venga acompañada de esa palabra en la misma línea o en la anterior: nombrar
# lo retirado es lo que evita que vuelva, describirlo como vigente es el defecto.
_RETIRO = re.compile(r"retirad|no se publica|desactualizad", re.I)


def _contratos_existentes():
    for rel in _CONTRATOS:
        path = RAIZ / rel
        if path.exists():
            yield rel, path
    # Y los SPEC de módulo, que son contrato de construcción por definición.
    for path in sorted(RAIZ.glob("modules/*/SPEC.md")):
        yield str(path.relative_to(RAIZ)), path


@pytest.mark.parametrize("rel", [r for r, _ in _contratos_existentes()])
def test_los_contratos_no_documentan_la_notacion_como_vigente(rel):
    lineas = (RAIZ / rel).read_text(encoding="utf-8").splitlines()
    ofensas = []
    for i, linea in enumerate(lineas):
        if not _NOTACION.search(linea):
            continue
        contexto = "\n".join(lineas[max(0, i - 2):i + 2])
        if not _RETIRO.search(contexto):
            ofensas.append(f"{rel}:{i + 1}  {linea.strip()[:80]}")
    assert not ofensas, (
        "Estos documentos-contrato nombran la escala de letras sin declararla retirada:\n  "
        + "\n  ".join(ofensas)
        + "\n\nLo vigente es el Perfil SDQ (Ejecución + Resiliencia). Si la mención es "
          "histórica, decí en la misma línea o en la anterior que está retirada."
    )


def test_la_regla_de_contratos_ve_una_reintroduccion(tmp_path):
    """PRUEBA NEGATIVA: que la lista de contratos no esté vacía ni el patrón muerto."""
    doc = tmp_path / "contrato.md"
    doc.write_text("### Escala de rating SDQ\n`SDQ-AAA · SDQ-AA+ … SDQ-D`. Badge por banda.\n",
                   encoding="utf-8")
    lineas = doc.read_text(encoding="utf-8").splitlines()
    sospechosas = [ln for ln in lineas if _NOTACION.search(ln) and not _RETIRO.search(ln)]
    assert sospechosas, "el detector no reconoce una reintroducción evidente en un documento"
    assert list(_contratos_existentes()), "la lista de contratos quedó vacía"
