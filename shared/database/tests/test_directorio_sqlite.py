"""REGLA: quien construye un engine crea antes el directorio del fichero SQLite.

**El caso que la motivó.** ``modules/banking_score/tests/test_api.py::TestHealth::
test_health_check`` fallaba «de forma intermitente» en la suite completa y pasaba en
aislamiento. No era orden aleatorio ni una carrera: el readiness toca la base REAL
(``SessionLocal``, no la in-memory que el test inyecta por ``get_db`` — comprobar una base
falsa no comprueba nada), y contra el ``DATABASE_URL`` por defecto,
``sqlite:///./data/sdq_market_intel.db``, en un árbol donde ``data/`` no existe la conexión
muere con «unable to open database file» → 503.

Parecía intermitente porque **se curaba solo**: el health es el test nº 25 de la suite y el
nº 40 (``test_report_generate``) crea ``data/reports`` al escribir un PDF. Primera corrida
sobre un árbol limpio: 1 failed. Segunda, sin tocar nada: todo verde. Como ``data/`` está
gitignorado, cada clon y cada worktree nuevo empieza el ciclo otra vez. En CI no se ve
porque el workflow fija ``DATABASE_URL=sqlite:///./test.db`` — sin subdirectorio.

**Por qué también un test estructural.** Los engines se construyen en más de un sitio: la
app (``shared/database/session.py``) y Alembic (``infrastructure/alembic/env.py``) tienen
cada uno el suyo, y este repo ya acumuló varias instancias de un guard presente en un motor
y ausente en el otro. La lección escrita no alcanzó ninguna de esas veces; leer el código
con ``ast`` sí.
"""
import ast
import os
import pathlib
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text

from shared.database.paths import ensure_sqlite_directory

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: Formas de construir un engine. ``engine_from_config`` es la de Alembic.
_CONSTRUCTORES = {"create_engine", "engine_from_config"}

#: Sitios que construyen un engine y legítimamente NO crean el directorio, con su motivo.
_EXENTOS = {
    # Trabaja con bases que YA existen: el origen es una base poblada y el destino lo crea
    # el deploy. Crear el directorio ahí convertiría una ruta mal escrita en una copia
    # vacía y silenciosa («no such table») en vez del error que la delata.
    "scripts/migrate_db.py",
}


class TestElGuard:
    def test_crea_el_directorio_que_falta_y_la_conexion_funciona(self, tmp_path):
        destino = tmp_path / "data" / "anidado" / "sdq.db"
        assert not destino.parent.exists()

        ensure_sqlite_directory(f"sqlite:///{destino}")

        assert destino.parent.is_dir()
        engine = create_engine(f"sqlite:///{destino}")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1

    def test_es_idempotente(self, tmp_path):
        destino = tmp_path / "data" / "sdq.db"
        ensure_sqlite_directory(f"sqlite:///{destino}")
        ensure_sqlite_directory(f"sqlite:///{destino}")  # no debe romper
        assert destino.parent.is_dir()

    @pytest.mark.parametrize("url", [
        "sqlite://",                       # memoria (database=None)
        "sqlite:///:memory:",              # memoria explícita
        "postgresql://u:p@host:5432/db",   # no es SQLite
        "no-es-una-url",                   # el error lo reporta create_engine
    ])
    def test_no_crea_nada_donde_no_corresponde(self, url, monkeypatch):
        llamadas = []
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: llamadas.append(a))
        ensure_sqlite_directory(url)
        assert llamadas == []

    def test_un_directorio_que_no_se_puede_crear_no_tumba_el_import(self, monkeypatch, tmp_path):
        """Degradar al error de conexión de siempre (que el health ya reporta), no explotar."""
        def _falla(*a, **k):
            raise OSError("read-only file system")
        monkeypatch.setattr(os, "makedirs", _falla)
        ensure_sqlite_directory(f"sqlite:///{tmp_path}/data/sdq.db")  # no debe propagar


class TestLaRutaReal:
    def test_el_readiness_responde_sano_en_un_arbol_sin_data(self, tmp_path):
        """El defecto original, reproducido: proceso nuevo, CWD limpio, URL por defecto.

        Se corre en un subproceso porque la cura actúa al IMPORTAR
        ``shared.database.session``, y en esta suite ese módulo ya está importado (y ``data/``
        ya existe en el árbol de trabajo). Sin el guard, esto devuelve 'unable to open
        database file' — se verificó revirtiendo el fuente.
        """
        entorno = {
            **os.environ,
            "PYTHONPATH": str(RAIZ),
            "DATABASE_URL": "sqlite:///./data/sdq_market_intel.db",
            "REDIS_URL": "",
        }
        codigo = (
            "from shared.observability.health import readiness\n"
            "sano, payload = readiness()\n"
            "print(sano, payload['checks']['database'].get('error', ''))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", codigo],
            cwd=tmp_path, env=entorno, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith("True "), proc.stdout + proc.stderr
        assert (tmp_path / "data" / "sdq_market_intel.db").exists()


class TestReglaEstructural:
    def _fuentes(self):
        """Todo .py del repo salvo tests, entorno virtual y artefactos.

        Se barre el repo ENTERO a propósito: acotar a ``shared/`` habría dejado fuera
        justamente el segundo motor (``infrastructure/alembic/env.py``), que es donde el
        guard faltaba.
        """
        excluidos = {".venv", "node_modules", "__pycache__", ".git", "frontend", ".claude"}
        for ruta in RAIZ.rglob("*.py"):
            partes = set(ruta.relative_to(RAIZ).parts)
            if partes & excluidos or "tests" in partes or ruta.name.startswith("test_"):
                continue
            yield ruta

    def test_todo_sitio_que_construye_un_engine_crea_el_directorio(self):
        infractores = []
        for ruta in self._fuentes():
            arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
            construye = any(
                isinstance(n, ast.Call)
                and (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) in _CONSTRUCTORES
                for n in ast.walk(arbol)
            )
            if not construye:
                continue
            relativa = str(ruta.relative_to(RAIZ))
            if relativa in _EXENTOS or relativa == "shared/database/paths.py":
                continue
            if "ensure_sqlite_directory" not in ruta.read_text(encoding="utf-8"):
                infractores.append(relativa)

        assert not infractores, (
            "Estos sitios construyen un engine sin crear el directorio del fichero SQLite "
            f"(llamá a ensure_sqlite_directory o declaralos en _EXENTOS con su motivo): {infractores}"
        )

    def test_los_exentos_existen(self):
        """Una exención huérfana deja de proteger sin avisar."""
        faltantes = [r for r in _EXENTOS if not (RAIZ / r).exists()]
        assert not faltantes, f"Exenciones que apuntan a archivos inexistentes: {faltantes}"
