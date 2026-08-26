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
from shared.narrative.claude_engine import NarrativeSinRespaldoError
from shared.narrative.cifras_pendientes import registrar as registrar_cifras
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

    #: Qué marcó el guard del motor para cada texto. La clave es el TEXTO porque los tests
    #: se leen mejor así: `_SIN_RESPALDO` viene marcado, `_CON_RESPALDO` no.
    _marcas = {_SIN_RESPALDO: ["152,1%: no coincide con ningún valor servido"]}

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
        """Hace lo que hace el motor REAL: genera y DEPOSITA lo que su guard marcó.

        El fake deposita porque el motor deposita. Antes este fake solo devolvía texto y la
        superficie lo re-juzgaba: eso es justamente lo que se eliminó, porque la superficie
        juzgaba con el snapshot y no con el contexto que produjo el texto.
        """
        self.calls += 1
        for seccion, texto in self._textos.items():
            if self._marcas.get(texto):
                registrar_cifras(seccion, list(self._marcas[texto]))
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
    """El detector ya NO vive en la superficie: vive en el motor, que tiene el contexto.

    Estos casos fijan que el chequeo determinista sigue distinguiendo lo mismo — pero contra
    el contexto REAL de la sección, que es la corrección de 2026-08-26.
    """

    def test_marca_la_cifra_que_el_contexto_no_sostiene(self):
        from shared.narrative.numeric_guard import deterministic_uncited_figures
        assert deterministic_uncited_figures(_CTX, _SIN_RESPALDO)

    def test_la_cifra_que_SI_esta_en_el_contexto_pasa(self):
        """El contrapeso: sin él, el gate bloquearía todo informe con números."""
        from shared.narrative.numeric_guard import deterministic_uncited_figures
        assert deterministic_uncited_figures(_CTX, _CON_RESPALDO) == []

    def test_una_seccion_vacia_no_es_un_hallazgo(self):
        from shared.narrative.numeric_guard import deterministic_uncited_figures
        assert deterministic_uncited_figures(_CTX, "") == []


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
    # Ni a L1. La versión anterior de este test exigía lo contrario —«sí queda en L1: no hay
    # que re-pagar la generación»— y esa decisión volvía INSERVIBLE el reintento que el propio
    # mensaje de veto promete. Ver `test_lo_marcado_no_queda_NI_en_L1_...` más abajo.
    assert "k-marcada" not in motor._cache


def test_lo_marcado_no_queda_NI_en_L1_para_que_el_reintento_regenere(monkeypatch):
    """El veto promete «reintente, el texto se regenera». Con L1 guardándolo, mentía.

    Medido en producción contra el SDQ Rating de Asociación Bonao al 2025-03-31: la primera
    generación tardó 264 s y se vetó; el reintento devolvió **el mismo veto en 4,7 s** —un HIT
    de L1—. El informe quedaba muerto hasta que expirara el TTL o el request cayera en otro
    worker, o sea al azar, y cada reintento del usuario era un no-op disfrazado de espera.

    La justificación vieja de conservarlo en L1 —«no re-pagar la generación dentro de la misma
    corrida»— no compraba nada: la clave incluye contexto y plantilla, así que dentro de una
    corrida se pide una sola vez.
    """
    from shared.narrative import claude_engine as ce

    monkeypatch.setattr(ce, "cache_set", lambda k, v, ttl: None)
    motor = ce.NarrativeEngine.__new__(ce.NarrativeEngine)
    motor._cache = {}

    marcado = ce.NarrativeResult(text="38%", model_used="claude-sonnet-4-6",
                                 guard_unsupported=["38%: no coincide con ningún valor servido"],
                                 guard_cifras=["38%: no coincide con ningún valor servido"])
    motor._set_cache("k", marcado)
    assert "k" not in motor._cache, (
        "el texto marcado quedó en L1: el reintento devolverá el mismo veto sin regenerar")
    assert motor._get_cached("k") is None


def test_lo_limpio_SI_queda_en_L1():
    """El contrapeso: sin él, la regla de arriba se satisface tirando la caché entera —y esa
    caché existe para que la descarga no espere 15-90 s."""
    from shared.narrative import claude_engine as ce

    motor = ce.NarrativeEngine.__new__(ce.NarrativeEngine)
    motor._cache = {}
    motor._set_cache("k", ce.NarrativeResult(text="ok", model_used="claude-sonnet-4-6"))
    assert "k" in motor._cache


def test_un_ensamblado_que_excede_el_techo_responde_503_y_no_muere_en_el_proxy(monkeypatch):
    """Sin techo, una generación larga muere en el PROXY con un 502 SIN CUERPO.

    El frontend lee `detail` para mostrar el motivo; un 502 no lo trae, así que el usuario ve
    «No se pudo cargar el producto» — un producto roto en vez de una explicación. Pasó con la
    Revisión Anual, donde el guard reintentaba sobre umbrales prospectivos y la petición
    llegaba a 16 llamadas al modelo para dos secciones.

    El 503 de degradación es la respuesta correcta porque es lo que de verdad ocurrió: el
    servicio de análisis no entregó a tiempo, y reintentar sirve.
    """
    import asyncio as _asyncio

    from shared.narrative.claude_engine import NarrativeDegradedError
    from shared.products import assembler as A

    monkeypatch.setattr(A, "PRESUPUESTO_DE_ENSAMBLADO_S", 0.05)

    async def _eterna(*a, **kw):
        await _asyncio.sleep(5)
        return {}

    monkeypatch.setattr(A, "_narratives_cached", _eterna)
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, _todas(_CON_RESPALDO))
    with pytest.raises(NarrativeDegradedError):
        asyncio.run(_content_from_snapshot(
            p, ProductTier.deep_dive, _snap(ProductTier.deep_dive, "Banco X"),
            "es", scope="bx"))


def test_un_ensamblado_NORMAL_no_se_corta():
    """El contrapeso: sin él, la regla se satisface poniendo el techo en cero."""
    from shared.products import assembler as A
    assert A.PRESUPUESTO_DE_ENSAMBLADO_S >= 120, (
        "un techo bajo convertiría informes buenos en 503; el límite del proxy son ~300 s")
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, _todas(_CON_RESPALDO))
    c = asyncio.run(_content_from_snapshot(
        p, ProductTier.deep_dive, _snap(ProductTier.deep_dive, "Banco X"), "es", scope="bx"))
    assert c.narratives["assessment"] == _CON_RESPALDO
