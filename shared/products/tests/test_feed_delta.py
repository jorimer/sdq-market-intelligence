"""La sección del delta de feeds, TRANSVERSAL: qué anexa el ensamblador, cuándo NO, y qué cachea.

Criterio de terminado de la Fase 1 del plan de entregables mensuales:

* **control negativo** — con la tabla de observaciones vacía, NINGÚN producto del catálogo
  cambia sus narrativas y la sección no aparece (no aparece vacía);
* **control positivo** — un producto que declara un feed con observaciones recibe la sección,
  con el encabezado vivo y el texto del modelo;
* **el ahorro** — la sección tiene caché PROPIA: dos entregas son UNA llamada, un mes nuevo del
  feed es UNA llamada más, y la huella del informe del índice no se mueve;
* **nunca empeora el informe** — degradación, cifra sin respaldo, afirmación causal y falta
  de presupuesto OMITEN la sección y la LISTAN, sin tumbar el informe ni cachear;
* **la ruta** — el entregable sale por HTTP con la sección en `commercial.sections`.
"""
import asyncio
import json
import inspect
from datetime import date
from typing import Any, Dict, Mapping

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.narrative.claude_engine as ce
from shared.database.base import Base
from shared.narrative import cifras_pendientes
from shared.observations import service as obs
from shared.products.contract import DataHealth, ProductSnapshot, ValidationState
from shared.products.feed_delta import (
    OMITIDA_CAUSAL,
    OMITIDA_DEGRADADA,
    OMITIDA_SIN_RESPALDO,
    OMITIDA_TIEMPO,
    SECCION_DELTA,
    Dimension,
    FeedDeclarado,
    anexar_delta_de_feeds,
    bloque_del_delta,
    contexto_del_delta,
    dias_desde_el_fin_del_periodo,
    encabezado_del_movimiento,
    frases_causales,
    huella_del_delta,
    senales_de_los_feeds,
)
from shared.products.manifest import SectorProductManifest
from shared.products.models import FeedDeltaCache, ProductReportCache
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec

#: Un eje REAL del catálogo bajo el que se registra el producto de prueba: el sensor de fuentes
#: resuelve el producto por el registro, y el registro solo admite claves del catálogo.
EJE = "tourism"
SERIE = "prueba.flujo.conteo"
SERIE_STOCK = "prueba.stock.personas"


@pytest.fixture()
def db():
    import app.main  # noqa: F401 — registra los productos y las tablas reales

    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    try:
        yield s
    finally:
        s.close()


def _feed(**kw: Any) -> FeedDeclarado:
    base: Dict[str, Any] = dict(
        clave="prueba_mensual", etiqueta="Emisor de prueba · conteo",
        emisor="Emisor de prueba", emisor_en_prosa="el Emisor de prueba",
        series=(SERIE,), etiquetas={SERIE: "cosas contadas"}, axis="tourism_intel",
        cadence="monthly", nota="Es un flujo de prueba.")
    base.update(kw)
    return FeedDeclarado(**base)


class _Producto:
    """Un producto mínimo que declara UN feed. Lo que el contrato exige para ensamblar."""

    sector_key = EJE

    def __init__(self, db, feeds=None):
        self._db = db
        self._feeds = feeds if feeds is not None else [_feed()]
        self.generaciones = 0

    def product_manifest(self):
        return SectorProductManifest(sector_key=EJE, display_name="Prueba", levels={
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("resumen",), narrative_templates=("executive_summary",),
                audience="x", cadence="x", price_band="x")})

    def data_signals(self):
        return DataHealth(coverage=1.0, freshness_days=10, cadence="annual", sources=("X",))

    def has_engine(self):
        return True

    def validation_state(self):
        return ValidationState(approved=True, score=0.5, notes="prueba")

    def snapshot(self, tier, period, scope=None):
        return ProductSnapshot(tier=tier, period="2025", payload={"x": 1},
                               entity_name="Sujeto de prueba")

    async def narratives(self, tier, snapshot, lang="es"):
        self.generaciones += 1
        return {"resumen": "Texto del índice."}

    async def render(self, *a, **k):
        return ""

    def feeds_mensuales(self):
        return list(self._feeds)

    def senales_de_fuentes(self):
        return senales_de_los_feeds(self._db, EJE, self.feeds_mensuales())


@pytest.fixture()
def producto(db, monkeypatch):
    """El producto de prueba, REGISTRADO bajo su eje para que el sensor lo encuentre."""
    from shared.products import registry

    p = _Producto(db)
    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: p)
    return p


def _punto(db, period, value, *, code=SERIE, nature="flow", publicado=None, **kw):
    obs.upsert(db, sector_key=EJE, series_code=code, period=period, value=value,
               unit="conteo", frequency="monthly", nature=nature, source="Emisor de prueba",
               published_at=publicado, **kw)
    db.commit()


def _feed_fresco(db, hoy=None):
    """Doce meses del año pasado y los del año en curso hasta el mes recién cerrado."""
    hoy = hoy or date.today()
    fin_anio, fin_mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    for m in range(1, 13):
        _punto(db, f"{fin_anio - 1}-{m:02d}", 100.0)
    for m in range(1, fin_mes + 1):
        _punto(db, f"{fin_anio}-{m:02d}", 130.0)
    return f"{fin_anio}-{fin_mes:02d}"


def _motor(monkeypatch, texto="Las cosas contadas suben frente al mismo mes del año anterior.",
           registrar_cifra=None):
    """Un motor falso que CUENTA llamadas por plantilla y, si se pide, marca una cifra."""
    llamadas = []

    async def fake(**kw):
        llamadas.append(kw)
        if registrar_cifra:
            cifras_pendientes.registrar(kw["template"], [registrar_cifra])
        return ce.NarrativeResult(text=texto)

    monkeypatch.setattr(ce.narrative_engine, "generate", fake)
    return llamadas


def _anexar(p, narr=None, tier=ProductTier.deep_dive, presupuesto=200.0):
    snap = p.snapshot(tier, "2025")
    return asyncio.run(anexar_delta_de_feeds(p, tier, snap, dict(narr or {"resumen": "i"}),
                                             "es", presupuesto_restante_s=presupuesto))


# ── Control NEGATIVO: todo el catálogo, con la tabla vacía ──────────────────────────

def test_con_la_tabla_VACIA_ningun_producto_del_catalogo_cambia(db):
    """La propiedad que hace seguro el mecanismo para los diecisiete ejes. Se cruza contra
    una segunda lectura —que el barrido encontró productos y que al menos uno declara feeds—
    para que un catálogo vacío no pase en verde."""
    from shared.products.registry import PRODUCT_CATALOG, get_product

    revisados, con_feeds = 0, 0
    for entrada in PRODUCT_CATALOG:
        p = get_product(entrada.sector_key, db)
        if p is None:
            continue
        revisados += 1
        if callable(getattr(p, "feeds_mensuales", None)):
            con_feeds += 1
        antes = {"a": "b"}
        snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2025", payload={})
        narr, omitidas = asyncio.run(anexar_delta_de_feeds(
            p, ProductTier.deep_dive, snap, dict(antes), "es", presupuesto_restante_s=200))
        assert narr == antes, f"{entrada.sector_key}: cambió sin observaciones"
        assert omitidas == [], f"{entrada.sector_key}: listó una omisión sin feed"
        assert SECCION_DELTA not in narr
    assert revisados >= 17, revisados
    assert con_feeds >= 1, "ningún producto declara feeds: el negativo no probó nada"


def test_un_producto_SIN_sesion_de_base_sale_intacto(monkeypatch):
    p = _Producto(None)
    snap = p.snapshot(ProductTier.deep_dive, "2025")
    assert asyncio.run(anexar_delta_de_feeds(p, ProductTier.deep_dive, snap, {"a": "b"}, "es")
                       ) == ({"a": "b"}, [])


def test_el_dict_de_narrativas_que_recibe_NO_se_modifica(db, producto, monkeypatch):
    _feed_fresco(db)
    _motor(monkeypatch)
    original = {"resumen": "i"}
    snap = producto.snapshot(ProductTier.deep_dive, "2025")
    asyncio.run(anexar_delta_de_feeds(producto, ProductTier.deep_dive, snap, original, "es"))
    assert original == {"resumen": "i"}


# ── Control POSITIVO ──────────────────────────────────────────────────────────────

def test_con_observaciones_la_seccion_LLEGA_con_encabezado_y_texto(db, producto, monkeypatch):
    ultimo = _feed_fresco(db)
    llamadas = _motor(monkeypatch)
    narr, omitidas = _anexar(producto)

    from shared.narrative.formato import mes_largo_es

    assert omitidas == []
    assert narr[SECCION_DELTA].startswith(f"Movimiento de {mes_largo_es(ultimo)}.")
    assert narr[SECCION_DELTA].endswith("suben frente al mismo mes del año anterior.")
    assert narr["resumen"] == "i", "la sección pisó otra narrativa"
    assert [k["template"] for k in llamadas] == ["feed_delta"]
    assert llamadas[0]["axis"] == "tourism_intel" and llamadas[0]["mode"] == "standard"


def test_el_contexto_lleva_las_relaciones_RESUELTAS_y_el_sujeto_en_cada_clave(db, producto):
    ultimo = _feed_fresco(db)
    b = bloque_del_delta(db, EJE, producto.feeds_mensuales())
    ctx = contexto_del_delta(b, producto.feeds_mensuales(), "2025")
    lectura = ctx["lecturas_por_emisor"][0]
    serie = lectura["series_del_periodo"][0]
    assert lectura["periodo_del_movimiento"] == ultimo
    assert serie["movimiento"]["direccion"] == "sube"
    assert serie["movimiento"]["variacion_pct"] == pytest.approx(30.0)
    assert serie["linea_base"]["tipo"] == "mismo_periodo_del_anio_anterior"
    assert lectura["nota_del_emisor"] == "Es un flujo de prueba."
    assert ctx["periodo_del_indice_anual_del_informe"] == "2025"
    assert "regla_de_alcance" in ctx and "NO explica su causa" in ctx["regla_de_alcance"]


def test_las_dimensiones_del_microdato_viajan_con_la_clave_que_declara_el_feed(db, monkeypatch):
    from shared.products import registry

    feed = _feed(dimensiones=(Dimension("cosas_contadas_por_provincia_del_mes", SERIE,
                                        "provincia"),))
    p = _Producto(db, [feed])
    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: p)
    ultimo = _feed_fresco(db)
    _punto(db, ultimo, 90.0, provincia="SANTIAGO")
    _punto(db, ultimo, 40.0, provincia="LA VEGA")
    ctx = contexto_del_delta(bloque_del_delta(db, EJE, [feed]), [feed], "2025")
    filas = ctx["lecturas_por_emisor"][0]["cosas_contadas_por_provincia_del_mes"]
    assert [f["provincia"] for f in filas] == ["SANTIAGO", "LA VEGA"]


# ── El AHORRO: caché propia, y el informe del índice no se entera ──────────────────

def test_dos_entregas_son_UNA_llamada_y_un_mes_nuevo_es_UNA_mas(db, producto, monkeypatch):
    ultimo = _feed_fresco(db)
    llamadas = _motor(monkeypatch)
    n1, _ = _anexar(producto)
    n2, _ = _anexar(producto)
    assert len(llamadas) == 1, "la segunda entrega volvió a llamar al modelo"
    assert n1 == n2
    assert db.query(FeedDeltaCache).count() == 1

    # Llega el mes siguiente: UNA llamada más, no seis.
    from shared.narrative.formato import mes_largo_es, mes_siguiente

    _punto(db, mes_siguiente(ultimo), 140.0)
    n3, _ = _anexar(producto)
    assert len(llamadas) == 2
    assert n3[SECCION_DELTA].startswith(f"Movimiento de {mes_largo_es(mes_siguiente(ultimo))}.")
    # Y la fila del mes anterior no se pisa: la clave lleva el período.
    assert {r.feed_period for r in db.query(FeedDeltaCache)} == {ultimo, mes_siguiente(ultimo)}


def test_el_periodo_nuevo_del_feed_NO_mueve_la_huella_del_informe_del_indice(db, producto):
    """El punto de toda la fase: el feed vive fuera del payload, así que la caché del
    informe sigue siendo HIT cuando el feed cambia."""
    from shared.products.assembler import _narrative_fingerprint

    ultimo = _feed_fresco(db)
    snap = producto.snapshot(ProductTier.deep_dive, "2025")
    antes = _narrative_fingerprint(snap.payload, "deep_dive", "es")
    from shared.narrative.formato import mes_siguiente

    _punto(db, mes_siguiente(ultimo), 140.0)
    despues = _narrative_fingerprint(producto.snapshot(ProductTier.deep_dive, "2025").payload,
                                     "deep_dive", "es")
    assert antes == despues


def test_lo_VIVO_no_entra_a_la_huella_ni_al_contexto(db, producto):
    """La fecha de la última descarga cambia a diario con la sonda. Si entrara a la huella,
    el delta se regeneraría cada día sin que el dato cambie — el defecto que #1164 cerró
    para el informe entero, reabierto para la sección."""
    _feed_fresco(db)
    f1 = _feed(ultima_descarga=date(2026, 9, 1))
    f2 = _feed(ultima_descarga=date(2026, 9, 12))
    b = bloque_del_delta(db, EJE, [f1])
    c1, c2 = contexto_del_delta(b, [f1], "2025"), contexto_del_delta(b, [f2], "2025")
    assert c1 == c2
    assert huella_del_delta(c1, "deep_dive", "es") == huella_del_delta(c2, "deep_dive", "es")
    plano = str(c1).lower()
    for prohibida in ("descarga", "verificado"):
        assert prohibida not in plano


def test_la_huella_cubre_la_RECETA_y_el_constructor_del_contexto(monkeypatch):
    """Tocar una plantilla o el archivo que arma el contexto tiene que invalidar el delta:
    la caché no tiene TTL."""
    ctx = {"a": 1}
    antes = huella_del_delta(ctx, "deep_dive", "es")
    original = ce.THIN_TEMPLATES["feed_delta"]
    monkeypatch.setitem(ce.THIN_TEMPLATES, "feed_delta", original + "\nOTRA REGLA.")
    assert huella_del_delta(ctx, "deep_dive", "es") != antes
    monkeypatch.setitem(ce.THIN_TEMPLATES, "feed_delta", original)
    assert huella_del_delta(ctx, "deep_dive", "es") == antes
    import shared.products.feed_delta as fd

    monkeypatch.setattr(fd, "_huella_de_este_archivo", lambda: "otra")
    assert huella_del_delta(ctx, "deep_dive", "es") != antes


def test_el_texto_CACHEADO_no_trae_el_encabezado(db, producto, monkeypatch):
    _feed_fresco(db)
    _motor(monkeypatch)
    _anexar(producto)
    fila = db.query(FeedDeltaCache).one()
    assert not fila.texto.startswith("Movimiento de ")
    assert fila.texto.endswith("suben frente al mismo mes del año anterior.")


def test_el_tier_y_el_idioma_son_claves_DISTINTAS(db, producto, monkeypatch):
    _feed_fresco(db)
    llamadas = _motor(monkeypatch)
    _anexar(producto, tier=ProductTier.deep_dive)
    _anexar(producto, tier=ProductTier.insight)
    snap = producto.snapshot(ProductTier.deep_dive, "2025")
    asyncio.run(anexar_delta_de_feeds(producto, ProductTier.deep_dive, snap, {}, "en"))
    assert len(llamadas) == 3 and db.query(FeedDeltaCache).count() == 3


# ── Nunca empeora el informe: se OMITE y se LISTA ────────────────────────────────

def test_con_el_motor_DEGRADADO_la_seccion_se_omite_se_lista_y_no_se_cachea(db, producto,
                                                                             monkeypatch):
    _feed_fresco(db)
    _motor(monkeypatch, texto=ce.STATIC_FALLBACKS["executive_summary"])
    narr, omitidas = _anexar(producto, {"resumen": "i"})
    assert narr == {"resumen": "i"}
    assert [o["motivo"] for o in omitidas] == [OMITIDA_DEGRADADA]
    assert omitidas[0]["seccion"] == SECCION_DELTA
    assert db.query(FeedDeltaCache).count() == 0


def test_una_cifra_SIN_RESPALDO_omite_el_delta_y_NO_veta_el_informe(db, producto, monkeypatch):
    """El guard corre con cajas PROPIAS: lo que marque en el delta se decide en el delta. Con
    las cajas del ensamblado del índice, una cifra sin respaldo acá vetaría un premium entero
    que no depende del feed."""
    _feed_fresco(db)
    _motor(monkeypatch, registrar_cifra="«45 %» no está en el contexto")
    with cifras_pendientes.acumulando() as caja_del_informe:
        narr, omitidas = _anexar(producto, {"resumen": "i"})
    assert narr == {"resumen": "i"}
    assert [o["motivo"] for o in omitidas] == [OMITIDA_SIN_RESPALDO]
    assert "45 %" in omitidas[0]["detalle"]
    assert caja_del_informe == {}, "el hallazgo del delta se filtró a la caja del informe"
    assert db.query(FeedDeltaCache).count() == 0


def test_una_afirmacion_CAUSAL_omite_la_seccion(db, producto, monkeypatch):
    """§0.3 del plan: la sección lee el movimiento; no explica su causa. El gate no puede
    respaldar una afirmación causal, así que el texto no se publica."""
    _feed_fresco(db)
    _motor(monkeypatch, texto="Las cosas contadas caen 12 % debido a la estacionalidad.")
    narr, omitidas = _anexar(producto, {"resumen": "i"})
    assert SECCION_DELTA not in narr
    assert [o["motivo"] for o in omitidas] == [OMITIDA_CAUSAL]
    assert "debido a" in omitidas[0]["detalle"]
    assert db.query(FeedDeltaCache).count() == 0


@pytest.mark.parametrize("texto, esperado", [
    ("La caída responde a la estacionalidad del verano.", ["responde a"]),
    ("El alza se explica por un permiso grande; debido a eso sube.", ["debido a", "se explica por"]),
    ("Sube 12 % frente a junio del año anterior; la ventana móvil también sube.", []),
    ("Corresponde a la lectura de junio.", []),           # «responde a» dentro de otra palabra
    ("Se debe leer con cautela.", []),
])
def test_el_detector_de_causas_sobre_una_MUESTRA(texto, esperado):
    assert frases_causales(texto) == esperado


def test_la_plantilla_PROHIBE_la_causa_y_las_frases_que_vigila_el_detector():
    plantilla = ce.THIN_TEMPLATES["feed_delta"]
    assert "NO expliques su causa" in plantilla
    for frase in ("debido a", "responde a", "por efecto de", "explicado por"):
        assert frase in plantilla, f"la plantilla no nombra «{frase}» y el detector la veta"


def test_sin_presupuesto_la_seccion_se_omite_por_TIEMPO_sin_llamar_al_modelo(db, producto,
                                                                             monkeypatch):
    _feed_fresco(db)
    llamadas = _motor(monkeypatch)
    narr, omitidas = _anexar(producto, {"resumen": "i"}, presupuesto=5.0)
    assert narr == {"resumen": "i"} and llamadas == []
    assert [o["motivo"] for o in omitidas] == [OMITIDA_TIEMPO]


def test_un_feed_que_REVIENTA_al_leerse_se_lista_y_no_tumba_el_informe(db, producto, monkeypatch):
    _feed_fresco(db)
    import shared.products.feed_delta as fd

    def roto(*a, **k):
        raise RuntimeError("tabla rota")

    monkeypatch.setattr(fd, "bloque_del_delta", roto)
    narr, omitidas = _anexar(producto, {"resumen": "i"})
    assert narr == {"resumen": "i"} and len(omitidas) == 1


# ── Frescura: atrasada publica con el mes nombrado; indeterminada veta ──────────────

def test_con_la_fuente_ATRASADA_se_publica_con_la_declaracion_y_la_fecha_de_descarga(
        db, monkeypatch):
    from shared.products import registry

    feed = _feed(ultima_descarga=date(2026, 9, 12))
    p = _Producto(db, [feed])
    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: p)
    for m in range(1, 13):
        _punto(db, f"2022-{m:02d}", 100.0)
    for m in range(1, 13):
        _punto(db, f"2023-{m:02d}", 130.0, publicado=date(2023, 12, 20))
    _motor(monkeypatch)
    narr, omitidas = _anexar(p)
    texto = narr[SECCION_DELTA]
    assert omitidas == []
    assert texto.startswith("Movimiento de diciembre de 2023. Es la última edición que publicó "
                            "el Emisor de prueba, el 20 de diciembre de 2023; la de enero de "
                            "2024, de cadencia mensual, no figuraba en la fuente en nuestra "
                            "última descarga, del 12 de septiembre de 2026.")
    assert "a la fecha de este informe" not in texto
    for clave in ("monthly", "quarterly", "annual"):
        assert clave not in texto


def test_con_frescura_INDETERMINADA_se_publica_el_VETO_con_su_causa_y_sin_modelo(db, producto,
                                                                                 monkeypatch):
    import shared.operations.fuentes_congeladas as fc

    _feed_fresco(db)
    llamadas = _motor(monkeypatch)
    monkeypatch.setattr(fc, "veredicto_de_la_fuente", lambda db, *, sector_key, clave: fc.Veredicto(
        eje=sector_key, estado=fc.INDETERMINADA, cadencia="monthly", motivo="x", clave=clave))
    narr, omitidas = _anexar(producto)
    assert narr[SECCION_DELTA].startswith("No se publica la lectura del movimiento del mes")
    assert "no depende de este feed" in narr[SECCION_DELTA]
    assert llamadas == [] and omitidas == []


def test_dos_emisores_en_el_mismo_eje_viajan_CADA_UNO_con_su_periodo(db, monkeypatch):
    """Fase 2 en ciernes: la ONE publica con más rezago que el MIVHED. Ni se promedian ni se
    elige uno; y si uno está vetado, se declara al pie mientras el otro se publica."""
    from shared.products import registry

    f_a = _feed()
    f_b = _feed(clave="otro_mensual", etiqueta="Otro emisor · stock", emisor="Otro emisor",
                series=(SERIE_STOCK,), etiquetas={SERIE_STOCK: "personas cubiertas"})
    p = _Producto(db, [f_a, f_b])
    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: p)
    ultimo = _feed_fresco(db)
    _punto(db, "2024-01", 500.0, code=SERIE_STOCK, nature="stock")
    _punto(db, "2024-02", 520.0, code=SERIE_STOCK, nature="stock")
    b = bloque_del_delta(db, EJE, [f_a, f_b])
    assert [x["periodo"] for x in b["lecturas"]] == [ultimo, "2024-02"]
    stock = b["lecturas"][1]["series"][0]
    assert stock["linea_base"]["tipo"] == "ultimo_nivel_publicado"
    enc = encabezado_del_movimiento(b, [f_a, f_b])
    assert enc.startswith("Movimiento de ") and "según Emisor de prueba" in enc
    assert "según Otro emisor" in enc


# ── El sensor y la sección juzgan con el MISMO criterio ─────────────────────────────

def test_la_senal_del_feed_mide_la_antiguedad_del_PERIODO(db, producto):
    ultimo = _feed_fresco(db)
    senales = producto.senales_de_fuentes()
    assert [s.clave for s in senales] == ["prueba_mensual"]
    assert senales[0].freshness_days == dias_desde_el_fin_del_periodo(ultimo)
    assert senales[0].cadence == "monthly"


@pytest.mark.parametrize("periodo, fin", [
    ("2026-06", date(2026, 6, 30)), ("2026-12", date(2026, 12, 31)),
    ("2025-Q4", date(2025, 12, 31)), ("2025-Q1", date(2025, 3, 31)), ("2025", date(2025, 12, 31)),
])
def test_el_fin_del_periodo_se_lee_en_las_tres_formas(periodo, fin):
    from shared.products.feed_delta import fin_del_periodo

    assert fin_del_periodo(periodo) == fin


def test_un_periodo_ilegible_NO_se_adivina():
    from shared.products.feed_delta import fin_del_periodo

    assert fin_del_periodo("2026-13") is None and fin_del_periodo("junio") is None
    assert dias_desde_el_fin_del_periodo("2026-Q5") is None


# ── Superficies: la sección tiene título donde se muestra ───────────────────────────

def test_todo_producto_con_feeds_TITULA_la_seccion_en_su_PDF():
    """Sin la entrada, el PDF imprime «Delta Mensual» con mayúsculas de identificador. El
    guard de la app cubre la otra superficie."""
    import sys

    import app.main  # noqa: F401
    from shared.products.registry import PRODUCT_CATALOG, get_product

    con_feeds = []
    for entrada in PRODUCT_CATALOG:
        p = get_product(entrada.sector_key, None)
        if p is None or not callable(getattr(p, "feeds_mensuales", None)):
            continue
        con_feeds.append(entrada.sector_key)
        titulos = getattr(sys.modules[type(p).__module__], "_SECTION_TITLES", {})
        assert titulos.get(SECCION_DELTA), (
            f"{entrada.sector_key} declara feeds y su PDF no titula «{SECCION_DELTA}»")
    assert "construction" in con_feeds


def test_la_plantilla_vieja_de_construccion_ya_NO_existe():
    """Dos plantillas para la misma sección es cómo una se queda atrás."""
    assert "construction_delta" not in ce.THIN_TEMPLATES
    assert "construction_delta" not in ce.TEMPLATES
    assert "feed_delta" in ce.THIN_TEMPLATES


def test_el_ensamblador_anexa_el_delta_DESPUES_de_los_gates_del_indice_y_ANTES_de_lo_vivo():
    """Se lee el código: antes de los gates, un delta degradado tumbaría un premium; después
    de `completar_en_vivo`, un producto no podría completar la sección; después del glosario,
    sus siglas no se definirían."""
    import shared.products.assembler as asm

    src = inspect.getsource(asm)
    i_gate = src.index("raise NarrativeSinRespaldoError(sin_respaldo)")
    i_delta = src.index("anexar_delta_de_feeds(")
    i_vivo = src.index('getattr(product, "completar_en_vivo", None)')
    i_glosario = src.index("glossary_section(")
    assert i_gate < i_delta < i_vivo < i_glosario


# ── La RUTA: el entregable sale por HTTP con el ensamblador real ────────────────────

def _cliente_http(db, producto, monkeypatch):
    """El router REAL de productos, con el producto de prueba activado y un usuario enterprise."""
    from shared.auth.dependencies import get_current_user
    from shared.database.session import get_db
    from shared.products import router as prod_router
    from shared.products.access import AccessTier
    from shared.products.models import ProductActivation

    db.add(ProductActivation(sector_key=EJE, tier="deep_dive", is_active=True))
    db.commit()
    monkeypatch.setattr(prod_router, "get_product", lambda sector, db: producto)

    class _U:
        tier = AccessTier.enterprise
        id = "u1"

    app = FastAPI()
    app.include_router(prod_router.router, prefix="/api/v1/products")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U()
    return TestClient(app)


def _informe_por_http(db, producto, monkeypatch) -> Dict[str, Any]:
    r = _cliente_http(db, producto, monkeypatch).get(
        f"/api/v1/products/{EJE}/deep_dive/report?scope=x")
    assert r.status_code == 200, r.text
    return r.json()


def test_por_HTTP_el_informe_trae_la_seccion_en_el_orden_y_lista_lo_omitido(db, producto,
                                                                             monkeypatch):
    """Un test del motor no es un test de la ruta. Acá solo se falsea el MODELO; el
    ensamblador, la caché y el orden son los reales."""
    _feed_fresco(db)
    _motor(monkeypatch)
    c = _cliente_http(db, producto, monkeypatch)

    r = c.get(f"/api/v1/products/{EJE}/deep_dive/report?scope=x")
    assert r.status_code == 200, r.text
    body = r.json()
    assert SECCION_DELTA in body["narratives"]
    assert body["narratives"][SECCION_DELTA].startswith("Movimiento de ")
    orden = body["commercial"]["sections"]
    assert SECCION_DELTA in orden
    assert orden.index("resumen") < orden.index(SECCION_DELTA) < orden.index("std_methodology")
    assert body["commercial"]["secciones_omitidas"] == []
    assert SECCION_DELTA not in body["payload"], "el delta volvió al payload"
    assert db.query(ProductReportCache).count() == 1 and db.query(FeedDeltaCache).count() == 1

    # Y el caso omitido se LISTA en la misma respuesta, sin tumbar el informe.
    _motor(monkeypatch, texto="Cae debido a la lluvia.")
    db.query(FeedDeltaCache).delete()
    db.commit()
    r2 = c.get(f"/api/v1/products/{EJE}/deep_dive/report?scope=x")
    assert r2.status_code == 200
    assert SECCION_DELTA not in r2.json()["narratives"]
    assert [o["motivo"] for o in r2.json()["commercial"]["secciones_omitidas"]] == [OMITIDA_CAUSAL]


# ── Segundo arreglo de prod (2026-09-14): ausencias narradas y el aviso repetido ─────────

def _fuentes_sisalril():
    from shared.data.sisalril_ars_client import SISALRILARSClient
    from shared.data.sisalril_client import SISALRILClient
    from shared.narrative.atribucion import Fuente

    return (Fuente.de_cliente(SISALRILClient, descripcion="afiliación al SFS"),
            Fuente.de_cliente(SISALRILARSClient, descripcion="saldos de las ARS"))


def _producto_con_dos_feeds_sisalril(db, monkeypatch):
    from shared.products import registry

    sfs, ars = _fuentes_sisalril()
    feeds = [_feed(clave="uno", fuente=sfs),
             _feed(clave="dos", etiqueta="Emisor de prueba · stock", series=(SERIE_STOCK,),
                   etiquetas={SERIE_STOCK: "personas en stock"}, fuente=ars)]
    p = _Producto(db, feeds=feeds)
    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: p)
    ultimo = _feed_fresco(db)
    _punto(db, ultimo, 50.0, code=SERIE_STOCK, nature="stock")
    anio, mes = (int(x) for x in ultimo.split("-"))
    previo = f"{anio}-{mes - 1:02d}" if mes > 1 else f"{anio - 1}-12"
    _punto(db, previo, 40.0, code=SERIE_STOCK, nature="stock")
    return p, sfs.atribucion


def test_una_serie_SIN_VALOR_no_llega_al_contexto_del_modelo(db, monkeypatch):
    """«el margen de solvencia requerido del sistema no cuenta con observación» salió en prod:
    la serie vacía viajaba en `series_sin_lectura` y la plantilla pedía declararla."""
    import json

    feed = _feed(series=(SERIE, SERIE_STOCK),
                 etiquetas={SERIE: "cosas contadas", SERIE_STOCK: "personas en stock"})
    from shared.products import registry

    p = _Producto(db, feeds=[feed])
    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: p)
    ultimo = _feed_fresco(db)
    _punto(db, ultimo, None, code=SERIE_STOCK, nature="stock")
    bloque = bloque_del_delta(db, EJE, [feed])
    assert bloque is not None and bloque["lecturas"][0].get("sin_lectura"), (
        "el caso dejó de reproducirse: el bloque ya no trae una serie sin lectura")
    ctx = contexto_del_delta(bloque, [feed], "2025")
    crudo = json.dumps(ctx, ensure_ascii=False)
    assert "sin_lectura" not in crudo
    assert "personas en stock" not in crudo


def test_el_aviso_EXIGIDO_sale_UNA_vez_al_pie_aunque_el_modelo_lo_escriba_en_cada_bloque(
        db, monkeypatch):
    p, aviso = _producto_con_dos_feeds_sisalril(db, monkeypatch)
    assert aviso, "el control dejó de servir: SISALRIL ya no exige aviso"
    _motor(monkeypatch, texto=(f"## Uno\n\nTexto del primero.\n\n*{aviso}*\n\n---\n\n"
                               f"## Dos\n\nTexto del segundo.\n\n*{aviso}*\n\n---"))
    narr, omitidas = _anexar(p)
    seccion = narr[SECCION_DELTA]
    assert omitidas == []
    assert seccion.count(aviso) == 1, seccion
    assert seccion.endswith(f"*{aviso}*"), seccion
    assert "Texto del primero." in seccion and "Texto del segundo." in seccion
    assert "---\n\n*" not in seccion, "quedó un separador huérfano antes del pie"


def test_sin_aviso_en_el_texto_del_modelo_el_pie_se_AGREGA_y_la_regla_se_lo_prohibe(
        db, monkeypatch):
    p, aviso = _producto_con_dos_feeds_sisalril(db, monkeypatch)
    llamadas = _motor(monkeypatch, texto="Texto sin fuente.")
    narr, _ = _anexar(p)
    assert narr[SECCION_DELTA].endswith("Texto sin fuente.\n\n" + f"*{aviso}*")
    from shared.products.feed_delta import REGLA_DE_LA_ATRIBUCION_DEL_DELTA

    assert llamadas[0]["context"]["regla_de_la_atribucion"] == REGLA_DE_LA_ATRIBUCION_DEL_DELTA


# ── La ventana de doce meses sin su base no se narra como hueco (2026-09-14) ─────────

def test_una_ventana_SIN_base_anterior_viaja_sin_el_motivo_del_hueco():
    """«faltan cinco de los doce meses del período equivalente del año anterior» salió en prod."""
    from shared.products.feed_delta import _serie_para_el_modelo

    serie = {"serie": "x", "valor": 10.0, "ventana_movil_12m": {
        "disponible": True, "desde": "2025-08", "hasta": "2026-07", "valor": 120.0,
        "comparable_con": "el índice anual del eje",
        "linea_base": {"tipo": "mismo_periodo_anio_anterior",
                       "no_disponible": "faltan 5 de los 12 meses de la ventana (2024-08, …)"}}}
    limpia = _serie_para_el_modelo(serie)
    crudo = json.dumps(limpia, ensure_ascii=False)
    assert "faltan" not in crudo and "no_disponible" not in crudo
    assert limpia["ventana_movil_12m"]["valor"] == 120.0, "el total de la ventana SÍ es un dato"
    from shared.products.feed_delta import LECTURA_DE_LA_VENTANA_SIN_BASE
    assert limpia["ventana_movil_12m"]["se_lee_como"] == LECTURA_DE_LA_VENTANA_SIN_BASE, (
        "sin la regla de lectura el modelo narra que la comparación no existe (construcción, prod)")
    assert serie["ventana_movil_12m"]["linea_base"]["no_disponible"], "no se muta el dato de origen"


def test_una_ventana_NO_disponible_no_viaja():
    from shared.products.feed_delta import _serie_para_el_modelo

    serie = {"serie": "x", "valor": 10.0, "ventana_movil_12m": {
        "disponible": False, "meses_faltantes": ["2025-01"], "motivo": "faltan 1 de los 12 meses"}}
    assert "ventana_movil_12m" not in _serie_para_el_modelo(serie)


def test_una_ventana_COMPLETA_con_base_viaja_entera():
    from shared.products.feed_delta import _serie_para_el_modelo

    ventana = {"disponible": True, "valor": 120.0, "linea_base": {"tipo": "x", "valor": 100.0},
               "movimiento": {"direccion": "sube", "variacion_pct": 20.0}}
    assert _serie_para_el_modelo({"serie": "x", "ventana_movil_12m": ventana})["ventana_movil_12m"] == ventana


def test_el_contexto_del_delta_NO_lleva_meses_faltantes(db, producto):
    """Con historia corta, el contexto que ve el modelo no trae ningún motivo de hueco."""
    _feed_fresco(db)
    bloque = bloque_del_delta(db, EJE, producto.feeds_mensuales())
    crudo = json.dumps(contexto_del_delta(bloque, producto.feeds_mensuales(), "2025"), ensure_ascii=False)
    assert "faltan" not in crudo and "meses_faltantes" not in crudo


def test_la_regla_de_la_ventana_sin_base_prohibe_decir_que_la_comparacion_no_existe():
    from shared.products.feed_delta import LECTURA_DE_LA_VENTANA_SIN_BASE

    assert "total" in LECTURA_DE_LA_VENTANA_SIN_BASE
    assert "no escribas" in LECTURA_DE_LA_VENTANA_SIN_BASE and "línea base" in LECTURA_DE_LA_VENTANA_SIN_BASE
    assert not any(c.isdigit() for c in LECTURA_DE_LA_VENTANA_SIN_BASE), "una cifra en la regla la vería el guard"


def test_una_ventana_COMPLETA_con_base_no_recibe_la_regla_de_lectura():
    from shared.products.feed_delta import _serie_para_el_modelo

    ventana = {"disponible": True, "valor": 120.0, "linea_base": {"tipo": "x", "valor": 100.0}}
    assert "se_lee_como" not in _serie_para_el_modelo({"serie": "x", "ventana_movil_12m": ventana})["ventana_movil_12m"]


# ── Términos vetados: los DECLARA el feed y los repara el MOTOR (2026-09-14 / 09-15) ─────
#
# «La demanda del sistema eléctrico se acentúa» salió en prod con la nota del feed prohibiéndola.
# El delta tuvo detector, corrección y regeneración propios; hoy declara sus términos bajo la
# clave de `shared.narrative.terminos_vetados` y el lazo del guard del motor los repara en el
# mismo reintento que las cifras. Estos tests corren el MOTOR REAL con el cliente falseado: con
# `narrative_engine.generate` falseado no probarían nada del mecanismo.

MOTIVO_PRUEBA = "las series son cosas contadas, no pedidas: nombrá cada serie con su etiqueta"

#: Literal y no importada: contra el código sin excepciones el test tiene que fallar por aserción.
CLAVE_EXCEPCIONES = "palabras_que_no_son_esos_terminos"


class _Msg:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()


def _motor_real(monkeypatch, textos):
    """El motor REAL (`_generate_guarded`) con el cliente falseado. Devuelve el mensaje de
    usuario de cada llamada de REDACCIÓN, en orden (las del juez no se cuentan)."""
    eng, llamadas, cola = ce.narrative_engine, [], list(textos)

    class _Cliente:
        class messages:
            @staticmethod
            def create(**kw):
                if "verificador" in (kw.get("system") or ""):
                    return _Msg('{"unsupported": []}')
                llamadas.append(kw["messages"][0]["content"])
                return _Msg(cola.pop(0) if len(cola) > 1 else cola[0])

    monkeypatch.setattr(eng, "_get_client", lambda: _Cliente())
    monkeypatch.setattr(eng, "_get_cached", lambda key: None)
    monkeypatch.setattr(eng, "_set_cache", lambda key, result: None)
    monkeypatch.setattr(ce.settings, "ANTHROPIC_MODEL", "test-model", raising=False)
    monkeypatch.setattr(ce.settings, "ANTHROPIC_GUARD_MODEL", "test-judge", raising=False)
    return llamadas


def _motor_secuencia(monkeypatch, textos):
    """Un motor falso que devuelve *textos* en orden y registra el contexto de cada llamada."""
    llamadas = []

    async def fake(**kw):
        llamadas.append(kw)
        return ce.NarrativeResult(text=textos[min(len(llamadas) - 1, len(textos) - 1)])

    monkeypatch.setattr(ce.narrative_engine, "generate", fake)
    return llamadas


def _producto_con_veto(db, monkeypatch, **kw):
    from shared.products import registry

    kw.setdefault("terminos_vetados", {"demanda": MOTIVO_PRUEBA})
    p = _Producto(db, feeds=[_feed(**kw)])
    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: p)
    _feed_fresco(db)
    return p


def test_con_un_termino_vetado_el_MOTOR_regenera_con_el_aviso_y_el_MOTIVO(db, monkeypatch):
    """Una sola regeneración, la del motor, con el aviso general y el motivo del feed. «demandas»
    es una flexión: el detector viejo del delta la dejaba pasar."""
    from shared.narrative.terminos_vetados import CLAVE

    p = _producto_con_veto(db, monkeypatch)
    llamadas = _motor_real(monkeypatch, ["Las demandas de cosas se leen en el período.",
                                         "Las cosas contadas se leen en el período."])
    narr, omitidas = _anexar(p)
    assert omitidas == []
    assert narr[SECCION_DELTA].endswith("Las cosas contadas se leen en el período.")
    assert len(llamadas) == 2, "la regeneración no la hizo el lazo del motor"
    aviso = llamadas[1].partition("CORRECCIÓN OBLIGATORIA — TÉRMINOS")[2]
    assert "«demanda»" in aviso and MOTIVO_PRUEBA in aviso
    assert CLAVE in llamadas[0], "el modelo no lee los términos en su contexto"
    assert not any("correccion_de_terminos" in m for m in llamadas), "volvió la corrección propia"


def test_si_el_termino_PERSISTE_se_quita_la_ORACION_y_la_seccion_se_publica(db, monkeypatch):
    from shared.narrative.claude_engine import _MAX_REINTENTOS_GUARD

    p = _producto_con_veto(db, monkeypatch)
    llamadas = _motor_real(monkeypatch, [
        "Las cosas contadas se leen en el período. La demanda de cosas se lee aparte."])
    narr, omitidas = _anexar(p)
    assert omitidas == []
    assert len(llamadas) == 1 + _MAX_REINTENTOS_GUARD
    assert narr[SECCION_DELTA].endswith("Las cosas contadas se leen en el período.")
    assert "demanda" not in narr[SECCION_DELTA].lower()
    assert db.query(FeedDeltaCache).one().texto == "Las cosas contadas se leen en el período."


def test_una_palabra_que_EMPIEZA_como_el_termino_y_no_lo_es_no_se_toca(db, monkeypatch):
    """«demandante» no es «demanda». El detector general acepta flexiones por la raíz, así que
    la excepción se DECLARA; sin ella, esta oración se quitaría."""
    p = _producto_con_veto(db, monkeypatch, excepciones_de_terminos=("demandante",))
    llamadas = _motor_real(monkeypatch, ["La parte demandante no aplica a estas cosas."])
    narr, omitidas = _anexar(p)
    assert omitidas == [] and len(llamadas) == 1
    assert narr[SECCION_DELTA].endswith("La parte demandante no aplica a estas cosas.")


def test_un_texto_CACHEADO_con_el_termino_no_se_sirve(db, monkeypatch):
    p = _producto_con_veto(db, monkeypatch)
    _motor_secuencia(monkeypatch, ["Las cosas contadas suben."])
    _anexar(p)
    fila = db.query(FeedDeltaCache).one()
    fila.texto = "Las demandas del sistema se acentúan."
    db.commit()
    llamadas = _motor_secuencia(monkeypatch, ["Las cosas contadas suben de nuevo."])
    narr, _ = _anexar(p)
    assert len(llamadas) == 1, "sirvió el texto cacheado con el término vetado"
    assert "demanda" not in narr[SECCION_DELTA].lower()


def test_el_contexto_DECLARA_los_terminos_bajo_la_clave_del_motor_solo_si_el_feed_los_declara(
        db, monkeypatch):
    from shared.narrative.terminos_vetados import CLAVE

    p = _producto_con_veto(db, monkeypatch, excepciones_de_terminos=("demandante",))
    llamadas = _motor_secuencia(monkeypatch, ["Las cosas contadas suben."])
    _anexar(p)
    contexto = llamadas[0]["context"]
    assert contexto[CLAVE] == {"demanda": MOTIVO_PRUEBA}
    assert contexto[CLAVE_EXCEPCIONES] == ["demandante"]
    assert "terminos_que_no_describen_estas_series" not in contexto["lecturas_por_emisor"][0]

    # Sin veto declarado las claves no aparecen: la huella de esos feeds no cambia.
    sin_veto = contexto_del_delta({"lecturas": [{"clave": "prueba_mensual", "emisor": "E",
                                                 "etiqueta": "E", "periodo": "2026-06"}]},
                                  [_feed()], "2025")
    assert CLAVE not in sin_veto and CLAVE_EXCEPCIONES not in sin_veto


def test_el_feed_del_IMTE_veta_DEMANDA_con_su_motivo_y_no_DEMANDANTE(db):
    from modules.energy_intel.products import EnergyProduct
    from shared.narrative.terminos_vetados import CLAVE, terminos_en

    feed = next(f for f in EnergyProduct(db).feeds_mensuales() if f.clave == "oc_seni_imte")
    assert isinstance(feed.terminos_vetados, Mapping) and feed.terminos_vetados.get("demanda")
    contexto = contexto_del_delta({"lecturas": [{"clave": feed.clave, "emisor": feed.emisor,
                                                 "etiqueta": feed.etiqueta, "periodo": "2026-06"}]},
                                  [feed], "2025")
    assert CLAVE in contexto
    assert terminos_en(contexto, "La demanda del sistema eléctrico se acentúa.") == ["demanda"]
    assert terminos_en(contexto, "La energía demandada creció.") == ["demanda"]
    assert terminos_en(contexto, "La parte demandante no aplica.") == []


def test_por_HTTP_el_termino_vetado_no_llega_al_informe(db, monkeypatch):
    """La ruta, con el ensamblador y el motor reales: solo se falsea el cliente del modelo."""
    p = _producto_con_veto(db, monkeypatch)
    _motor_real(monkeypatch, [
        "Las cosas contadas se leen en el período. La demanda de cosas se lee aparte."])
    body = _informe_por_http(db, p, monkeypatch)
    assert body["commercial"]["secciones_omitidas"] == []
    texto = body["narratives"][SECCION_DELTA]
    assert texto.endswith("Las cosas contadas se leen en el período.")
    assert "demanda" not in texto.lower()
