"""Tests del Entorno Operativo (Fase 4): contrato macro compartido + sección del deep dive."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.settings.models import AppSetting
from shared.contracts import APP_SETTING_KEY, load_macro_contract
from modules.banking_score.reports.narrative import (
    _SECTION_TO_TEMPLATE, _build_section_context)
from modules.banking_score.reports.pdf_generator import _build_macro_table, _get_styles


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__])
    return sessionmaker(bind=engine)()


_CONTRACT = {
    "period": "2026-06",
    "factors": [
        {"key": "inflation", "label": "Inflación interanual", "value": 5.35, "unit": "%",
         "direction": "adverso", "magnitude": "moderado", "reading": "5.35%, sobre meta"},
        {"key": "activity", "label": "Actividad (IMAE)", "value": 4.2, "unit": "%",
         "direction": "favorable", "magnitude": "alto", "reading": "expansión sostenida"},
        {"key": "reserves", "label": "Reservas", "value": None, "unit": None,
         "direction": "n/d", "magnitude": "n/d", "reading": ""},
    ],
}


def test_load_macro_contract_absent_returns_empty(db):
    assert load_macro_contract(db) == {}


def test_load_macro_contract_parses(db):
    db.add(AppSetting(key=APP_SETTING_KEY, value=json.dumps(_CONTRACT), is_secret=False))
    db.commit()
    c = load_macro_contract(db)
    assert c["period"] == "2026-06"
    assert len(c["factors"]) == 3


def test_load_macro_contract_bad_json_returns_empty(db):
    db.add(AppSetting(key=APP_SETTING_KEY, value="{not json", is_secret=False))
    db.commit()
    assert load_macro_contract(db) == {}


def test_section_maps_to_operating_env_template():
    assert _SECTION_TO_TEMPLATE["entorno_operativo"] == "banking_operating_env"


def test_build_section_context_entorno_operativo():
    scoring = {
        "rating_tier": "SDQ-AA",
        "entorno_macro": {"period": "2026-06", "factors": _CONTRACT["factors"][:2]},
    }
    ctx = _build_section_context("entorno_operativo", "Banco X", scoring, "2026-03-31")
    assert ctx["entity_name"] == "Banco X"
    assert ctx["rating_tier"] == "SDQ-AA"
    assert ctx["entorno_macro"]["period"] == "2026-06"
    assert len(ctx["entorno_macro"]["factors"]) == 2
    # No arrastra indicadores de la entidad (es telón sistémico, no perfil del banco).
    assert "indicators" not in ctx and "indicadores" not in ctx


def test_build_macro_table_renders_available_factors():
    els = _build_macro_table({"period": "2026-06", "factors": _CONTRACT["factors"]}, _get_styles())
    assert els  # no vacío
    # La tabla es el segundo elemento (tras el título).
    from reportlab.platypus import Table
    tables = [e for e in els if isinstance(e, Table)]
    assert len(tables) == 1
    # header + 3 filas de factores (incluye la n/d, que el snapshot ya filtró aguas arriba)
    assert len(tables[0]._cellvalues) == 4


def test_build_macro_table_empty_when_no_factors():
    assert _build_macro_table({"period": "2026-06", "factors": []}, _get_styles()) == []
    assert _build_macro_table({}, _get_styles()) == []
