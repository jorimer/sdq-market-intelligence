"""Gate de CIFRA SIN RESPALDO — el gemelo del de degradación, para el otro informe malo.

Reproduce el defecto real: **el 152 % llegó a un PDF de rating**. El guard marcó la cifra, el
texto sobrevivió a la regeneración y el informe se emitió igual con `guard_flags=1` — porque
la marca no tenía ningún consumidor: era una etiqueta en una línea de log.

La degradación deja una sección HUECA y se nota. Ésta la deja LLENA con un número que nadie
puede respaldar, que se lee como hallazgo y viaja citado. Por eso falla igual de cerrado.

Contrato que fijan estos tests:

  * PREMIUM (nombrado) con ≥1 sección de análisis que afirma una cifra sin respaldo → lanza
    ``NarrativeSinRespaldoError``, con la sección y los hallazgos LISTADOS.
  * PULSE (sistema/abierto) → solo se registra; no rompe la entrega.
  * La caché de narrativas NUNCA persiste ese texto: vive en Postgres y no tiene TTL, así que
    una cifra sin respaldo cacheada se sirve idéntica y en silencio para siempre.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.narrative.claude_engine import (NarrativeSinRespaldoError,
                                            secciones_con_cifra_sin_respaldo)
from shared.products import (Granularity, ProductTier, SectorProductManifest, TierLevelSpec)
from shared.products.assembler import _content_from_snapshot, _narratives_cached
from shared.products.contract import ProductSnapshot
from shared.products.models import ProductReportCache  # noqa: F401 — registra la tabla

_SECTIONS = ("assessment", "peer_positioning", "recommendation")

#: El contexto sostiene 185,0 y NADA más. Es el caso real: la constante hardcodeada era 185
#: y el panel daba 152,1.
_CTX = {"has_data": True, "cobertura_provisiones": 185.0}
_SIN_RESPALDO = "La cobertura de provisiones del sistema se ubica en 152,1% al cierre."
_CON_RESPALDO = "La cobertura de provisiones del sistema es 185,0% al cierre."


class _Product:
    sector_key = "banking_score"

    def __init__(self, granularity, tier, textos, db=None):
        self._gran, self._tier, self._textos, self._db = granularity, tier, textos, db
        self.calls = 0

    def product_manifest(self):
        return SectorProductManifest(
            sector_key=self.sector_key, display_name="Fake", levels={
                self._tier: TierLevelSpec(
                    tier=self._tier, granularity=self._gran, sections=_SECTIONS,
                    narrative_templates=(), audience="x", cadence="on_demand",
                    price_band="x")})

    async def narratives(self, tier, snapshot, lang="es"):
        self.calls += 1
        return dict(self._textos)


def _snap(tier, entity):
    return ProductSnapshot(tier=tier, period="2025", payload=dict(_CTX), entity_name=entity)


def _todas(texto):
    return {s: texto for s in _SECTIONS}


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


class TestElDetector:
    def test_marca_la_cifra_que_el_contexto_no_sostiene(self):
        h = secciones_con_cifra_sin_respaldo(_todas(_SIN_RESPALDO), _SECTIONS, _CTX)
        assert set(h) == set(_SECTIONS)
        assert any("152,1" in f for f in h["assessment"])

    def test_la_cifra_que_SI_esta_en_el_contexto_pasa(self):
        """El contrapeso: sin él, el gate bloquearía todo informe con números."""
        assert secciones_con_cifra_sin_respaldo(_todas(_CON_RESPALDO), _SECTIONS, _CTX) == {}

    def test_una_seccion_vacia_no_es_un_hallazgo(self):
        assert secciones_con_cifra_sin_respaldo({"assessment": ""}, ["assessment"], _CTX) == {}


class TestElGatePremium:
    def test_un_deep_dive_con_cifra_sin_respaldo_NO_se_entrega(self):
        p = _Product(Granularity.named_entity, ProductTier.deep_dive, _todas(_SIN_RESPALDO))
        with pytest.raises(NarrativeSinRespaldoError) as ei:
            asyncio.run(_content_from_snapshot(
                p, ProductTier.deep_dive, _snap(ProductTier.deep_dive, "Banco X"),
                "es", scope="bx"))
        assert set(ei.value.hallazgos) == set(_SECTIONS)

    def test_el_veto_se_LISTA_no_es_silencioso(self):
        """Un veto silencioso se lee como que el informe no existía. El error nombra la
        sección y trae los hallazgos, que es lo que permite ir a arreglarlo."""
        p = _Product(Granularity.named_entity, ProductTier.insight,
                     {"assessment": _SIN_RESPALDO, "peer_positioning": _CON_RESPALDO,
                      "recommendation": "Prosa sin cifras."})
        with pytest.raises(NarrativeSinRespaldoError) as ei:
            asyncio.run(_content_from_snapshot(
                p, ProductTier.insight, _snap(ProductTier.insight, "Banco X"),
                "es", scope="bx"))
        assert list(ei.value.hallazgos) == ["assessment"]     # umbral = 1
        assert "assessment" in str(ei.value)
        assert any("152,1" in f for f in ei.value.hallazgos["assessment"])

    def test_una_narrativa_sana_se_entrega(self):
        p = _Product(Granularity.named_entity, ProductTier.deep_dive, _todas(_CON_RESPALDO))
        c = asyncio.run(_content_from_snapshot(
            p, ProductTier.deep_dive, _snap(ProductTier.deep_dive, "Banco X"),
            "es", scope="bx"))
        assert c.narratives["assessment"] == _CON_RESPALDO

    def test_el_pulse_abierto_solo_se_registra(self):
        """Misma política que la degradación: el nivel abierto no rompe la entrega."""
        p = _Product(Granularity.system, ProductTier.pulse, _todas(_SIN_RESPALDO))
        c = asyncio.run(_content_from_snapshot(
            p, ProductTier.pulse, _snap(ProductTier.pulse, None), "es", scope=None))
        assert c.narratives["assessment"] == _SIN_RESPALDO


class TestLaCacheNoLoPersiste:
    """Esta tabla vive en Postgres y NO tiene TTL: lo que entre se sirve para siempre."""

    def test_no_se_escribe_fila_con_cifra_sin_respaldo(self, db):
        p = _Product(Granularity.named_entity, ProductTier.deep_dive,
                     _todas(_SIN_RESPALDO), db=db)
        asyncio.run(_narratives_cached(p, ProductTier.deep_dive,
                                       _snap(ProductTier.deep_dive, "Banco X"), "es", "bx"))
        assert db.query(ProductReportCache).count() == 0, (
            "una cifra sin respaldo cacheada se sirve idéntica en cada descarga posterior")

    def test_la_sana_SI_se_cachea(self, db):
        """El contrapeso: sin él, este guard podría estar rompiendo la caché entera."""
        p = _Product(Granularity.named_entity, ProductTier.deep_dive,
                     _todas(_CON_RESPALDO), db=db)
        asyncio.run(_narratives_cached(p, ProductTier.deep_dive,
                                       _snap(ProductTier.deep_dive, "Banco X"), "es", "bx"))
        assert db.query(ProductReportCache).count() == 1


def test_el_motor_no_propaga_a_la_cache_compartida_lo_que_el_mismo_marco(monkeypatch):
    """La otra mitad: el juez semántico del motor ve cosas que el determinista no.

    Si el motor escribe en L2 un texto que él marcó, esa cifra sobrevive a la corrida que la
    produjo — es exactamente cómo un hallazgo del guard terminó citado en un PDF.
    """
    from shared.narrative import claude_engine as ce

    escrituras = []
    monkeypatch.setattr(ce, "cache_set", lambda k, v, ttl: escrituras.append(k))

    motor = ce.NarrativeEngine.__new__(ce.NarrativeEngine)
    motor._cache = {}

    limpio = ce.NarrativeResult(text="ok", model_used="claude-sonnet-4-6")
    motor._set_cache("k-limpia", limpio)
    assert len(escrituras) == 1, "una narrativa limpia SÍ se comparte"

    marcado = ce.NarrativeResult(text="152,1%", model_used="claude-sonnet-4-6",
                                 guard_unsupported=["152,1%: no aparece en el contexto"])
    antes = len(escrituras)
    motor._set_cache("k-marcada", marcado)
    assert len(escrituras) == antes, "el texto marcado no puede llegar a la caché compartida"
    assert "k-marcada" in motor._cache, "sí queda en L1: no hay que re-pagar la generación"
