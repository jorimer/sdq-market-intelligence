"""El feed mensual de construcción, DECLARADO al mecanismo transversal: qué declara, qué no toca.

Desde la Fase 1 del plan de entregables mensuales la sección del movimiento del mes la narra
el ensamblador (`shared/products/feed_delta`), con caché propia. Lo que queda de este módulo
es la DECLARACIÓN del feed y sus invariantes:

* **control positivo** — con feed fresco, la sección llega al informe ensamblado con el delta
  computado y su desglose por provincia y tipología, y las mismas cifras de antes;
* **control negativo** — sin observaciones, el informe sale IDÉNTICO y la sección no aparece;
* **el ahorro** — un mes nuevo del feed cuesta UNA llamada al modelo, no las del informe
  entero, y el informe del índice sigue siendo HIT;
* **invariante dura** — el ICC anual persistido no se mueve ni un decimal por este trabajo, y
  el delta NO entra al payload (si entrara, la huella del informe rotaría con el feed).
"""
import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.narrative.claude_engine as ce
from modules.construction_intel.models.models import ConstructionScore
from modules.construction_intel.products import ConstructionProduct
from modules.construction_intel.service import (
    CLAVE_DEL_FEED,
    SERIE_PERMISOS,
    SERIE_SQM,
    ingest_observaciones_mensuales,
)
from shared.database.base import Base
from shared.observations import service as obs
from shared.products.assembler import assemble_product_content
from shared.products.feed_delta import SECCION_DELTA, bloque_del_delta, contexto_del_delta
from shared.products.models import FeedDeltaCache, ProductReportCache
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def icc(db):
    """Un ICC persistido: sin él el producto no arma snapshot."""
    db.add(ConstructionScore(period="2025", icc_score=58.0, band="B", coverage=1.0,
                             permits=1200, sqm=900000.0, investment_dop=5e10,
                             prod_growth_3y=3.1, breakdown={"dimensions": {}}))
    db.commit()


def _mes(period, permisos, sqm, *, provincias=None, tipologias=None):
    return {period: {"permits": permisos, "sqm": sqm,
                     "by_province": {p: {"permits": 1, "sqm": v}
                                     for p, v in (provincias or {}).items()},
                     "by_typology": {t: {"permits": 1, "sqm": v}
                                     for t, v in (tipologias or {}).items()}}}


def _feed_fresco(db, hoy=None):
    """Doce meses del año pasado y los del año en curso hasta el mes recién cerrado.

    El último período es el MES ANTERIOR al de hoy: es lo que un emisor mensual tiene
    publicado, y deja la fuente dentro del tope del sensor.
    """
    hoy = hoy or date.today()
    fin_anio, fin_mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    periodos = {}
    for m in range(1, 13):
        periodos.update(_mes(f"{fin_anio - 1}-{m:02d}", 100, 50_000.0))
    for m in range(1, fin_mes + 1):
        ult = m == fin_mes
        periodos.update(_mes(
            f"{fin_anio}-{m:02d}", 130, 65_000.0,
            provincias={"SANTO DOMINGO": 40_000.0, "SANTIAGO": 25_000.0} if ult else None,
            tipologias={"APARTAMENTOS": 45_000.0, "VIVIENDAS": 20_000.0} if ult else None))
    ingest_observaciones_mensuales(db, {"periodos": periodos, "sin_mes": 0})
    return f"{fin_anio}-{fin_mes:02d}"


def _feed_atrasado(db, publicado_el="2023-12-20"):
    periodos = {}
    for m in range(1, 13):
        periodos.update(_mes(f"2022-{m:02d}", 100, 50_000.0))
    for m in range(1, 13):
        periodos.update(_mes(f"2023-{m:02d}", 130, 65_000.0))
    ingest_observaciones_mensuales(
        db, {"periodos": periodos, "sin_mes": 0, "publicado_el": publicado_el})


def _motor(monkeypatch, texto="Las licencias suben frente al mismo mes del año anterior."):
    """Motor falso que CUENTA llamadas por plantilla. Sin clave de API el real degrada."""
    llamadas = []

    async def fake(**kw):
        llamadas.append(kw["template"])
        return ce.NarrativeResult(text=texto)

    monkeypatch.setattr(ce.narrative_engine, "generate", fake)
    return llamadas


def _bloque(db):
    feeds = ConstructionProduct(db).feeds_mensuales()
    return bloque_del_delta(db, "construction", feeds), feeds


def _entregado(db, tier=ProductTier.deep_dive):
    """El informe como lo ENSAMBLA la plataforma: índice + delta + estándar, con sus cachés."""
    return asyncio.run(assemble_product_content(ConstructionProduct(db), tier, period="2025"))


def _hoy_utc_largo():
    """La fecha de la última descarga en estos tests es la de la ingesta, sellada por la base
    en UTC. Con la fecha LOCAL el test fallaría entre la medianoche UTC y la de Santo Domingo."""
    from datetime import datetime, timezone

    from shared.narrative.formato import fecha_larga_es

    return fecha_larga_es(datetime.now(timezone.utc).date().isoformat())


# ── La declaración ────────────────────────────────────────────────────────────────

def test_el_producto_DECLARA_el_feed_con_sus_series_y_su_sujeto_en_las_dimensiones(db):
    feeds = ConstructionProduct(db).feeds_mensuales()
    # Desde la Fase 7 el eje declara también la obra pública adjudicada (DGCP). El MIVHED sigue
    # primero: es el feed cuya forma fija este test.
    assert [x.clave for x in feeds] == [CLAVE_DEL_FEED, "dgcp_obras"]
    f = feeds[0]
    # Trimestral: el dato es mensual y el MIVHED lo publica por trimestre (ficha de datos.gob.do).
    assert (f.clave, f.cadence, f.axis) == (CLAVE_DEL_FEED, "quarterly", "construction_intel")
    assert set(f.series) == {SERIE_PERMISOS, SERIE_SQM}
    assert f.emisor_en_prosa == "el MIVHED"
    assert {d.clave_de_contexto for d in f.dimensiones} == {
        "metros_cuadrados_licenciados_por_provincia_del_mes",
        "metros_cuadrados_licenciados_por_tipologia_del_mes",
        "metros_cuadrados_licenciados_por_municipio_del_mes",
        "metros_cuadrados_licenciados_por_barrio_o_sector_del_mes"}
    assert f.fuente is not None and f.fuente.license, "el feed viaja sin licencia del emisor"
    assert "indicador líder" in f.nota


def test_la_declaracion_no_exige_base_de_datos():
    """El guard de títulos y el catálogo instancian productos sin sesión."""
    f = ConstructionProduct(None).feeds_mensuales()[0]
    assert f.clave == CLAVE_DEL_FEED and f.ultima_descarga is None


# ── Control POSITIVO ─────────────────────────────────────────────────────────────

def test_con_feed_fresco_el_bloque_TRAE_el_movimiento_del_mes(db, icc):
    ultimo = _feed_fresco(db)
    b, feeds = _bloque(db)
    assert b["periodo"] == ultimo and b["no_publicables"] == []
    lectura = b["lecturas"][0]
    permisos = next(s for s in lectura["series"] if s["serie"] == SERIE_PERMISOS)
    assert permisos["linea_base"]["tipo"] == "mismo_periodo_del_anio_anterior"
    assert permisos["movimiento"]["direccion"] == "sube"
    assert permisos["movimiento"]["variacion_pct"] == pytest.approx(30.0)
    # El microdato que el agregado anual descartaba.
    dims = lectura["dimensiones"]
    assert dims["metros_cuadrados_licenciados_por_provincia_del_mes"][0]["provincia"] == "SANTO DOMINGO"
    assert dims["metros_cuadrados_licenciados_por_tipologia_del_mes"][0]["tipologia"] == "APARTAMENTOS"
    ctx = contexto_del_delta(b, feeds, "2025")
    assert ctx["lecturas_por_emisor"][0]["emisor_del_movimiento"] == "MIVHED (datos.gob.do)"
    assert "MIVHED" in ctx["source"]


@pytest.mark.asyncio
async def test_la_seccion_se_ENSAMBLA_se_ordena_y_llega_al_documento(db, icc, monkeypatch):
    """Una sección fuera del manifiesto que no entra al orden NO existe para el cliente: la
    app dibuja el orden."""
    _feed_fresco(db)
    _motor(monkeypatch)
    content = await assemble_product_content(ConstructionProduct(db), ProductTier.deep_dive,
                                             period="2025")
    assert SECCION_DELTA in content.narratives
    assert SECCION_DELTA in content.section_order
    assert content.secciones_omitidas == ()
    declaradas = ConstructionProduct(db).product_manifest().require_level(
        ProductTier.deep_dive).sections
    assert set(declaradas) < set(content.section_order)


def test_la_seccion_tiene_TITULO_en_el_documento(db):
    """Sin entrada en el mapa de títulos, el render imprime la clave técnica."""
    from modules.construction_intel.products import _SECTION_TITLES

    assert _SECTION_TITLES.get(SECCION_DELTA)


# ── Control NEGATIVO: sin feed, el informe sale como antes ───────────────────────

def test_SIN_observaciones_la_seccion_NO_aparece(db, icc, monkeypatch):
    """No aparece vacía: no aparece. Una sección presente y sin contenido se lee como que el
    eje no tuvo nada que decir, que es una afirmación y es falsa."""
    _motor(monkeypatch)
    content = _entregado(db)
    declaradas = ConstructionProduct(db).product_manifest().require_level(
        ProductTier.deep_dive).sections
    assert SECCION_DELTA not in content.narratives
    assert SECCION_DELTA not in content.section_order
    assert content.secciones_omitidas == ()
    assert set(declaradas) <= set(content.narratives)


# ── El AHORRO: un mes nuevo cuesta UNA llamada y el índice sigue en caché ────────

def test_un_mes_nuevo_del_feed_cuesta_UNA_llamada_y_el_informe_del_indice_es_HIT(
        db, icc, monkeypatch):
    """La prueba de la Fase 1. Antes, el delta iba al payload y cada mes regeneraba el Deep
    Dive entero: N secciones del índice + 1. Ahora, 1."""
    from shared.narrative.formato import mes_largo_es, mes_siguiente

    ultimo = _feed_fresco(db)
    llamadas = _motor(monkeypatch)
    _entregado(db)
    del_indice = [t for t in llamadas if t != "feed_delta"]
    assert llamadas.count("feed_delta") == 1 and len(del_indice) >= 2
    huella_antes = db.query(ProductReportCache).one().fingerprint

    llamadas.clear()
    _entregado(db)
    assert llamadas == [], "una segunda entrega sin cambios volvió a generar"

    # Llega el mes siguiente del MIVHED.
    llamadas.clear()
    obs.upsert(db, sector_key="construction", series_code=SERIE_PERMISOS,
               period=mes_siguiente(ultimo), value=150.0, unit="conteo", frequency="monthly",
               nature="flow", source="MIVHED")
    obs.upsert(db, sector_key="construction", series_code=SERIE_SQM,
               period=mes_siguiente(ultimo), value=70_000.0, unit="m2", frequency="monthly",
               nature="flow", source="MIVHED")
    db.commit()
    content = _entregado(db)
    assert llamadas == ["feed_delta"], f"un mes nuevo del feed costó {llamadas}"
    assert db.query(ProductReportCache).one().fingerprint == huella_antes, (
        "el feed movió la huella del informe del índice: el ahorro no existe")
    assert content.narratives[SECCION_DELTA].startswith(
        f"Movimiento de {mes_largo_es(mes_siguiente(ultimo))}.")
    assert db.query(FeedDeltaCache).count() == 2


def test_el_delta_NO_entra_al_payload(db, icc):
    """Si entrara, la huella del informe rotaría con cada mes del feed."""
    _feed_fresco(db)
    payload = ConstructionProduct(db).snapshot(ProductTier.deep_dive, "2025").payload
    assert SECCION_DELTA not in payload


def test_el_modulo_ya_NO_narra_el_delta_por_su_cuenta():
    """Dos mecanismos para la misma sección es cómo uno se queda atrás."""
    import inspect

    import modules.construction_intel.products as m

    src = inspect.getsource(m)
    for viejo in ("_delta_mensual", "_narrar_delta", "_encabezado_del_movimiento",
                  "construction_delta_context", "completar_en_vivo"):
        assert viejo not in src, f"«{viejo}» sigue en el módulo"


# ── Fuente ATRASADA: se publica con el mes nombrado y la declaración al lado ─────
#
# Decisión del dueño (2026-09-10). La lectura nombra su período —no se hace pasar por el mes
# en curso— y que el emisor lleve semanas sin publicar es en sí información.

def test_con_la_fuente_ATRASADA_el_bloque_SE_PUBLICA_con_su_delta(db, icc):
    _feed_atrasado(db)
    b, _ = _bloque(db)
    assert b["no_publicables"] == [], "la fuente atrasada volvió a vetar la sección"
    lectura = b["lecturas"][0]
    assert lectura["periodo"] == "2023-12" and lectura["series"]
    assert lectura["fuente_del_feed"]["al_dia"] is False
    assert lectura["fuente_del_feed"]["ultima_publicacion"] == "2023-12-20"


def test_el_texto_NOMBRA_el_mes_y_DECLARA_la_ultima_publicacion(db, icc, monkeypatch):
    """La MISMA frase que servía el módulo antes de la migración."""
    _feed_atrasado(db)
    _motor(monkeypatch)
    texto = _entregado(db).narratives[SECCION_DELTA]
    assert texto.startswith("Movimiento de diciembre de 2023.")
    assert "Es la última edición que publicó el MIVHED, el 20 de diciembre de 2023" in texto
    assert "la de enero de 2024, de cadencia trimestral" in texto
    assert f"no figuraba en la fuente en nuestra última descarga, del {_hoy_utc_largo()}." in texto
    assert "a la fecha de este informe" not in texto
    for clave in ("monthly", "quarterly", "annual"):
        assert clave not in texto, f"la clave de máquina «{clave}» llegó al informe"


def test_la_fecha_declarada_se_COMPUTA_de_la_publicacion_y_no_esta_escrita(db, icc, monkeypatch):
    _feed_atrasado(db, publicado_el="2024-01-05")
    _motor(monkeypatch)
    texto = _entregado(db).narratives[SECCION_DELTA]
    assert "el 5 de enero de 2024" in texto and "20 de diciembre" not in texto


def test_con_la_fuente_AL_DIA_se_nombra_el_mes_SIN_declaracion(db, icc, monkeypatch):
    from shared.narrative.formato import mes_largo_es

    ultimo = _feed_fresco(db)
    _motor(monkeypatch)
    texto = _entregado(db).narratives[SECCION_DELTA]
    assert texto.startswith(f"Movimiento de {mes_largo_es(ultimo)}.")
    assert "no figuraba en la fuente" not in texto


def test_sin_fecha_de_publicacion_la_declaracion_NO_inventa_una(db, icc, monkeypatch):
    _feed_atrasado(db, publicado_el=None)
    _motor(monkeypatch)
    texto = _entregado(db).narratives[SECCION_DELTA]
    assert "Es la última edición disponible de el MIVHED" in texto or \
        "última edición disponible" in texto
    assert "la de enero de 2024" in texto
    assert "publicó el MIVHED, el" not in texto


def test_una_verificacion_de_la_SONDA_mas_nueva_que_la_ingesta_es_la_que_se_cita(
        db, icc, monkeypatch):
    """La sonda baja el CSV a diario sin ingerir: su fecha es una descarga, y si es la más
    nueva es la que el lector necesita. Y como es lo VIVO, cambia SIN regenerar."""
    from datetime import datetime, timedelta, timezone

    from modules.construction_intel.service import guardar_verificacion
    from shared.narrative.formato import fecha_larga_es

    _feed_atrasado(db)
    llamadas = _motor(monkeypatch)
    _entregado(db)
    manana = datetime.now(timezone.utc) + timedelta(days=1)
    guardar_verificacion(db, {"verificado_el": manana.isoformat()})
    llamadas.clear()
    texto = _entregado(db).narratives[SECCION_DELTA]
    assert f"del {fecha_larga_es(manana.date().isoformat())}." in texto
    assert llamadas == [], "la fecha de la sonda regeneró el delta: lo vivo entró a la huella"


# ── Frescura INDETERMINADA: ahí sí se veta, y se dice por qué ────────────────────

def test_con_frescura_INDETERMINADA_lo_vetado_se_ESCRIBE_con_su_causa(db, icc, monkeypatch):
    import shared.operations.fuentes_congeladas as fc

    _feed_fresco(db)
    llamadas = _motor(monkeypatch)
    monkeypatch.setattr(fc, "veredicto_de_la_fuente", lambda db, *, sector_key, clave: fc.Veredicto(
        eje=sector_key, estado=fc.INDETERMINADA, cadencia="monthly", motivo="x", clave=clave))
    texto = _entregado(db).narratives[SECCION_DELTA]
    assert texto.startswith("No se publica") and "no depende de este feed" in texto
    assert "feed_delta" not in llamadas
    for clave in ("monthly", "quarterly", "annual"):
        assert clave not in texto


# ── La invariante dura: el índice no se mueve ────────────────────────────────────

def test_el_feed_NO_toca_el_ICC_persistido(db, icc):
    antes = [(r.period, r.icc_score, r.permits, r.sqm, r.coverage)
             for r in db.query(ConstructionScore).all()]
    _feed_fresco(db)
    despues = [(r.period, r.icc_score, r.permits, r.sqm, r.coverage)
               for r in db.query(ConstructionScore).all()]
    assert antes == despues


def test_la_ingesta_es_IDEMPOTENTE(db):
    ingest_observaciones_mensuales(db, {"periodos": _mes("2025-01", 10, 100.0), "sin_mes": 0})
    n1 = obs.contar(db, sector_key="construction")
    ingest_observaciones_mensuales(db, {"periodos": _mes("2025-01", 10, 100.0), "sin_mes": 0})
    assert obs.contar(db, sector_key="construction") == n1
    ingest_observaciones_mensuales(db, {"periodos": _mes("2025-02", 20, 200.0), "sin_mes": 0})
    periodos = {r.period for r in obs.serie(db, sector_key="construction",
                                            series_code=SERIE_SQM)}
    assert periodos == {"2025-02"}


def test_los_permisos_SIN_MES_se_declaran_y_no_se_reparten(db):
    r = ingest_observaciones_mensuales(
        db, {"periodos": _mes("2025-01", 10, 100.0), "sin_mes": 7})
    assert r["sin_mes"] == 7


# ── §5.1: el feed es otra FUENTE, y no toca el gate del índice ───────────────────

def test_el_feed_NO_mueve_el_readiness_del_eje(db, icc):
    from shared.products.readiness import compute_readiness

    p = ConstructionProduct(db)
    antes = compute_readiness(p, ProductTier.deep_dive)["readiness"]
    _feed_fresco(db)
    p2 = ConstructionProduct(db)
    assert compute_readiness(p2, ProductTier.deep_dive)["readiness"] == pytest.approx(antes)
    assert p2.data_signals().cadence == "annual", "el índice dejó de declararse anual"


def test_el_feed_se_declara_como_SENAL_DE_FUENTE_con_su_propia_cadencia(db, icc):
    ultimo = _feed_fresco(db)
    senales = ConstructionProduct(db).senales_de_fuentes()
    assert len(senales) == 1
    s = senales[0]
    assert (s.clave, s.cadence) == (CLAVE_DEL_FEED, "quarterly")
    assert ultimo in s.detalle


def test_el_sensor_juzga_las_DOS_fuentes_del_eje_por_separado(db, icc):
    from shared.operations.fuentes_congeladas import leer_fuentes_de_los_ejes

    periodos = {f"2023-{m:02d}": {"permits": 100, "sqm": 50_000.0} for m in range(1, 13)}
    ingest_observaciones_mensuales(db, {"periodos": periodos, "sin_mes": 0})
    filas = {v.id: v for v in leer_fuentes_de_los_ejes(db) if v.eje == "construction"}
    assert set(filas) == {"construction", f"construction:{CLAVE_DEL_FEED}"}
    assert filas["construction"].cadencia == "annual"
    assert filas[f"construction:{CLAVE_DEL_FEED}"].cadencia == "quarterly"


def test_la_metodologia_NOMBRA_las_dos_cadencias(db, icc):
    from shared.products.report_sections import standard_sections

    _feed_fresco(db)
    met = standard_sections(ConstructionProduct(db), ProductTier.deep_dive,
                            as_of=None).get("std_methodology", "")
    assert "**Cadencia:** anual" in met
    # El feed del MIVHED es TRIMESTRAL: su ficha en datos.gob.do lo declara así.
    assert "Fuentes sub-anuales" in met and "MIVHED · licencias emitidas (trimestral)" in met
