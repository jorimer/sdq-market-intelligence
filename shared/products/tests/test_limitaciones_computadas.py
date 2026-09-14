"""§Limitaciones COMPUTADA (Fase 4a): qué se escribe, qué nunca, y que llega a todo producto.

* **positivo** — con la fuente del feed atrasada, la sección nombra el atraso con la fecha de
  publicación del emisor y la de nuestra última descarga;
* **negativo** — un eje sin nada propio del período lo DICE, explícitamente;
* **consolidar, no sembrar** (decisión del dueño, 2026-08-31) — las dimensiones sin dato nunca se
  listan: si hay brecha, UNA vez la frase de método; sin señal del registro, ninguna;
* **el texto fijo sobrevive** como párrafo de cierre, y un fallo nunca tumba la entrega;
* **estructural** — todo producto que declara `limitations` en un nivel la recibe computada, leído
  de los manifiestos y no de una lista.
"""
import asyncio
from datetime import date
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.narrative.claude_engine as ce
from shared.database.base import Base
from shared.observations import service as obs
from shared.products.contract import DataHealth, ProductSnapshot, ValidationState
from shared.products.feed_delta import FeedDeclarado, senales_de_los_feeds
from shared.products.limitaciones import (
    FRASE_DE_METODO,
    FRASE_DELTA_OMITIDO,
    FRASE_SIN_LIMITACIONES,
    SECCION,
    completar_limitaciones,
    limitaciones_computadas,
)
from shared.products.manifest import SectorProductManifest
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec

EJE = "tourism"
SERIE = "prueba.flujo.conteo"
FIJO = "Texto fijo de diseño del producto."


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


def _feed(**kw: Any) -> FeedDeclarado:
    base: Dict[str, Any] = dict(
        clave="prueba_mensual", etiqueta="las cosas contadas del emisor de prueba",
        emisor="Emisor de prueba", emisor_en_prosa="el Emisor de prueba", series=(SERIE,),
        etiquetas={SERIE: "cosas contadas"}, axis="tourism_intel", cadence="monthly")
    base.update(kw)
    return FeedDeclarado(**base)


class _Producto:
    sector_key = EJE

    def __init__(self, db, *, feeds=None, senales=None, frescura_indice=10,
                 cadencia_indice="annual"):
        self._db = db
        self._feeds = feeds if feeds is not None else []
        self._senales = senales
        self._frescura = frescura_indice
        self._cadencia = cadencia_indice

    def product_manifest(self):
        return SectorProductManifest(sector_key=EJE, display_name="Prueba", levels={
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("resumen", SECCION), narrative_templates=("executive_summary",),
                audience="x", cadence="x", price_band="x")})

    def data_signals(self):
        return DataHealth(coverage=1.0, freshness_days=self._frescura, cadence=self._cadencia,
                          sources=("Emisor del índice",))

    def has_engine(self):
        return True

    def validation_state(self):
        return ValidationState(approved=True, score=0.5, notes="prueba")

    def snapshot(self, tier, period, scope=None):
        return ProductSnapshot(tier=tier, period="2025", payload={"x": 1}, entity_name="Sujeto")

    async def narratives(self, tier, snapshot, lang="es"):
        return {"resumen": "Texto del índice.", SECCION: FIJO}

    async def render(self, *a, **k):
        return ""

    def feeds_mensuales(self):
        return list(self._feeds)

    def senales_de_fuentes(self):
        return senales_de_los_feeds(self._db, EJE, self.feeds_mensuales())

    def variable_signals(self):
        if self._senales is None:
            raise AttributeError  # se sobreescribe por instancia cuando hace falta
        return {"period": "2025", "signals": self._senales}


def _registrar(monkeypatch, p):
    from shared.products import registry

    monkeypatch.setitem(registry._REGISTRY, EJE, lambda _db: p)


def _snap(p):
    return p.snapshot(ProductTier.deep_dive, "2025")


def _punto(db, period, value, publicado=None):
    obs.upsert(db, sector_key=EJE, series_code=SERIE, period=period, value=value, unit="conteo",
               frequency="monthly", nature="flow", source="Emisor de prueba",
               published_at=publicado)
    db.commit()


def _sin_variable_signals(p):
    """Un producto sin `variable_signals`: se borra el método de la instancia."""
    p.variable_signals = None
    return p


# ── Positivo: el atraso del feed se nombra con sus dos fechas ─────────────────────

def test_con_el_feed_ATRASADO_la_seccion_nombra_la_publicacion_y_la_descarga(db, monkeypatch):
    feed = _feed(ultima_descarga=date(2026, 9, 12))
    p = _sin_variable_signals(_Producto(db, feeds=[feed]))
    _registrar(monkeypatch, p)
    for m in range(1, 13):
        _punto(db, f"2023-{m:02d}", 100.0, publicado=date(2023, 12, 20))
    texto = limitaciones_computadas(p, ProductTier.deep_dive, _snap(p))
    assert ("La lectura mensual de las cosas contadas del emisor de prueba corresponde a "
            "diciembre de 2023, la última edición que publicó el Emisor de prueba, el 20 de "
            "diciembre de 2023; la de enero de 2024 no figuraba en la fuente en nuestra última "
            "descarga, del 12 de septiembre de 2026.") in texto
    assert "El índice de este informe corresponde a 2025; la lectura mensual, a diciembre de 2023." in texto
    assert FRASE_SIN_LIMITACIONES not in texto


def test_la_fuente_del_INDICE_atrasada_se_nombra_sin_dias(db, monkeypatch):
    p = _sin_variable_signals(_Producto(db, frescura_indice=2000, cadencia_indice="annual"))
    _registrar(monkeypatch, p)
    texto = limitaciones_computadas(p, ProductTier.deep_dive, _snap(p))
    assert "La fuente del índice (Emisor del índice) no publicó una edición nueva dentro de su ciclo anual" in texto
    assert "2000" not in texto and "días" not in texto, "una cifra de días envejece sola"


def test_una_frescura_INDETERMINADA_dice_que_no_se_pudo_verificar(db, monkeypatch):
    p = _sin_variable_signals(_Producto(db, frescura_indice=None))
    _registrar(monkeypatch, p)
    texto = limitaciones_computadas(p, ProductTier.deep_dive, _snap(p))
    assert "No fue posible verificar la vigencia de la fuente del índice" in texto


# ── Negativo: sin nada propio del período, se dice ────────────────────────────────

def test_un_eje_AL_DIA_y_sin_brecha_lo_dice_explicitamente(db, monkeypatch):
    p = _sin_variable_signals(_Producto(db, frescura_indice=10))
    _registrar(monkeypatch, p)
    assert limitaciones_computadas(p, ProductTier.deep_dive, _snap(p)) == FRASE_SIN_LIMITACIONES


# ── Consolidar, no sembrar ────────────────────────────────────────────────────────

def _senal(key, state):
    from shared.registry.signals import VariableSignal

    return VariableSignal(key=key, label=f"Etiqueta de {key}", state=state)


def test_con_una_BRECHA_va_la_frase_de_metodo_una_vez_y_sin_nombrar_variables(db, monkeypatch):
    from shared.registry.signals import GAP, REAL

    p = _Producto(db, senales=[_senal("produccion", REAL), _senal("empleo", GAP),
                               _senal("inversion", GAP)])
    _registrar(monkeypatch, p)
    texto = limitaciones_computadas(p, ProductTier.deep_dive, _snap(p))
    assert texto.count(FRASE_DE_METODO) == 1
    for prohibida in ("empleo", "inversion", "Etiqueta de", "no tenemos", "brecha", "gap"):
        assert prohibida not in texto, f"«{prohibida}» sembró el faltante en el documento"


def test_sin_BRECHA_no_hay_frase_de_metodo(db, monkeypatch):
    from shared.registry.signals import REAL

    p = _Producto(db, senales=[_senal("produccion", REAL)])
    _registrar(monkeypatch, p)
    assert FRASE_DE_METODO not in limitaciones_computadas(p, ProductTier.deep_dive, _snap(p))


def test_SIN_variable_signals_no_se_infiere_ninguna_brecha(db, monkeypatch):
    """Sin la señal del registro no hay evidencia de que falte nada: no se deduce del payload."""
    p = _sin_variable_signals(_Producto(db))
    _registrar(monkeypatch, p)
    assert FRASE_DE_METODO not in limitaciones_computadas(p, ProductTier.deep_dive, _snap(p))


def test_una_seccion_OMITIDA_se_menciona_sin_el_motivo_tecnico(db, monkeypatch):
    p = _sin_variable_signals(_Producto(db))
    _registrar(monkeypatch, p)
    omitidas = [{"seccion": "delta_mensual", "motivo": "cifra_sin_respaldo",
                 "detalle": "«45 %» no está en el contexto"}]
    texto = limitaciones_computadas(p, ProductTier.deep_dive, _snap(p), omitidas)
    assert FRASE_DELTA_OMITIDO in texto
    assert "cifra_sin_respaldo" not in texto and "45 %" not in texto


@pytest.mark.parametrize("clave", ["monthly", "quarterly", "annual", "al_dia", "congelada",
                                   "indeterminada", "gap", "rubric"])
def test_ninguna_CLAVE_de_maquina_llega_al_texto(db, monkeypatch, clave):
    from shared.registry.signals import GAP

    feed = _feed(ultima_descarga=date(2026, 9, 12))
    p = _Producto(db, feeds=[feed], senales=[_senal("x", GAP)], frescura_indice=2000)
    _registrar(monkeypatch, p)
    for m in range(1, 13):
        _punto(db, f"2023-{m:02d}", 100.0, publicado=date(2023, 12, 20))
    texto = limitaciones_computadas(p, ProductTier.deep_dive, _snap(p),
                                    [{"seccion": "delta_mensual", "motivo": "tiempo"}])
    assert clave not in texto


# ── El texto fijo sobrevive y un fallo no tumba nada ──────────────────────────────

def test_el_texto_fijo_queda_como_PARRAFO_DE_CIERRE(db, monkeypatch):
    p = _sin_variable_signals(_Producto(db))
    _registrar(monkeypatch, p)
    narr = completar_limitaciones(p, ProductTier.deep_dive, _snap(p), {SECCION: FIJO, "a": "b"})
    assert narr[SECCION] == f"{FRASE_SIN_LIMITACIONES}\n\n{FIJO}"
    assert narr["a"] == "b"


def test_un_nivel_SIN_limitations_no_recibe_nada(db, monkeypatch):
    p = _sin_variable_signals(_Producto(db))
    _registrar(monkeypatch, p)
    original = {"resumen": "x"}
    assert completar_limitaciones(p, ProductTier.deep_dive, _snap(p), dict(original)) == original


def test_un_FALLO_al_computar_sirve_el_texto_fijo(db, monkeypatch):
    import shared.products.limitaciones as lim

    p = _sin_variable_signals(_Producto(db))

    def roto(*a, **k):
        raise RuntimeError("sin base")

    monkeypatch.setattr(lim, "limitaciones_computadas", roto)
    narr = completar_limitaciones(p, ProductTier.deep_dive, _snap(p), {SECCION: FIJO})
    assert narr == {SECCION: FIJO}


def test_lo_computado_NO_se_guarda_en_la_cache_del_informe(db, monkeypatch):
    """Los veredictos cambian más seguido que el contenido: lo computado va después de la caché."""
    from shared.products.assembler import assemble_product_content
    from shared.products.models import ProductReportCache

    p = _sin_variable_signals(_Producto(db))
    _registrar(monkeypatch, p)

    async def fake(**kw):
        return ce.NarrativeResult(text="x")

    monkeypatch.setattr(ce.narrative_engine, "generate", fake)
    content = asyncio.run(assemble_product_content(p, ProductTier.deep_dive, period="2025"))
    assert content.narratives[SECCION].startswith(FRASE_SIN_LIMITACIONES)
    fila = db.query(ProductReportCache).one()
    assert fila.narratives[SECCION] == FIJO, "lo computado quedó grabado en la caché sin TTL"


# ── Estructural: llega a TODO producto que declara la sección ─────────────────────

def test_todo_producto_que_declara_limitations_la_recibe_COMPUTADA(db):
    """Se leen los manifiestos, no una lista: un producto nuevo con la sección queda cubierto.
    Se cruza contra un piso para que un catálogo vacío no pase en verde."""
    from shared.products.registry import PRODUCT_CATALOG, get_product

    con_seccion = []
    for entrada in PRODUCT_CATALOG:
        p = get_product(entrada.sector_key, db)
        if p is None:
            continue
        niveles = [t for t, spec in p.product_manifest().levels.items()
                   if SECCION in spec.sections]
        for tier in niveles:
            con_seccion.append((entrada.sector_key, tier.value))
            snap = ProductSnapshot(tier=tier, period="2025", payload={})
            narr = completar_limitaciones(p, tier, snap, {SECCION: FIJO})
            assert narr[SECCION].endswith(FIJO), f"{entrada.sector_key}/{tier.value}: se perdió el fijo"
            assert narr[SECCION] != FIJO, f"{entrada.sector_key}/{tier.value}: no recibió lo computado"
    assert len(con_seccion) >= 15, con_seccion


def test_el_ensamblador_COMPLETA_las_limitaciones_despues_del_delta_y_antes_de_lo_vivo():
    import inspect

    import shared.products.assembler as asm

    src = inspect.getsource(asm)
    i_delta = src.index("anexar_delta_de_feeds(")
    i_lim = src.index("completar_limitaciones(")
    i_vivo = src.index('getattr(product, "completar_en_vivo", None)')
    assert i_delta < i_lim < i_vivo
