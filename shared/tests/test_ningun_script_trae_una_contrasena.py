"""REGLA ESTRUCTURAL: ningún script del repo trae una contraseña escrita.

**El caso (2026-09-14).** Catorce scripts de `scripts/` traían la contraseña de la cuenta E2E como
literal. El dueño la cambió en producción y quedaron todos rotos a la vez, cada uno por su lado; y
cada uno que se corriera sumaba un login fallido al contador de bloqueo de la cuenta. Ahora la
contraseña se lee de `SDQ_E2E_PASSWORD` a través de `scripts/e2e_credentials.py`.

**La regla.** En `scripts/*.py` no hay ningún literal de texto usado como contraseña:

- asignado a un nombre que contiene `PASSWORD`;
- como valor de una clave `"password"` en un diccionario;
- como argumento `password=` de una llamada.

Se lee el código con `ast` y no con una búsqueda de la contraseña: este test no puede contenerla, y
una contraseña NUEVA escrita a mano tampoco la conocería.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _es_literal(nodo: ast.AST) -> bool:
    return isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) and bool(nodo.value)


def contrasenas_literales(fuente: str) -> List[int]:
    """Líneas donde un literal de texto se usa como contraseña."""
    lineas: List[int] = []
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, (ast.Assign, ast.AnnAssign)):
            objetivos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
            if (nodo.value is not None and _es_literal(nodo.value)
                    and any(isinstance(t, ast.Name) and "PASSWORD" in t.id.upper()
                            for t in objetivos)):
                lineas.append(nodo.lineno)
        elif isinstance(nodo, ast.Dict):
            for clave, valor in zip(nodo.keys, nodo.values):
                if (isinstance(clave, ast.Constant) and isinstance(clave.value, str)
                        and clave.value.lower() == "password" and _es_literal(valor)):
                    lineas.append(valor.lineno)
        elif isinstance(nodo, ast.Call):
            for kw in nodo.keywords:
                if kw.arg and kw.arg.lower() == "password" and _es_literal(kw.value):
                    lineas.append(kw.value.lineno)
    return sorted(lineas)


# ── El detector no nace ciego ──

def test_el_detector_caza_las_tres_formas():
    fuente = (
        'E2E_PASSWORD = "secreto"\n'
        'body = {"email": "a@b.c", "password": "secreto"}\n'
        'login(email="a@b.c", password="secreto")\n')
    assert contrasenas_literales(fuente) == [1, 2, 3]


def test_el_detector_deja_pasar_la_contrasena_del_entorno():
    fuente = (
        'PASSWORD = e2e_password()\n'
        'body = {"email": "a@b.c", "password": PASSWORD}\n'
        'login(password=os.environ["SDQ_E2E_PASSWORD"])\n'
        'ENV_VAR = "SDQ_E2E_PASSWORD"\n')
    assert contrasenas_literales(fuente) == []


# ── La regla sobre el repo ──

def test_ningun_script_trae_una_contrasena_escrita():
    archivos = sorted(SCRIPTS.glob("*.py"))
    assert archivos, f"No se encontró ningún script en {SCRIPTS}: el test no estaría mirando nada."
    fallos = []
    for archivo in archivos:
        for linea in contrasenas_literales(archivo.read_text(encoding="utf-8")):
            fallos.append(f"{archivo.relative_to(SCRIPTS.parent)}:{linea}")
    assert not fallos, "\n  ".join(
        ["Scripts con una contraseña escrita. Leela del entorno con "
         "`scripts/e2e_credentials.e2e_password()` (o la variable que corresponda):"] + fallos)
