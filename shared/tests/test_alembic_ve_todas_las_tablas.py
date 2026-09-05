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

**Y la dirección inversa, que se agregó después.** Una tabla que Alembic ve y la app NO
registra no rompe producción —la migración la crea igual— pero no existe cuando la base se
monta desde el metadata, que es como corren los tests y como se arma un informe a mano.
`rb_country_aggregates` estuvo así: su módulo no tiene `api/`, así que nada importaba sus
modelos al arrancar y la tabla desaparecía en esa superficie. Es la misma familia que el
defecto del anuario — registrado en un lado, invisible en otro.

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

#: La dirección inversa NO se puede medir en la sonda de arriba: `Base.metadata` es global y
#: ACUMULATIVO, así que una vez que los imports de env.py registran una tabla, `de_la_app` la
#: contiene por construcción y `de_env - de_la_app` sale vacío siempre. La primera versión de
#: este chequeo pasó en verde con el defecto puesto delante. Hacen falta dos procesos
#: SEPARADOS, cada uno partiendo de un metadata limpio.
_SOLO_APP = '''
import sys
sys.path.insert(0, {raiz!r})
from shared.database.base import Base
import app.main  # noqa: F401
print(",".join(sorted(Base.metadata.tables)))
'''

_SOLO_ENV = '''
import sys
sys.path.insert(0, {raiz!r})
from shared.database.base import Base
{imports}
print(",".join(sorted(Base.metadata.tables)))
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


#: Tablas que Alembic ve y la app no registra al arrancar, medidas el 2026-09-05. Se listan
#: en vez de esconderse: la migración las crea en producción, así que no rompen ahí, pero no
#: existen cuando la base se monta desde el metadata. Esta lista solo puede ACHICARSE — una
#: tabla nueva no entra acá, se arregla importando su modelo desde algo que `app/main.py`
#: alcance.
INVISIBLES_AL_2026_09_05 = {"dgii_contribuyente_subclase", "llm_calls"}


def _tablas(codigo: str) -> set:
    salida = subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                            text=True, cwd=str(RAIZ), timeout=300)
    assert salida.returncode == 0, salida.stderr[-2000:]
    return {t for t in salida.stdout.strip().split(",") if t}


def test_la_app_registra_TODAS_las_tablas_que_ve_alembic():
    """La dirección inversa, en procesos separados porque el metadata es acumulativo."""
    de_la_app = _tablas(_SOLO_APP.format(raiz=str(RAIZ)))
    de_env = _tablas(_SOLO_ENV.format(raiz=str(RAIZ), imports=_imports_de_env()))
    assert len(de_la_app) > 40 and len(de_env) > 40, (
        f"una de las dos sondas midió casi nada (app={len(de_la_app)}, env={len(de_env)}): "
        f"el chequeo no estaría protegiendo nada")

    invisibles = sorted((de_env - de_la_app) - INVISIBLES_AL_2026_09_05)
    assert not invisibles, (
        f"Estas tablas las ve Alembic pero NO la aplicación: {invisibles}. La migración las "
        f"crea en producción, así que el defecto no se ve ahí — se ve al montar una base "
        f"desde el metadata, que es como corren los tests y como se armó el primer boletín "
        f"a mano: la tabla simplemente no existe. Pasó con `rb_country_aggregates`, cuyo "
        f"módulo no tiene `api/` y por lo tanto nada importaba sus modelos al arrancar. "
        f"Importá el modelo desde algo que `app/main.py` alcance.")
