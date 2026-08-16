"""Tests del registro de gasto del modelo.

Lo que se protege no es «la fila se guarda». Son las tres propiedades que, al fallar,
devuelven el sistema al estado que originó esto: un total sin dueño, una caché
invisible, y un registro que puede tumbar un informe.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.database.base import Base
from shared.observability import llm_ledger as L
from shared.observability import spend
from shared.observability.models import LLMCall


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[LLMCall.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("shared.database.session.SessionLocal", Session)
    s = Session()
    yield s
    s.close()


# ─────────────────────────────────────────────────────────────────────────────
# El disparador es la razón de ser de la tabla
# ─────────────────────────────────────────────────────────────────────────────

def test_la_llamada_queda_a_nombre_de_quien_la_disparo(db):
    """Sin esto hay un total y ninguna forma de saber a quién cobrárselo: descubrir que
    una tarea diaria generaba 203 informes costó leer código y logs."""
    with L.attributed_to("operacion", "prewarm-report-cache"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=0.10,
                      module="banking_score", template="t")
    fila = db.query(LLMCall).one()
    assert fila.trigger_kind == "operacion"
    assert fila.trigger_detail == "prewarm-report-cache"


def test_sin_contexto_la_llamada_se_marca_desconocida_no_se_pierde(db):
    L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=0.02)
    fila = db.query(LLMCall).one()
    assert fila.trigger_detail == L.TRIGGER_UNKNOWN


def test_la_atribucion_no_se_filtra_fuera_de_su_bloque(db):
    with L.attributed_to("operacion", "market-brief"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m")
    L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m")
    detalles = sorted(f.trigger_detail for f in db.query(LLMCall).all())
    assert detalles == ["desconocido", "market-brief"]


def test_la_atribucion_anidada_restaura_la_anterior(db):
    """El prewarm calienta en paralelo; una global les mezclaría la atribución."""
    with L.attributed_to("operacion", "externa"):
        with L.attributed_to("endpoint", "interna"):
            assert L.current_caller().detail == "interna"
        assert L.current_caller().detail == "externa"


# ─────────────────────────────────────────────────────────────────────────────
# El registro jamás tumba la entrega
# ─────────────────────────────────────────────────────────────────────────────

def test_un_fallo_al_registrar_no_propaga(monkeypatch):
    """Preferimos perder una fila a perder un informe."""
    def explota():
        raise RuntimeError("base caída")

    monkeypatch.setattr("shared.database.session.SessionLocal", explota)
    L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=1.0)  # no debe lanzar


# ─────────────────────────────────────────────────────────────────────────────
# Los HIT de caché se registran, con costo cero
# ─────────────────────────────────────────────────────────────────────────────

def test_el_hit_de_cache_se_registra_y_se_distingue(db):
    """Sin el HIT no se distingue «nadie pidió esto» de «lo pidieron cien veces y la
    caché lo absorbió», que es la diferencia que justifica tener caché."""
    with L.attributed_to("endpoint", "/report"):
        for _ in range(9):
            L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m",
                          cost_usd=0.0, cache_hit=True)
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=0.5)
    res = spend.spend_summary(db, days=1)
    fila = next(f for f in res["por_disparador"] if f["clave"] == "/report")
    assert fila["llamadas"] == 10
    assert fila["hits_de_cache"] == 9
    assert fila["generaciones_reales"] == 1
    assert fila["costo_usd"] == 0.5


# ─────────────────────────────────────────────────────────────────────────────
# La consulta responde la pregunta que motivó todo
# ─────────────────────────────────────────────────────────────────────────────

def test_el_resumen_ordena_por_costo_y_separa_producir_de_verificar(db):
    with L.attributed_to("operacion", "prewarm-report-cache"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=8.0,
                      module="banking_score")
        L.record_call(purpose=L.PURPOSE_GUARD, model="m", cost_usd=4.0,
                      module="banking_score")
    with L.attributed_to("endpoint", "/brand/report"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=1.0,
                      module="brand_intel")

    res = spend.spend_summary(db, days=1)
    assert res["costo_total_usd"] == 13.0
    assert res["llamadas_totales"] == 3
    # El disparador más caro va primero: es la pregunta que se hace primero.
    assert res["por_disparador"][0]["clave"] == "prewarm-report-cache"
    assert res["por_disparador"][0]["costo_usd"] == 12.0
    # Y el juez se ve APARTE de lo que produce, que es lo que lo hacía invisible.
    motivos = {f["clave"]: f["costo_usd"] for f in res["por_motivo"]}
    assert motivos[L.PURPOSE_GUARD] == 4.0
    assert motivos[L.PURPOSE_NARRATIVE] == 9.0


def test_el_total_no_depende_de_la_lista_truncada(db):
    """El total se computa aparte: una lista cortada a ``top`` sumaría mal, y el total es
    justo la cifra que se mira primero."""
    for i in range(20):
        with L.attributed_to("operacion", f"op-{i}"):
            L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=1.0)
    res = spend.spend_summary(db, days=1, top=3)
    assert len(res["por_disparador"]) == 3
    assert res["costo_total_usd"] == 20.0


def test_el_detalle_por_disparador_ordena_por_costo(db):
    with L.attributed_to("operacion", "x"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=0.1)
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=0.9)
    filas = spend.spend_detail(db, days=1, trigger="x")
    assert [f["costo_usd"] for f in filas] == [0.9, 0.1]


def test_la_ventana_excluye_lo_viejo(db):
    from datetime import datetime, timedelta, timezone
    viejo = (datetime.now(timezone.utc) - timedelta(days=90)).replace(tzinfo=None)
    db.add(LLMCall(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=99.0,
                   trigger_kind="operacion", trigger_detail="antigua",
                   created_at=viejo))
    db.commit()
    assert spend.spend_summary(db, days=30)["costo_total_usd"] == 0.0
