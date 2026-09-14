"""La ingesta canónica MANUAL escribe con el mismo alcance que la agendada.

**El defecto que lo obligó.** `macro-canonical-sync` persiste con
`alcance=PERSISTIBLES_VERIFICADOS`: la corrida en seco del 2026-09-03 encontró 29.427 empates
(misma serie y período, valores distintos) que `_upsert_records` resuelve por orden de lectura
y sin dejar marca. Pero `POST /api/v1/macro-monitor/excel/ingest-canonical?persist=true`
—por el hilo o por la tarea Celery `ingest_canonical_task`— llamaba
`ingest_canonical(db, persist=persist)` SIN alcance, y `None` significa «todo». Un admin que
apretaba el botón reescribía en `MacroSeries` (que sirve la Data API que consume PMS) justo lo
que la sincronización agendada se cuida de no escribir: hoy, las hojas no habilitadas de los
libros que el mapa acota por hoja.

`persist=false` sigue LEYENDO y reportando todo: el alcance acota lo que se escribe, no lo que
se lee, y el reporte completo es con lo que se decide qué habilitar después.

Los tests piden por HTTP (la ruta), y por la tarea del worker: un test del motor no es un test
de la ruta. El estructural cierra el patrón para el próximo llamador de `ingest_canonical`.
"""
import ast
import pathlib
import threading
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from modules.macro_monitor.models.models import ExcelFileReport, MacroSeries  # noqa: F401
from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole
from shared.data.base_client import Record
from shared.data.bcrd_excel import canonical
from shared.data.bcrd_excel.extract import _slug, default_prefix
from shared.data.lineage import Lineage
from shared.database.base import Base

HOJA_FUERA = "hoja_no_habilitada"


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    # El lanzador y la tarea abren su propia sesión: que sea ésta.
    monkeypatch.setattr("shared.database.session.SessionLocal", lambda: session)
    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", _motor_falso)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _motor_falso(entry, **kw):
    """Cada libro produce una serie de una hoja NO habilitada y, si el mapa lo acota por hoja,
    otra de su primera hoja habilitada."""
    lin = Lineage(source="BCRD", license="x", fetched_at=date.today())
    base = default_prefix(entry.filename)
    codigos = [f"{base}.{HOJA_FUERA}.valor"]
    hojas = canonical.PERSISTIBLES_VERIFICADOS.get(entry.filename)
    if hojas:
        codigos.append(f"{base}.{_slug(hojas[0])}.valor")
    report = SimpleNamespace(ok=True, flagged=[],
                             series=[SimpleNamespace(code=c, flags=[]) for c in codigos])
    spec = SimpleNamespace(method="heuristic", orientation="period_rows",
                           frequency="annual", confidence=0.8)
    return SimpleNamespace(file=entry.filename, spec=spec, report=report,
                           records=[Record(series=c, period="2020", value=1.0, lineage=lin)
                                    for c in codigos])


def _lo_que_el_alcance_permite():
    permitidos = set()
    for archivo in {s.source_file for s in canonical.registry()}:
        base = default_prefix(archivo)
        hojas = canonical.PERSISTIBLES_VERIFICADOS.get(archivo, "fuera")
        if hojas is None:
            permitidos.add(f"{base}.{HOJA_FUERA}.valor")
        elif hojas != "fuera":
            permitidos.add(f"{base}.{_slug(hojas[0])}.valor")
    return permitidos


def _escritos(db):
    return {r.series_code for r in db.query(MacroSeries).all()}


class _HiloEnLinea(threading.Thread):
    """Corre en línea SOLO el hilo del lanzador; el resto de los hilos (TestClient) igual."""

    def start(self):
        if "start_canonical_ingest_background" in getattr(self._target, "__qualname__", ""):
            self.run()
        else:
            super().start()


@pytest.fixture()
def cliente(db, monkeypatch):
    from shared.config.settings import settings

    monkeypatch.setattr(settings, "USE_CELERY", False)
    monkeypatch.setattr(threading, "Thread", _HiloEnLinea)
    guardados = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: User(
        id="u1", email="t@sdq.do", password_hash="x", full_name="T", role=UserRole.admin)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(guardados)


def test_el_caso_es_representativo():
    """Si ningún libro se acotara por hoja y todos estuvieran habilitados enteros, los tests
    de abajo pasarían con el código viejo: no habría nada que dejar afuera."""
    assert any(canonical.PERSISTIBLES_VERIFICADOS.values())


def test_la_ruta_con_persist_escribe_solo_lo_verificado(cliente, db):
    r = cliente.post("/api/v1/macro-monitor/excel/ingest-canonical?persist=true")
    assert r.status_code == 200, r.text
    assert r.json()["via"] == "thread"
    permitidos = _lo_que_el_alcance_permite()
    assert permitidos and _escritos(db) == permitidos


def test_la_ruta_en_seco_lee_y_reporta_todo_sin_escribir(cliente, db):
    r = cliente.post("/api/v1/macro-monitor/excel/ingest-canonical?persist=false")
    assert r.status_code == 200, r.text
    assert _escritos(db) == set()
    assert db.query(ExcelFileReport).count() == len(
        {s.source_file for s in canonical.registry()})


def test_la_tarea_del_worker_escribe_solo_lo_verificado(db):
    from modules.macro_monitor.tasks import ingest_canonical_task

    ingest_canonical_task.run(persist=True)
    permitidos = _lo_que_el_alcance_permite()
    assert permitidos and _escritos(db) == permitidos


# ── Estructural: nadie persiste el canónico sin alcance ───────────────────────────

RAIZ = pathlib.Path(__file__).resolve().parents[3]
#: Los worktrees traen código viejo de otras sesiones; se compara contra la ruta RELATIVA
#: (ver `shared/tests/test_toda_ruta_recibe_su_path.py`, donde comparar la absoluta apagó el
#: barrido entero dentro de un worktree). `scripts/` SÍ se lee.
EXCLUIDOS = (".venv", "/tests/", ".claude/worktrees", "node_modules", "/.git/", "/frontend/")

#: Llamadores que persisten sin alcance a propósito, con el motivo.
EXCEPCIONES = {
    "scripts/dry_run_canonical_ingest.py": (
        "corrida en seco descartable: intercepta `_upsert_records` hacia una base scratch "
        "vacía y medir TODO el canónico —empates incluidos— es exactamente su propósito"),
}


def _llamadas_sin_alcance(arbol):
    """Líneas donde `ingest_canonical(...)` puede persistir sin un `alcance=` explícito."""
    for n in ast.walk(arbol):
        if not isinstance(n, ast.Call):
            continue
        nombre = (n.func.id if isinstance(n.func, ast.Name)
                  else n.func.attr if isinstance(n.func, ast.Attribute) else None)
        if nombre != "ingest_canonical":
            continue
        kw = {k.arg: k.value for k in n.keywords}
        persist = kw.get("persist")
        if persist is None or (isinstance(persist, ast.Constant) and persist.value is False):
            continue  # sin persist no escribe nada
        alcance = kw.get("alcance")
        if alcance is None or (isinstance(alcance, ast.Constant) and alcance.value is None):
            yield n.lineno


def _barrido():
    for f in RAIZ.rglob("*.py"):
        rel = f.relative_to(RAIZ).as_posix()
        if any(x in "/" + rel for x in EXCLUIDOS):
            continue
        try:
            arbol = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensivo
            continue
        yield rel, arbol


def test_nadie_persiste_el_canonico_sin_alcance():
    malas = [f"{rel}:{linea}" for rel, arbol in _barrido() if rel not in EXCEPCIONES
             for linea in _llamadas_sin_alcance(arbol)]
    assert not malas, (
        "`ingest_canonical` persiste sin `alcance=`, y `None` escribe TODO el canónico —"
        "incluidos los empates que el upsert resuelve por orden de lectura—. Pasá "
        "`alcance=PERSISTIBLES_VERIFICADOS` o declarala en EXCEPCIONES con su motivo: "
        + ", ".join(malas))


def test_el_barrido_ENCUENTRA_los_llamadores():
    """Un barrido que no encuentra nada pasa en verde sin haber mirado."""
    llamadores = {rel for rel, arbol in _barrido()
                  if any(isinstance(n, ast.Call) and getattr(n.func, "attr",
                         getattr(n.func, "id", None)) == "ingest_canonical"
                         for n in ast.walk(arbol))}
    assert {"modules/macro_monitor/operations.py",
            "modules/macro_monitor/service.py",
            "modules/macro_monitor/tasks.py"} <= llamadores
    assert set(EXCEPCIONES) <= llamadores, "una excepción que ya no llama es una excepción muerta"


def test_el_chequeo_DETECTA_el_defecto_que_lo_originó():
    fuente = ("def _run():\n"
              "    ingest_canonical(db, persist=persist)\n"
              "def ok():\n"
              "    ingest_canonical(db, persist=True, alcance=PERSISTIBLES_VERIFICADOS)\n"
              "def seco():\n"
              "    ingest_canonical(db, persist=False)\n"
              "def nulo():\n"
              "    service.ingest_canonical(db, persist=True, alcance=None)\n")
    assert list(_llamadas_sin_alcance(ast.parse(fuente))) == [2, 8]
