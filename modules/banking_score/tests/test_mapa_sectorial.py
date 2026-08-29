"""El mapa sectorial: la posición de una entidad en el libro del SISTEMA, por sector.

Lo que fija este archivo es la ATRIBUCIÓN — separar si el deterioro de una entidad en un
sector es suyo o del sector—, que es la lectura que ningún banco puede producir con su
propio libro y por la que existe toda la tabla `cartera_sectorial`.
"""
from datetime import date

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra users para las FK
from shared.database.base import Base
from modules.banking_score.models.models import Bank, BankType, CarteraSectorial
from modules.banking_score.reports import mapa_sectorial as ms

CORTE = date(2025, 12, 31)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.fixture
def db_con_panel(db_session):
    """Dos entidades en construcción: una peor que el sector, otra igual que el sector."""
    mala = Bank(name="Banco Malo en Construcción", bank_type=BankType.banca_multiple)
    sana = Bank(name="Banco Alineado", bank_type=BankType.banca_multiple)
    db_session.add_all([mala, sana])
    db_session.flush()
    filas = [
        # (banco, sector, provincia, deuda, vencida, temprana)
        (mala, "F - CONSTRUCCIÓN", "DISTRITO NACIONAL", 100_000_000, 12_000_000, 4_000_000),
        (mala, "G - COMERCIO", "DISTRITO NACIONAL", 50_000_000, 1_000_000, 500_000),
        (sana, "F - CONSTRUCCIÓN", "SANTIAGO", 100_000_000, 2_000_000, 400_000),
        (sana, "F - CONSTRUCCIÓN", "LA VEGA", 100_000_000, 2_000_000, 400_000),
    ]
    for banco, sector, prov, deuda, venc, temp in filas:
        db_session.add(CarteraSectorial(
            bank_id=banco.id, period_end=CORTE, sector=sector, provincia=prov,
            deuda=deuda, vencida=venc, vencida_31_90=temp))
    db_session.commit()
    return db_session, mala, sana


class TestElSistemaPorSector:
    def test_agrega_sobre_provincias_Y_entidades(self, db_con_panel):
        db, _, _ = db_con_panel
        s = {x["sector"]: x for x in ms.sistema_por_sector(db, CORTE)["sectores"]}
        # construcción = 100M (mala) + 100M + 100M (sana, dos provincias)
        assert s["F - CONSTRUCCIÓN"]["deuda"] == 300_000_000
        assert s["F - CONSTRUCCIÓN"]["entidades_que_prestan"] == 2

    def test_la_mora_del_sector_es_del_SECTOR_no_el_promedio_de_entidades(self, db_con_panel):
        """Ponderada por exposición: (12+2+2)/300 = 5,33%. El promedio simple de las tasas
        de cada entidad daría otra cosa y sería una cifra que no le corresponde a nadie."""
        db, _, _ = db_con_panel
        s = {x["sector"]: x for x in ms.sistema_por_sector(db, CORTE)["sectores"]}
        assert s["F - CONSTRUCCIÓN"]["mora_pct"] == pytest.approx(5.33, abs=0.01)

    def test_trae_la_mora_TEMPRANA_que_es_la_señal_adelantada(self, db_con_panel):
        db, _, _ = db_con_panel
        s = {x["sector"]: x for x in ms.sistema_por_sector(db, CORTE)["sectores"]}
        assert s["F - CONSTRUCCIÓN"]["mora_temprana_31_90_pct"] == pytest.approx(1.6, abs=0.01)

    def test_sin_dato_lo_DECLARA_en_vez_de_devolver_una_tabla_vacia(self, db_session):
        r = ms.sistema_por_sector(db_session, date(2019, 12, 31))
        assert r["sin_dato"] is True and r["sectores"] == []


class TestLaAtribucion:
    """La lectura que exige el panel completo: ¿es mi originación o es el sector?"""

    def test_peor_que_su_sector_es_IDIOSINCRATICO(self, db_con_panel):
        db, mala, _ = db_con_panel
        f = {x["sector"]: x for x in ms.posicion_de_la_entidad(db, mala, CORTE)["sectores"]}
        c = f["F - CONSTRUCCIÓN"]
        assert c["mora_pct"] == 12.0 and c["mora_del_sector_pct"] == pytest.approx(5.33, abs=.01)
        assert c["brecha_de_mora_pp"] == pytest.approx(6.67, abs=0.01)
        assert c["atribucion"] == "idiosincratico_peor"

    def test_alineada_con_su_sector_es_COMPARTIDO(self, db_con_panel):
        """Mora 2% contra 5,33% del sector: mejor que el sector, y por más de un punto."""
        db, _, sana = db_con_panel
        f = {x["sector"]: x for x in ms.posicion_de_la_entidad(db, sana, CORTE)["sectores"]}
        assert f["F - CONSTRUCCIÓN"]["atribucion"] == "idiosincratico_mejor"

    def test_una_exposicion_chica_NO_se_narra_como_señal(self, db_session):
        """Un solo crédito mueve la mora decenas de puntos: la celda se muestra, pero no se
        atribuye. Ocultarla sería peor —desaparecería sin aviso—."""
        b = Bank(name="Banco Chico", bank_type=BankType.corporacion_credito)
        db_session.add(b)
        db_session.flush()
        db_session.add(CarteraSectorial(bank_id=b.id, period_end=CORTE, sector="B - PESCA",
                                        provincia="SAMANÁ", deuda=50_000, vencida=25_000,
                                        vencida_31_90=0))
        db_session.commit()
        c = ms.posicion_de_la_entidad(db_session, b, CORTE)["sectores"][0]
        assert c["mora_pct"] == 50.0            # la cifra se publica
        assert c["atribucion"] == "exposicion_no_material"   # pero no se atribuye

    def test_las_DOS_cuotas_llevan_su_poblacion_en_la_clave(self, db_con_panel):
        """`peso_en_su_cartera_pct` y `cuota_del_sector_pct` tienen denominadores distintos.
        Sin el sujeto en la clave el modelo publica «concentra el 33% del sector» cuando es
        de su propia cartera — ese defecto ya salió publicado una vez en este repo."""
        db, mala, _ = db_con_panel
        f = {x["sector"]: x for x in ms.posicion_de_la_entidad(db, mala, CORTE)["sectores"]}
        c = f["F - CONSTRUCCIÓN"]
        assert c["peso_en_su_cartera_pct"] == pytest.approx(66.67, abs=.01)   # 100 de 150
        assert c["cuota_del_sector_pct"] == pytest.approx(33.33, abs=.01)     # 100 de 300

    def test_una_entidad_sin_desglose_devuelve_None_y_no_una_tabla_vacia(self, db_session):
        b = Bank(name="Banco Sin Cartera", bank_type=BankType.cambiaria)
        db_session.add(b)
        db_session.commit()
        assert ms.posicion_de_la_entidad(db_session, b, CORTE) is None


class TestNuncaSeRellenaUnHueco:
    def test_un_cociente_sin_denominador_es_None_y_NO_cero(self):
        """Servir 0,0 convierte «no lo sé» en «no tiene mora», que es una afirmación."""
        assert ms._pct(5, 0) is None
        assert ms._pct(None, 100) is None
        assert ms._pct(0, 100) == 0.0   # esto SÍ es un cero medido
