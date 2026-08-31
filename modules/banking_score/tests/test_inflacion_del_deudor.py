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
from shared.database.base import Base
from modules.banking_score.reports import inflacion_del_deudor as I

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
             "inflacion_del_deudor": {"brecha_quintil_1_menos_quintil_5_pp": 7.1},
             "indicators": {}},
            "2026-03-31")
        assert ctx["inflacion_del_deudor"], (
            "el bloque se computa y no llega al modelo: la sección no puede mencionarlo")

    def test_la_plantilla_declara_CUANDO_usarlo_y_cuando_no(self):
        from shared.narrative.claude_engine import THIN_TEMPLATES
        thin = THIN_TEMPLATES["banking_sector_map"]
        assert "inflacion_del_deudor" in thin
        assert "no menciones inflación por quintil" in thin, (
            "sin la rama negativa, el modelo inventa el bloque cuando falta")
        assert "NO la presentes como causa probada" in thin, (
            "es contexto de capacidad de pago, no la atribución de la mora")

    @pytest.mark.parametrize("archivo,ancla", [
        ("modules/banking_score/products.py", "scoring_result[\"inflacion_del_deudor\"]"),
        ("modules/banking_score/products.py", "pl[\"inflacion_del_deudor\"]"),
        ("modules/banking_score/products_year_review.py", "out[\"inflacion_del_deudor\"]"),
        ("modules/banking_score/api/router_reports.py",
         "scoring_result[\"inflacion_del_deudor\"]"),
    ])
    def test_llega_por_los_CUATRO_caminos_que_emiten_un_informe(self, archivo, ancla):
        """Trimestral, año por trimestres, Revisión Anual y la ruta de informes. Cablearlo
        en uno solo es cómo el mapa sectorial terminó estando en un informe de cuatro."""
        import pathlib
        assert ancla in pathlib.Path(archivo).read_text(), (
            f"«{archivo}» no sirve el bloque: ese informe saldría sin la lectura")


class TestUnaSerieSinSujetoNoSePERSISTE:
    """El defecto que apareció al ir a buscar el IPC por quintil.

    La planilla del BCRD trae, junto a los cinco índices por quintil, cinco columnas de
    TASA. La inferencia no encuentra un rótulo que las distinga —las cinco se llaman
    «tasa de inflación»— y las desempata por índice de columna: `tasa_de_inflacion_c5`,
    `_c7`, `_c9`, `_c11`. Ese nombre no dice de QUÉ quintil es la tasa.

    El commit que trajo la planilla lo declaró y dijo que se descartaban «a propósito». La
    ingesta las persistió igual: la intención estaba escrita y nada la hacía cumplir. En
    producción quedaron dieciocho series así —también del IMAE y del IPC por región—, una
    tasa sin su región al lado de índices que sí nombran su población, y quien las consuma
    después no tiene cómo saber que el rótulo no identifica nada.

    Es la doctrina del sujeto rota en el punto donde se FABRICA el nombre, y por eso el
    veto va en la frontera de ESCRITURA y no en cada extractor: es la única puerta por la
    que pasan todos.
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
        from modules.banking_score.reports.inflacion_del_deudor import _PREFIJO, QUINTILES
        for q in QUINTILES:
            assert not _sin_sujeto(f"{_PREFIJO}{q}")

    def test_el_veto_se_REGISTRA_y_no_es_silencioso(self):
        """Un veto que no deja marca se lee como que la planilla no traía esas columnas."""
        import inspect
        from modules.macro_monitor import service
        src = inspect.getsource(service._upsert_records)
        assert "logger.info" in src and "descartadas" in src
