"""El feed mensual de SEGUROS (Fase 3): qué se escribe, qué no, y qué no puede publicar el Pulse.

* **Convivencia** — la afiliación SFS se escribe en `insurance_series` Y en
  `sector_observations`; por período las dos tablas tienen las mismas filas y los mismos
  valores (plan §2.1: no se migra, conviven).
* **Naturaleza** — la afiliación entra como STOCK y su delta se mide contra el último nivel.
* **Sistema de ARS** — un total exige a TODAS las ARS; un período con una ausente es `None`.
  Los acumulados al mes (ingresos, gastos, beneficio) no entran a la tabla transversal.
* **Pulse** — el roster viaja al sensor de anonimización: un texto que nombra una ARS no sale.
* **Readiness** — `DataHealth.cadence` sigue trimestral.
"""
import asyncio
from collections import Counter
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.narrative.claude_engine as ce
from modules.insurance_intel.ars_sync import (
    STOCKS_DE_SISTEMA,
    ars_sync,
    escribir_agregados_de_sistema,
)
from modules.insurance_intel.models.models import InsuranceSeries
from modules.insurance_intel.products import InsuranceProduct
from modules.insurance_intel.sisalril_sync import sisalril_sfs_sync
from shared.data.base_client import Record
from shared.data.lineage import Lineage
from shared.database.base import Base
from shared.observations.models import SectorObservation
from shared.products.tiers import ProductTier

SFS = ("sfs.afiliacion.total", "sfs.afiliacion.contributivo", "sfs.afiliacion.subsidiado")


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


def _obs(db, **filtros):
    q = db.query(SectorObservation).filter(SectorObservation.sector_key == "insurance")
    for campo, valor in filtros.items():
        q = q.filter(getattr(SectorObservation, campo) == valor)
    return q.all()


# ── Convivencia: las dos tablas dicen lo mismo ───────────────────────────────────

def test_la_afiliacion_SFS_se_escribe_en_las_DOS_tablas_con_las_mismas_filas_por_periodo(db):
    r = sisalril_sfs_sync(db, mode="fixture")
    assert r["observaciones"] > 0

    viejas = (db.query(InsuranceSeries)
              .filter(InsuranceSeries.series_code.in_(SFS),
                      InsuranceSeries.entity_slug.is_(None)).all())
    nuevas = [o for o in _obs(db) if o.series_code in SFS]
    assert viejas and nuevas

    por_periodo_viejas = Counter(v.period for v in viejas)
    por_periodo_nuevas = Counter(o.period for o in nuevas)
    assert por_periodo_viejas == por_periodo_nuevas, (
        "por período, insurance_series y sector_observations no tienen las mismas filas SFS")
    valores_viejos = {(v.series_code, v.period): v.value for v in viejas}
    valores_nuevos = {(o.series_code, o.period): o.value for o in nuevas}
    assert valores_viejos == valores_nuevos


def test_la_ingesta_SFS_es_IDEMPOTENTE(db):
    sisalril_sfs_sync(db, mode="fixture")
    n1 = len(_obs(db))
    sisalril_sfs_sync(db, mode="fixture")
    assert len(_obs(db)) == n1


def test_la_afiliacion_entra_como_STOCK_y_sin_fecha_de_publicacion_inventada(db):
    """El conector solo sabe cuándo DESCARGÓ el CSV. Esa fecha no es la del emisor, y el
    encabezado del delta la citaría como «la última edición que publicó»."""
    sisalril_sfs_sync(db, mode="fixture")
    nuevas = [o for o in _obs(db) if o.series_code in SFS]
    assert {o.nature for o in nuevas} == {"stock"}
    assert {o.frequency for o in nuevas} == {"monthly"}
    assert all(o.published_at is None for o in nuevas)
    assert all(o.license for o in nuevas), "la observación viaja sin licencia del emisor"


def test_el_delta_de_la_afiliacion_se_mide_contra_el_ULTIMO_NIVEL(db):
    from shared.products.feed_delta import bloque_del_feed

    sisalril_sfs_sync(db, mode="fixture")
    feed = next(f for f in InsuranceProduct(db).feeds_mensuales() if f.clave == "sisalril_sfs")
    b = bloque_del_feed(db, "insurance", feed)
    assert b is not None and "no_publicable" not in b, b
    total = next(s for s in b["series"] if s["serie"] == "sfs.afiliacion.total")
    assert total["naturaleza"] == "stock"
    assert total["linea_base"]["tipo"] == "ultimo_nivel_publicado"
    assert "ventana_movil_12m" not in total, "a un stock se le computó una ventana de flujo"


# ── El sistema de ARS: un total exige a todas ──────────────────────────────────

def _rec(serie, periodo, valor, ars):
    lin = Lineage(source="SISALRIL", license="x", fetched_at=date(2026, 9, 14))
    return Record(series=serie, period=periodo, value=valor, lineage=lin, unit="RD$",
                  dimension=ars)


def test_un_periodo_COMPLETO_suma_y_uno_con_una_ARS_ausente_se_declara_None(db):
    records = [
        _rec("ars.patrimonio", "2026-03", 100.0, "001"),
        _rec("ars.patrimonio", "2026-03", 50.0, "003"),
        _rec("ars.patrimonio", "2026-04", 110.0, "001"),      # la 003 no reporta abril
        _rec("ars.ingreso_salud", "2026-04", 999.0, "001"),   # acumulado: no entra
    ]
    r = escribir_agregados_de_sistema(db, records, source="SISALRIL", license="x")
    db.commit()
    assert r == {"ars_en_el_universo": 2, "puntos_completos": 1, "puntos_con_ars_faltantes": 1}
    filas = {o.period: o.value for o in _obs(db, series_code="ars.sistema.patrimonio")}
    assert filas == {"2026-03": 150.0, "2026-04": None}, (
        "abril sumó solo la ARS que reportó: un sistema más chico con nombre de completo")


def test_los_ACUMULADOS_al_mes_no_entran_a_la_tabla_transversal(db):
    ars_sync(db, mode="fixture")
    codigos = {o.series_code for o in _obs(db)}
    assert set(STOCKS_DE_SISTEMA.values()) <= codigos
    for acumulado in ("ars.ingreso_salud", "ars.gasto_salud", "ars.beneficio_neto",
                      "ars.sistema.ingreso_salud", "ars.sistema.gasto_salud"):
        assert acumulado not in codigos, f"«{acumulado}» entró al feed y se leería como flujo"
    assert {o.nature for o in _obs(db) if o.series_code.startswith("ars.sistema.")} == {"stock"}


# ── El producto declara los dos feeds, y el índice sigue trimestral ──────────────

def test_el_producto_DECLARA_los_dos_feeds_y_el_sensor_los_ve(db):
    from shared.operations.fuentes_congeladas import leer_fuentes_de_los_ejes

    sisalril_sfs_sync(db, mode="fixture")
    ars_sync(db, mode="fixture")
    p = InsuranceProduct(db)
    assert [f.clave for f in p.feeds_mensuales()] == ["sisalril_sfs", "sisalril_ars"]
    assert {s.clave for s in p.senales_de_fuentes()} == {"sisalril_sfs", "sisalril_ars"}
    ids = {v.id for v in leer_fuentes_de_los_ejes(db) if v.eje == "insurance"}
    assert {"insurance:sisalril_sfs", "insurance:sisalril_ars"} <= ids


def test_la_declaracion_no_exige_base_de_datos():
    feeds = InsuranceProduct(None).feeds_mensuales()
    assert len(feeds) == 2 and all(f.ultima_descarga is None for f in feeds)


def test_el_indice_de_seguros_SIGUE_trimestral(db):
    sisalril_sfs_sync(db, mode="fixture")
    assert InsuranceProduct(db).data_signals().cadence == "quarterly"


def test_el_PDF_de_seguros_titula_la_seccion_con_SU_fuente():
    from modules.insurance_intel.products import _SECTION_TITLES

    titulo = _SECTION_TITLES.get("delta_mensual") or ""
    assert "SISALRIL" in titulo and "licencias" not in titulo.lower()


# ── El Pulse: el roster llega al sensor y un nombre de ARS no sale ───────────────

def _sembrar_pulse(db):
    from modules.insurance_intel.sis_sync import sis_insurance_sync

    sis_insurance_sync(db, mode="fixture")
    sisalril_sfs_sync(db, mode="fixture")
    ars_sync(db, mode="fixture")


def _motor(monkeypatch, texto_del_delta):
    async def fake(**kw):
        if kw.get("template") == "feed_delta":
            return ce.NarrativeResult(text=texto_del_delta)
        return ce.NarrativeResult(text="El mercado asegurador creció frente al año anterior.")

    monkeypatch.setattr(ce.narrative_engine, "generate", fake)


def test_el_snapshot_del_Pulse_lleva_el_ROSTER_de_aseguradoras_y_ARS(db):
    _sembrar_pulse(db)
    snap = InsuranceProduct(db).snapshot(ProductTier.pulse, "")
    assert snap.payload.get("has_data"), "el fixture del SIS no armó el pulso"
    assert "ARS Universal" in snap.entity_roster
    assert "roster" not in snap.payload, "el roster entró al payload y movería la huella"


def test_un_delta_de_Pulse_que_NOMBRA_una_ARS_no_se_entrega(db, monkeypatch):
    from shared.products.anonymization import AnonymizationError
    from shared.products.assembler import assemble_product_content

    _sembrar_pulse(db)
    _motor(monkeypatch, "El patrimonio de ARS Universal sube frente al último nivel.")
    with pytest.raises(AnonymizationError):
        asyncio.run(assemble_product_content(InsuranceProduct(db), ProductTier.pulse, period=""))


def test_un_delta_de_Pulse_ANONIMO_se_entrega_con_la_seccion(db, monkeypatch):
    """El contrapeso del de arriba: sin nombres, el Pulse sale y trae el delta."""
    from shared.products.assembler import assemble_product_content

    _sembrar_pulse(db)
    _motor(monkeypatch, "La afiliación total al SFS sube frente al último nivel publicado.")
    content = asyncio.run(assemble_product_content(InsuranceProduct(db), ProductTier.pulse,
                                                   period=""))
    assert "delta_mensual" in content.narratives
    assert "delta_mensual" in content.section_order
