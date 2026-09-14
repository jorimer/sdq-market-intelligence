"""El Pulse de seguros le pasa su ROSTER al sensor de anonimización — y el sensor lo usa.

Hasta el 2026-09-14 el `ProductSnapshot` del Pulse salía sin `entity_roster`: el ensamblador
corría `enforce_anonymized` sobre el texto con un roster vacío, que solo mira claves reservadas,
y un Pulse que nombrara una aseguradora o una ARS se entregaba. Estos tests ensamblan el Pulse
de verdad, con el roster que arma el producto desde sus dos fuentes: la tabla de entidades y el
mapa de nombres oficiales de las ARS del conector.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.sisalril_ars_client import ARS_NAMES
from shared.database.base import Base
from shared.products import AnonymizationError, ProductTier, assemble_product_content
from modules.insurance_intel.models.models import InsuranceEntity
from modules.insurance_intel.products import InsuranceProduct

_ASEGURADORA = "Seguros Ejemplo Persistida"
_ARS = sorted(ARS_NAMES.values(), key=len)[-1]  # la más larga: sin ambigüedad de substring


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(InsuranceEntity(slug="seguros_ejemplo", name=_ASEGURADORA, entity_type="aseguradora"))
    s.commit()
    # El pulso de mercado se arma de las series del SIS; acá importa el ROSTER, no el pulso.
    monkeypatch.setattr(
        "modules.insurance_intel.products._pulse",
        lambda db, as_of=None: {"has_data": True, "period": "2026-03", "latest_year": "2025",
                                "total_premiums_rd": 1.5e11, "n_ramos": 11})
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _ensamblar(db, monkeypatch, texto):
    async def _narrativas(product, tier, snapshot, lang, scope):
        return {"insurance_pulse": texto}

    monkeypatch.setattr("shared.products.assembler._narratives_cached", _narrativas)
    return asyncio.run(assemble_product_content(InsuranceProduct(db), ProductTier.pulse,
                                                period=""))


def test_el_roster_trae_las_aseguradoras_persistidas_y_las_ars_del_conector(db):
    snap = InsuranceProduct(db).snapshot(ProductTier.pulse, "")
    assert snap.entity_name is None
    assert _ASEGURADORA in snap.entity_roster
    assert _ARS in snap.entity_roster
    assert _ASEGURADORA not in str(snap.payload)


@pytest.mark.parametrize("nombre", [_ASEGURADORA, _ARS])
def test_un_pulse_cuyo_TEXTO_nombra_una_entidad_no_se_entrega(db, monkeypatch, nombre):
    with pytest.raises(AnonymizationError):
        _ensamblar(db, monkeypatch, f"{nombre} concentra la mayor parte de las primas del año.")


def test_un_pulse_anonimo_se_entrega(db, monkeypatch):
    content = _ensamblar(db, monkeypatch,
                         "El mercado asegurador creció y la concentración por ramo se mantuvo.")
    assert content.narratives["insurance_pulse"].startswith("El mercado asegurador")
