"""Los conteos regionales (2.2 y 2.5 de la END) y el guard que impide fabricar una mejora.

Contar cuántas regiones cruzan un umbral es la forma más silenciosa de inventar progreso: si
un año trae nueve regiones en vez de diez, el conteo baja porque falta un dato, no porque una
región haya cruzado el umbral. Y baja **en la dirección de la meta** — la ley pide que el
número llegue a cero—, así que se lee como avance y el único aviso sería que nadie lo note.
"""
from types import SimpleNamespace

import pytest

from modules.social_dev import social_sync as ss

REGIONES = [(f"r{i}", f"R{i}") for i in range(10)]


class _DB:
    """Doble mínimo: sirve filas y captura los upserts, sin tocar base."""

    def __init__(self, filas):
        self._filas = filas
        self.escrito = []

    def query(self, *cols):
        return self

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._filas


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    monkeypatch.setattr("shared.data.one_client.region_catalog", lambda: REGIONES)
    monkeypatch.setattr(ss, "_upsert_indicator",
                        lambda db, **kw: db.escrito.append(kw))


def _panel(anio, valores, tema="poverty_rate"):
    return [(anio, f"r{i}", v) for i, v in enumerate(valores)]


def test_un_anio_con_las_diez_regiones_se_cuenta():
    """2010 real: las diez regiones sobre 20% de pobreza moderada, y la línea base legal del
    2.5 es exactamente 10. El oráculo de la propia ley valida la derivación."""
    db = _DB(_panel("2010", [31, 36, 40, 41, 44, 50, 53, 56, 61, 64]))
    ss._sync_conteos_regionales(db, lambda _: None)
    moderada = [e for e in db.escrito if "moderada" in e["theme"]]
    assert moderada and moderada[0]["value"] == 10.0
    assert moderada[0]["period"] == "2010"


def test_un_anio_INCOMPLETO_no_se_cuenta():
    """Nueve regiones, ocho sobre el umbral. Publicarlo diría «8» contra un año anterior de
    «10» y se leería como que dos regiones salieron de la pobreza. Lo que pasó es que faltó
    un dato."""
    db = _DB(_panel("2016", [28, 29, 29, 30, 34, 40, 41, 42, 18]))  # nueve
    ss._sync_conteos_regionales(db, lambda _: None)
    assert not [e for e in db.escrito if e["period"] == "2016"], (
        "un panel incompleto NO produce conteo: bajaría en la dirección de la meta")


def test_el_umbral_es_ESTRICTO_como_dice_la_ley():
    """«mayor que 20%», no «20% o más». Una región exactamente en 20,0 no cuenta, y con diez
    regiones al filo la diferencia es el indicador entero."""
    db = _DB(_panel("2020", [20.0] * 5 + [20.1] * 5))
    ss._sync_conteos_regionales(db, lambda _: None)
    moderada = [e for e in db.escrito if "moderada" in e["theme"]]
    assert moderada[0]["value"] == 5.0


def test_el_conteo_se_publica_como_NACIONAL():
    """Su insumo es por región y su resultado es del país: contar cuántas regiones cruzan un
    umbral no es una cifra de ninguna demarcación."""
    db = _DB(_panel("2010", [31] * 10))
    ss._sync_conteos_regionales(db, lambda _: None)
    assert all(e["entity"] == ss.HEALTH_ENTITY for e in db.escrito)
    assert all(e["disagg"] == "nacional" for e in db.escrito)


def test_la_fuente_declara_que_el_numero_es_un_COMPUTO_nuestro():
    """Un consumidor tiene que poder distinguir «lo publica la ONE» de «lo calculamos con el
    panel de la ONE». La segunda es nuestra responsabilidad, no la del emisor."""
    db = _DB(_panel("2010", [31] * 10))
    ss._sync_conteos_regionales(db, lambda _: None)
    assert db.escrito, "el caso tiene que producir escrituras o el test no prueba nada"
    assert all("cómputo sdq" in e["source"].lower() for e in db.escrito)
    assert all(len(e["source"]) <= 40 for e in db.escrito), (
        "`sd_indicators.source` es varchar(40): Postgres rechaza el commit entero")
