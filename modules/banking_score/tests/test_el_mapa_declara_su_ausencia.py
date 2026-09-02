"""El informe no puede prometer 17 secciones y entregar 16 sin decir por qué.

Verificando el Deep Dive punta a punta en producción (2026-09-02, Banco Popular) apareció
que `commercial.sections` declara 17 y `narratives` trae 16: faltaba `mapa_sectorial`, y
desaparecía en silencio.

La omisión del DATO es correcta —una tabla de guiones se leería como «esta entidad no
presta»— pero la de la SECCIÓN no: el comprador ve una sección prometida que no está.

Y no es un caso raro. El cubo de crédito de la SB va un trimestre detrás de los estados
financieros, así que al informe del trimestre CORRIENTE le falta SIEMPRE — que es el que se
vende. Medido sobre 89 entidades en un corte con cubo: 48 sin mapa.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.banking_score.models.models import Bank, BankType, BankingData
from modules.banking_score.reports.mapa_sectorial import (
    MOTIVO_ENTIDAD_SIN_DESGLOSE, MOTIVO_FUENTE_SIN_PUBLICAR, MOTIVO_NO_OTORGA_CREDITO,
    motivo_sin_mapa,
)
from shared.database.base import Base
from shared.reference.cartera_sectorial import CarteraSectorial

CORTE = date(2025, 6, 30)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _banco(db, nombre, tipo=BankType.banca_multiple):
    b = Bank(name=nombre, bank_type=tipo)
    db.add(b)
    db.flush()
    db.add(BankingData(bank_id=b.id, period_end=CORTE))
    db.commit()
    return b


class TestLasTRESAusenciasSeDistinguen:
    """Hasta hoy se veían todas iguales: la sección no estaba. Cada una autoriza a decir
    algo distinto, y confundirlas hace que un trimestre sin publicar se lea como una
    característica del banco evaluado."""

    def test_la_entidad_NO_PRESTA(self, db):
        """46 de las 89 entidades supervisadas. Decirles «no registra cartera clasificada»
        es cierto y se lee como una deficiencia: no prestan, no hay cartera que clasificar."""
        cambiaria = _banco(db, "Agente de Cambio", BankType.cambiaria)
        otro = _banco(db, "Banco Con Cubo")
        db.add(CarteraSectorial(bank_id=otro.id, period_end=CORTE,
                                sector="F - CONSTRUCCIÓN", provincia="SANTIAGO", deuda=100))
        db.commit()
        assert motivo_sin_mapa(db, CORTE, cambiaria) == MOTIVO_NO_OTORGA_CREDITO

    def test_la_FUENTE_no_publicó_el_trimestre(self, db):
        """El caso más frecuente en el informe más nuevo: el cubo va un trimestre atrás."""
        banco = _banco(db, "Banco Múltiple")
        assert motivo_sin_mapa(db, CORTE, banco) == MOTIVO_FUENTE_SIN_PUBLICAR

    def test_la_ENTIDAD_no_está_en_el_cubo_del_sistema(self, db):
        """Ojo con este: era lo que PARECÍA pasarle a FONDESA y al Caribe, y resultó ser un
        fallo NUESTRO de emparejamiento. Un hueco acá merece comprobarse antes de darlo por
        bueno — declararlo a la ligera escribe un motivo falso sobre datos que sí existen."""
        falta = _banco(db, "Banco Sin Cubo")
        otro = _banco(db, "Banco Con Cubo")
        db.add(CarteraSectorial(bank_id=otro.id, period_end=CORTE,
                                sector="F - CONSTRUCCIÓN", provincia="SANTIAGO", deuda=100))
        db.commit()
        assert motivo_sin_mapa(db, CORTE, falta) == MOTIVO_ENTIDAD_SIN_DESGLOSE

    def test_los_tres_motivos_son_DISTINTOS(self, db):
        """Sin esto, los tests de arriba pasarían con una función que devuelve siempre lo
        mismo — que es exactamente el estado del que venimos."""
        assert len({MOTIVO_NO_OTORGA_CREDITO, MOTIVO_FUENTE_SIN_PUBLICAR,
                    MOTIVO_ENTIDAD_SIN_DESGLOSE}) == 3


class TestLoPrometidoYLoEntregado:

    def test_el_manifiesto_del_deep_dive_promete_el_mapa(self):
        """Si dejara de prometerlo, el resto de este archivo no protegería nada."""
        from modules.banking_score.products import BankingProduct
        from shared.products.contract import ProductTier

        manifiesto = BankingProduct().product_manifest().require_level(ProductTier.deep_dive)
        assert "mapa_sectorial" in manifiesto.sections

    @pytest.mark.asyncio
    async def test_sin_mapa_la_seccion_SIGUE_estando_con_su_motivo(self, db, monkeypatch):
        """LA REGRESIÓN. Antes la sección se quitaba de la lista y desaparecía del informe."""
        from modules.banking_score import products as mod
        from shared.products.contract import ProductSnapshot, ProductTier

        banco = _banco(db, "Banco Múltiple")
        del banco
        snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2025-06-30",
                               payload={"scoring_result": {}, "peer_block": None},
                               entity_name="Banco Múltiple", entity_roster=())

        async def _sin_ia(secciones, *a, **k):
            return {s: f"prosa de {s}" for s in secciones}

        monkeypatch.setattr(mod, "generate_named_narratives", _sin_ia)
        out = await mod.BankingProduct(db=db).narratives(ProductTier.deep_dive, snap)
        assert "mapa_sectorial" in out, "la sección volvió a desaparecer en silencio"
        assert out["mapa_sectorial"] == MOTIVO_FUENTE_SIN_PUBLICAR

    @pytest.mark.asyncio
    async def test_un_fallo_al_computar_el_motivo_NO_tumba_el_informe(self, monkeypatch):
        """Sin sesión no hay entidad que resolver. Que falte la sección es un empate con el
        comportamiento anterior; que se caiga el informe entero no lo es."""
        from modules.banking_score import products as mod
        from shared.products.contract import ProductSnapshot, ProductTier

        snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2025-06-30",
                               payload={"scoring_result": {}, "peer_block": None},
                               entity_name="X", entity_roster=())

        async def _sin_ia(secciones, *a, **k):
            return {s: "prosa" for s in secciones}

        monkeypatch.setattr(mod, "generate_named_narratives", _sin_ia)
        out = await mod.BankingProduct(db=None).narratives(ProductTier.deep_dive, snap)
        assert "mapa_sectorial" not in out
