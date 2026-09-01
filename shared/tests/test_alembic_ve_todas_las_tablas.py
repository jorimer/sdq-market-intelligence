"""Toda tabla que la app registra tiene que estar en el metadata que ve Alembic.

**Por qué existe.** `infrastructure/alembic/env.py` importa los modelos a mano para poblar
`Base.metadata`. Un modelo que no esté en esa lista no existe para `autogenerate`, que
entonces lo ve solo en la base y propone **borrar la tabla**. No falla nada: sale una
migración plausible que destruye datos.

Se descubrió al mudar `cartera_sectorial` a `shared/reference/` (fase 1 del plan de
enriquecimiento sectorial). Mientras vivía en `banking_score/models/models.py` se registraba
de PASO —el import de `Bank` ejecuta ese módulo entero—, y al mudarla ese arrastre
desapareció. Comprobado: sin su línea, `autogenerate` emite
`op.drop_table('cartera_sectorial')`.

El test no vigila esa tabla sino la REGLA, porque el arrastre transitivo hace que el próximo
modelo suelto entre por la misma puerta y en silencio.

Corre en un SUBPROCESO a propósito: `Base.metadata` es global y para entonces el resto de la
suite ya importó media aplicación, así que comparar dentro de este proceso mediría el estado
acumulado y no lo que env.py registra por su cuenta.
"""
import ast
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
ENV_PY = RAIZ / "infrastructure" / "alembic" / "env.py"

# Se ejecutan SOLO los imports de env.py —no el archivo entero, que abre la base y corre la
# configuración de Alembic— y se compara contra lo que registra la app completa.
_SONDA = '''
import sys
sys.path.insert(0, {raiz!r})
from shared.database.base import Base
{imports}
de_env = set(Base.metadata.tables)
import app.main  # noqa: F401  — la app completa
de_la_app = set(Base.metadata.tables)
print(",".join(sorted(de_la_app - de_env)))
'''


def _imports_de_env() -> str:
    arbol = ast.parse(ENV_PY.read_text())
    lineas = []
    for n in arbol.body:
        if isinstance(n, ast.ImportFrom) and n.module and (
                n.module.startswith(("modules.", "shared."))):
            nombres = ", ".join(a.name for a in n.names)
            lineas.append(f"from {n.module} import {nombres}")
    return "\n".join(lineas)


def test_env_py_registra_TODAS_las_tablas_de_la_app():
    imports = _imports_de_env()
    assert imports.count("\n") > 20, (
        "no se leyeron los imports de env.py; el test estaría midiendo nada")

    salida = subprocess.run(
        [sys.executable, "-c", _SONDA.format(raiz=str(RAIZ), imports=imports)],
        capture_output=True, text=True, cwd=str(RAIZ), timeout=300)
    assert salida.returncode == 0, salida.stderr[-2000:]

    faltantes = [t for t in salida.stdout.strip().split(",") if t]
    assert not faltantes, (
        "Estas tablas existen en la aplicación y NO en el metadata que ve Alembic: "
        f"{faltantes}. `autogenerate` propondría BORRARLAS —una migración plausible que "
        "destruye datos—. Agregá su import a infrastructure/alembic/env.py.")
