"""Los tiempos por sección — la medición que faltaba para diagnosticar un corte por tiempo.

El registro guardaba costo, tokens y caché, pero no cuánto tardaba nada. Cuando un Deep Dive
se pasó del techo el 2026-08-26 no se pudo decir si lo consumió UNA sección lenta o la suma de
todas: hubo que descartar el tope de gasto a mano y aun así quedarse sin causa.

Lo que estos tests protegen es que la medición no MIENTA, que es más fácil de lo que parece:

  * un HIT de caché no tarda, y contarlo haría parecer una generación mucho más rápida;
  * una fila anterior a esta medición no es «0 s», es «no medido», y se DECLARA;
  * el informe que se cortó tiene que poder encontrarse, que es todo el punto.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.database.base import Base
from shared.observability.models import LLMCall
from shared.observability.tiempos_de_narrativa import tiempos_de_narrativa


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[LLMCall.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _fila(db, *, purpose="narrativa", template="banking_risk", segundos=None,
          cache_hit=False, corto=False, module="banking", dias=0, sin_detalle=False):
    detalle = {} if sin_detalle else {"segundos": segundos}
    if purpose == "ensamblado":
        detalle["corto_por_tiempo"] = corto
    f = LLMCall(purpose=purpose, model="m", cost_usd=0.0, module=module,
                template=template, cache_hit=cache_hit, detail=detalle)
    f.created_at = datetime.now(timezone.utc) - timedelta(days=dias)
    db.add(f)
    db.commit()
    return f


def test_señala_la_seccion_MAS_LENTA_por_p90(db):
    """Es la pregunta entera: ¿cuál me como el tiempo?"""
    for s in (20, 22, 25, 210):
        _fila(db, template="banking_risk", segundos=s)
    for s in (18, 19, 20, 21):
        _fila(db, template="banking_summary", segundos=s)
    out = tiempos_de_narrativa(db)
    assert out["por_seccion"][0]["plantilla"] == "banking_risk"
    assert out["por_seccion"][0]["max"] == 210.0


def test_un_HIT_de_cache_NO_entra_en_los_percentiles(db):
    """Contarlo haría parecer una generación real mucho más rápida — el autoengaño exacto
    que esta medición viene a evitar."""
    _fila(db, template="banking_risk", segundos=200.0)
    for _ in range(9):
        _fila(db, template="banking_risk", segundos=0.0, cache_hit=True)
    out = tiempos_de_narrativa(db)
    fila = next(s for s in out["por_seccion"] if s["plantilla"] == "banking_risk")
    assert fila["n"] == 1, "los 9 hits no pueden diluir la mediana"
    assert fila["mediana"] == 200.0


def test_una_fila_SIN_medicion_se_declara_y_no_cuenta_como_cero(db):
    """«No medido» y «tardó 0» son cosas distintas; confundirlas es el mismo modo de falla
    que `stale=null`."""
    _fila(db, segundos=30.0)
    _fila(db, sin_detalle=True)
    out = tiempos_de_narrativa(db)
    assert out["llamadas_sin_medicion"] == 1
    assert out["por_seccion"][0]["n"] == 1


def test_el_informe_CORTADO_se_puede_encontrar(db):
    _fila(db, purpose="ensamblado", template="deep_dive", segundos=271.4, corto=True)
    _fila(db, purpose="ensamblado", template="insight", segundos=63.2, corto=False)
    out = tiempos_de_narrativa(db)
    assert out["informes"]["n"] == 2
    assert out["informes"]["cortados_por_tiempo"] == 1
    assert out["informes"]["ultimos_cortados"][0]["segundos"] == 271.4
    assert out["informes"]["ultimos_cortados"][0]["nivel"] == "deep_dive"


def test_el_ensamblado_no_se_mezcla_con_las_secciones(db):
    """Un total de informe entre los tiempos de sección inventaría una sección lentísima."""
    _fila(db, purpose="ensamblado", template="deep_dive", segundos=271.4)
    _fila(db, template="banking_risk", segundos=40.0)
    out = tiempos_de_narrativa(db)
    assert [s["plantilla"] for s in out["por_seccion"]] == ["banking_risk"]


def test_el_rango_por_defecto_deja_fuera_lo_viejo(db):
    _fila(db, template="reciente", segundos=10.0, dias=0)
    _fila(db, template="vieja", segundos=99.0, dias=30)
    assert {s["plantilla"] for s in tiempos_de_narrativa(db)["por_seccion"]} == {"reciente"}


def test_un_ensamblado_LENTO_que_TERMINO_se_puede_encontrar(db):
    """La mitad que faltaba del diagnóstico.

    El caso real: alguien vio «No se pudo cargar el producto» en el navegador y el endpoint
    decía `cortados_por_tiempo: 0`. Leído solo, eso se entiende como «no fue un problema de
    tiempo» — y es falso: el informe había TERMINADO a los 130 s, después de que el proxy ya
    hubiera cortado la conexión. Un techo propio por encima del límite del proxy nunca llega
    a actuar, así que la ausencia de cortes no prueba nada por sí sola.
    """
    _fila(db, purpose="ensamblado", template="deep_dive", segundos=130.0, corto=False)
    _fila(db, purpose="ensamblado", template="deep_dive", segundos=12.0, corto=False)
    out = tiempos_de_narrativa(db)
    assert out["informes"]["cortados_por_tiempo"] == 0
    lentos = out["informes"]["mas_lentos"]
    assert [e["segundos"] for e in lentos] == [130.0, 12.0], "van de más lento a menos"


def test_el_ensamblado_CORTADO_no_se_repite_entre_los_mas_lentos(db):
    """Son dos listas con dos preguntas distintas: `ultimos_cortados` es «¿a quién matamos
    nosotros?» y `mas_lentos` es «¿a quién mataron por fuera?». Mezclarlas haría que el
    cortado —siempre el más largo— tapara al que interesa."""
    _fila(db, purpose="ensamblado", template="deep_dive", segundos=300.0, corto=True)
    _fila(db, purpose="ensamblado", template="deep_dive", segundos=130.0, corto=False)
    out = tiempos_de_narrativa(db)["informes"]
    assert [e["segundos"] for e in out["ultimos_cortados"]] == [300.0]
    assert [e["segundos"] for e in out["mas_lentos"]] == [130.0]
