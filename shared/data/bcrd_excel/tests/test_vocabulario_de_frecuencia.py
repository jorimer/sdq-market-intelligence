"""La cadencia se escribe en UN idioma, y es el que ya viaja al cliente.

`ExtractionSpec.frequency` declara `"annual" | "quarterly" | "monthly"` (`spec.py:78`) y el
esquema del intérprete lo restringe a esos tres (`interpreter.py:49`). La inferencia
heurística los respetaba en dos de sus tres ramas y en la tercera escribía `"trimestral"`
—tres líneas más abajo, misma función—. El caché de layouts terminó con los cuatro valores
conviviendo: `quarterly`, `annual`, `None` y `trimestral`.

**Por qué importa más de lo que parece.** `mm_series.frequency` se sirve por la Data API
(`macro_monitor/service.py`), que consume PMS, y hoy se deriva al leer con `_infer_frequency`
—que devuelve inglés—. Al empezar a PERSISTIR la cadencia, un `"trimestral"` guardado se
serviría tal cual y cambiaría el valor de un campo de un contrato vivo. Los otros módulos que
ya pueblan esa columna (`insurance_intel`, `pension_intel`) escriben inglés.

El test es ESTRUCTURAL —lee el código con `ast`— porque el defecto es de una rama entre
varias: un test de comportamiento solo cubre la rama que su fixture activa, y la que se
olvida es justamente la que se rompe. El español SIGUE siendo correcto en
`CanonicalSeries.frequency`, que es documentación del registro y no la columna.
"""
from __future__ import annotations

import ast
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[1]
VOCABULARIO = {"annual", "quarterly", "monthly"}

#: Dónde se construye un ExtractionSpec. Si aparece otro sitio, va acá.
ARCHIVOS = ["inference.py", "interpreter.py", "engine.py", "extract.py"]


def _cadenas(nodo) -> list:
    """Todo literal str alcanzable desde *nodo*, incluidos los de un ternario.

    No alcanza con mirar `frequency=<literal>`: la rama de matriz arma el valor en una
    variable (`freq = "quarterly" if ... else "annual"`) y lo pasa por nombre. Un barrido
    que solo viera el literal en la llamada dejaría esa rama —dos de los tres valores— fuera
    de la regla, y el test pasaría en verde sin cubrirla. Es el mismo punto ciego que ya
    costó caro en este repo: mirar la forma en que está escrito hoy, no la propiedad.
    """
    return [(n.lineno, n.value) for n in ast.walk(nodo)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _literales_de_frequency(ruta: Path):
    """(línea, valor) de cada cadena que termina siendo una cadencia en este archivo:
    la pasada como `frequency=`, y la asignada a una variable que se llama como tal."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    out = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            for kw in nodo.keywords:
                if kw.arg == "frequency":
                    out.extend(_cadenas(kw.value))
        elif isinstance(nodo, ast.Assign):
            nombres = [t.id for t in nodo.targets if isinstance(t, ast.Name)]
            if any("freq" in n.lower() for n in nombres):
                out.extend(_cadenas(nodo.value))
    return out


def test_el_motor_escribe_la_cadencia_en_un_solo_idioma():
    infractores = []
    for nombre in ARCHIVOS:
        ruta = MOTOR / nombre
        if not ruta.exists():
            continue
        for linea, valor in _literales_de_frequency(ruta):
            if valor not in VOCABULARIO:
                infractores.append(f"{nombre}:{linea} frequency={valor!r}")
    assert not infractores, (
        "El motor de Excel escribe la cadencia fuera del vocabulario "
        f"{sorted(VOCABULARIO)}: {infractores}. Ese valor termina en `mm_series.frequency` y "
        "se sirve por la Data API, donde hoy el cliente recibe inglés."
    )


def test_el_barrido_encuentra_algo():
    """Una aserción de AUSENCIA pasa sola: si el barrido no encuentra ni un `frequency=`,
    el test de arriba queda en verde sin proteger nada (glob roto, archivo renombrado)."""
    total = sum(len(_literales_de_frequency(MOTOR / n))
                for n in ARCHIVOS if (MOTOR / n).exists())
    assert total >= 4, (
        f"el barrido solo encontró {total} cadenas de cadencia; eran 4 al escribir este "
        "test (las dos del ternario de la rama matriz, más las dos de period_rows). "
        "Si bajó, el barrido dejó de ver una rama.")
