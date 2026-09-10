"""La sonda diaria del MIVHED: mira la fuente, deja constancia, y NO ingiere.

Existe para acotar a un día el tiempo en que el informe puede declarar un atraso que el
emisor ya corrigió. El sync corre cada 720 h; sin la sonda, una edición publicada al día
siguiente de un sync tardaba hasta un mes en verse.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from shared.database.base import Base


@pytest.fixture()
def db(monkeypatch):
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    import modules.construction_intel.operations as ops_mod

    monkeypatch.setattr(ops_mod, "SessionLocal", lambda: s)
    # La sonda cierra su sesión al terminar; acá es la del test, que la cierra la fixture.
    monkeypatch.setattr(s, "close", lambda: None)
    yield s


_CSV_JUNIO = ("Fecha de Emisión,Mes,Año,Provincia,Municipio,Barrio/Sector,"
              "Número de Licencia,Tipologia,Metros Cuadrados,Inversión Total\n"
              "06/15/2026,JUNIO,2026,LA ALTAGRACIA,HIG,X,P1,HOSPEDAJE,1000,61600000\n")
_CSV_JULIO = _CSV_JUNIO + "07/10/2026,JULIO,2026,SANTIAGO,STG,Y,P2,VIVIENDAS,200,12320000\n"


def _fuente(monkeypatch, csv=_CSV_JUNIO, publicado_el="2026-07-21", falla=None):
    from shared.data import mivhed_client as mc

    def _bajar(self, slug):
        if falla:
            raise falla
        return csv, publicado_el

    monkeypatch.setattr(mc.MIVHEDClient, "_fetch_csv_con_fecha", _bajar)


def _disparos(monkeypatch):
    import shared.operations.service as svc

    llamadas = []
    monkeypatch.setattr(svc, "trigger",
                        lambda name, **kw: llamadas.append((name, kw)) or {"started": True})
    return llamadas


def _tenemos_junio(db, publicado_el="2026-07-21"):
    from modules.construction_intel.service import ingest_observaciones_mensuales

    ingest_observaciones_mensuales(db, {
        "periodos": {"2026-06": {"permits": 1, "sqm": 1000.0,
                                 "by_province": {}, "by_typology": {}}},
        "sin_mes": 0, "publicado_el": publicado_el})


def _correr():
    from modules.construction_intel.operations import _run_vigilancia_mivhed

    return _run_vigilancia_mivhed({}, None, lambda _m: None)


# ── Sin novedad: deja constancia y no dispara nada ───────────────────────────────

def test_sin_novedad_NO_dispara_el_sync(db, monkeypatch):
    _tenemos_junio(db)
    _fuente(monkeypatch)
    disparos = _disparos(monkeypatch)
    r = _correr()
    assert r["hay_novedad"] is False and disparos == []
    assert "sin novedad" in r["lectura"]


def test_sin_novedad_igual_REGISTRA_que_miro(db, monkeypatch):
    """Esa fecha es la que el informe cita como «nuestra última descarga»."""
    from modules.construction_intel.service import leer_verificacion

    _tenemos_junio(db)
    _fuente(monkeypatch)
    _disparos(monkeypatch)
    _correr()
    v = leer_verificacion(db)
    assert v and v["verificado_el"] and v["ultimo_periodo_en_fuente"] == "2026-06"


# ── Con novedad: dispara el sync completo ────────────────────────────────────────

def test_un_mes_NUEVO_en_la_fuente_dispara_el_sync(db, monkeypatch):
    _tenemos_junio(db)
    _fuente(monkeypatch, csv=_CSV_JULIO, publicado_el="2026-08-21")
    disparos = _disparos(monkeypatch)
    r = _correr()
    assert r["hay_novedad"] is True
    assert [n for n, _ in disparos] == ["mivhed-construction-sync"]


def test_una_REPUBLICACION_sin_mes_nuevo_tambien_dispara(db, monkeypatch):
    """El emisor puede corregir el mismo archivo. Una fecha de publicación posterior basta."""
    _tenemos_junio(db, publicado_el="2026-07-21")
    _fuente(monkeypatch, csv=_CSV_JUNIO, publicado_el="2026-08-02")
    disparos = _disparos(monkeypatch)
    assert _correr()["hay_novedad"] is True and len(disparos) == 1


def test_sin_nada_ingerido_todavia_cualquier_mes_es_novedad(db, monkeypatch):
    _fuente(monkeypatch)
    disparos = _disparos(monkeypatch)
    assert _correr()["hay_novedad"] is True and len(disparos) == 1


# ── No ingiere, y un fallo no se disfraza de verificación ───────────────────────

def test_la_sonda_NO_ingiere_nada(db, monkeypatch):
    from shared.observations import service as obs

    _tenemos_junio(db)
    antes = obs.contar(db, sector_key="construction")
    _fuente(monkeypatch, csv=_CSV_JULIO, publicado_el="2026-08-21")
    _disparos(monkeypatch)
    _correr()
    assert obs.contar(db, sector_key="construction") == antes
    assert obs.ultimo_periodo(db, sector_key="construction") == "2026-06"


def test_no_poder_bajar_la_fuente_NO_pisa_la_ultima_verificacion(db, monkeypatch):
    """No poder llegar a la fuente no es evidencia de que siga igual, y la fecha de la última
    lectura buena no se reemplaza por la de una que no leyó nada."""
    from modules.construction_intel.service import guardar_verificacion, leer_verificacion

    _tenemos_junio(db)
    guardar_verificacion(db, {"verificado_el": "2026-09-01T10:00:00+00:00"})
    _fuente(monkeypatch, falla=RuntimeError("503 del portal"))
    disparos = _disparos(monkeypatch)
    r = _correr()
    assert "error" in r and disparos == []
    assert "NO es evidencia" in r["lectura"]
    assert leer_verificacion(db)["verificado_el"].startswith("2026-09-01")


def test_la_sonda_NUNCA_levanta(db, monkeypatch):
    _fuente(monkeypatch, falla=ValueError("csv roto"))
    _disparos(monkeypatch)
    assert isinstance(_correr(), dict)


# ── Registro de la operación ─────────────────────────────────────────────────────

def test_la_sonda_existe_y_es_mas_frecuente_que_el_sync():
    from shared.operations.service import OPERATIONS

    import modules.construction_intel.operations  # noqa: F401 — registra

    sonda, sync = OPERATIONS["mivhed-vigilancia"], OPERATIONS["mivhed-construction-sync"]
    assert sonda.default_interval_hours == 24
    assert sonda.default_interval_hours < sync.default_interval_hours
    assert not sonda.needs_params, "una operación con parámetros no recibe agenda al arrancar"
