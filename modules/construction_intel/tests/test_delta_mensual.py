"""La sección del movimiento del mes: cuándo aparece, cuándo NO, y qué no puede tocar.

El criterio de terminado de la rebanada vertical vive acá:

* **control positivo** — con feed fresco, la sección existe, trae el delta computado y su
  desglose por provincia y tipología;
* **control negativo 1** — sin observaciones, el informe sale IDÉNTICO a como salía y la
  sección **no aparece** (en vez de aparecer vacía);
* **control negativo 2** — con la fuente congelada, la sección **no publica** y **dice por
  qué**;
* **invariante dura** — el ICC anual persistido no se mueve ni un decimal por este trabajo.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


# ── Control POSITIVO ─────────────────────────────────────────────────────────────

def test_con_feed_fresco_la_seccion_TRAE_el_movimiento_del_mes(db, icc):
    ultimo = _feed_fresco(db)
    payload = ConstructionProduct(db).snapshot(ProductTier.deep_dive, "2025").payload

    d = payload["delta_mensual"]
    assert d["periodo"] == ultimo
    assert "no_publicable" not in d
    permisos = next(s for s in d["series"] if s["serie"] == SERIE_PERMISOS)
    assert permisos["linea_base"]["tipo"] == "mismo_periodo_del_anio_anterior"
    assert permisos["movimiento"]["direccion"] == "sube"
    assert permisos["movimiento"]["variacion_pct"] == pytest.approx(30.0)
    # El microdato que el agregado anual descartaba.
    assert d["provincias"][0]["provincia"] == "SANTO DOMINGO"
    assert d["tipologias"][0]["tipologia"] == "APARTAMENTOS"


@pytest.mark.asyncio
async def test_la_seccion_se_ORDENA_y_llega_al_documento(db, icc):
    """Una sección fuera del manifiesto que no entra al orden NO existe para el cliente: la
    app dibuja el orden. Le pasó al año-por-trimestres, con el PDF saliendo completo."""
    from shared.products.assembler import orden_de_secciones

    _feed_fresco(db)
    p = ConstructionProduct(db)
    snap = p.snapshot(ProductTier.deep_dive, "2025")
    declaradas = p.product_manifest().require_level(ProductTier.deep_dive).sections
    narr = await p.narratives(ProductTier.deep_dive, snap)

    assert "delta_mensual" in narr
    assert "delta_mensual" in orden_de_secciones(declaradas, narr, {})


def test_la_seccion_tiene_TITULO_en_el_documento(db):
    """Sin entrada en el mapa de títulos, el render imprime la clave técnica."""
    from modules.construction_intel.products import _SECTION_TITLES

    assert _SECTION_TITLES.get("delta_mensual")


# ── Control NEGATIVO 1: sin feed, el informe sale como antes ─────────────────────

def test_SIN_observaciones_la_seccion_NO_aparece(db, icc):
    """No aparece vacía: no aparece. Una sección presente y sin contenido se lee como que el
    eje no tuvo nada que decir, que es una afirmación y es falsa."""
    payload = ConstructionProduct(db).snapshot(ProductTier.deep_dive, "2025").payload
    assert "delta_mensual" not in payload


@pytest.mark.asyncio
async def test_SIN_observaciones_las_secciones_son_EXACTAMENTE_las_de_antes(db, icc):
    p = ConstructionProduct(db)
    snap = p.snapshot(ProductTier.deep_dive, "2025")
    narr = await p.narratives(ProductTier.deep_dive, snap)
    declaradas = p.product_manifest().require_level(ProductTier.deep_dive).sections
    assert set(narr) == set(declaradas), "el informe sin feed cambió de secciones"


# ── Control NEGATIVO 2: la frescura VETA, y lo vetado se DECLARA ─────────────────

def test_con_la_fuente_CONGELADA_la_seccion_no_publica_y_dice_por_que(db, icc):
    """Publicar «el último mes» de un feed muerto describiría un mes viejo con cara de
    actual, que en un documento fechado es una afirmación falsa."""
    periodos = {}
    for m in range(1, 13):
        periodos.update(_mes(f"2022-{m:02d}", 100, 50_000.0))
    for m in range(1, 13):
        periodos.update(_mes(f"2023-{m:02d}", 130, 65_000.0))
    ingest_observaciones_mensuales(db, {"periodos": periodos, "sin_mes": 0})

    d = ConstructionProduct(db).snapshot(ProductTier.deep_dive, "2025").payload["delta_mensual"]
    assert "no_publicable" in d
    assert "series" not in d
    assert d["ultimo_periodo_observado"] == "2023-12"


@pytest.mark.asyncio
async def test_lo_vetado_se_ESCRIBE_en_el_informe_con_su_causa(db, icc):
    """Un bloque que se esfuma se lee como que el eje no tiene nada que decir este mes."""
    periodos = {f"2023-{m:02d}": {"permits": 100, "sqm": 50_000.0} for m in range(1, 13)}
    ingest_observaciones_mensuales(db, {"periodos": periodos, "sin_mes": 0})
    p = ConstructionProduct(db)
    snap = p.snapshot(ProductTier.deep_dive, "2025")
    texto = (await p.narratives(ProductTier.deep_dive, snap))["delta_mensual"]

    assert "No se publica" in texto
    assert "fuente" in texto.lower() and "días" in texto
    assert "no depende de este feed" in texto, (
        "el texto no aclara que el índice anual sigue en pie")


# ── La invariante dura: el índice no se mueve ────────────────────────────────────

def test_el_feed_NO_toca_el_ICC_persistido(db, icc):
    """Es la propiedad que hace segura toda la rebanada: el índice publicado no cambia."""
    antes = [(r.period, r.icc_score, r.permits, r.sqm, r.coverage)
             for r in db.query(ConstructionScore).all()]
    _feed_fresco(db)
    despues = [(r.period, r.icc_score, r.permits, r.sqm, r.coverage)
               for r in db.query(ConstructionScore).all()]
    assert antes == despues


def test_la_ingesta_es_IDEMPOTENTE(db):
    """El CSV del MIVHED es un archivo completo en cada descarga, no un incremento: un
    upsert fila a fila dejaría vivos los meses que el emisor haya retirado."""
    ingest_observaciones_mensuales(db, {"periodos": _mes("2025-01", 10, 100.0), "sin_mes": 0})
    n1 = obs.contar(db, sector_key="construction")
    ingest_observaciones_mensuales(db, {"periodos": _mes("2025-01", 10, 100.0), "sin_mes": 0})
    assert obs.contar(db, sector_key="construction") == n1

    # Y un mes que el emisor RETIRA desaparece, en vez de sobrevivir sin que nadie lo note.
    ingest_observaciones_mensuales(db, {"periodos": _mes("2025-02", 20, 200.0), "sin_mes": 0})
    assert obs.serie(db, sector_key="construction", series_code=SERIE_PERMISOS) != []
    periodos = {r.period for r in obs.serie(db, sector_key="construction",
                                            series_code=SERIE_SQM)}
    assert periodos == {"2025-02"}


def test_los_permisos_SIN_MES_se_declaran_y_no_se_reparten(db):
    r = ingest_observaciones_mensuales(
        db, {"periodos": _mes("2025-01", 10, 100.0), "sin_mes": 7})
    assert r["sin_mes"] == 7


# ── §5.1: el feed es otra FUENTE, y no toca el gate del índice ───────────────────

def test_el_feed_NO_mueve_el_readiness_del_eje(db, icc):
    """La decisión del §5.1, hecha comprobable.

    Si el feed se declarara en `DataHealth.cadence` como `monthly`, el índice anual —con dato
    del cierre— caería a factor de frescura 0 y perdería 0,300 de readiness contra un umbral
    de activación de 0,85: como el máximo es 1,0, el eje dejaría de publicarse en TODOS sus
    niveles. Por eso el feed viaja como fuente aparte y no como otra cadencia del mismo eje.
    """
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
    assert (s.clave, s.cadence) == (CLAVE_DEL_FEED, "monthly")
    assert ultimo in s.detalle


def test_el_sensor_juzga_las_DOS_fuentes_del_eje_por_separado(db, icc):
    """El índice anual al día y el feed mensual congelado son dos hechos, y un veredicto por
    eje obligaba a elegir cuál contar."""
    from shared.operations.fuentes_congeladas import leer_fuentes_de_los_ejes

    periodos = {f"2023-{m:02d}": {"permits": 100, "sqm": 50_000.0} for m in range(1, 13)}
    ingest_observaciones_mensuales(db, {"periodos": periodos, "sin_mes": 0})
    filas = {v.id: v for v in leer_fuentes_de_los_ejes(db) if v.eje == "construction"}

    assert set(filas) == {"construction", f"construction:{CLAVE_DEL_FEED}"}
    assert filas["construction"].cadencia == "annual"
    assert filas[f"construction:{CLAVE_DEL_FEED}"].cadencia == "monthly"


# ── Lo que el CLIENTE lee ────────────────────────────────────────────────────────

def test_la_metodologia_NOMBRA_las_dos_cadencias(db, icc):
    """Con la línea sola —«Cadencia: anual»— el documento diría «anual» en una página y
    traería un mes en la otra: se contradice solo."""
    from shared.products.report_sections import standard_sections

    _feed_fresco(db)
    met = standard_sections(ConstructionProduct(db), ProductTier.deep_dive,
                            as_of=None).get("std_methodology", "")
    assert "**Cadencia:** anual" in met
    assert "Fuentes sub-anuales" in met and "mensual" in met


@pytest.mark.asyncio
async def test_el_texto_del_veto_no_arrastra_la_clave_de_MAQUINA_de_la_cadencia(db, icc):
    """`cadence` es una clave que elige umbrales, no una palabra en español. Pegar el motivo
    del panel en el informe publicaba «su fuente (monthly)» en un documento en castellano —
    el mismo defecto que obligó a traducir la cadencia en la metodología."""
    periodos = {f"2023-{m:02d}": {"permits": 100, "sqm": 50_000.0} for m in range(1, 13)}
    ingest_observaciones_mensuales(db, {"periodos": periodos, "sin_mes": 0})
    p = ConstructionProduct(db)
    texto = (await p.narratives(ProductTier.deep_dive,
                                p.snapshot(ProductTier.deep_dive, "2025")))["delta_mensual"]

    for clave in ("monthly", "quarterly", "annual"):
        assert clave not in texto, f"la clave de máquina «{clave}» llegó al informe"
    assert "mensual" in texto
