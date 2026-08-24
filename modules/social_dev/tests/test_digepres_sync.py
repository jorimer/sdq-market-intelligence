"""La serie del 2.33 corre en el worker, año por año, y es reanudable.

El defecto que originó todo esto llegó a producción el 2026-08-24: la lectura de ~400 MB
de PDF vivía dentro del panel social, o sea dentro del proceso que atiende la API. El
proceso murió en el séptimo documento —sin traza, que es la firma del sistema matando por
memoria—, se llevó puesta la API unos segundos, y no persistió NADA: el commit llegaba al
final, así que los seis años ya leídos se perdieron enteros.
"""
import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.social_dev import digepres_sync
from modules.social_dev.models.models import SocialIndicator  # noqa: F401 — registra tabla
from shared.database.base import Base
from modules.social_dev.digepres_sync import OPERACION, anios_persistidos, run_digepres_salud


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


class _Gasto:
    def __init__(self, pct):
        self.pct_pib = pct


@pytest.fixture()
def entorno(db, monkeypatch):
    """El emisor y el PIB, sustituidos. Lo que se prueba es NUESTRO recorrido."""
    monkeypatch.setattr(digepres_sync, "SessionLocal", lambda: db)
    monkeypatch.setattr("shared.data.wdi_client.fetch_wb_indicator",
                        lambda *a, **k: ([{"date": str(a), "value": 1e12}
                                          for a in range(2009, 2023)], None))
    monkeypatch.setattr(digepres_sync, "url_del_documento", lambda n: f"https://x/{n}",
                        raising=False)
    return db


def _sin_red(monkeypatch, leidos, documentos, falla_en=None):
    """Sustituye descarga y lectura; `leidos` acumula los años que se llegaron a leer."""
    import shared.data.digepres_funcional as df

    monkeypatch.setattr(df, "DOCUMENTOS", documentos)
    monkeypatch.setattr(df, "url_del_documento", lambda n: f"https://x/{n}")

    class _Resp:
        def raise_for_status(self): pass
        def iter_bytes(self, n): return [b"%PDF-x"]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Cli:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def stream(self, *a, **k): return _Resp()

    monkeypatch.setattr(digepres_sync.httpx, "Client", _Cli)

    def _leer(ruta, anio, pib):
        if falla_en is not None and anio == falla_en:
            raise RuntimeError("el proceso se muere acá")
        leidos.append(anio)
        return _Gasto(1.0 + anio / 10000.0)

    monkeypatch.setattr(df, "leer_documento", _leer)


class TestEsReanudable:
    def test_lo_leido_se_persiste_ANIO_POR_ANIO(self, entorno, monkeypatch):
        """Es la propiedad que vuelve segura una tarea larga: un corte no borra el avance."""
        leidos = []
        _sin_red(monkeypatch, leidos, {2009: "a.pdf", 2010: "b.pdf", 2011: "c.pdf"})
        res = run_digepres_salud()
        assert res["anios_nuevos"] == 3
        assert sorted(anios_persistidos(entorno)) == [2009, 2010, 2011]

    def test_una_corrida_siguiente_NO_vuelve_a_bajar_lo_que_ya_esta(self, entorno,
                                                                    monkeypatch):
        """400 MB de descarga por año ya leído es exactamente lo que pasó en producción."""
        leidos = []
        docs = {2009: "a.pdf", 2010: "b.pdf"}
        _sin_red(monkeypatch, leidos, docs)
        run_digepres_salud()
        leidos.clear()
        run_digepres_salud()
        assert leidos == [], f"volvió a leer {leidos}"

    def test_force_SI_vuelve_a_leer(self, entorno, monkeypatch):
        """Para cuando el emisor corrige un documento ya ingerido."""
        leidos = []
        _sin_red(monkeypatch, leidos, {2009: "a.pdf"})
        run_digepres_salud()
        leidos.clear()
        run_digepres_salud(force=True)
        assert leidos == [2009]

    def test_un_ANIO_que_falla_no_se_lleva_a_los_anteriores(self, entorno, monkeypatch):
        """El caso real: murió en el séptimo y se perdieron los seis. Ahora quedan."""
        leidos = []
        _sin_red(monkeypatch, leidos, {2009: "a.pdf", 2010: "b.pdf", 2011: "c.pdf"},
                 falla_en=2010)
        res = run_digepres_salud()
        assert sorted(anios_persistidos(entorno)) == [2009, 2011]
        assert "2010" in str(res["fallidos"]) or 2010 in res["fallidos"]


def test_los_huecos_del_emisor_VIAJAN_en_el_resultado(entorno, monkeypatch):
    """2020 y 2025 son METAS de la ley y el emisor no publica el cuadro esos años. Un hueco
    callado se lee como que la serie termina ahí."""
    _sin_red(monkeypatch, [], {2009: "a.pdf"})
    res = run_digepres_salud()
    assert "2020" in res["sin_cuadro_en_la_fuente"]
    assert "2025" in res["sin_cuadro_en_la_fuente"]


def test_la_operacion_llega_registrada_por_el_ARRANQUE_real():
    """Se importa `app.main` en vez de llamar a `register()` a mano, y no es un detalle.

    `register()` construye Operation NUEVAS: llamarlo por segunda vez reemplaza las que ya
    estaban por instancias sin sus disparadores, y las saca de la cascada de alertas sin
    que nada avise. Este test lo hizo — dejó al panel social mudo y lo delató el guard
    `test_toda_operacion_NO_excluida_despierta_el_barrido`.

    Y probar el arranque real vale más: confirma que la operación está ENGANCHADA desde
    `app/main.py`, que es lo que hace falta para que exista en producción."""
    import app.main  # noqa: F401 — registra las operaciones de todos los módulos

    from shared.alerts.motor import SWEEP_OP_NAME
    from shared.operations.service import OPERATIONS

    assert OPERACION in OPERATIONS
    assert SWEEP_OP_NAME in OPERATIONS[OPERACION].triggers, (
        "la operación no despierta el barrido de alertas: una serie nueva que entra sin "
        "avisar es una alerta que llega un día tarde")


def test_REGLA_el_panel_social_no_lee_PDF_en_el_proceso_web():
    """REGLA ESTRUCTURAL: la lectura pesada no vuelve al proceso que atiende la API.

    Es la que cierra el defecto de verdad. La lección escrita —«esto va en el worker»— no
    impide que la próxima fuente entre por el mismo camino: `social_sync.py` ya tiene
    veintidós sub-syncs y agregar el veintitrés es una línea. Cuando ese sub-sync lee PDF,
    el proceso web se muere sin traza y se lleva la API con él.

    Se lee `social_sync.py` con `ast` y se exige que no nombre ni al lector de documentos
    ni a `pdfplumber`. Si una fuente nueva de verdad necesita PDF, el camino es una tarea
    del worker —como `modules/social_dev/tasks.py`—, no una excepción acá.
    """
    from modules.social_dev import social_sync

    arbol = ast.parse(Path(social_sync.__file__).read_text(encoding="utf-8"))
    prohibidos = {"pdfplumber", "digepres_funcional", "leer_documento", "leer_informe"}
    encontrados = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            encontrados |= {a.name.split(".")[-1] for a in n.names} & prohibidos
        elif isinstance(n, ast.ImportFrom):
            encontrados |= {(n.module or "").split(".")[-1]} & prohibidos
            encontrados |= {a.name for a in n.names} & prohibidos
        elif isinstance(n, ast.Name):
            encontrados |= {n.id} & prohibidos
    assert not encontrados, (
        f"`social_sync` nombra {sorted(encontrados)} y corre en el proceso WEB. Leer un PDF "
        f"del emisor son hasta 66 MB y 980 páginas: el 2026-08-24 eso mató al proceso en "
        f"producción, sin traza y llevándose la API. Si la fuente nueva necesita PDF, va en "
        f"una tarea del worker (ver `modules/social_dev/tasks.py`).")
