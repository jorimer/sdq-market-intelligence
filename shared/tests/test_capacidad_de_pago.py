"""La inflación que enfrenta el deudor llega al informe, y llega bien.

El BCRD publica el IPC abierto por quintil de ingreso. La planilla estuvo veintiocho meses
sin ingerir; cuando se ingirió, quedó persistida y sin que ningún informe la leyera — que es
la forma silenciosa de no entregar un dato. Este archivo fija las dos mitades: que el cómputo
sea correcto, y que el resultado llegue al contexto con el que el modelo escribe.

Por qué el dato importa acá y no en el telón macro: el crédito de consumo se concentra en los
quintiles bajos. La inflación por quintil sola es un dato público que cualquiera baja; al
lado del peso de esa cartera en el libro de la entidad —y de su mora contra el resto del
sistema— es una atribución que exige el panel completo.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra users para las FK
# `MacroSeries` se importa ACÁ y no dentro del helper: `create_all` solo crea las tablas de
# los modelos ya registrados en el metadata, y con el import diferido la tabla no existía —
# el test fallaba con «no such table» y el orden de ejecución decidía a cuál le tocaba.
from modules.macro_monitor.models.models import MacroSeries  # noqa: F401
from modules.social_dev.models.models import SocialIndicator  # noqa: F401
from shared.database.base import Base
from shared import capacidad_de_pago as I

CORTE = date(2026, 3, 31)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _sembrar(db, quintil, puntos):
    for periodo, valor in puntos:
        db.add(MacroSeries(series_code=f"{I._PREFIJO}{quintil}", period=periodo,
                           value=valor, unit="índice", frequency="monthly", source="BCRD"))
    db.commit()


def _serie_mensual(inicio_anio, meses, base, final):
    """Índices que crecen linealmente de *base* a *final* en *meses* puntos."""
    out = []
    for i in range(meses):
        y, m = divmod(i, 12)
        out.append((f"{inicio_anio + y}-{m + 1:02d}",
                    base + (final - base) * i / max(meses - 1, 1)))
    return out


@pytest.fixture()
def db_con_quintiles(db):
    # Cinco años; el quintil 1 acumula 40% y el 5 acumula 30% → brecha de 10 pp.
    finales = {1: 140.0, 2: 138.0, 3: 136.0, 4: 133.0, 5: 130.0}
    for q, fin in finales.items():
        _sembrar(db, q, _serie_mensual(2021, 60, 100.0, fin))
    return db


class TestElComputo:
    def test_la_acumulada_sale_del_INDICE_y_no_de_sumar_variaciones(self, db_con_quintiles):
        r = I.inflacion_por_quintil(db_con_quintiles, CORTE)
        acum = r["inflacion_acumulada_por_quintil_de_ingreso_pct"]
        assert acum["quintil_1"] == pytest.approx(40.0, abs=0.01)
        assert acum["quintil_5"] == pytest.approx(30.0, abs=0.01)

    def test_la_brecha_se_COMPUTA_y_el_modelo_la_copia(self, db_con_quintiles):
        r = I.inflacion_por_quintil(db_con_quintiles, CORTE)
        assert r["brecha_quintil_1_menos_quintil_5_pp"] == pytest.approx(10.0, abs=0.01)
        assert r["quintil_mas_golpeado"] == "quintil_1"

    def test_no_arrastra_meses_POSTERIORES_al_corte(self, db_con_quintiles):
        """Un informe de marzo no puede citar la inflación de julio, por el mismo motivo
        por el que el telón macro se poda por fecha."""
        _sembrar(db_con_quintiles, 1, [("2026-07", 999.0)])
        r = I.inflacion_por_quintil(db_con_quintiles, CORTE)
        assert r["hasta"] <= "2026-03"
        assert r["inflacion_acumulada_por_quintil_de_ingreso_pct"]["quintil_1"] < 100

    def test_sin_UN_quintil_devuelve_None_y_no_media_brecha(self, db):
        """La lectura es la comparación entre extremos: con cuatro de cinco no se puede
        afirmar cuál es el extremo. Media brecha parece una medición y no lo es."""
        for q in (1, 2, 3, 4):
            _sembrar(db, q, _serie_mensual(2021, 60, 100.0, 140.0))
        assert I.inflacion_por_quintil(db, CORTE) is None

    def test_una_ventana_CORTA_no_afirma_una_trayectoria(self, db):
        for q in I.QUINTILES:
            _sembrar(db, q, _serie_mensual(2026, 3, 100.0, 101.0))
        assert I.inflacion_por_quintil(db, CORTE) is None

    def test_cada_clave_nombra_su_poblacion(self, db_con_quintiles):
        r = I.inflacion_por_quintil(db_con_quintiles, CORTE)
        assert "por_quintil_de_ingreso" in "".join(
            k for k in r if k.startswith("inflacion_acumulada"))
        assert "quintil_1_menos_quintil_5" in "".join(
            k for k in r if k.startswith("brecha"))


class TestLlegaAlContextoDelModelo:
    """El cómputo correcto que nadie lee es exactamente lo que ya pasó con esta serie."""

    def test_el_contexto_de_la_seccion_lo_LLEVA(self):
        from modules.banking_score.reports.narrative import _build_section_context
        ctx = _build_section_context(
            "mapa_sectorial", "Banco Prueba",
            {"mapa_sectorial": {"sectores": []},
             "capacidad_de_pago": {
                 "inflacion_del_deudor": {"brecha_quintil_1_menos_quintil_5_pp": 7.1}},
             "indicators": {}},
            "2026-03-31")
        assert ctx["capacidad_de_pago"], (
            "el bloque se computa y no llega al modelo: la sección no puede mencionarlo")

    def test_la_plantilla_declara_CUANDO_usarlo_y_cuando_no(self):
        from shared.narrative.claude_engine import THIN_TEMPLATES
        thin = THIN_TEMPLATES["banking_sector_map"]
        assert "inflacion_del_deudor" in thin
        assert "no existe para este informe" in thin, (
            "sin la rama negativa, el modelo inventa el bloque cuando falta")
        assert "NO las presentes como causa probada" in thin, (
            "es contexto de capacidad de pago, no la atribución de la mora")
        # Las tres lecturas nombradas, para que agregar una y olvidar su regla falle.
        for clave in ("inflacion_del_deudor", "salario_minimo", "mercado_laboral"):
            assert clave in thin, f"la plantilla no dice qué hacer con «{clave}»"
        assert "nunca como «el salario mínimo» a secas" in thin, (
            "hay once categorías y varias congeladas: sin su nombre, el piso no tiene sujeto")

    @pytest.mark.parametrize("archivo,ancla", [
        ("modules/banking_score/products.py", "scoring_result[\"capacidad_de_pago\"]"),
        ("modules/banking_score/products.py", "pl[\"capacidad_de_pago\"]"),
        ("modules/banking_score/products_year_review.py", "out[\"capacidad_de_pago\"]"),
        ("modules/banking_score/api/router_reports.py",
         "scoring_result[\"capacidad_de_pago\"]"),
    ])
    def test_llega_por_los_CUATRO_caminos_que_emiten_un_informe(self, archivo, ancla):
        """Trimestral, año por trimestres, Revisión Anual y la ruta de informes. Cablearlo
        en uno solo es cómo el mapa sectorial terminó estando en un informe de cuatro."""
        import pathlib
        assert ancla in pathlib.Path(archivo).read_text(), (
            f"«{archivo}» no sirve el bloque: ese informe saldría sin la lectura")


class TestUnaSerieSinSujetoNoSePERSISTE:
    """La ÚLTIMA red: una serie que ni siquiera el encabezado del grupo puede nombrar.

    El desempate correcto lo hace `inference`, calificando con el encabezado del grupo
    (`quintil_2 · tasa de inflación`) — ver
    `shared/data/bcrd_excel/tests/test_el_desempate_nombra_el_grupo.py`. Este veto solo
    alcanza a lo que queda después: una columna que comparte nombre y cuyo vecino tampoco
    aporta un rótulo distinto. Ahí la serie es genuinamente innombrable y no se sirve.

    Vale registrar por qué es la última red y no la primera. La reacción inicial a las
    dieciocho series `_c<n>` de producción fue vetarlas y listo. Estaba mal: se verificó
    contra el dato que cada tasa del IPC por quintiles coincide con error 0,00000 pp sobre
    setenta puntos con la variación mensual de su índice. Eran series bien medidas y mal
    nombradas, y descartarlas habría sido arreglar el síntoma tirando la medición.
    """

    def test_reconoce_un_codigo_desempatado_por_COORDENADA(self):
        from modules.macro_monitor.service import _sin_sujeto
        assert _sin_sujeto("bcrd.xls.ipc_quintiles_base_2019_2020.tasa_de_inflacion_c5")
        assert _sin_sujeto("bcrd.xls.imae_2018.acumulada_c14")

    def test_NO_veta_una_serie_que_sí_nombra_su_poblacion(self):
        from modules.macro_monitor.service import _sin_sujeto
        assert not _sin_sujeto("bcrd.xls.ipc_quintiles_base_2019_2020.quintil_1")
        assert not _sin_sujeto("gdp_growth")
        # Un código que TERMINA en dígito sin el separador `_c` no es una coordenada: la
        # base de un índice, un año, un quintil. Vetarlos sería tirar el dato bueno.
        assert not _sin_sujeto("bcrd.xls.ipc_base_2019_2020.indice_general")
        assert not _sin_sujeto("serie_2024")

    def test_las_cinco_del_QUINTIL_que_sí_sirven_pasan(self):
        from modules.macro_monitor.service import _sin_sujeto
        from shared.capacidad_de_pago import _PREFIJO, QUINTILES
        for q in QUINTILES:
            assert not _sin_sujeto(f"{_PREFIJO}{q}")

    def test_el_veto_se_REGISTRA_y_no_es_silencioso(self):
        """Un veto que no deja marca se lee como que la planilla no traía esas columnas."""
        import inspect
        from modules.macro_monitor import service
        src = inspect.getsource(service._upsert_records)
        assert "logger.info" in src and "descartadas" in src


def _sembrar_social(db, tema, puntos, unidad="RD$/mes"):
    for periodo, valor in puntos:
        db.add(SocialIndicator(theme=tema, entity_key="salario_minimo", period=periodo,
                               value=valor, unit=unidad, source="MHE"))
    db.commit()


class TestElPisoDeIngreso:
    """El salario mínimo dominicano no es UNO: son once combinaciones, y varias llevan años
    congeladas. Servir una sin decir cuál —y sin decir de cuándo es— publicaría como piso
    vigente un número que hoy no cobra nadie."""

    def test_toma_el_ultimo_valor_y_FECHA_su_escalon(self, db):
        _sembrar_social(db, I._TEMA_SALARIO_REFERENCIA,
                        [("2024-01", 24000.0), ("2024-02", 24000.0),
                         ("2025-04", 27989.0), ("2025-05", 27989.0), ("2026-03", 27989.0)])
        r = I.salario_minimo(db, CORTE)
        assert r["salario_minimo_mensual_de_empresa_grande_no_sectorizada_rd"] == 27989.0
        assert r["ultimo_ajuste"] == "2025-04"
        assert r["meses_sin_ajuste"] == 11
        assert r["congelada"] is False

    def test_una_categoria_CONGELADA_se_declara(self, db):
        """«Zona franca en áreas deprimidas» no se ajusta desde 2006. Sin la marca, la serie
        escalonada la hace ver idéntica a una vigente."""
        _sembrar_social(db, I._TEMA_SALARIO_REFERENCIA,
                        [("2006-07", 5400.0)] + [(f"{y}-01", 5400.0)
                                                 for y in range(2007, 2027)])
        r = I.salario_minimo(db, CORTE)
        assert r["ultimo_ajuste"] == "2006-07"
        assert r["congelada"] is True

    def test_la_clave_NOMBRA_su_categoria(self, db):
        _sembrar_social(db, I._TEMA_SALARIO_REFERENCIA, [("2026-01", 27989.0)])
        r = I.salario_minimo(db, CORTE)
        assert any("empresa_grande" in k for k in r), (
            "«salario mínimo» a secas no dice cuál de las once es")

    def test_sin_serie_devuelve_None_y_no_un_cero(self, db):
        assert I.salario_minimo(db, CORTE) is None

    def test_no_arrastra_meses_POSTERIORES_al_corte(self, db):
        _sembrar_social(db, I._TEMA_SALARIO_REFERENCIA,
                        [("2026-01", 27989.0), ("2026-07", 31000.0)])
        r = I.salario_minimo(db, CORTE)
        assert r["salario_minimo_mensual_de_empresa_grande_no_sectorizada_rd"] == 27989.0


class TestElCreditoMedidoEnSalariosMinimos:
    def test_computa_la_escala(self, db):
        _sembrar_social(db, I._TEMA_SALARIO_REFERENCIA, [("2026-01", 28000.0)])
        sal = I.salario_minimo(db, CORTE)
        assert I.credito_en_salarios_minimos(101_410.0, sal) == 3.6

    @pytest.mark.parametrize("credito,salario", [(None, {"x": 1}), (101_410.0, None),
                                                 (0.0, {"x": 1})])
    def test_sin_una_de_las_dos_patas_devuelve_None(self, credito, salario):
        assert I.credito_en_salarios_minimos(credito, salario) is None

    def test_un_salario_sin_su_clave_NO_produce_una_escala(self, db):
        """Si la clave cambia de nombre, la cuenta debe apagarse en vez de dividir por algo
        que no es el piso."""
        assert I.credito_en_salarios_minimos(101_410.0, {"otra_clave": 28000.0}) is None


class TestLaFormalidadDelEmpleo:
    def test_toma_el_TRIMESTRE_del_corte_y_no_un_promedio_anual(self, db):
        _sembrar_social(db, "informality_rate_trimestral",
                        [("2025-Q4", 55.0), ("2026-Q1", 54.1)], unidad="%")
        _sembrar_social(db, "unemployment_rate_trimestral",
                        [("2026-Q1", 4.95)], unidad="%")
        r = I.mercado_laboral(db, CORTE)
        assert r["trimestre"] == "2026-Q1"
        assert r["ocupacion_informal_pct"] == 54.1
        assert r["desocupacion_abierta_su1_pct"] == 4.95

    def test_sin_informalidad_no_hay_lectura(self, db):
        """Es la que responde la pregunta de crédito —ingreso verificable—; las otras dos
        solas no sostienen la sección."""
        _sembrar_social(db, "unemployment_rate_trimestral", [("2026-Q1", 4.95)], unidad="%")
        assert I.mercado_laboral(db, CORTE) is None


class TestElBloqueCompleto:
    def test_devuelve_lo_que_HAY_y_omite_lo_que_falta(self, db_con_quintiles):
        """Media respuesta es mejor que ninguna, siempre que se declare cuál falta — y la
        forma de declararlo es que la clave no esté."""
        r = I.capacidad_de_pago(db_con_quintiles, CORTE)
        assert "inflacion_del_deudor" in r
        assert "salario_minimo" not in r and "mercado_laboral" not in r

    def test_sin_NINGUNA_lectura_devuelve_None(self, db):
        assert I.capacidad_de_pago(db, CORTE) is None

    def test_una_lectura_que_falla_NO_se_lleva_puestas_a_las_otras(self, db_con_quintiles,
                                                                  monkeypatch):
        monkeypatch.setattr(I, "salario_minimo",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        r = I.capacidad_de_pago(db_con_quintiles, CORTE)
        assert "inflacion_del_deudor" in r


def _sembrar_canasta(db, quintil, puntos):
    from modules.macro_monitor.models.models import MacroSeries
    for periodo, valor in puntos:
        db.add(MacroSeries(series_code=f"{I._PREFIJO_CANASTA}{quintil}", period=periodo,
                           value=valor, unit="RD$", frequency="monthly", source="BCRD"))
    db.commit()


@pytest.fixture()
def db_con_canasta(db):
    """Cifras REALES del BCRD a julio de 2026, redondeadas. A nivel de módulo porque la usan
    la clase que lee el costo y la que computa la cobertura."""
    for q, v in ((1, 29662.0), (2, 38669.0), (3, 45581.0), (4, 52701.0), (5, 80666.0)):
        _sembrar_canasta(db, q, [("2026-02", v - 500), ("2026-03", v)])
    return db


class TestLoQueCuestaLaCanasta:
    """El IPC dice cuánto SUBIÓ la canasta; esto dice cuánto CUESTA. Contra el piso de
    ingreso da la frase que no necesita índices, y el documento metodológico del BCRD señala
    esa comparación como la referencia de las discusiones sobre el salario mínimo."""

    def test_toma_el_ULTIMO_costo_hasta_el_corte(self, db_con_canasta):
        r = I.costo_de_la_canasta(db_con_canasta, CORTE)
        assert r["periodo"] == "2026-03"
        assert r["costo_mensual_de_la_canasta_por_quintil_de_ingreso_rd"]["quintil_1"] == 29662.0

    def test_sin_UN_quintil_no_hay_lectura(self, db):
        for q in (1, 2, 3, 4):
            _sembrar_canasta(db, q, [("2026-03", 30000.0)])
        assert I.costo_de_la_canasta(db, CORTE) is None

    def test_la_clave_nombra_su_poblacion_y_su_unidad(self, db_con_canasta):
        r = I.costo_de_la_canasta(db_con_canasta, CORTE)
        assert any("por_quintil_de_ingreso_rd" in k for k in r)


class TestLaCoberturaDelPisoDeIngreso:
    def test_se_COMPUTA_y_el_modelo_la_copia(self, db_con_canasta):
        _sembrar_social(db_con_canasta, I._TEMA_SALARIO_REFERENCIA, [("2026-03", 27989.0)])
        sal = I.salario_minimo(db_con_canasta, CORTE)
        can = I.costo_de_la_canasta(db_con_canasta, CORTE)
        r = I.cobertura_del_piso_de_ingreso(sal, can)
        cob = r["cobertura_de_la_canasta_por_el_salario_minimo_pct"]
        assert cob["quintil_1"] == 94.4
        assert cob["quintil_5"] == 34.7

    def test_declara_QUÉ_quintiles_no_cubre(self, db_con_canasta):
        _sembrar_social(db_con_canasta, I._TEMA_SALARIO_REFERENCIA, [("2026-03", 27989.0)])
        r = I.cobertura_del_piso_de_ingreso(
            I.salario_minimo(db_con_canasta, CORTE),
            I.costo_de_la_canasta(db_con_canasta, CORTE))
        assert r["quintiles_que_el_piso_NO_cubre"] == [f"quintil_{q}" for q in (1, 2, 3, 4, 5)]

    @pytest.mark.parametrize("sal,can", [(None, {"x": 1}), ({"x": 1}, None), (None, None)])
    def test_con_una_sola_pata_NO_inventa_un_cociente(self, sal, can):
        assert I.cobertura_del_piso_de_ingreso(sal, can) is None

    def test_si_la_clave_del_salario_cambia_la_cuenta_se_APAGA(self, db_con_canasta):
        """En vez de dividir por algo que no es el piso."""
        can = I.costo_de_la_canasta(db_con_canasta, CORTE)
        assert I.cobertura_del_piso_de_ingreso({"otra": 28000.0}, can) is None

    def test_el_bloque_completo_la_INCLUYE_cuando_estan_las_dos(self, db_con_canasta):
        _sembrar_social(db_con_canasta, I._TEMA_SALARIO_REFERENCIA, [("2026-03", 27989.0)])
        r = I.capacidad_de_pago(db_con_canasta, CORTE)
        assert "cobertura_del_piso_de_ingreso" in r


def test_la_plantilla_declara_la_cobertura_como_COPIADA():
    from shared.narrative.claude_engine import THIN_TEMPLATES
    thin = THIN_TEMPLATES["banking_sector_map"]
    assert "cobertura_del_piso_de_ingreso" in thin
    assert "cópiala, no la calcules" in thin
    assert "no como que ese hogar gane el mínimo" in thin, (
        "la cobertura dice qué alcanza el PISO, no cuánto gana el deudor")


def test_las_cinco_series_de_canasta_estan_en_el_registro_CANONICO():
    """Sin esto la ingesta no las trae, y la lectura de arriba queda computando sobre nada —
    que es exactamente lo que pasó con el IPC por quintil durante veintiocho meses."""
    from shared.data.bcrd_excel.canonical import REGISTRY
    claves = {c.key for c in REGISTRY}
    for q in I.QUINTILES:
        assert f"costo_canasta_quintil_{q}" in claves


class TestLaHolguraQueLaMedidaAngostaNoVe:
    """SU1 = 4,95% y SU4 = 10,55% al primer trimestre de 2026. La resta es el punto."""

    @pytest.fixture()
    def db_laboral(self, db):
        for tema, v in (("informality_rate_trimestral", 54.10),
                        ("unemployment_rate_trimestral", 4.95),
                        ("underutilization_su4_trimestral", 10.55),
                        ("underemployment_rate_trimestral", 1.91),
                        ("employment_rate_trimestral", 63.00)):
            _sembrar_social(db, tema, [("2026-Q1", v)], unidad="%")
        return db

    def test_sirve_las_DOS_medidas_con_su_nombre(self, db_laboral):
        r = I.mercado_laboral(db_laboral, CORTE)
        assert r["desocupacion_abierta_su1_pct"] == 4.95
        assert r["subutilizacion_amplia_su4_pct"] == 10.55

    def test_la_brecha_se_COMPUTA_y_no_se_le_pide_al_modelo(self, db_laboral):
        r = I.mercado_laboral(db_laboral, CORTE)
        assert r["holgura_que_SU1_no_ve_pp"] == 5.60

    def test_sin_la_ANCHA_no_hay_brecha_inventada(self, db):
        for tema, v in (("informality_rate_trimestral", 54.10),
                        ("unemployment_rate_trimestral", 4.95)):
            _sembrar_social(db, tema, [("2026-Q1", v)], unidad="%")
        r = I.mercado_laboral(db, CORTE)
        assert "holgura_que_SU1_no_ve_pp" not in r

    def test_la_lectura_EXPLICA_por_qué_la_ancha_importa_en_crédito(self, db_laboral):
        r = I.mercado_laboral(db_laboral, CORTE)
        assert "ingreso insuficiente" in r["por_que_importa_en_credito"]


def test_la_referencia_del_salario_EXISTE_en_la_fuente():
    """Un binding a una serie inexistente no falla: DESAPARECE.

    La primera versión declaró `sm_empresa_grande_no_sectorizado` — plausible, y falsa. La
    clave real la produce `social_sync._tema_salario` sobre la fuente, y con la equivocada
    `salario_minimo()` devolvía `None`, la cobertura no se computaba y el informe salía sin
    la lectura sin que nada fallara. Se descubrió comparando contra la fuente, no corriendo
    el código: el código «funcionaba».

    Este test reconstruye las claves desde el mismo slug que usa la ingesta, así que sigue
    valiendo si la fuente cambia el nombre de una categoría.
    """
    from modules.social_dev.social_sync import _tema_salario

    class _Serie:
        def __init__(self, tamano, area):
            self.tamano, self.area = tamano, area

    # Las categorías tal como las publica el MHE en datos.gob.do.
    reales = [_Serie("Empresa grande", "Empresas del sector no sectorizado"),
              _Serie("Empresa mediana", "Empresas del sector no sectorizado"),
              _Serie("Microempresa", "Empresas del sector no sectorizado"),
              _Serie("Zona franca en áreas geográficas deprimidas", "Zona franca")]
    temas = {_tema_salario(s) for s in reales}
    assert I._TEMA_SALARIO_REFERENCIA in temas, (
        f"«{I._TEMA_SALARIO_REFERENCIA}» no es ninguna de las claves que la ingesta "
        f"produce: {sorted(temas)}. La lectura devolvería None en silencio.")


def test_la_referencia_es_la_categoria_VIGENTE_y_no_una_congelada():
    """Zona franca deprimida (RD$3.600, sin ajuste desde 2006) y Gobierno Central
    (RD$10.000, desde 2019) siguen publicándose. Tomar una de ésas como «el salario mínimo»
    publicaría como piso de hoy un número de hace veinte años."""
    assert "zona_franca" not in I._TEMA_SALARIO_REFERENCIA
    assert "gobierno" not in I._TEMA_SALARIO_REFERENCIA
    assert "empresa_grande" in I._TEMA_SALARIO_REFERENCIA


class TestLaPrecisionDeLaEncuesta:
    """La ENCFT es una ENCUESTA y publicábamos sus cifras desnudas.

    El BCRD publica el error estándar, el intervalo al 95% y el coeficiente de variación de
    cada estimación —en dos hojas del mismo libro que ya descargábamos— y no se usaban. Una
    diferencia menor que los intervalos NO es una diferencia: sin ellos, «5,60 puntos» se lee
    como un hecho exacto de una medición que no lo es. Es la doctrina de ordenar solo lo
    comparable, aplicada al dato de encuesta.
    """

    @pytest.fixture()
    def db_con_precision(self, db):
        for tema, v in (("informality_rate_trimestral", 54.10),
                        ("unemployment_rate_trimestral", 4.95),
                        ("underutilization_su4_trimestral", 10.55),
                        # Cifras REALES del BCRD al primer trimestre de 2026.
                        ("unemployment_rate_trimestral_ic95_inf", 4.43),
                        ("unemployment_rate_trimestral_ic95_sup", 5.48),
                        ("unemployment_rate_trimestral_cv", 6.45),
                        ("underutilization_su4_trimestral_ic95_inf", 9.87),
                        ("underutilization_su4_trimestral_ic95_sup", 11.23),
                        ("underutilization_su4_trimestral_cv", 3.93)):
            _sembrar_social(db, tema, [("2026-Q1", v)], unidad="%")
        return db

    def test_sirve_el_INTERVALO_y_el_coeficiente_de_variacion(self, db_con_precision):
        r = I.mercado_laboral(db_con_precision, CORTE)
        p = r["precision_de_la_encuesta"]["desocupacion_abierta_su1"]
        assert p["ic95_inferior"] == 4.43 and p["ic95_superior"] == 5.48
        assert p["coeficiente_de_variacion_pct"] == 6.45

    def test_decide_si_la_brecha_SE_PUEDE_AFIRMAR(self, db_con_precision):
        """SU1 llega a 5,48 y SU4 arranca en 9,87: no se solapan, la brecha es real."""
        r = I.mercado_laboral(db_con_precision, CORTE)
        assert r["la_brecha_entre_SU1_y_SU4_es_significativa"] is True

    def test_si_los_intervalos_SE_SOLAPAN_la_brecha_no_se_afirma(self, db):
        for tema, v in (("informality_rate_trimestral", 54.10),
                        ("unemployment_rate_trimestral", 9.0),
                        ("underutilization_su4_trimestral", 10.0),
                        ("unemployment_rate_trimestral_ic95_inf", 8.0),
                        ("unemployment_rate_trimestral_ic95_sup", 10.5),
                        ("underutilization_su4_trimestral_ic95_inf", 9.2),
                        ("underutilization_su4_trimestral_ic95_sup", 11.0)):
            _sembrar_social(db, tema, [("2026-Q1", v)], unidad="%")
        r = I.mercado_laboral(db, CORTE)
        assert r["la_brecha_entre_SU1_y_SU4_es_significativa"] is False

    def test_sin_precision_la_lectura_sigue_saliendo_sin_el_bloque(self, db):
        for tema, v in (("informality_rate_trimestral", 54.10),
                        ("unemployment_rate_trimestral", 4.95)):
            _sembrar_social(db, tema, [("2026-Q1", v)], unidad="%")
        r = I.mercado_laboral(db, CORTE)
        assert "precision_de_la_encuesta" not in r
        assert r["ocupacion_informal_pct"] == 54.10

    def test_la_plantilla_prohibe_afirmar_una_diferencia_que_se_SOLAPA(self):
        from shared.narrative.claude_engine import THIN_TEMPLATES
        thin = THIN_TEMPLATES["banking_sector_map"]
        assert "la_brecha_entre_SU1_y_SU4_es_significativa" in thin
        assert "los intervalos se solapan" in thin


class TestLaHolguraPorRegion:
    """La holgura laboral no es nacional, y el informe citaba solo el país."""

    @pytest.fixture()
    def db_regional(self, db):
        from modules.social_dev.models.models import SocialIndicator
        # Cifras REALES de la ENCFT 2025.
        for dom, su4, su1 in (("ozama", 13.70, 6.31), ("norte", 6.52, 2.24),
                              ("sur", 14.00, 5.60), ("este", 9.35, 4.11)):
            for tema, v in (("subutilizacion_su4_regional_anual", su4),
                            ("desocupacion_su1_regional_anual", su1)):
                db.add(SocialIndicator(theme=tema, entity_key=dom, period="2025",
                                       value=v, unit="%", source="BCRD"))
        db.commit()
        return db

    def test_sirve_la_tabla_por_dominio(self, db_regional):
        r = I.mercado_laboral_por_region(db_regional, CORTE)
        assert r["por_dominio"]["sur"]["subutilizacion_amplia_su4_pct"] == 14.00
        assert r["por_dominio"]["norte"]["subutilizacion_amplia_su4_pct"] == 6.52

    def test_la_DISPERSION_se_computa_y_nombra_los_extremos(self, db_regional):
        r = I.mercado_laboral_por_region(db_regional, CORTE)
        assert r["dispersion_de_la_subutilizacion_pp"] == pytest.approx(7.48, abs=.01)
        assert r["dominio_con_mas_holgura"] == "sur"
        assert r["dominio_con_menos_holgura"] == "norte"

    def test_el_TOTAL_PAIS_no_entra_entre_los_que_se_comparan(self):
        """Meterlo produciría una «dispersión» contra un promedio, que es otra cuenta."""
        assert "nacional" not in I._DOMINIOS_ENCFT

    def test_con_un_solo_dominio_NO_hay_dispersion(self, db):
        from modules.social_dev.models.models import SocialIndicator
        db.add(SocialIndicator(theme="subutilizacion_su4_regional_anual", entity_key="sur",
                               period="2025", value=14.0, unit="%", source="BCRD"))
        db.commit()
        assert I.mercado_laboral_por_region(db, CORTE) is None

    def test_DECLARA_de_dónde_sale_la_correspondencia_con_el_credito(self, db_regional):
        """Antes esta lectura declaraba que NO se cruzaba con las provincias del libro,
        porque la correspondencia no estaba verificada. Se verificó: los dominios de la
        ENCFT se construyen sobre las 10 Regiones de Desarrollo del Decreto 710-04 —lo dice
        su diseño muestral— y la partición del cubo de la SIB coincide provincia por
        provincia. La declaración cambia con el hecho, no al revés."""
        r = I.mercado_laboral_por_region(db_regional, CORTE)
        assert "710-04" in r["que_es"]
        assert "nomenclaturas distintas" not in r["que_es"]

    def test_entra_al_bloque_de_capacidad_de_pago(self, db_regional):
        r = I.capacidad_de_pago(db_regional, CORTE)
        assert "holgura_por_region" in r


class TestLaHolguraDondePresta:
    """El cruce que ningún banco puede hacer — y no por el dato, que es público, sino por la
    mitad que le falta: el libro de crédito abierto por provincia de las otras noventa y una
    entidades."""

    @pytest.fixture()
    def db_cruce(self, db):
        from modules.social_dev.models.models import SocialIndicator
        for dom, su4, su1 in (("ozama", 13.70, 6.31), ("norte", 6.52, 2.24),
                              ("sur", 14.00, 5.60), ("este", 9.35, 4.11),
                              ("nacional", 10.88, 4.95)):
            for tema, v in (("subutilizacion_su4_regional_anual", su4),
                            ("desocupacion_su1_regional_anual", su1)):
                db.add(SocialIndicator(theme=tema, entity_key=dom, period="2025",
                                       value=v, unit="%", source="BCRD"))
        db.commit()
        return db

    _PROVINCIAS = [
        {"provincia": "DISTRITO NACIONAL", "deuda": 600_000_000.0},
        {"provincia": "SANTIAGO", "deuda": 300_000_000.0},
        {"provincia": "SAN CRISTOBAL", "deuda": 100_000_000.0},
    ]

    def test_agrupa_la_cartera_por_DOMINIO(self, db_cruce):
        r = I.holgura_donde_presta(db_cruce, CORTE, self._PROVINCIAS)
        pesos = {f["dominio"]: f["peso_en_su_cartera_pct"] for f in r["por_dominio"]}
        assert pesos == {"ozama": 60.0, "norte": 30.0, "sur": 10.0}

    def test_la_holgura_se_pondera_por_SU_exposicion_y_no_es_el_promedio_del_pais(
            self, db_cruce):
        """Un promedio simple de los cuatro daría la holgura de un banco que prestara igual
        en los cuatro, que no es ninguno."""
        r = I.holgura_donde_presta(db_cruce, CORTE, self._PROVINCIAS)
        esperado = 0.60 * 13.70 + 0.30 * 6.52 + 0.10 * 14.00
        assert r["subutilizacion_ponderada_por_su_exposicion_pct"] == pytest.approx(
            esperado, abs=.01)
        assert r["subutilizacion_ponderada_por_su_exposicion_pct"] != pytest.approx(
            (13.70 + 6.52 + 14.00 + 9.35) / 4, abs=.1)

    def test_la_comparacion_contra_el_PAIS_se_computa(self, db_cruce):
        r = I.holgura_donde_presta(db_cruce, CORTE, self._PROVINCIAS)
        assert r["subutilizacion_del_pais_pct"] == 10.88
        assert r["mas_holgura_que_el_pais_pp"] == pytest.approx(
            r["subutilizacion_ponderada_por_su_exposicion_pct"] - 10.88, abs=.01)

    def test_SIN_PROVINCIA_queda_fuera_y_se_DECLARA(self, db_cruce):
        provincias = self._PROVINCIAS + [{"provincia": "SIN PROVINCIA",
                                          "deuda": 200_000_000.0}]
        r = I.holgura_donde_presta(db_cruce, CORTE, provincias)
        assert {f["dominio"] for f in r["por_dominio"]} == {"ozama", "norte", "sur"}
        assert r["cartera_sin_dominio_asignable_pct"] == pytest.approx(16.67, abs=.01)
        assert "no le corresponde" in r["por_que_queda_fuera"]

    def test_declara_de_dónde_sale_la_region(self, db_cruce):
        r = I.holgura_donde_presta(db_cruce, CORTE, self._PROVINCIAS)
        assert "710-04" in r["procedencia_de_la_region"]

    def test_sin_dato_laboral_no_hay_cruce(self, db):
        assert I.holgura_donde_presta(db, CORTE, self._PROVINCIAS) is None

    def test_sin_provincias_no_hay_cruce(self, db_cruce):
        assert I.holgura_donde_presta(db_cruce, CORTE, []) is None

    @pytest.mark.parametrize("archivo", [
        "modules/banking_score/products.py",
        "modules/banking_score/api/router_reports.py",
    ])
    def test_las_rutas_que_emiten_un_informe_lo_SIRVEN(self, archivo):
        import pathlib
        assert "holgura_donde_presta" in pathlib.Path(archivo).read_text()
