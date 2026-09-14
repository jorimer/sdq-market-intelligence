"""Energía es el tercer eje con feed mensual: el IMTE del OC-SENI (Fase 5).

Lo que se prueba acá es lo que el eje tiene de propio. El contrato del delta —encabezado, caché,
veto por frescura, atribución al pie— ya lo prueba `shared/products/tests/test_feed_delta.py`
con un producto de prueba; estos tests fijan que ENERGÍA lo cumple con su dato real (el fixture
es la hoja «Iny» de la edición del 20 de agosto de 2026).
"""
import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data import oc_seni_client as oc
from shared.database.base import Base
from shared.observations import service as obs
from shared.observations.models import SectorObservation
from shared.products.tiers import ProductTier


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


def _sincronizar(db):
    from modules.energy_intel.service import sincronizar_imte

    return sincronizar_imte(db, client=oc.OCSENIClient(mode="fixture"))


# ── La ingesta ────────────────────────────────────────────────────────────────────

def test_la_ingesta_escribe_las_cuatro_series_con_su_NATURALEZA_y_la_fecha_del_OC(db):
    r = _sincronizar(db)
    assert r["edicion"] == "2026-07" and r["publicada"] == "2026-08-20"
    filas = db.query(SectorObservation).filter_by(sector_key="energy").all()
    naturalezas = {f.series_code: f.nature for f in filas}
    assert naturalezas == {
        oc.SERIE_INYECCIONES: "flow", oc.SERIE_RETIROS: "flow",
        oc.SERIE_RETIROS_DISTRIBUIDORAS: "flow", oc.SERIE_PERDIDAS: "rate"}
    assert {f.published_at for f in filas} == {date(2026, 8, 20)}, (
        "la fecha de publicación tiene que ser la del OC, no la de la descarga")
    assert obs.ultimo_periodo(db, sector_key="energy", con_valor=True) == "2026-07"


def test_re_sincronizar_REEMPLAZA_la_serie_y_un_mes_retirado_por_el_OC_desaparece(db):
    """El libro trae el año en curso y el anterior enteros: la edición nueva es la verdad. Un
    upsert fila a fila dejaría vivo un mes que el OC ya no publica."""
    from shared.data.base_client import Record
    from shared.data.lineage import Lineage

    from modules.energy_intel.service import escribir_observaciones_imte

    retirado = Record(series=oc.SERIE_INYECCIONES, period="2024-12", value=1.0,
                      lineage=Lineage(source="x", license="x", fetched_at=date(2026, 1, 1)),
                      unit="GWh")
    escribir_observaciones_imte(db, [retirado], publicada=date(2026, 1, 20), source="x", license="x")
    db.commit()
    n = _sincronizar(db)["puntos"]
    filas = db.query(SectorObservation).filter_by(sector_key="energy")
    assert filas.count() == n
    assert filas.filter_by(period="2024-12").count() == 0, "quedó vivo un mes que el OC retiró"


def test_si_el_OC_falla_el_IRSE_queda_escrito_y_la_corrida_lo_DICE(monkeypatch):
    from modules.energy_intel import operations, service

    monkeypatch.setattr(service, "backfill_scores", lambda _db: {"period": "2025", "periods": ["2025"]})

    def revienta(_db, client=None):
        raise oc.EstructuraInesperada("OC-SENI: la hoja cambió")

    monkeypatch.setattr(service, "sincronizar_imte", revienta)

    class _Sesion:
        cerrada = revertida = False

        def rollback(self):
            _Sesion.revertida = True

        def close(self):
            _Sesion.cerrada = True

    monkeypatch.setattr(operations, "SessionLocal", _Sesion)
    out = operations._run_sie_energy_sync({}, None, lambda _m: None)
    assert out["periods"] == ["2025"], "el feed tumbó el índice"
    assert "EstructuraInesperada" in out["imte"]["error"]
    assert _Sesion.revertida and _Sesion.cerrada


def test_la_operacion_corre_MENSUAL():
    from shared.operations.service import OPERATIONS

    import modules.energy_intel.operations  # noqa: F401

    assert OPERATIONS["sie-energy-sync"].default_interval_hours == 720


# ── El producto ───────────────────────────────────────────────────────────────────

def test_el_producto_DECLARA_el_feed_y_el_sensor_lo_mide(db):
    from modules.energy_intel.products import _SECTION_TITLES, EnergyProduct

    _sincronizar(db)
    p = EnergyProduct(db)
    # Desde la Fase 7 el eje declara DOS feeds (IMTE y obra pública eléctrica): se elige por clave.
    feed = next(f for f in p.feeds_mensuales() if f.clave == "oc_seni_imte")
    assert set(feed.series) == {s for s, _ in oc.FILAS_IMTE.values()}
    assert feed.fuente is not None and feed.fuente.atribucion, (
        "la licencia del OC-SENI no está en el registro o no exige aviso")
    assert _SECTION_TITLES.get("delta_mensual")
    (senal,) = [s for s in p.senales_de_fuentes() if s.clave == "oc_seni_imte"]
    assert "2026-07" in senal.detalle


def test_sin_observaciones_el_eje_NO_tiene_senal_ni_seccion(db):
    from modules.energy_intel.products import EnergyProduct

    assert EnergyProduct(db).senales_de_fuentes() == []


# ── §2.3: la trayectoria va en el payload ─────────────────────────────────────────

def test_la_trayectoria_del_IRSE_viaja_en_el_PAYLOAD_y_el_contexto_la_lee_de_ahi(monkeypatch):
    from shared.narrative import claude_engine as ce

    from modules.energy_intel import products as ep

    class _Score:
        period, energy_score, band, coverage = "2025", 60.0, "Adecuado", 1.0
        transition_score, breakdown = 50.0, {}

    monkeypatch.setattr(ep, "_latest_score", lambda _db, _p=None: _Score())
    monkeypatch.setattr(ep, "_index_dict", lambda _s: {"energy_score": 60.0})
    monkeypatch.setattr(ep, "_trend_series", lambda _db: [("2024", 55.0), ("2025", 60.0)])
    p = ep.EnergyProduct(db=object())
    snap = p.snapshot(ProductTier.deep_dive, "2025")
    assert snap.payload["trayectoria_del_irse"] == [
        {"periodo": "2024", "score": 55.0}, {"periodo": "2025", "score": 60.0}]

    # Y el contexto NO la vuelve a leer de la base: con la base vacía, sale la del payload.
    monkeypatch.setattr(ep, "_trend_series", lambda _db: [])
    monkeypatch.setattr(ep, "energy_ai_context", lambda *a, **k: {})
    vistos = []

    async def fake(**kw):
        vistos.append(kw)
        return ce.NarrativeResult(text="x")

    monkeypatch.setattr(ce.narrative_engine, "generate", fake)
    asyncio.run(p.narratives(ProductTier.deep_dive, snap))
    posicion = [k for k in vistos if k["template"] == "sector_positioning"]
    assert posicion and posicion[0]["context"]["trayectoria"] == snap.payload["trayectoria_del_irse"]


def test_si_la_SIE_falla_el_IMTE_se_sincroniza_igual(monkeypatch):
    """El 2026-09-14 la SIE retiró el CSV de capacidad y el feed mensual quedó sin correr."""
    from modules.energy_intel import operations, service

    def sie_caida(_db):
        raise RuntimeError("SIE: el recurso respondió HTTP 404")

    monkeypatch.setattr(service, "backfill_scores", sie_caida)
    monkeypatch.setattr(service, "sincronizar_imte", lambda _db, client=None: {"edicion": "2026-07"})

    class _Sesion:
        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(operations, "SessionLocal", _Sesion)
    out = operations._run_sie_energy_sync({}, None, lambda _m: None)
    assert out["imte"] == {"edicion": "2026-07"}
    assert "404" in out["irse"]["error"]


def test_si_caen_las_DOS_la_corrida_falla_a_la_vista(monkeypatch):
    from modules.energy_intel import operations, service

    def revienta(*a, **k):
        raise RuntimeError("caída")

    monkeypatch.setattr(service, "backfill_scores", revienta)
    monkeypatch.setattr(service, "sincronizar_imte", revienta)

    class _Sesion:
        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(operations, "SessionLocal", _Sesion)
    with pytest.raises(RuntimeError, match="energía sin sincronizar"):
        operations._run_sie_energy_sync({}, None, lambda _m: None)


def test_una_pagina_de_error_de_la_SIE_no_se_parsea_como_CSV(monkeypatch):
    import httpx

    from shared.data.sie_client import SIEClient

    class _Resp:
        status_code = 404
        content = b"<html>" + b"x" * 200000

    class _Cliente:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Cliente)
    monkeypatch.setattr(SIEClient, "_resolve_csv", lambda self, slug: "https://sie.gob.do/x.csv")
    with pytest.raises(RuntimeError, match="HTTP 404"):
        SIEClient().installed_capacity()
