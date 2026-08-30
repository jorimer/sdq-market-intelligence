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
        assert c["mora_pct"] == 12.0
        # 4M de mora sobre 200M en el RESTO del sector (las dos provincias de la sana).
        assert c["mora_del_resto_del_sector_pct"] == pytest.approx(2.0, abs=.01)
        assert c["brecha_de_mora_pp"] == pytest.approx(10.0, abs=0.01)
        assert c["atribucion"] == "idiosincratico_peor"

    def test_compararse_contra_el_TOTAL_le_encoge_la_brecha_a_la_entidad(self, db_con_panel):
        """El sesgo que motivó excluir a la entidad de su propia referencia.

        La mora del sector ENTERO es 5,33% ((12+2+2)/300) porque los 12 puntos de la mala
        entran en el promedio que debía juzgarla. Contra el RESTO es 2%. La misma entidad
        pasa de una brecha de 6,67 pp a una de 10 pp: el total le perdona un tercio, y le
        perdona tanto más cuanto mayor es su cuota. Con el 33% del sector ya se nota; en un
        banco con el 30% del crédito del país, la referencia es en buena medida él mismo."""
        db, mala, _ = db_con_panel
        sector = {x["sector"]: x
                  for x in ms.sistema_por_sector(db, CORTE)["sectores"]}["F - CONSTRUCCIÓN"]
        f = {x["sector"]: x for x in ms.posicion_de_la_entidad(db, mala, CORTE)["sectores"]}
        c = f["F - CONSTRUCCIÓN"]
        assert sector["mora_pct"] == pytest.approx(5.33, abs=.01)   # incluyéndola
        brecha_contra_el_total = c["mora_pct"] - sector["mora_pct"]
        assert brecha_contra_el_total == pytest.approx(6.67, abs=.01)
        assert c["brecha_de_mora_pp"] > brecha_contra_el_total, (
            "la brecha contra el resto debe ser MAYOR que contra el total: el total "
            "incluye a la entidad y la arrastra hacia sí misma")

    def test_alineada_con_su_sector_es_COMPARTIDO(self, db_con_panel):
        """Mora 2% contra 5,33% del sector: mejor que el sector, y por más de un punto."""
        db, _, sana = db_con_panel
        f = {x["sector"]: x for x in ms.posicion_de_la_entidad(db, sana, CORTE)["sectores"]}
        assert f["F - CONSTRUCCIÓN"]["atribucion"] == "idiosincratico_mejor"

    def test_una_exposicion_chica_NO_se_narra_como_señal(self, db_session):
        """Un solo crédito mueve la mora decenas de puntos: la celda se muestra, pero no se
        atribuye. Ocultarla sería peor —desaparecería sin aviso—.

        El sector lleva un segundo prestador A PROPÓSITO: sin él, la celda tampoco tendría
        contra qué compararse, y el test pasaría por el motivo equivocado."""
        b = Bank(name="Banco Chico", bank_type=BankType.corporacion_credito)
        otro = Bank(name="Banco Pescador", bank_type=BankType.banca_multiple)
        db_session.add_all([b, otro])
        db_session.flush()
        db_session.add(CarteraSectorial(bank_id=b.id, period_end=CORTE, sector="B - PESCA",
                                        provincia="SAMANÁ", deuda=50_000, vencida=25_000,
                                        vencida_31_90=0))
        db_session.add(CarteraSectorial(bank_id=otro.id, period_end=CORTE, sector="B - PESCA",
                                        provincia="SAMANÁ", deuda=80_000_000, vencida=800_000,
                                        vencida_31_90=0))
        db_session.commit()
        c = ms.posicion_de_la_entidad(db_session, b, CORTE)["sectores"][0]
        assert c["mora_pct"] == 50.0            # la cifra se publica
        assert c["mora_del_resto_del_sector_pct"] == 1.0     # hay contra qué comparar
        assert c["atribucion"] == "exposicion_no_material"   # pero no se atribuye

    def test_ser_el_UNICO_prestador_del_sector_se_declara_y_no_se_llama_sin_dato(
            self, db_session):
        """El dato está completo; lo que no existe es un comparable. Decir «sin_dato» sería
        declarar una brecha en la medición donde no la hay, y taparía el hallazgo: que la
        entidad está sola en ese sector."""
        b = Bank(name="Banco Solitario", bank_type=BankType.banca_multiple)
        db_session.add(b)
        db_session.flush()
        db_session.add(CarteraSectorial(bank_id=b.id, period_end=CORTE, sector="B - PESCA",
                                        provincia="SAMANÁ", deuda=90_000_000,
                                        vencida=3_000_000, vencida_31_90=0))
        db_session.commit()
        c = ms.posicion_de_la_entidad(db_session, b, CORTE)["sectores"][0]
        assert c["mora_pct"] == pytest.approx(3.33, abs=.01)   # su cifra sí se publica
        assert c["mora_del_resto_del_sector_pct"] is None
        assert c["brecha_de_mora_pp"] is None
        assert c["atribucion"] == "sin_resto_con_que_comparar"
        assert c["entidades_en_el_resto_del_sector"] == 0

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


class TestLaTasaEsUnPromedioPonderado:
    """La medida que llegó con el cubo y que un promedio simple arruinaría.

    La SIB publica `tasaPorDeuda` como Σ(tasa × saldo) —su *Catálogo de Indicadores
    Financieros* v3.0: «la variable de ponderación es el saldo adeudado»—. Persistimos el
    cociente por celda, así que agregar celdas obliga a RE-PONDERAR. Este archivo fija las
    dos formas de equivocarse: promediar los cocientes, y dejar en el denominador las
    celdas que no aportaron numerador.
    """

    @pytest.fixture
    def db_con_tasas(self, db_session):
        b = Bank(name="Banco Tasa", bank_type=BankType.banca_multiple)
        db_session.add(b)
        db_session.flush()
        filas = [
            # Una celda ENORME y barata, y una chica y cara. El promedio simple sería
            # 24,0%; el ponderado por saldo es 8,4% — casi tres veces menos.
            ("DISTRITO NACIONAL", 990_000_000, 990_000_000, 8.0),
            ("PEDERNALES", 10_000_000, 10_000_000, 40.0),
        ]
        for prov, deuda, con_tasa, tasa in filas:
            db_session.add(CarteraSectorial(
                bank_id=b.id, period_end=CORTE, sector="F - CONSTRUCCIÓN", provincia=prov,
                deuda=deuda, vencida=0, vencida_31_90=0,
                deuda_con_tasa=con_tasa, tasa_ponderada=tasa))
        db_session.commit()
        return db_session, b

    def test_pondera_por_saldo_y_no_promedia_los_cocientes(self, db_con_tasas):
        db, _ = db_con_tasas
        s = {x["sector"]: x for x in ms.sistema_por_sector(db, CORTE)["sectores"]}
        esperado = (8.0 * 990_000_000 + 40.0 * 10_000_000) / 1_000_000_000
        assert s["F - CONSTRUCCIÓN"]["tasa_promedio_ponderada_pct"] == pytest.approx(
            esperado, abs=.01)
        assert esperado == pytest.approx(8.32, abs=.01)
        # El promedio simple de los cocientes: la respuesta equivocada.
        assert s["F - CONSTRUCCIÓN"]["tasa_promedio_ponderada_pct"] != pytest.approx(
            24.0, abs=.5)

    def test_una_celda_sin_tasa_creible_sale_del_numerador_Y_del_denominador(
            self, db_con_tasas):
        """Si saliera solo del numerador, su saldo diluiría la tasa hacia cero y el
        resultado parecería un dato cuando es un artefacto."""
        db, b = db_con_tasas
        db.add(CarteraSectorial(
            bank_id=b.id, period_end=CORTE, sector="F - CONSTRUCCIÓN", provincia="AZUA",
            deuda=5_000_000_000, vencida=0, vencida_31_90=0,
            deuda_con_tasa=5_000_000_000, tasa_ponderada=None))
        db.commit()
        s = {x["sector"]: x for x in ms.sistema_por_sector(db, CORTE)["sectores"]}
        # La tasa no se mueve: la celda sin tasa no vota, aunque sea cinco veces mayor.
        assert s["F - CONSTRUCCIÓN"]["tasa_promedio_ponderada_pct"] == pytest.approx(
            8.32, abs=.01)
        # Pero su deuda SÍ entra en la exposición: no es una celda que se oculte.
        assert s["F - CONSTRUCCIÓN"]["deuda"] == 6_000_000_000

    def test_sin_ninguna_tasa_la_medida_es_None_y_nunca_cero(self, db_session):
        """Los 22 trimestres anteriores al backfill del cubo no tienen tasa. Servir 0,0%
        diría «presta gratis», que es una afirmación que nadie midió."""
        b = Bank(name="Banco Viejo", bank_type=BankType.banca_multiple)
        db_session.add(b)
        db_session.flush()
        db_session.add(CarteraSectorial(bank_id=b.id, period_end=CORTE, sector="B - PESCA",
                                        provincia="SAMANÁ", deuda=90_000_000, vencida=0,
                                        vencida_31_90=0))
        db_session.commit()
        s = ms.sistema_por_sector(db_session, CORTE)["sectores"][0]
        assert s["tasa_promedio_ponderada_pct"] is None
        assert s["deuda"] == 90_000_000


class TestElSpreadDeTasaContraElResto:
    """La lectura que ningún banco puede producir solo: a qué precio coloca en un sector
    contra el precio al que colocan los demás EN ESE MISMO SECTOR."""

    @pytest.fixture
    def db_con_dos(self, db_session):
        caro = Bank(name="Banco Caro", bank_type=BankType.banca_multiple)
        barato = Bank(name="Banco Barato", bank_type=BankType.banca_multiple)
        db_session.add_all([caro, barato])
        db_session.flush()
        for banco, tasa, venc in ((caro, 22.0, 2_000_000), (barato, 12.0, 2_000_000)):
            db_session.add(CarteraSectorial(
                bank_id=banco.id, period_end=CORTE, sector="F - CONSTRUCCIÓN",
                provincia="DISTRITO NACIONAL", deuda=100_000_000, vencida=venc,
                vencida_31_90=0, deuda_con_tasa=100_000_000, tasa_ponderada=tasa,
                provision=1_000_000, garantia=50_000_000, creditos=100,
                deuda_moneda_extranjera=20_000_000))
        db_session.commit()
        return db_session, caro

    def test_el_spread_se_COMPUTA_y_el_modelo_no_lo_deriva(self, db_con_dos):
        db, caro = db_con_dos
        c = ms.posicion_de_la_entidad(db, caro, CORTE)["sectores"][0]
        assert c["tasa_promedio_ponderada_pct"] == 22.0
        assert c["tasa_del_resto_del_sector_pct"] == 12.0
        assert c["spread_de_tasa_pp"] == 10.0

    def test_con_la_MISMA_mora_el_spread_es_margen_y_los_dos_datos_viajan_juntos(
            self, db_con_dos):
        """Cobra 10 puntos más por el mismo riesgo observado. La lectura exige las dos
        cifras en la misma fila; separarlas deja que el modelo empareje mal."""
        db, caro = db_con_dos
        c = ms.posicion_de_la_entidad(db, caro, CORTE)["sectores"][0]
        assert c["brecha_de_mora_pp"] == 0.0
        assert c["spread_de_tasa_pp"] == 10.0
        assert c["atribucion"] == "compartido_con_el_sector"

    def test_las_demas_medidas_del_cubo_tambien_traen_su_referencia(self, db_con_dos):
        db, caro = db_con_dos
        c = ms.posicion_de_la_entidad(db, caro, CORTE)["sectores"][0]
        # Cobertura sobre la VENCIDA, no sobre la total: 1M sobre 2M de mora.
        assert c["cobertura_de_provision_sobre_vencida_pct"] == 50.0
        assert c["cobertura_del_resto_del_sector_pct"] == 50.0
        assert c["garantia_sobre_deuda_pct"] == 50.0
        assert c["dolarizacion_de_la_deuda_pct"] == 20.0
        assert c["credito_promedio"] == 1_000_000.0

    def test_cada_clave_nombra_su_poblacion(self, db_con_dos):
        """La regla del sujeto, aplicada a las medidas nuevas: toda referencia dice que es
        del RESTO del sector, y ninguna medida queda con un nombre que el modelo pueda
        reatribuir a la entidad."""
        db, caro = db_con_dos
        c = ms.posicion_de_la_entidad(db, caro, CORTE)["sectores"][0]
        referencias = [k for k in c if "resto" in k]
        assert len(referencias) >= 6, "las referencias deben nombrar al resto del sector"
        # Una CUOTA se calcula sobre el todo —si excluyera a la entidad, las cuotas de las
        # noventa y dos no sumarían 100 y «cuota» dejaría de significar cuota—. Una
        # COMPARACIÓN excluye a la entidad, o se compara contra sí misma. Son dos cosas
        # distintas y por eso `cuota_del_sector_pct` es la única exenta.
        CUOTAS = {"cuota_del_sector_pct"}
        assert not [k for k in c if k.endswith("_del_sector_pct")
                    and "resto" not in k and k not in CUOTAS], (
            "una clave «…_del_sector_pct» sin «resto» miente sobre contra qué se compara")
        assert c["cuota_del_sector_pct"] == 50.0, (
            "la cuota se computa sobre el sector ENTERO, incluida la entidad")
