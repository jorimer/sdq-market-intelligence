"""El Pulse de la Revisión Anual le pasa su ROSTER al sensor — y el sensor lo usa.

`test_producto_revision_anual` ya prueba que el payload del año del sistema se arma por lista
blanca. Lo que no probaba nadie es el TEXTO: el snapshot del Pulse salía sin `entity_roster`, así
que `enforce_anonymized` sobre las narrativas solo miraba claves reservadas y un año del sistema
que dijera «Banco X cambió de banda» se entregaba en el nivel abierto.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products import AnonymizationError, ProductTier, assemble_product_content
from modules.banking_score.models.models import Bank, BankType
from modules.banking_score.products_year_review import BankingYearReviewProduct
from modules.banking_score.tests.test_producto_revision_anual import _anuario_falso

_ENTIDAD = "Banco Múltiple Caribe Internacional"
#: Una entidad que ya no aparece en el año —absorbida, liquidada— tampoco se puede nombrar.
_ABSORBIDA = "Banco de Ahorro y Crédito Absorbido"


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(Bank(name=_ENTIDAD, bank_type=BankType.banca_multiple))
    s.add(Bank(name=_ABSORBIDA, bank_type=BankType.banca_multiple))
    s.commit()
    monkeypatch.setattr("modules.banking_score.reports.anuario._anios_con_cierre",
                        lambda db: [2025])
    monkeypatch.setattr("modules.banking_score.reports.anuario.anuario_del_sistema",
                        lambda db, anio: _anuario_falso(anio))
    monkeypatch.setattr("modules.banking_score.reports.mapa_sectorial.sistema_por_sector",
                        lambda db, corte: None)
    monkeypatch.setattr("modules.banking_score.reports.mapa_sectorial.motivo_sin_mapa",
                        lambda db, corte, bank: "sin cubo de créditos en la prueba")
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _ensamblar(db, monkeypatch, texto):
    async def _narrativas(product, tier, snapshot, lang, scope):
        return {"anio_del_sistema": texto}

    monkeypatch.setattr("shared.products.assembler._narratives_cached", _narrativas)
    return asyncio.run(assemble_product_content(BankingYearReviewProduct(db), ProductTier.pulse,
                                                period="2025"))


def test_el_roster_es_el_padron_entero_y_no_viaja_en_el_payload(db):
    snap = BankingYearReviewProduct(db).snapshot(ProductTier.pulse, "2025")
    assert snap.entity_name is None
    assert {_ENTIDAD, _ABSORBIDA} <= set(snap.entity_roster)
    assert _ABSORBIDA not in str(snap.payload)


@pytest.mark.parametrize("nombre", [_ENTIDAD, _ABSORBIDA])
def test_un_anio_del_sistema_cuyo_TEXTO_nombra_una_entidad_no_se_entrega(db, monkeypatch, nombre):
    with pytest.raises(AnonymizationError):
        _ensamblar(db, monkeypatch, f"En el año, {nombre} pasó de Adecuada a En vigilancia.")


def test_un_anio_del_sistema_anonimo_se_entrega(db, monkeypatch):
    content = _ensamblar(db, monkeypatch,
                         "La mediana del sistema cayó en el año y el deterioro superó a la mejora.")
    assert content.narratives["anio_del_sistema"].startswith("La mediana")
