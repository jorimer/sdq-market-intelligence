"""La fecha en que el MIVHED publicó su CSV se captura del portal, no se escribe a mano.

El dato no la trae; el CKAN del portal sí (`last_modified` del recurso). Se tiraba al
resolver la URL, y sin ella «la fuente no publica desde tal fecha» solo se podía transcribir.
"""
import pytest

from shared.data import mivhed_client as mod


class _Resp:
    def __init__(self, payload=None, content=b""):
        self._payload, self.content = payload, content

    def json(self):
        return self._payload


def _falso_httpx(monkeypatch, recurso):
    csv = ("Fecha de Emisión,Mes,Año,Provincia,Municipio,Barrio/Sector,"
           "Número de Licencia,Tipologia,Metros Cuadrados,Inversión Total\n"
           "06/15/2026,JUNIO,2026,LA ALTAGRACIA,HIG,X,P1,HOSPEDAJE,1000,61600000\n")

    class _Cliente:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            if params:
                return _Resp({"result": {"resources": [recurso]}})
            return _Resp(content=csv.encode("utf-8"))

    import httpx
    monkeypatch.setattr(httpx, "Client", _Cliente)


def test_la_fecha_de_publicacion_sale_del_last_modified_del_recurso(monkeypatch):
    _falso_httpx(monkeypatch, {"format": "CSV", "url": "https://x/l.csv",
                               "last_modified": "2026-07-21T12:39:08.996340"})
    m = mod.MIVHEDClient().licenses_mensual()
    assert m["publicado_el"] == "2026-07-21"
    assert "2026-06" in m["periodos"]


def test_la_lectura_de_ambas_trae_la_fecha_en_la_mensual(monkeypatch):
    _falso_httpx(monkeypatch, {"format": "CSV", "url": "https://x/l.csv",
                               "last_modified": "2026-07-21T12:39:08"})
    ambas = mod.MIVHEDClient().licenses_ambas()
    assert ambas["mensual"]["publicado_el"] == "2026-07-21"
    assert 2026 in ambas["anual"], "la lectura anual del ICC dejó de salir"


def test_sin_fecha_en_el_portal_se_declara_que_no_se_sabe(monkeypatch):
    """No se inventa: sin `last_modified` la fecha es None, y la sección lo dice así."""
    _falso_httpx(monkeypatch, {"format": "CSV", "url": "https://x/l.csv"})
    assert mod.MIVHEDClient().licenses_mensual()["publicado_el"] is None


def test_la_ingesta_persiste_la_fecha_en_published_at():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from modules.construction_intel.service import ingest_observaciones_mensuales
    from shared.database.base import Base
    from shared.observations import service as obs

    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e)()
    try:
        r = ingest_observaciones_mensuales(db, {
            "periodos": {"2026-06": {"permits": 1, "sqm": 1000.0,
                                     "by_province": {}, "by_typology": {}}},
            "sin_mes": 0, "publicado_el": "2026-07-21"})
        assert r["publicado_el"] == "2026-07-21"
        assert obs.ultima_publicacion(db, sector_key="construction").isoformat() == "2026-07-21"
    finally:
        db.close()


@pytest.mark.parametrize("crudo", ["", "no-es-fecha", None])
def test_una_fecha_ilegible_queda_en_NULL(crudo):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from modules.construction_intel.service import ingest_observaciones_mensuales
    from shared.database.base import Base
    from shared.observations import service as obs

    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e)()
    try:
        ingest_observaciones_mensuales(db, {
            "periodos": {"2026-06": {"permits": 1, "sqm": 1.0,
                                     "by_province": {}, "by_typology": {}}},
            "sin_mes": 0, "publicado_el": crudo})
        assert obs.ultima_publicacion(db, sector_key="construction") is None
    finally:
        db.close()
