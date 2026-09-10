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


async def _entregado(p, tier=ProductTier.deep_dive):
    """El texto como lo ENTREGA la plataforma: lo cacheable más lo que se completa en vivo.

    Desde que la fecha de la última descarga se agrega después de la caché, `narratives()`
    devuelve solo lo del modelo; probar sobre `narratives()` a secas prueba lo que se guarda,
    no lo que se sirve.
    """
    snap = p.snapshot(tier, "2025")
    return p.completar_en_vivo(tier, snap, await p.narratives(tier, snap))


def _hoy_utc_largo():
    """La fecha de la última descarga en estos tests es la de la ingesta, sellada por la base
    en UTC. Con la fecha LOCAL el test fallaría entre la medianoche UTC y la de Santo Domingo."""
    from datetime import datetime, timezone

    from shared.narrative.formato import fecha_larga_es

    return fecha_larga_es(datetime.now(timezone.utc).date().isoformat())


# ── Fuente ATRASADA: se publica con el mes nombrado y la declaración al lado ─────
#
# Decisión del dueño (2026-09-10). El primer diseño vetaba la sección; se cambió porque la
# lectura nombra su período —no se hace pasar por el mes en curso— y que el emisor lleve
# semanas sin publicar es en sí información que el lector quiere.

def _feed_atrasado(db, publicado_el="2023-12-20"):
    periodos = {}
    for m in range(1, 13):
        periodos.update(_mes(f"2022-{m:02d}", 100, 50_000.0))
    for m in range(1, 13):
        periodos.update(_mes(f"2023-{m:02d}", 130, 65_000.0))
    ingest_observaciones_mensuales(
        db, {"periodos": periodos, "sin_mes": 0, "publicado_el": publicado_el})


def test_con_la_fuente_ATRASADA_la_seccion_SE_PUBLICA_con_su_delta(db, icc):
    _feed_atrasado(db)
    d = ConstructionProduct(db).snapshot(ProductTier.deep_dive, "2025").payload["delta_mensual"]
    assert "no_publicable" not in d, "la fuente atrasada volvió a vetar la sección"
    assert d["periodo"] == "2023-12"
    assert d["series"], "se publicó la sección sin la lectura"
    assert d["fuente_del_feed"]["al_dia"] is False
    assert d["fuente_del_feed"]["ultima_publicacion"] == "2023-12-20"


@pytest.mark.asyncio
async def test_el_texto_NOMBRA_el_mes_y_DECLARA_la_ultima_publicacion(db, icc):
    _feed_atrasado(db)
    texto = (await _entregado(ConstructionProduct(db)))["delta_mensual"]
    assert texto.startswith("Movimiento de diciembre de 2023.")
    assert "el 20 de diciembre de 2023" in texto
    assert "la de enero de 2024" in texto
    assert f"no figuraba en la fuente en nuestra última descarga, del {_hoy_utc_largo()}." in texto


@pytest.mark.asyncio
async def test_la_fecha_declarada_se_COMPUTA_de_la_publicacion_y_no_esta_escrita(db, icc):
    """Una fecha transcrita se desincroniza con la primera edición nueva. Con otra fecha de
    publicación en el dato, el texto tiene que decir OTRA fecha."""
    _feed_atrasado(db, publicado_el="2024-01-05")
    texto = (await _entregado(ConstructionProduct(db)))["delta_mensual"]
    assert "el 5 de enero de 2024" in texto
    assert "20 de diciembre" not in texto


@pytest.mark.asyncio
async def test_con_la_fuente_AL_DIA_se_nombra_el_mes_SIN_declaracion(db, icc):
    """La declaración de atraso no puede aparecer cuando no hay atraso."""
    ultimo = _feed_fresco(db)
    texto = (await _entregado(ConstructionProduct(db)))["delta_mensual"]
    from shared.narrative.formato import mes_largo_es

    assert texto.startswith(f"Movimiento de {mes_largo_es(ultimo)}.")
    assert "no figuraba en la fuente" not in texto


@pytest.mark.asyncio
async def test_sin_fecha_de_publicacion_la_declaracion_NO_inventa_una(db, icc):
    """Si el portal no declaró la fecha, se dice lo que se sabe: el mes que falta."""
    _feed_atrasado(db, publicado_el=None)
    texto = (await _entregado(ConstructionProduct(db)))["delta_mensual"]
    assert "última edición disponible" in texto
    assert "la de enero de 2024" in texto
    assert " el 20 de" not in texto and "publicó el MIVHED, el" not in texto


# ── Frescura INDETERMINADA: ahí sí se veta, y se dice por qué ────────────────────

def _forzar_indeterminada(monkeypatch):
    import shared.operations.fuentes_congeladas as fc

    def indeterminada(db, *, sector_key, clave):
        return fc.Veredicto(eje=sector_key, estado=fc.INDETERMINADA, cadencia="monthly",
                            motivo="no se pudo medir", clave=clave)

    monkeypatch.setattr(fc, "veredicto_de_la_fuente", indeterminada)


def test_con_frescura_INDETERMINADA_la_seccion_no_publica(db, icc, monkeypatch):
    """Sin saber cuándo publicó la fuente no hay declaración honesta que poner al lado, y
    publicar sin ella presentaría la lectura como vigente sin saberlo."""
    _feed_fresco(db)
    _forzar_indeterminada(monkeypatch)
    d = ConstructionProduct(db).snapshot(ProductTier.deep_dive, "2025").payload["delta_mensual"]
    assert "no_publicable" in d and "series" not in d


@pytest.mark.asyncio
async def test_lo_vetado_se_ESCRIBE_con_su_causa_y_sin_claves_de_maquina(db, icc, monkeypatch):
    _feed_fresco(db)
    _forzar_indeterminada(monkeypatch)
    texto = (await _entregado(ConstructionProduct(db)))["delta_mensual"]
    assert texto.startswith("No se publica")
    assert "no depende de este feed" in texto
    for clave in ("monthly", "quarterly", "annual"):
        assert clave not in texto


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
async def test_la_declaracion_no_arrastra_la_clave_de_MAQUINA_de_la_cadencia(db, icc):
    """`cadence` es una clave que elige umbrales, no una palabra en español: publicar «su
    fuente (monthly)» en un documento en castellano es el defecto que obligó a traducir la
    cadencia en la metodología."""
    _feed_atrasado(db)
    texto = (await _entregado(ConstructionProduct(db)))["delta_mensual"]
    for clave in ("monthly", "quarterly", "annual"):
        assert clave not in texto, f"la clave de máquina «{clave}» llegó al informe"
    assert "mensual" in texto


# ── Un tipo nuevo se registra en TODAS sus superficies ───────────────────────────

@pytest.mark.parametrize("lang", ["es", "en", "fr"])
def test_toda_seccion_del_producto_tiene_TITULO_en_la_app(lang):
    """La app titula las secciones con `platform.catalog.section.<clave>` y, sin entrada, cae
    a la clave con espacios: el informe mostraba «delta mensual» mientras el PDF decía otra
    cosa. Dos superficies en desacuerdo, y ninguna fallaba."""
    import json
    import pathlib

    from modules.construction_intel.products import _SECTION_TITLES

    raiz = pathlib.Path(__file__).resolve().parents[3]
    titulos = json.loads((raiz / "frontend" / "src" / "shared" / "i18n" / f"{lang}.json")
                         .read_text(encoding="utf-8"))["platform"]["catalog"]["section"]
    faltan = sorted(k for k in _SECTION_TITLES if k not in titulos)
    assert not faltan, f"{lang}: secciones sin título en la app: {faltan}"


# ── La frase afirma solo lo que se sabe, y se completa DESPUÉS de la caché ───────

@pytest.mark.asyncio
async def test_lo_que_se_CACHEA_no_trae_el_encabezado(db, icc):
    """El encabezado lleva la fecha de la última descarga, que cambia con cada verificación.
    Si quedara en el texto cacheado, esa fecha viajaría congelada en la caché."""
    _feed_atrasado(db)
    p = ConstructionProduct(db)
    cacheable = await p.narratives(ProductTier.deep_dive, p.snapshot(ProductTier.deep_dive, "2025"))
    assert not cacheable["delta_mensual"].startswith("Movimiento de ")


@pytest.mark.asyncio
async def test_la_frase_NUNCA_afirma_el_estado_actual_de_la_fuente(db, icc):
    """«No figura en la fuente a la fecha de este informe» afirmaba el estado ACTUAL de la
    fuente, y lo único verificado era la última descarga: falso durante hasta 30 días si el
    emisor publicaba entre dos syncs."""
    _feed_atrasado(db)
    texto = (await _entregado(ConstructionProduct(db)))["delta_mensual"]
    assert "a la fecha de este informe" not in texto
    assert "no figura en la fuente" not in texto
    assert "en nuestra última descarga" in texto


@pytest.mark.asyncio
async def test_una_verificacion_de_la_SONDA_mas_nueva_que_la_ingesta_es_la_que_se_cita(db, icc):
    """La sonda baja el CSV a diario sin ingerir: su fecha es una descarga, y si es la más
    nueva es la que el lector necesita."""
    from datetime import datetime, timedelta, timezone

    from modules.construction_intel.service import guardar_verificacion
    from shared.narrative.formato import fecha_larga_es

    _feed_atrasado(db)
    manana = datetime.now(timezone.utc) + timedelta(days=1)
    guardar_verificacion(db, {"verificado_el": manana.isoformat()})
    texto = (await _entregado(ConstructionProduct(db)))["delta_mensual"]
    assert f"del {fecha_larga_es(manana.date().isoformat())}." in texto


def test_un_encabezado_VIEJO_grabado_en_la_cache_se_REEMPLAZA_y_no_se_apila(db, icc):
    """La versión anterior grababa el encabezado —con la frase falsa— dentro del texto
    cacheado. Esas filas siguen siendo HIT, porque cambiar products.py no rota la huella: el
    encabezado viejo se reemplaza al servir."""
    _feed_atrasado(db)
    p = ConstructionProduct(db)
    snap = p.snapshot(ProductTier.deep_dive, "2025")
    viejo = ("Movimiento de diciembre de 2023. Es la última edición que publicó el MIVHED, "
             "el 20 de diciembre de 2023; la de enero de 2024, de cadencia mensual, no figura "
             "en la fuente a la fecha de este informe.\n\n## Flujo de licencias\n\ntexto")
    texto = p.completar_en_vivo(ProductTier.deep_dive, snap, {"delta_mensual": viejo})["delta_mensual"]
    assert texto.count("Movimiento de diciembre de 2023.") == 1
    assert "a la fecha de este informe" not in texto
    assert texto.endswith("## Flujo de licencias\n\ntexto")


def test_lo_VETADO_no_se_toca_al_completar(db, icc, monkeypatch):
    _feed_fresco(db)
    _forzar_indeterminada(monkeypatch)
    p = ConstructionProduct(db)
    snap = p.snapshot(ProductTier.deep_dive, "2025")
    veto = {"delta_mensual": "No se publica la lectura del movimiento del mes: x."}
    assert p.completar_en_vivo(ProductTier.deep_dive, snap, dict(veto)) == veto

