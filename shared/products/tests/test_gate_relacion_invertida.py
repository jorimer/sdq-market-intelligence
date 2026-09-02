"""Gate de RELACIÓN INVERTIDA — el tercero, y el más acotado de los tres a propósito.

Reproduce el defecto real: la §7 de un Deep Dive de banca entregado afirmó que la
capitalización contable «SUPERA en 3.70 puntos porcentuales al promedio de su grupo» cuando
estaba POR DEBAJO —7.41% contra una mediana de grupo de 11.11%— contradiciendo a la §2 y a la
§10 del MISMO documento.

Por qué es el más acotado: una relación invertida es REPARABLE. El sistema ya computó la
lectura correcta y el motor se la entrega al modelo para que la copie. Frenar quince secciones
buenas por una frase corregible no protege al cliente — le niega un análisis correcto casi
entero. Se llega al veto solo cuando el modelo contradice esa lectura DOS veces.

Contrato que fijan estos tests:

  * PREMIUM (nombrado) con relaciones pendientes → ``NarrativeRelacionInvertidaError``, con
    las secciones LISTADAS.
  * PULSE (sistema/abierto) → solo se registra; no rompe la entrega.
  * Sin relaciones pendientes → no cambia nada.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.narrative.claude_engine import NarrativeRelacionInvertidaError
from shared.narrative.relaciones_pendientes import registrar
from shared.products import Granularity, ProductTier, SectorProductManifest, TierLevelSpec
from shared.products.assembler import _content_from_snapshot
from shared.products.contract import ProductSnapshot
from shared.products.models import ProductReportCache  # noqa: F401 — registra la tabla

_SECTIONS = ("assessment", "peer_positioning", "recommendation")

#: Contexto que sostiene todas las cifras del texto: el gate que se prueba acá es el de
#: RELACIÓN, no el de cifra sin respaldo.
_CTX = {"has_data": True, "patrimonio_activos": 7.41}
_TEXTO = "La capitalización contable es 7.41% del activo."

#: Lo que el motor depositaría tras fallar la reparación dos veces.
_PENDIENTE = ["patrimonio_activos: se afirma 'por encima', la dirección servida es 'por debajo'"]


class _Product:
    """Producto de mentira que, al narrar, deposita una relación pendiente — igual que haría
    el motor real cuando la corrección no converge."""

    sector_key = "banking_score"

    def __init__(self, granularity, tier, *, deja_pendiente=True):
        self._gran, self._tier, self._deja = granularity, tier, deja_pendiente

    def product_manifest(self):
        return SectorProductManifest(
            sector_key=self.sector_key, display_name="Fake", levels={
                self._tier: TierLevelSpec(
                    tier=self._tier, granularity=self._gran, sections=_SECTIONS,
                    narrative_templates=(), audience="x", cadence="on_demand",
                    price_band="x")})

    async def narratives(self, tier, snapshot, lang="es"):
        if self._deja:
            registrar("peer_positioning", list(_PENDIENTE))
        return {s: _TEXTO for s in _SECTIONS}


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


def _correr(product, tier, entity):
    snap = ProductSnapshot(tier=tier, period="2025", payload=dict(_CTX), entity_name=entity)
    return asyncio.run(_content_from_snapshot(product, tier, snap, "es"))


def test_PREMIUM_no_se_entrega_y_LISTA_la_seccion():
    p = _Product(Granularity.named_entity, ProductTier.deep_dive)
    with pytest.raises(NarrativeRelacionInvertidaError) as e:
        _correr(p, ProductTier.deep_dive, "Banco X")
    assert "peer_positioning" in e.value.hallazgos, e.value.hallazgos


def test_el_PULSE_abierto_registra_pero_ENTREGA():
    """El Pulse es el nivel abierto: por doctrina solo registra. Si el motor vetara por su
    cuenta —en vez de reportar y dejar decidir acá— lo rompería."""
    p = _Product(Granularity.system, ProductTier.pulse)
    contenido = _correr(p, ProductTier.pulse, None)
    assert set(contenido.narratives) >= set(_SECTIONS)


def test_sin_relaciones_pendientes_el_premium_se_entrega_normal():
    """Prueba negativa: si el gate frenara siempre, los tests de arriba pasarían igual y no
    probarían nada."""
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, deja_pendiente=False)
    contenido = _correr(p, ProductTier.deep_dive, "Banco X")
    assert set(contenido.narratives) >= set(_SECTIONS)


def test_el_acumulador_se_abre_alrededor_de_la_generacion():
    """Si el `with` no envolviera a `_narratives_cached`, lo que el motor deposita se perdería
    y el gate no vería nunca nada — que es exactamente el estado del que venimos."""
    import inspect

    from shared.products import assembler

    fuente = inspect.getsource(assembler._content_from_snapshot)
    i_with = fuente.index("with acumulando()")
    i_gen = fuente.index("_narratives_cached(")
    assert i_with < i_gen, "la generación quedó fuera del acumulador"


class TestLaCacheNoLoPersiste:
    """El agujero exacto, medido en producción el 2026-09-02.

    Una descarga generó, el motor marcó la relación invertida, `_narratives_cached` cacheó el
    texto IGUAL, y el gate de entrega respondió 503. La descarga siguiente fue un HIT —el
    motor no corre, así que no emite hallazgos— y **el mismo texto que se acababa de vetar
    salió con 200 en 4,7 segundos**.

    O sea: el veto se esquivaba REINTENTANDO, y lo que quedaba servido en Postgres sin TTL era
    justamente el informe que se había decidido no entregar.

    Sus dos hermanos —fallback estático y cifra sin respaldo— ya se protegían en la escritura;
    éste se quedó afuera. Un guard que existe en dos de tres lugares.
    """

    def _generar(self, product, tier, db, entity="Banco X"):
        from shared.products.assembler import _narratives_cached

        snap = ProductSnapshot(tier=tier, period="2025", payload=dict(_CTX),
                               entity_name=entity)
        return asyncio.run(_narratives_cached(product, tier, snap, "es", "bx"))

    def test_no_se_escribe_fila_con_relacion_invertida(self, db):
        p = _Product(Granularity.named_entity, ProductTier.deep_dive)
        p._db = db
        self._generar(p, ProductTier.deep_dive, db)
        assert db.query(ProductReportCache).count() == 0, (
            "el texto vetado quedó cacheado: la próxima descarga lo sirve con 200 y el veto "
            "se vuelve esquivable reintentando")

    def test_la_sana_SI_se_cachea(self, db):
        """El contrapeso: sin él, este guard podría estar rompiendo la caché entera."""
        p = _Product(Granularity.named_entity, ProductTier.deep_dive, deja_pendiente=False)
        p._db = db
        self._generar(p, ProductTier.deep_dive, db)
        assert db.query(ProductReportCache).count() == 1

    def test_los_TRES_gates_protegen_la_escritura(self):
        """La regla que faltaba, leída del fuente: los tres motivos por los que un informe NO
        se entrega son los tres por los que NO se cachea. Si aparece un cuarto gate y nadie
        lo agrega acá, la caché vuelve a servir lo que la entrega rechaza."""
        import inspect

        from shared.products import assembler

        fuente = inspect.getsource(assembler._narratives_cached)
        for señal in ("is_static_fallback_text", "if sin_respaldo:", "if invertidas:"):
            assert señal in fuente, f"la escritura de caché no se protege de «{señal}»"
