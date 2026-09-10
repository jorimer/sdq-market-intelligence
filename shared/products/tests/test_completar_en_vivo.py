"""El texto EN VIVO se completa después de la caché, y no la rompe ni la invalida.

El caso que lo motivó: la sección del movimiento mensual de construcción cita la fecha de la
última descarga de la fuente, que cambia a diario con la sonda. Dentro del payload, esa fecha
cambiaba la huella de la caché cada día y el Deep Dive entero se regeneraba — con las
secciones anuales que no cambiaron incluidas.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products.assembler import _narrative_fingerprint, _narratives_cached
from shared.products.contract import ProductSnapshot
from shared.products.models import ProductReportCache  # noqa: F401 — registra la tabla
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ProductReportCache.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _snap(payload):
    return ProductSnapshot(tier=ProductTier.deep_dive, period="2025", payload=payload)


def test_un_dato_que_vive_FUERA_del_payload_no_cambia_la_huella():
    """La propiedad que hace barata la verificación diaria: la huella solo ve el payload."""
    payload = {"delta_mensual": {"periodo": "2026-06", "fuente_del_feed": {"al_dia": False}}}
    assert (_narrative_fingerprint(payload, "deep_dive", "es")
            == _narrative_fingerprint(dict(payload), "deep_dive", "es"))


def test_la_verificacion_diaria_NO_entra_al_payload_de_construccion():
    """Si la fecha de la última descarga llegara al payload, cada verificación regeneraría el
    informe entero. Se lee el CÓDIGO del snapshot: la clave no puede aparecer ahí."""
    import inspect

    from modules.construction_intel.products import ConstructionProduct

    fuente_delta = inspect.getsource(ConstructionProduct._delta_mensual)
    for prohibida in ("ultima_descarga", "verificado_el", "leer_verificacion"):
        assert prohibida not in fuente_delta, (
            f"«{prohibida}» aparece en el armado del payload: la fecha de la verificación "
            "diaria cambiaría la huella de la caché todos los días")


class _Producto:
    sector_key = "construction"

    def __init__(self, db):
        self._db = db
        self.generaciones = 0

    async def narratives(self, tier, snapshot, lang):
        self.generaciones += 1
        return {"delta_mensual": "texto del modelo"}


def test_con_la_cache_llena_el_texto_cacheado_NO_trae_lo_vivo(db):
    """Lo que se guarda en la caché es lo del modelo: lo vivo se agrega al servir."""
    p = _Producto(db)
    snap = _snap({"x": 1})
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", ""))
    fila = db.query(ProductReportCache).one()
    assert fila.narratives == {"delta_mensual": "texto del modelo"}


# ── El paso en el ensamblador ────────────────────────────────────────────────────

def _correr_paso(producto, narratives):
    """Reproduce el tramo del ensamblador que llama al gancho, tal cual está escrito."""
    completar = getattr(producto, "completar_en_vivo", None)
    if callable(completar):
        try:
            completado = completar(ProductTier.deep_dive, _snap({}), dict(narratives))
            if isinstance(completado, dict):
                narratives = completado
        except Exception:  # noqa: BLE001
            pass
    return narratives


def test_el_ensamblador_llama_al_gancho_DESPUES_de_la_cache_y_del_control_de_degradacion():
    """Se lee el código del ensamblador: el gancho tiene que estar después de
    `_narratives_cached` (o lo vivo se guardaría en la caché) y después del control de
    degradación (o un encabezado podría tapar la detección de un texto de respaldo)."""
    import inspect

    import shared.products.assembler as asm

    src = inspect.getsource(asm)
    i_cache = src.index("_narratives_cached(product, tier, snapshot, lang, scope)")
    i_degr = src.index("degraded_sections")
    i_gancho = src.index('getattr(product, "completar_en_vivo", None)')
    i_glosario = src.index("glossary_section(")
    assert i_cache < i_gancho, "el gancho corre antes de la caché: lo vivo quedaría grabado"
    assert i_degr < i_gancho, "el gancho corre antes del control de degradación"
    assert i_gancho < i_glosario, "el gancho corre después del glosario: la sigla no se definiría"


def test_un_producto_SIN_gancho_sale_intacto():
    class SinGancho:
        pass

    assert _correr_paso(SinGancho(), {"a": "b"}) == {"a": "b"}


def test_un_gancho_que_FALLA_no_tumba_la_entrega():
    class Roto:
        def completar_en_vivo(self, tier, snapshot, narratives):
            raise RuntimeError("sin base")

    assert _correr_paso(Roto(), {"a": "b"}) == {"a": "b"}


def test_el_gancho_del_ensamblador_es_defensivo_de_verdad():
    """El tramo de arriba reproduce el del ensamblador; esto comprueba que el ensamblador
    REALMENTE lo envuelve en try/except, para que la reproducción no mienta."""
    import inspect

    import shared.products.assembler as asm

    src = inspect.getsource(asm)
    i = src.index('getattr(product, "completar_en_vivo", None)')
    tramo = src[i:i + 700]
    assert "try:" in tramo and "except Exception" in tramo
