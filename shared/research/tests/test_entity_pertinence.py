"""Tests del match de entidad ambiguo + candado de pertinencia (caso McDonald's→Citibank).

El informe "¿dónde ubicar una sucursal nueva de McDonald's?" quedó anclado a
"Citibank N.A. Sucursal República Dominicana" porque "sucursal" contaba como token
distintivo. Tres capas lo impiden ahora:
1. "sucursal"/"ahorros"/"prestamos" son stopwords (forma legal, no identidad).
2. Un token AMBIGUO ('popular', 'motor', 'reservas'…) solo ancla con el eje corroborante.
3. ``entity_check``: el Cerebro veta matches débiles (solo descarta, nunca agrega).
"""
from types import SimpleNamespace

import pytest

import shared.research.entity_check as ec
import shared.research.resolve as res
from shared.research.resolve import (
    ResolvedEntity,
    _distinctive_tokens,
    detect_axes,
    finalize_targets,
    resolve_entities,
)

_MCDONALDS_Q = "Donde se podría ubicar una sucursal nueva de McDonalds y que potencial tendría?"

_ROSTER = [
    {"value": "citibank", "label": "Citibank N.A. Sucursal República Dominicana"},
    {"value": "popular", "label": "Banco Popular Dominicano"},
    {"value": "lafise", "label": "Banco Múltiple Lafise"},
    {"value": "bonao", "label": "Asociación Bonao de Ahorros y Préstamos"},
    {"value": "motor", "label": "Motor Crédito Banco de Ahorro y Crédito"},
    {"value": "banreservas", "label": "Banco de Reservas de la República Dominicana"},
]


class _FakeProduct:
    def scope_options(self):
        return _ROSTER


def _patch_roster(monkeypatch):
    monkeypatch.setattr(res, "PRODUCT_CATALOG", [SimpleNamespace(sector_key="banking")])
    monkeypatch.setattr(res, "is_implemented", lambda sk: sk == "banking")
    monkeypatch.setattr(res, "get_product", lambda sk, db: _FakeProduct())


# ─── capa 1: forma legal como stopword ─────────────────────────────────
def test_sucursal_no_es_token_distintivo():
    assert _distinctive_tokens("Citibank N.A. Sucursal República Dominicana") == ["citibank"]


def test_ahorros_prestamos_no_son_distintivos():
    assert _distinctive_tokens("Asociación Bonao de Ahorros y Préstamos") == ["bonao"]


# ─── capa 2: corroboración del eje para tokens ambiguos ────────────────
def test_pregunta_mcdonalds_no_resuelve_entidad(monkeypatch):
    _patch_roster(monkeypatch)
    axes = detect_axes(_MCDONALDS_Q)
    assert axes == []
    entities = resolve_entities(_MCDONALDS_Q, db=object(), axes=axes or None)
    assert entities == []
    targets = finalize_targets(_MCDONALDS_Q, axes, entities)
    assert targets.is_empty and targets.context == []


def test_banco_popular_sigue_resolviendo_con_eje(monkeypatch):
    _patch_roster(monkeypatch)
    q = "¿Qué tan sólido es el Banco Popular Dominicano?"
    axes = detect_axes(q)
    assert "banking" in axes
    entities = resolve_entities(q, db=object(), axes=axes)
    assert [e.scope_value for e in entities] == ["popular"]
    # ambiguo+eje = aceptado pero DÉBIL → lo re-verifica el Cerebro.
    assert entities[0].weak is True


def test_lafise_token_fuerte_resuelve_sin_eje(monkeypatch):
    _patch_roster(monkeypatch)
    q = "¿Cómo está Lafise?"
    entities = resolve_entities(q, db=object(), axes=None)
    assert [e.scope_value for e in entities] == ["lafise"]
    assert entities[0].weak is True  # fuerte pero SIN eje → débil (se verifica)


def test_lafise_fuerte_mas_eje_es_confianza_plena(monkeypatch):
    _patch_roster(monkeypatch)
    q = "¿Cuál es el rating de Lafise?"
    axes = detect_axes(q)
    entities = resolve_entities(q, db=object(), axes=axes)
    assert [e.scope_value for e in entities] == ["lafise"]
    assert entities[0].weak is False


def test_motor_de_la_economia_no_resuelve_motor_credito(monkeypatch):
    _patch_roster(monkeypatch)
    q = "¿Cuál es el motor de la economía dominicana este año?"
    entities = resolve_entities(q, db=object(), axes=detect_axes(q) or None)
    assert entities == []


def test_prestamos_del_sistema_no_cuelga_de_una_asociacion(monkeypatch):
    _patch_roster(monkeypatch)
    q = "¿Están creciendo los préstamos en el sistema?"
    axes = detect_axes(q)
    assert "banking" in axes  # 'prestamo' ahora rutea el eje…
    entities = resolve_entities(q, db=object(), axes=axes)
    assert entities == []  # …pero ninguna asociación cuelga de 'prestamos'


# ─── capa 3: candado del Cerebro (solo descarta, fail-safe conserva) ───
def _weak_citibank():
    return ResolvedEntity(sector_key="banking", scope_value="citibank",
                          label="Citibank N.A. Sucursal República Dominicana",
                          matched_on="sucursal", weak=True)


@pytest.mark.asyncio
async def test_entity_check_descarta_y_recomputa_contexto(monkeypatch):
    targets = finalize_targets(_MCDONALDS_Q, [], [_weak_citibank()])
    assert targets.context  # la entidad espuria sembró contexto (monetario/macro)

    async def _no(question, entity):
        return False
    monkeypatch.setattr(ec, "_is_about_entity", _no)
    await ec.verify_entity_pertinence(_MCDONALDS_Q, targets)
    assert targets.entities == []
    assert targets.context == []  # el contexto sembrado por la entidad falsa no sobrevive


@pytest.mark.asyncio
async def test_entity_check_sin_veredicto_conserva(monkeypatch):
    targets = finalize_targets(_MCDONALDS_Q, [], [_weak_citibank()])

    async def _none(question, entity):
        return None  # sin Cerebro/presupuesto/error
    monkeypatch.setattr(ec, "_is_about_entity", _none)
    await ec.verify_entity_pertinence(_MCDONALDS_Q, targets)
    assert len(targets.entities) == 1  # fail-safe: conservar


@pytest.mark.asyncio
async def test_entity_check_no_toca_matches_fuertes(monkeypatch):
    strong = ResolvedEntity(sector_key="banking", scope_value="lafise",
                            label="Banco Múltiple Lafise", matched_on="lafise", weak=False)
    targets = finalize_targets("rating de Lafise", ["banking"], [strong])

    async def _boom(question, entity):
        raise AssertionError("no debe verificar matches fuertes")
    monkeypatch.setattr(ec, "_is_about_entity", _boom)
    await ec.verify_entity_pertinence("rating de Lafise", targets)
    assert len(targets.entities) == 1
