"""La sección de desempeño se publica por DOS caminos, y tienen que decir lo mismo.

* El eje macro la pide a la base: `app/products_macro._track_record_md` → `desempeno.seccion`.
* El producto «SDQ Proyecciones Macro» la arma del SNAPSHOT, en otro proceso y sin base:
  `products_forecast._md_desempeno`.

El segundo tenía la frase de «todavía no hay pronósticos puntuados» duplicada palabra por
palabra. Cuando se corrigió el primero —porque decía que los trimestres no habían cerrado
mientras la verdad era que **no podían** cerrar, con las filas del BVAR apuntando a una serie
inexistente— esta copia siguió mintiendo, y nada falló: cada superficie desaparece el
problema en un lugar distinto.

Es el mismo defecto que ya costó cuatro registros de a uno en el anuario. Acá lo vigila la
paridad, no una lección escrita.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor import products_forecast
from modules.macro_monitor.forecasting import desempeno, ledger
from shared.data import medida_de_pronostico as med
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base

SERIE = "bcrd.xls.pib_2018.serie_original_indice"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _desde_el_snapshot(db) -> str:
    """El camino del producto: se arma el payload y se renderiza SIN volver a la base."""
    payload = products_forecast.MacroForecastProduct(db)._payload(db)
    return products_forecast._md_desempeno(payload)


def test_sin_nada_emitido_las_dos_dicen_lo_MISMO(db):
    assert desempeno.seccion(db) == _desde_el_snapshot(db) == desempeno.SIN_HISTORIAL


def test_con_una_fila_ROTA_las_dos_la_NOMBRAN(db):
    """El caso que separaba a las dos superficies. `pib_real` es el nombre de la variable en
    el bloque: esa fila no está esperando el trimestre, no puede cerrar nunca."""
    ledger.registrar(db, model_id="bvar_minnesota.5v.v1", target_series="pib_real",
                     horizon="2026-Q3", as_of="2026-08-15", point=1.2, h=1,
                     measure=med.DLOG_PCT, intervals=[[0.80, 0.3, 2.1]])

    de_la_base = desempeno.seccion(db)
    del_snapshot = _desde_el_snapshot(db)
    assert de_la_base == del_snapshot, (
        "las dos superficies publican textos distintos para el mismo estado; el documento se "
        "contradice según por dónde salga")
    for texto in (de_la_base, del_snapshot):
        assert "pib_real" in texto
        assert desempeno.SIN_HISTORIAL not in texto, (
            "la sección sigue diciendo que los trimestres no cerraron")


def test_con_track_record_Y_una_fila_rota_las_dos_muestran_LAS_DOS_COSAS(db):
    """La tabla no puede tapar lo roto: con `n` acumulándose, una fila que no cierra se leería
    como si el `n` fuera todo lo emitido."""
    db.add(MacroSeries(series_code=SERIE, period="2025-Q3", value=131.0))
    db.add(MacroSeries(series_code=SERIE, period="2025-Q4", value=132.0))
    db.commit()
    f = ledger.registrar(db, model_id="bridge_imae_pib.m2.v1", target_series=SERIE,
                         horizon="2025-Q4", as_of="2025-11-15", point=0.7, h=1,
                         measure=med.DLOG_PCT, intervals=[[0.80, -0.3, 1.7]])
    ledger.puntuar_pendientes(db)
    assert f.status == "scored"
    ledger.registrar(db, model_id="bvar_minnesota.5v.v1", target_series="pib_real",
                     horizon="2026-Q3", as_of="2026-08-15", point=1.2, h=1,
                     measure=med.DLOG_PCT, intervals=[[0.80, 0.3, 2.1]])

    de_la_base = desempeno.seccion(db)
    del_snapshot = _desde_el_snapshot(db)
    for texto in (de_la_base, del_snapshot):
        assert "bridge_imae_pib.m2.v1" in texto      # la tabla
        assert "pib_real" in texto                   # y lo que no va a cerrar
        assert desempeno.HAY_ROTAS in texto


def test_la_prosa_NO_esta_duplicada_en_la_otra_superficie():
    """Estructural: el texto vive en constantes y la otra superficie las IMPORTA. Un literal
    copiado se corrige de un lado y sigue mintiendo del otro — así estaba."""
    import inspect

    fuente = inspect.getsource(products_forecast)
    for constante in (desempeno.SIN_HISTORIAL, desempeno.HAY_ROTAS,
                      desempeno.QUE_SI_SE_PUEDE_ESPERAR):
        # La frase entera no puede aparecer literal; se busca un tramo largo y distintivo.
        aguja = constante[:60]
        assert aguja not in fuente, (
            f"«{aguja}…» está escrito de nuevo en `products_forecast`: cuando se corrija del "
            "otro lado, esta copia va a seguir publicando el texto viejo")
