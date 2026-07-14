"""Tests de la capa de research del padrón DGII (§B).

Valida: ``dgii_passages`` emite un pasaje por vertical con el conteo del corte más reciente,
``kind=registry`` + ``meta.state=real`` (→ REAL en el gate) y el caveat embebido; y la
prueba de aceptación end-to-end: la pregunta control ancla REAL citando a DGII."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# importar el orquestador arriba registra sus modelos en Base.metadata (para create_all)
import shared.research.orchestrator as orch
from shared.database.base import Base
from shared.knowledge.ingest import dgii_passages
from shared.registry.signals import REAL
from shared.research.models import Evidence
from shared.reference.models import DgiiContribuyenteSubclase

_CONTROL_Q = "¿Cuántos contribuyentes activos hay en restaurantes de comida rápida en RD?"


def _seed(db, corte=date(2026, 1, 29)):
    data = {"552118": 957, "552113": 1009, "551101": 1897, "523110": 4329, "011111": 5000}
    for code, act in data.items():
        db.add(DgiiContribuyenteSubclase(corte=corte, subclase=code, descripcion="d",
                                         activos=act, source="DGII"))
    db.commit()


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)      # todas las tablas registradas (evita faltantes)
    s = sessionmaker(bind=engine)()
    _seed(s)
    try:
        yield s
    finally:
        s.close()


def test_dgii_passages_emite_verticales_reales_con_caveat(db):
    ps = {p.meta["vertical"]: p for p in dgii_passages(db)}
    # comida rápida = 552118 (957) + 552113 (1009) = 1.966
    cr = ps["comida_rapida"]
    assert "1.966" in cr.text and "comida rápida" in cr.text
    assert "restaurantes de comida rápida" in cr.text        # sinónimo para el retrieval
    assert "no equivale a «cantidad de locales»" in cr.text  # caveat viaja con el dato
    assert cr.kind == "registry" and cr.meta["state"] == "real"
    assert cr.meta["corte"] == "2026-01-29"
    # el estado derivado por el gate es REAL
    assert Evidence.from_passage(cr.as_result(10.0)).state == REAL
    # hoteles (551xxx) y farmacias (523110) también salen
    assert "1.897" in ps["hoteles"].text
    assert "4.329" in ps["farmacias"].text


def test_dgii_passages_sin_db_o_sin_datos_vacio():
    assert dgii_passages(None) == []


@pytest.mark.asyncio
async def test_control_question_ancla_real_citando_dgii(db):
    """Aceptación §B.4: la pregunta control ancla REAL con fuente DGII (no brecha)."""
    ans = await orch.answer_question(_CONTROL_Q, db=db, narrate=False)
    assert any(sq.state == REAL for sq in ans.sub_questions)
    assert any("DGII" in s for s in ans.sources)
    assert ans.coverage_real > 0
