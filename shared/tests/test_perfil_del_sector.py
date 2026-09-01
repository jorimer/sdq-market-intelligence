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
from shared.perfil_del_sector import (actividad_del_sector, corte_del_cubo_para_el_anio,
                                      credito_al_sector,
                                      inversion_extranjera_del_sector, letras_del_slug,
                                      ocupacion_del_sector, perfil_del_sector,
                                      salario_del_sector)
from shared.reference.cartera_sectorial import CarteraSectorial
from shared.reference.sector_variables import (IED_DIMENSION, LABOR_ENCFT_DIMENSION,
                                               SECTOR_DIMENSION, SectorVariable)

CORTE = date(2025, 12, 31)


def _var(db, dimension, clave, variable, periodo, valor):
    """Una fila de `si_variables` — la tabla que el 2026-09-01 se mudó a `shared/`."""
    db.add(SectorVariable(sector_code=clave, dimension=dimension, variable=variable,
                          period=str(periodo), value=valor))


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
        assert r["peso_del_sector_en_la_cartera_del_sistema_pct"] == 25.0, (
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

    def test_la_cobertura_LISTA_lo_que_este_sector_no_tiene(self, db_session):
        """Dato interno del contexto, no texto para el informe: la ausencia no se le declara
        al lector. Sirve para que el consumidor sepa sobre qué está afirmando."""
        _celda(db_session, "b1", "F - CONSTRUCCIÓN", 1000.0)
        db_session.commit()
        p = perfil_del_sector(db_session, "construccion", CORTE)
        assert p["cobertura"]["lecturas_servidas"] == ["credito_del_sistema"]
        assert p["cobertura"]["lecturas_sin_dato_para_este_sector"] == [
            "costo_laboral", "actividad", "ocupacion", "inversion_extranjera"]


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


def test_las_DOS_PUNTAS_del_contrato_usan_las_mismas_claves(db_session):
    """`contexto_del_perfil_del_sector` lee exactamente las claves que las CINCO lecturas
    emiten.

    **Por qué existe.** En la fase 4 renombré una clave del perfil y NO el `.get()` que la
    lee del otro lado: `peso` llegó a producción en `None`, y el informe generado citó deuda,
    entidades, tasa y mora pero nunca el peso del sector. Los tests no lo vieron porque su
    fixture estaba escrita a mano y arrastraba el nombre viejo — fixture y código derivaron
    juntos, que es la forma en que un test deja de medir la realidad.

    **El emisor es el CÓDIGO REAL, no una fixture.** Se llaman las cinco funciones contra una
    base cargada y se une lo que devuelven; una fixture escrita a mano volvería a derivar.

    Se comparan CLAVES y no valores: un `None` puede ser legítimo —la celda no trae conteo de
    créditos y `credito_promedio` no se puede derivar—, pero un nombre que el emisor no emite
    NUNCA lo es. La primera versión de este test comparaba valores y marcaba ese None
    legítimo, que es ruido y termina en que alguien lo relaje.
    """
    import ast
    import inspect

    from shared import perfil_del_sector as mod

    # Los DOS casos de cada lectura, porque algunas claves solo aparecen en uno:
    # `por_que_es_agregado` existe cuando la fuente agrupa —la letra D de la SIB, la rama
    # «Otros Servicios» de la ENCFT, la actividad «Comercio / Industria» de la IED— y
    # construcción no lo es en ninguna. Probar solo el caso simple dejaría esas claves fuera.
    _celda(db_session, "b1", "F - CONSTRUCCIÓN", 1000.0, vencida=50.0, tasa=11.4)
    _celda(db_session, "b1", "D - INDUSTRIA MANUFACTURERA", 2000.0, tasa=10.4)
    for anio in ("2024", "2025"):
        _var(db_session, SECTOR_DIMENSION, "construccion", "sector_size", anio, 13.4)
        _var(db_session, SECTOR_DIMENSION, "construccion", "sector_growth", anio, -1.8)
        _var(db_session, LABOR_ENCFT_DIMENSION, "construccion", "employment", anio, 432957.0)
        _var(db_session, LABOR_ENCFT_DIMENSION, "otros_servicios", "employment", anio, 1488383.0)
        _var(db_session, IED_DIMENSION, "turismo", "ied_usd_mm", anio, 1120.5)
        _var(db_session, IED_DIMENSION, "comercio_industria", "ied_usd_mm", anio, 890.1)
    db_session.commit()

    emisores = (
        lambda: credito_al_sector(db_session, "construccion", CORTE),
        lambda: credito_al_sector(db_session, "manufactura_local", CORTE),
        lambda: actividad_del_sector(db_session, "construccion", 2025),
        lambda: ocupacion_del_sector(db_session, "construccion", 2025),   # rama directa
        lambda: ocupacion_del_sector(db_session, "salud", 2025),          # rama agregada
        lambda: inversion_extranjera_del_sector(db_session, "turismo", 2025),        # directa
        lambda: inversion_extranjera_del_sector(db_session, "manufactura_local", 2025),  # agg
    )
    emite = set()
    for fn in emisores:
        fila = fn()
        assert fila, "un emisor devolvió vacío: el contrato se estaría verificando a ciegas"
        emite |= set(fila)

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(mod)))
              if isinstance(n, ast.FunctionDef) and n.name == "contexto_del_perfil_del_sector")
    # Los `.get("...")` que el bloque hace sobre las filas de cada lectura.
    lee = {n.args[0].value for n in ast.walk(fn)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "get" and n.args
           and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}
    # Éstas son claves del PERFIL (el diccionario de afuera), no de una fila.
    lee -= {"credito_del_sistema", "costo_laboral", "actividad", "ocupacion",
            "inversion_extranjera"}
    del_salario = {"salario_promedio_cotizable_del_sector_dop_mes", "anio", "fuente"}
    huerfanas = lee - emite - del_salario
    assert not huerfanas, (
        f"el bloque de contexto lee claves que el perfil NO emite: {sorted(huerfanas)}. "
        "Llegarían vacías al modelo y la cifra desaparecería del informe sin que nada falle")


def test_el_contra_caso_una_clave_inventada_SI_llega_vacia(db_session):
    """Sin esto, el test de arriba pasaría aunque el bloque no leyera nada del perfil."""
    from shared.perfil_del_sector import contexto_del_perfil_del_sector

    bloque = contexto_del_perfil_del_sector(
        {"credito_del_sistema": {"corte": "2025-12-31", "clave_que_no_existe": 1}},
        "construccion")
    c = bloque["credito_del_sistema_al_sector_construccion"]
    assert [k for k, v in c.items() if v is None], (
        "el lector no está leyendo del perfil: devuelve valores sin que el emisor los dé")


class TestUnAnioEnCursoTambienLeeElCubo:
    """El producto de energía estaba en 2026 y pedía `2026-12-31`, que no existe: la capa de
    crédito no viajaba y nunca iba a viajar. El año que viene le pasa a todos los ejes.

    La caída al último trimestre DEL AÑO es legítima porque esta capa no es del índice: es
    contexto agregado, viaja con su propio corte y la plantilla exige citarlo.
    """

    def test_un_anio_cerrado_usa_su_DICIEMBRE(self, db_session):
        from shared.perfil_del_sector import corte_del_cubo_para_el_anio
        for mes_dia in ((3, 31), (6, 30), (9, 30), (12, 31)):
            _celda(db_session, "b1", "F - CONSTRUCCIÓN", 100.0)
            db_session.query(CarteraSectorial).filter_by(period_end=CORTE).update(
                {"period_end": date(2025, *mes_dia)})
            db_session.commit()
        assert corte_del_cubo_para_el_anio(db_session, 2025) == date(2025, 12, 31)

    def test_un_anio_EN_CURSO_usa_su_ultimo_trimestre(self, db_session):
        db_session.add(CarteraSectorial(
            bank_id="b1", period_end=date(2026, 3, 31), sector="F - CONSTRUCCIÓN",
            provincia="SIN PROVINCIA", deuda=100.0))
        db_session.commit()
        assert corte_del_cubo_para_el_anio(db_session, 2026) == date(2026, 3, 31)

    def test_NUNCA_se_sale_del_anio(self, db_session):
        """Un informe de 2026 no lee el cubo de 2025: eso sí contradiría el encabezado."""
        from shared.perfil_del_sector import corte_del_cubo_para_el_anio
        db_session.add(CarteraSectorial(
            bank_id="b1", period_end=date(2025, 12, 31), sector="F - CONSTRUCCIÓN",
            provincia="SIN PROVINCIA", deuda=100.0))
        db_session.commit()
        assert corte_del_cubo_para_el_anio(db_session, 2026) is None

    def test_sin_ningun_corte_devuelve_None(self, db_session):
        from shared.perfil_del_sector import corte_del_cubo_para_el_anio
        assert corte_del_cubo_para_el_anio(db_session, 2019) is None


class TestLaHolguraDeUnaRegion:
    """`parse_regiones` persiste 7 indicadores × 5 dominios × 11 años y hasta la fase 6 solo
    los leía banca, agregados y ponderados por exposición crediticia. Un producto que YA es
    regional los quiere directos."""

    def test_las_diez_regiones_de_desarrollo_resuelven_a_un_dominio(self):
        from shared.data.regiones_rd import (REGIONES_DE_DESARROLLO,
                                             dominio_de_la_region)
        assert len(REGIONES_DE_DESARROLLO) == 10
        sin_dominio = [r for r in REGIONES_DE_DESARROLLO if dominio_de_la_region(r) is None]
        assert not sin_dominio, f"regiones sin dominio ENCFT: {sin_dominio}"

    def test_acepta_las_DOS_formas_que_circulan_en_el_repo(self):
        """La fuente rotula «CIBAO NORDESTE» y los productos usan «cibao_nordeste»."""
        from shared.data.regiones_rd import dominio_de_la_region
        assert dominio_de_la_region("CIBAO NORDESTE") == dominio_de_la_region("cibao_nordeste")
        assert dominio_de_la_region("cibao_nordeste") is not None

    def test_una_region_que_NO_existe_no_se_asigna_a_ningun_dominio(self):
        """Asignarle uno le atribuiría condiciones laborales de otro territorio."""
        from shared.data.regiones_rd import dominio_de_la_region
        assert dominio_de_la_region("REGION INVENTADA") is None
        assert dominio_de_la_region("") is None

    def test_el_mapa_se_DERIVA_y_no_se_escribe_dos_veces(self):
        """Una segunda tabla del mismo mapa es como las dos se desincronizan."""
        from shared.data.regiones_rd import DOMINIOS, dominio_de_la_region
        for dominio, regiones in DOMINIOS.items():
            for region in regiones:
                assert dominio_de_la_region(region) == dominio

    def test_la_respuesta_DICE_que_el_dato_es_del_dominio(self, db_session, monkeypatch):
        """La ENCFT publica por dominio (4), no por región (10). Atribuirlo a la región
        afirmaría una precisión que la fuente no tiene."""
        import shared.capacidad_de_pago as cap
        monkeypatch.setattr(cap, "mercado_laboral_por_region", lambda db, c: {
            "anio": "2024",
            "por_dominio": {"norte": {"subutilizacion_amplia_su4_pct": 18.4,
                                      "desocupacion_abierta_su1_pct": 5.1}}})
        monkeypatch.setattr(cap, "_ultimo_valor_de", lambda *a, **k: 15.0)
        r = cap.holgura_de_la_region(db_session, CORTE, "cibao_nordeste")
        assert r["dominio_encft_al_que_pertenece"] == "norte"
        aviso = r["el_dato_es_del_DOMINIO_no_de_la_region"]
        assert "por dominio" in aviso and "no por región de desarrollo" in aviso
        # LA RELACIÓN SE COMPUTA ACÁ: el modelo la copia, no la deriva.
        assert r["mas_subutilizacion_que_el_pais_pp"] == 3.4
