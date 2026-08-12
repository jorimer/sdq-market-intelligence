"""Caché de narrativas del assembler: un HIT evita regenerar; el cambio de dato invalida."""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products.assembler import _narratives_cached, _narrative_fingerprint
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


class _FakeProduct:
    sector_key = "macro"

    def __init__(self, db):
        # Los productos reales guardan la sesión en `_db` (NO `db`): el fake debe reflejar
        # el contrato real, o el test pasaría mientras producción no cachea (fue el bug).
        self._db = db
        self.calls = 0

    async def narratives(self, tier, snapshot, lang):
        self.calls += 1
        return {"risk_assessment": f"generación #{self.calls}"}


def _snap(payload):
    return ProductSnapshot(tier=ProductTier.deep_dive, period="2024", payload=payload)


def test_second_call_is_a_cache_hit(db):
    p = _FakeProduct(db)
    snap = _snap({"irmp_score": 50})
    n1 = asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "DO"))
    n2 = asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "DO"))
    assert p.calls == 1                       # el 2º no regeneró (HIT)
    assert n1 == n2 == {"risk_assessment": "generación #1"}
    assert db.query(ProductReportCache).count() == 1


def test_changed_data_invalidates(db):
    p = _FakeProduct(db)
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, _snap({"irmp_score": 50}), "es", "DO"))
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, _snap({"irmp_score": 55}), "es", "DO"))
    assert p.calls == 2                        # el payload cambió → fingerprint distinto → MISS
    row = db.query(ProductReportCache).filter_by(scope="DO", period="2024").one()  # actualizado en sitio
    assert row.narratives == {"risk_assessment": "generación #2"}


def test_scope_and_lang_are_separate_keys(db):
    p = _FakeProduct(db)
    snap = _snap({"irmp_score": 50})
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "DO"))
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "CR"))  # otro ámbito
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "en", "DO"))  # otro idioma
    assert p.calls == 3 and db.query(ProductReportCache).count() == 3


def test_fingerprint_changes_with_version(monkeypatch):
    import shared.products.assembler as asm
    fp1 = _narrative_fingerprint({"x": 1}, "deep_dive", "es")
    # Cualquier versión DISTINTA de la vigente (no un literal, que queda obsoleto al bumpear).
    monkeypatch.setattr(asm, "NARRATIVE_CACHE_VERSION", asm.NARRATIVE_CACHE_VERSION + ".test")
    fp2 = _narrative_fingerprint({"x": 1}, "deep_dive", "es")
    assert fp1 != fp2   # bumpear la versión invalida toda la caché


def test_no_db_falls_back_to_direct_generation():
    p = _FakeProduct(None)
    n = asyncio.run(_narratives_cached(p, ProductTier.deep_dive, _snap({"a": 1}), "es", None))
    assert p.calls == 1 and n == {"risk_assessment": "generación #1"}


# ── La receta entra en el fingerprint ─────────────────────────────────────────
#
# Esta caché vive en Postgres y NO tiene TTL: se invalida solo si cambia el dato. El bump
# manual estaba documentado y aun así no se movió en tres arreglos de prompt seguidos
# (#580, veto de léxico visceral, #631), que pudieron quedar sin efecto acá.

def test_prompt_change_invalidates_the_product_cache(monkeypatch):
    from shared.products import assembler as asm
    payload = {"periodo": "2026-03", "isf": 66}
    before = asm._narrative_fingerprint(payload, "deep_dive", "es")

    import shared.narrative.cerebro as cerebro
    monkeypatch.setattr(cerebro, "NO_META_COMMENTARY",
                        cerebro.NO_META_COMMENTARY + "\nREGLA NUEVA", raising=False)
    assert asm._narrative_fingerprint(payload, "deep_dive", "es") != before


def test_guard_version_invalidates_the_product_cache(monkeypatch):
    from shared.products import assembler as asm
    payload = {"periodo": "2026-03"}
    before = asm._narrative_fingerprint(payload, "deep_dive", "es")

    import shared.narrative.numeric_guard as ng
    monkeypatch.setattr(ng, "GUARD_VERSION", "999", raising=False)
    assert asm._narrative_fingerprint(payload, "deep_dive", "es") != before


def test_stable_recipe_and_data_keeps_the_hit():
    """La caché existe para que la descarga no espere 15-90 s: sin cambios, HIT sigue HIT."""
    from shared.products import assembler as asm
    payload = {"periodo": "2026-03", "isf": 66}
    assert (asm._narrative_fingerprint(payload, "deep_dive", "es")
            == asm._narrative_fingerprint(dict(payload), "deep_dive", "es"))


def test_data_change_still_invalidates():
    """La invalidación por DATO, que ya existía, sigue funcionando."""
    from shared.products import assembler as asm
    a = asm._narrative_fingerprint({"isf": 66}, "deep_dive", "es")
    b = asm._narrative_fingerprint({"isf": 67}, "deep_dive", "es")
    assert a != b


# ── La receta tiene que cubrir también el CONTEXTO que ve el modelo ────────────
#
# El 2026-08-11 se corrigió `concentracion_top4_pct` en `insurance_intel/ai_context.py` —la
# clave que hacía publicar «cuatro compañías concentran el 87,1%» cuando eran cuatro RAMOS—,
# se desplegó, y el Deep Dive de MAPFRE siguió sirviendo el texto viejo: el fingerprint no
# miraba el constructor de contexto. Esta caché vive en Postgres y NO tiene TTL, así que el
# informe habría quedado mal indefinidamente.

_MOD_SEGUROS = "modules.insurance_intel.products"     # type(product).__module__ real
_MOD_PENSION = "modules.pension_intel.products"


def test_el_fingerprint_cambia_si_cambia_el_contexto_del_sector(monkeypatch):
    """Tocar `modules/<mod>/ai_context.py` tiene que producir MISS en ESE sector."""
    import shared.products.assembler as asm

    n = {"i": 0}

    def _fake(mod):
        n["i"] += 1
        return "huella-nueva" if n["i"] > 1 else "huella-vieja"

    monkeypatch.setattr(asm, "_contexto_ia_version", _fake)
    payload = {"isf": 71.1}
    antes = asm._narrative_fingerprint(payload, "deep_dive", "es", modulo_producto=_MOD_SEGUROS)
    despues = asm._narrative_fingerprint(payload, "deep_dive", "es", modulo_producto=_MOD_SEGUROS)
    assert antes != despues


def test_resuelve_el_MODULO_no_el_sector_key():
    """El bug que casi se despacha: `sector_key` es "insurance" y la carpeta es
    `insurance_intel`. Buscando por sector_key el archivo no existe → "" → la huella no
    invalida NADA, y todo queda en verde. Se deriva de `type(product).__module__`."""
    import shared.products.assembler as asm

    assert asm._contexto_ia_version(_MOD_SEGUROS) != ""
    assert asm._contexto_ia_version("insurance") == ""      # sector_key: NO resuelve
    assert asm._contexto_ia_version("modules.insurance.products") == ""


def test_la_huella_se_deriva_del_archivo_real():
    """Derivada del contenido, no una constante que alguien deba acordarse de subir."""
    import shared.products.assembler as asm

    h = asm._contexto_ia_version(_MOD_SEGUROS)
    assert h and len(h) == 12
    assert h != asm._contexto_ia_version(_MOD_PENSION)


def test_un_sector_sin_constructor_no_rompe_la_entrega():
    """Sin `ai_context.py` no hay nada que versionar; nunca una excepción."""
    import shared.products.assembler as asm

    assert asm._contexto_ia_version("modules.banking_score.products") == ""
    assert asm._contexto_ia_version(None) == ""
    assert asm._contexto_ia_version("cualquier.cosa") == ""


def test_la_huella_es_POR_SECTOR_no_global():
    """Invalidar el panel entero por tocar un módulo obliga a regenerar todo sin motivo."""
    import shared.products.assembler as asm

    payload = {"isf": 71.1}
    a = asm._narrative_fingerprint(payload, "deep_dive", "es", modulo_producto=_MOD_SEGUROS)
    b = asm._narrative_fingerprint(payload, "deep_dive", "es", modulo_producto=_MOD_PENSION)
    assert a != b


def test_el_ensamblador_pasa_el_MODULO_y_no_el_sector_key():
    """Contrato: si alguien vuelve a pasar `product.sector_key`, la huella queda muerta."""
    import inspect

    import shared.products.assembler as asm

    src = inspect.getsource(asm._narratives_cached)
    assert "modulo_producto=type(product).__module__" in src, (
        "el fingerprint debe recibir el módulo del producto, no su sector_key")
