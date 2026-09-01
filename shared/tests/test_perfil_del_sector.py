"""El perfil de un sector: crédito y costo laboral, unidos por el crosswalk.

Fase 3 del plan de enriquecimiento sectorial. Lo que se protege acá no es el cálculo —ése lo
hacen las primitivas compartidas con el mapa de banca— sino el SUJETO: varias letras de la
SIB alimentan a más de un slug, y publicar el agregado como si fuera del sector pedido es
exactamente el error que en este repo se publicó como «cuatro compañías concentran el 87,1%»
cuando eran cuatro ramos.
"""
from datetime import date

import pytest

from shared.data.bcrd_sectors import sector_catalog
from shared.perfil_del_sector import (credito_al_sector, letras_del_slug,
                                      perfil_del_sector, salario_del_sector)
from shared.reference.cartera_sectorial import CarteraSectorial

CORTE = date(2025, 12, 31)


@pytest.fixture()
def db_session():
    """Base en memoria con TODO el metadata: el perfil toca `cartera_sectorial` y
    `app_settings`, que viven en módulos distintos."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.main  # noqa: F401 — registra todos los modelos
    from shared.database.base import Base
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _celda(db, banco, etiqueta, deuda, vencida=0.0, tasa=None, base=None):
    db.add(CarteraSectorial(
        bank_id=banco, period_end=CORTE, sector=etiqueta, provincia="SIN PROVINCIA",
        deuda=deuda, vencida=vencida, tasa_ponderada=tasa,
        deuda_con_tasa=(base if base is not None else (deuda if tasa is not None else 0))))


class TestElIndiceInversoSaleDelCrosswalk:

    def test_los_slugs_de_una_letra_apuntan_a_esa_letra(self):
        assert letras_del_slug("construccion") == ["F"]
        assert letras_del_slug("turismo") == ["H"]

    def test_dos_slugs_pueden_compartir_UNA_letra(self):
        """La SIB no separa manufactura local de zonas francas."""
        assert letras_del_slug("manufactura_local") == letras_del_slug("zonas_francas") == ["D"]

    def test_agropecuario_lo_alimentan_DOS_letras(self):
        assert sorted(letras_del_slug("agropecuario")) == ["A", "B"]

    def test_el_slug_sin_cobertura_no_inventa_letra(self):
        assert letras_del_slug("comunicaciones") == []

    def test_todo_slug_del_catalogo_esta_decidido(self):
        """Barrido con prueba negativa: o tiene letras, o es la brecha declarada."""
        todos = [s for s, _n in sector_catalog()]
        assert len(todos) == 17
        sin_letra = [s for s in todos if not letras_del_slug(s)]
        assert sin_letra == ["comunicaciones"]


class TestElSujetoViajaConElNumero:

    def test_un_slug_de_letra_propia_NO_se_marca_como_agregado(self, db_session):
        _celda(db_session, "b1", "F - CONSTRUCCIÓN", 1000.0, vencida=50.0, tasa=11.4)
        db_session.commit()
        r = credito_al_sector(db_session, "construccion", CORTE)
        assert r["es_agregado"] is False
        assert r["el_agregado_incluye"] is None
        assert r["mora_pct"] == 5.0

    def test_un_slug_que_COMPARTE_letra_declara_su_poblacion(self, db_session):
        """La cifra de la D no es de la manufactura local: es del agregado que publica la
        fuente. Sin esto, el modelo la atribuye al sector más cercano."""
        _celda(db_session, "b1", "D - INDUSTRIA MANUFACTURERA", 2000.0, tasa=10.4)
        db_session.commit()
        r = credito_al_sector(db_session, "manufactura_local", CORTE)
        assert r["es_agregado"] is True
        assert r["el_agregado_incluye"] == ["manufactura_local", "zonas_francas"]
        assert r["por_que_es_agregado"] and "zonas francas" in r["por_que_es_agregado"]

    def test_las_dos_letras_de_agropecuario_se_SUMAN(self, db_session):
        _celda(db_session, "b1", "A - AGRICULTURA, GANADERÍA, CAZA Y SILVICULTURA", 800.0)
        _celda(db_session, "b1", "B - PESCA", 200.0)
        db_session.commit()
        r = credito_al_sector(db_session, "agropecuario", CORTE)
        assert r["deuda_del_sistema_al_sector"] == 1000.0
        assert sorted(r["letras_ciiu_de_la_fuente"]) == ["A", "B"]

    def test_el_peso_en_el_pais_se_COMPUTA_contra_el_total_del_corte(self, db_session):
        _celda(db_session, "b1", "F - CONSTRUCCIÓN", 250.0)
        _celda(db_session, "b2", "Y - CONSUMO DE BIENES Y SERVICIOS", 750.0)
        db_session.commit()
        r = credito_al_sector(db_session, "construccion", CORTE)
        assert r["peso_del_sector_en_el_credito_del_pais_pct"] == 25.0, (
            "el denominador es el crédito del PAÍS, hogares incluidos: casi la mitad del "
            "libro dominicano no va a un sector productivo")

    def test_la_tasa_se_RE_PONDERA_y_no_se_promedia(self, db_session):
        """Dos celdas de tamaño distinto: el promedio simple daría 15,0."""
        _celda(db_session, "b1", "F - CONSTRUCCIÓN", 900.0, tasa=10.0, base=900.0)
        _celda(db_session, "b2", "F - CONSTRUCCIÓN", 100.0, tasa=20.0, base=100.0)
        db_session.commit()
        r = credito_al_sector(db_session, "construccion", CORTE)
        assert r["tasa_promedio_ponderada_pct"] == 11.0


class TestLoQueNoHayNoSeInventa:

    def test_el_slug_sin_letra_devuelve_None(self, db_session):
        _celda(db_session, "b1", "F - CONSTRUCCIÓN", 1000.0)
        db_session.commit()
        assert credito_al_sector(db_session, "comunicaciones", CORTE) is None

    def test_un_corte_sin_desglose_devuelve_None(self, db_session):
        assert credito_al_sector(db_session, "construccion", date(2019, 12, 31)) is None

    def test_un_slug_que_no_existe_no_arma_perfil(self, db_session):
        assert perfil_del_sector(db_session, "no_existe_este_sector", CORTE) is None

    def test_sin_salario_persistido_esa_lectura_falta_pero_el_perfil_SALE(self, db_session):
        """Media respuesta es mejor que ninguna, y cuál falta lo dice la ausencia de su
        clave — no un cero."""
        _celda(db_session, "b1", "F - CONSTRUCCIÓN", 1000.0)
        db_session.commit()
        p = perfil_del_sector(db_session, "construccion", CORTE)
        assert "credito_del_sistema" in p
        assert "costo_laboral" not in p
        assert p["cobertura"]["lecturas_servidas"] == ["credito_del_sistema"]

    def test_la_cobertura_LISTA_lo_que_todavia_no_se_sirve(self, db_session):
        """No es un olvido: son tablas de `sector_intel`. Es dato interno del contexto, no
        texto para el informe."""
        _celda(db_session, "b1", "F - CONSTRUCCIÓN", 1000.0)
        db_session.commit()
        p = perfil_del_sector(db_session, "construccion", CORTE)
        assert p["cobertura"]["lecturas_pendientes"] == [
            "ocupacion_encft", "tamano_y_crecimiento_bcrd"]


class TestElSalarioTraeSuAnio:

    def test_sin_AppSetting_no_hay_salario(self, db_session):
        assert salario_del_sector(db_session, "construccion") is None

    def test_con_el_AppSetting_trae_valor_y_ANIO(self, db_session):
        """Es una lectura transversal: leerla como si fuera del corte del informe sería
        atribuirle una fecha que no tiene."""
        import json

        from shared.settings.models import AppSetting
        db_session.add(AppSetting(
            key="sector_operating_cost", is_secret=False,
            value=json.dumps({"series": {"construccion": 28500.0}, "year": "2025",
                              "unit": "RD$/mes", "source": "TSS"})))
        db_session.commit()
        r = salario_del_sector(db_session, "construccion")
        assert r["salario_promedio_cotizable_del_sector_dop_mes"] == 28500.0
        assert r["anio"] == "2025" and r["fuente"] == "TSS"

    def test_un_slug_sin_salario_en_la_serie_devuelve_None(self, db_session):
        import json

        from shared.settings.models import AppSetting
        db_session.add(AppSetting(
            key="sector_operating_cost", is_secret=False,
            value=json.dumps({"series": {"construccion": 28500.0}, "year": "2025"})))
        db_session.commit()
        assert salario_del_sector(db_session, "turismo") is None


def test_las_primitivas_son_LAS_MISMAS_que_usa_el_mapa_de_banca():
    """Un segundo cuerpo de agregación discreparía en silencio — ya pasó hoy con el
    serializador del cubo, y costó la tasa de 38 entidades."""
    import ast
    import inspect

    from modules.banking_score.reports import mapa_sectorial
    from shared import perfil_del_sector as perfil

    def _origen(mod, nombre):
        arbol = ast.parse(inspect.getsource(mod))
        for n in ast.walk(arbol):
            if isinstance(n, ast.ImportFrom) and any(a.name == nombre for a in n.names):
                return n.module
        return None

    for nombre in ("_medidas", "_sumar", "_vacio"):
        assert _origen(mapa_sectorial, nombre) == "shared.reference.cartera_agregacion"
        assert _origen(perfil, nombre) == "shared.reference.cartera_agregacion"
