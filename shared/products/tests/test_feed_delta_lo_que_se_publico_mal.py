"""Tres defectos del delta de feeds que llegaron a PRODUCCIÓN con la Fase 3 (2026-09-14).

Vistos en el Pulse y en el Deep Dive de seguros servidos por HTTP, después del merge de #1169:

* **D1** — «Es la última edición disponible de el CNSS». El emisor se escribe con su artículo
  y la frase le anteponía «de» sin contraer.
* **D2** — una subsección entera sobre saldos de ARS de julio de 2026 que «no cuentan con
  observación disponible». El total de sistema de un período con una ARS sin reportar se
  persiste NULL (correcto), pero el feed tomaba ese período como el último: la sección narraba
  una ausencia —lo que la decisión del dueño del 2026-08-31 prohíbe— y el sensor daba «al día»
  midiendo un mes sin ningún valor.
* **D3** — la línea de atribución ODbL salía dos veces: los dos feeds de seguros son de SISALRIL
  con la misma licencia.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.narrative.formato import de_seguido_de
from shared.observations import service as obs
from shared.products.feed_delta import (
    FeedDeclarado,
    bloque_del_feed,
    dias_desde_el_fin_del_periodo,
    encabezado_del_movimiento,
    senales_de_los_feeds,
)

EJE = "tourism"
SERIE = "prueba.stock.saldo"


@pytest.fixture()
def db():
    import app.main  # noqa: F401 — registra productos y tablas reales

    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    try:
        yield s
    finally:
        s.close()


def _feed(**kw):
    base = dict(clave="prueba_sistema", etiqueta="los saldos de prueba", emisor="Emisor de prueba",
                emisor_en_prosa="el Emisor de prueba", series=(SERIE,),
                etiquetas={SERIE: "saldo del sistema"}, axis="tourism_intel", cadence="monthly")
    base.update(kw)
    return FeedDeclarado(**base)


def _punto(db, period, value):
    obs.upsert(db, sector_key=EJE, series_code=SERIE, period=period, value=value, unit="RD$",
               frequency="monthly", nature="stock", source="Emisor de prueba")
    db.commit()


@pytest.fixture()
def registrado(db, monkeypatch):
    """El sensor resuelve el producto por el registro: se registra uno mínimo con el feed."""
    from shared.products import registry

    feed = _feed()

    class _P:
        sector_key = EJE
        _db = db

        def feeds_mensuales(self):
            return [feed]

        def senales_de_fuentes(self):
            return senales_de_los_feeds(db, EJE, [feed])

        def data_signals(self):
            from shared.products.contract import DataHealth
            return DataHealth(coverage=1.0, freshness_days=10, cadence="annual")

    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: _P())
    return feed


# ── D2 · un período con todas sus filas en NULL no es el último ──────────────────

def test_el_ultimo_periodo_CON_VALOR_ignora_un_mes_vacio(db):
    _punto(db, "2026-06", 100.0)
    _punto(db, "2026-07", None)
    assert obs.ultimo_periodo(db, sector_key=EJE, series=[SERIE]) == "2026-07"
    assert obs.ultimo_periodo(db, sector_key=EJE, series=[SERIE], con_valor=True) == "2026-06"


def test_la_seccion_lee_el_ultimo_mes_CON_VALOR_y_no_narra_el_vacio(db, registrado):
    _punto(db, "2026-05", 90.0)
    _punto(db, "2026-06", 100.0)
    _punto(db, "2026-07", None)
    b = bloque_del_feed(db, EJE, registrado)
    assert b is not None and b["periodo"] == "2026-06", b
    assert b["series"], "la lectura del último mes con valor salió vacía"
    assert b["sin_lectura"] == [], "el mes vacío llegó al contexto como serie sin lectura"


def test_el_sensor_mide_el_MISMO_mes_que_la_seccion(db, registrado):
    """El panel decía «al día» midiendo un julio vacío, y la sección leía otro mes."""
    _punto(db, "2026-06", 100.0)
    _punto(db, "2026-07", None)
    senal = senales_de_los_feeds(db, EJE, [registrado])[0]
    assert "2026-06" in senal.detalle
    assert senal.freshness_days == dias_desde_el_fin_del_periodo("2026-06")
    assert bloque_del_feed(db, EJE, registrado)["periodo"] == "2026-06"


def test_un_feed_SIN_ningun_valor_no_tiene_seccion_ni_senal(db, registrado):
    _punto(db, "2026-07", None)
    assert bloque_del_feed(db, EJE, registrado) is None
    assert senales_de_los_feeds(db, EJE, [registrado]) == []


# ── D1 · «de» + artículo se contrae; un nombre propio no ─────────────────────────

@pytest.mark.parametrize("frase, esperado", [
    ("el CNSS", "del CNSS"),
    ("el MIVHED", "del MIVHED"),
    ("SISALRIL", "de SISALRIL"),
    ("El Salvador", "de El Salvador"),
    ("la ONE", "de la ONE"),
])
def test_de_seguido_de(frase, esperado):
    assert de_seguido_de(frase) == esperado


def test_el_encabezado_de_una_fuente_sin_fecha_de_publicacion_CONTRAE(db):
    bloque = {"lecturas": [{"clave": "prueba_sistema", "periodo": "2026-05", "emisor": "CNSS",
                            "fuente_del_feed": {"al_dia": False, "ultimo_periodo": "2026-05",
                                                "ultima_publicacion": None,
                                                "cadencia": "mensual"}}]}
    feed = _feed(emisor_en_prosa="el CNSS", ultima_descarga=date(2026, 9, 14))
    texto = encabezado_del_movimiento(bloque, [feed])
    assert "disponible del CNSS" in texto
    assert "de el " not in texto


# ── D3 · la misma atribución no se repite; dos distintas sí ──────────────────────

def test_una_atribucion_IDENTICA_sale_una_vez_y_dos_distintas_salen_las_dos():
    """Con los conectores REALES, no con textos inventados: un texto que el registro de
    licencias no reconoce no exige atribución, y el test terminaría en skip sin probar nada."""
    from shared.data.mivhed_client import MIVHEDClient
    from shared.data.sisalril_ars_client import SISALRILARSClient
    from shared.data.sisalril_client import SISALRILClient
    from shared.narrative.atribucion import Fuente, bloque_de_atribucion

    sfs = Fuente.de_cliente(SISALRILClient, descripcion="afiliación al SFS")
    ars = Fuente.de_cliente(SISALRILARSClient, descripcion="saldos de las ARS")
    mivhed = Fuente.de_cliente(MIVHEDClient, descripcion="licencias de construcción")
    assert sfs.atribucion and sfs.atribucion == ars.atribucion, (
        "el caso de prod dejó de reproducirse: los dos feeds de seguros ya no comparten aviso")
    assert mivhed.atribucion and mivhed.atribucion != sfs.atribucion, (
        "el control dejó de servir: MIVHED y SISALRIL exigen hoy el mismo aviso")

    igual = bloque_de_atribucion(sfs, ars)
    assert igual["atribucion_obligatoria"].count(sfs.atribucion) == 1
    assert "afiliación al SFS" in igual["source"] and "saldos de las ARS" in igual["source"], (
        "deduplicar el aviso no puede borrar al emisor de la procedencia")

    distintas = bloque_de_atribucion(sfs, mivhed)
    assert sfs.atribucion in distintas["atribucion_obligatoria"]
    assert mivhed.atribucion in distintas["atribucion_obligatoria"]
