"""REGLA ESTRUCTURAL: una migración no vuelve a crear un ENUM que ya existe.

**El caso que la motivó (2026-08-13).** `d1c8e4b90735` declaró
`sa.Enum("export", "import", name="tradedirection")` dentro de su `create_table`. En Postgres
los tipos viven en un namespace GLOBAL, así que eso emite `CREATE TYPE` y revienta con
"type tradedirection already exists" — lo había creado `14e19953826c` para `ti_flows`.

**Por qué el CI no lo vio.** El job de migraciones corre sobre SQLite, donde el enum se
resuelve como VARCHAR con un CHECK por tabla y no hay namespace que colisionar. Pasó en verde,
y el fallo apareció recién en el arranque del contenedor de producción: el script corre
`alembic upgrade head` antes de levantar el servidor, la migración crasheó y la app nunca
respondió el healthcheck. Deploy caído.

Como el gate de CI no puede alcanzar esta clase de defecto, se lee el código.
"""
import ast
import pathlib
import re

VERSIONES = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"

# Declarar el tipo SIN crearlo es lo correcto y no debe marcarse.
_NO_CREA = ("create_type=False", "postgresql.ENUM")


def _enums_por_migracion():
    """``{archivo: {nombre_enum}}`` para cada `sa.Enum(..., name="x")` que SÍ crearía el tipo."""
    out = {}
    for f in sorted(VERSIONES.glob("*.py")):
        fuente = f.read_text(encoding="utf-8")
        # Un archivo que declara la forma "no crear" para un nombre YA maneja el caso
        # Postgres: la otra rama del `if dialect` es la de SQLite, que no colisiona.
        manejados = set(re.findall(
            r"(?:create_type=False[^)]*?|postgresql\.ENUM\()[^)]*?name=[\"'](\w+)[\"']", fuente))
        manejados |= set(re.findall(
            r"name=[\"'](\w+)[\"'][^)]*?create_type=False", fuente))
        nombres = set()
        for nodo in ast.walk(ast.parse(fuente)):
            if not isinstance(nodo, ast.Call):
                continue
            fn = ast.unparse(nodo.func) if hasattr(ast, "unparse") else ""
            if not fn.endswith("Enum"):
                continue
            trozo = ast.unparse(nodo) if hasattr(ast, "unparse") else ""
            if any(x in trozo for x in _NO_CREA):
                continue          # referencia un tipo existente: correcto
            for kw in nodo.keywords:
                if (kw.arg == "name" and isinstance(kw.value, ast.Constant)
                        and str(kw.value.value) not in manejados):
                    nombres.add(str(kw.value.value))
        if nombres:
            out[f.name] = nombres
    return out


def test_hay_migraciones_que_revisar():
    assert len(list(VERSIONES.glob("*.py"))) > 20


def test_ningun_enum_se_crea_dos_veces():
    """Dos migraciones que crean el mismo tipo = deploy caído en Postgres, verde en SQLite."""
    visto = {}
    duplicados = []
    for archivo, nombres in _enums_por_migracion().items():
        for n in nombres:
            if n in visto:
                duplicados.append(f"'{n}': {visto[n]} y {archivo}")
            else:
                visto[n] = archivo
    assert not duplicados, (
        "Estas migraciones crean un tipo ENUM que otra ya creó. En Postgres el namespace de "
        "tipos es GLOBAL y el segundo `CREATE TYPE` aborta el `upgrade head` que corre al "
        "arrancar el contenedor — la app no levanta y el healthcheck falla. En SQLite no "
        "colisiona, así que el CI no lo ve. Para reusar un tipo existente, declararlo con "
        "`postgresql.ENUM(..., create_type=False)`:\n  " + "\n  ".join(duplicados))


def test_las_etiquetas_del_enum_compartido_coinciden():
    """Reusar el tipo con OTRAS etiquetas es peor que recrearlo: pasa el CREATE y rompe al
    insertar. La primera versión de d1c8e4b90735 puso `import` donde el tipo tiene `import_`."""
    etiquetas = {}
    for f in sorted(VERSIONES.glob("*.py")):
        for m in re.finditer(r"ENUM?\(([^)]*?)name=[\"'](\w+)[\"']", f.read_text(encoding="utf-8")):
            args, nombre = m.group(1), m.group(2)
            vals = tuple(sorted(re.findall(r"[\"'](\w+)[\"']", args)))
            if not vals:
                continue
            etiquetas.setdefault(nombre, []).append((f.name, vals))
    for nombre, usos in etiquetas.items():
        distintas = {v for _, v in usos}
        assert len(distintas) == 1, (
            f"el enum '{nombre}' se declara con etiquetas distintas en "
            f"{[u[0] for u in usos]}: {distintas}")
