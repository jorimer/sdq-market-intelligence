"""Turismo es el cuarto eje con feed mensual: la llegada de no residentes del BCRD (Fase 6).

El contrato del delta ya lo prueba `shared/products/tests/test_feed_delta.py`; acá se fija que
TURISMO lo cumple con su dato real, y que el feed estacional se mide contra el mismo mes del año
anterior —la base del año anterior visible en el contexto—, que es lo que la fase exige.
"""
import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data import bcrd_llegadas_client as bl
from shared.database.base import Base
from shared.observations.models import SectorObservation
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    import app.main  # noqa: F401

    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    try:
        yield s
    finally:
        s.close()


def _sincronizar(db):
    from modules.tourism_intel.service import sincronizar_llegadas_mensuales

    return sincronizar_llegadas_mensuales(db, client=bl.BCRDLlegadasClient(mode="fixture"))


def test_la_ingesta_escribe_FLUJOS_con_la_fecha_del_BCRD(db):
    r = _sincronizar(db)
    assert r["periodo"] == "2026-07" and r["publicada"] == "2026-08-31"
    filas = db.query(SectorObservation).filter_by(sector_key="tourism").all()
    assert {f.nature for f in filas} == {"flow"}
    assert {f.published_at for f in filas} == {date(2026, 8, 31)}


def test_re_sincronizar_REEMPLAZA_y_un_mes_retirado_desaparece(db):
    from shared.data.base_client import Record
    from shared.data.lineage import Lineage

    from modules.tourism_intel.service import escribir_observaciones_llegadas

    viejo = Record(series=bl.SERIE_TOTAL, period="1990-01", value=1.0, unit="personas",
                   lineage=Lineage(source="x", license="x", fetched_at=date(2026, 1, 1)))
    escribir_observaciones_llegadas(db, [viejo], publicada=None, source="x", license="x")
    db.commit()
    n = _sincronizar(db)["puntos"]
    filas = db.query(SectorObservation).filter_by(sector_key="tourism")
    assert filas.count() == n
    assert filas.filter_by(period="1990-01").count() == 0


def test_si_el_BCRD_falla_el_ITT_queda_y_la_corrida_lo_DICE(monkeypatch):
    from modules.tourism_intel import operations, service

    monkeypatch.setattr(service, "backfill_scores", lambda _db: {"count": 3})

    def revienta(_db, client=None):
        raise bl.EstructuraInesperada("BCRD: la hoja cambió")

    monkeypatch.setattr(service, "sincronizar_llegadas_mensuales", revienta)

    class _Sesion:
        revertida = cerrada = False

        def rollback(self):
            _Sesion.revertida = True

        def close(self):
            _Sesion.cerrada = True

    monkeypatch.setattr(operations, "SessionLocal", _Sesion)
    out = operations._run_tourism_sync({}, None, lambda _m: None)
    assert out["count"] == 3
    assert "EstructuraInesperada" in out["llegadas_mensuales"]["error"]
    assert _Sesion.revertida and _Sesion.cerrada


def test_la_operacion_corre_MENSUAL():
    from shared.operations.service import OPERATIONS

    import modules.tourism_intel.operations  # noqa: F401

    assert OPERATIONS["one-tourism-sync"].default_interval_hours == 720


def test_el_producto_declara_el_feed_y_el_contexto_trae_la_BASE_del_año_anterior(db, monkeypatch):
    from shared.products.feed_delta import bloque_del_delta, contexto_del_delta

    from modules.tourism_intel.products import _SECTION_TITLES, TourismProduct

    _sincronizar(db)
    p = TourismProduct(db)
    from shared.products import registry

    monkeypatch.setitem(registry._REGISTRY, "tourism", lambda _db: p)
    (feed,) = p.feeds_mensuales()
    assert feed.fuente is not None and _SECTION_TITLES.get("delta_mensual")
    (senal,) = p.senales_de_fuentes()
    assert "2026-07" in senal.detalle
    bloque = bloque_del_delta(db, "tourism", [feed])
    ctx = contexto_del_delta(bloque, [feed], "2025")
    (lectura,) = ctx["lecturas_por_emisor"]
    total = next(s for s in lectura["series_del_periodo"] if s["serie"] == bl.SERIE_TOTAL)
    assert "2025-07" in str(total), "la base del mismo mes del año anterior no está en el contexto"


def test_la_trayectoria_del_ITT_viaja_en_el_PAYLOAD(monkeypatch):
    from shared.narrative import claude_engine as ce

    from modules.tourism_intel import products as tp

    class _Score:
        period, itt_score, band, coverage, breakdown = "2025", 70.0, "Fuerte", 1.0, {}

    monkeypatch.setattr(tp, "_latest_score", lambda _db, _p=None: _Score())
    monkeypatch.setattr(tp, "_index_dict", lambda _s: {"itt_score": 70.0})
    monkeypatch.setattr(tp, "_trend_series", lambda _db: [("2024", 65.0), ("2025", 70.0)])
    p = tp.TourismProduct(db=object())
    snap = p.snapshot(ProductTier.deep_dive, "2025")
    assert snap.payload["trayectoria_del_itt"] == [
        {"periodo": "2024", "score": 65.0}, {"periodo": "2025", "score": 70.0}]
    monkeypatch.setattr(tp, "_trend_series", lambda _db: [])
    monkeypatch.setattr(tp, "tourism_ai_context", lambda *a, **k: {})
    vistos = []

    async def fake(**kw):
        vistos.append(kw)
        return ce.NarrativeResult(text="x")

    monkeypatch.setattr(ce.narrative_engine, "generate", fake)
    asyncio.run(p.narratives(ProductTier.deep_dive, snap))
    posicion = [k for k in vistos if k["context"].get("trayectoria")]
    assert posicion and posicion[0]["context"]["trayectoria"] == snap.payload["trayectoria_del_itt"]


def test_el_texto_de_ocupacion_ya_NO_dice_que_solo_hay_PDFs():
    from modules.tourism_intel import ai_context, products

    assert "solo aparecen como cifra suelta" not in products._LIMITATIONS
    assert "SITUR" in products._LIMITATIONS
    assert ai_context.OCUPACION_HOTELERA_VERIFICADA_EL == "2026-09-14"
