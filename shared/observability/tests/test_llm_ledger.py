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
    with L.attributed_to("operacion", "informes-nocturnos"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=0.10,
                      module="banking_score", template="t")
    fila = db.query(LLMCall).one()
    assert fila.trigger_kind == "operacion"
    assert fila.trigger_detail == "informes-nocturnos"


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
    """Una operación que genera en paralelo mezclaría la atribución con una global."""
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
    res = spend.spend_summary(db)
    fila = next(f for f in res["por_disparador"] if f["clave"] == "/report")
    assert fila["llamadas"] == 10
    assert fila["hits_de_cache"] == 9
    assert fila["generaciones_reales"] == 1
    assert fila["costo_usd"] == 0.5


# ─────────────────────────────────────────────────────────────────────────────
# La consulta responde la pregunta que motivó todo
# ─────────────────────────────────────────────────────────────────────────────

def test_el_resumen_ordena_por_costo_y_separa_producir_de_verificar(db):
    with L.attributed_to("operacion", "informes-nocturnos"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=8.0,
                      module="banking_score")
        L.record_call(purpose=L.PURPOSE_GUARD, model="m", cost_usd=4.0,
                      module="banking_score")
    with L.attributed_to("endpoint", "/brand/report"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=1.0,
                      module="brand_intel")

    res = spend.spend_summary(db)
    assert res["costo_total_usd"] == 13.0
    assert res["llamadas_totales"] == 3
    # El disparador más caro va primero: es la pregunta que se hace primero.
    assert res["por_disparador"][0]["clave"] == "informes-nocturnos"
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
    res = spend.spend_summary(db, top=3)
    assert len(res["por_disparador"]) == 3
    assert res["costo_total_usd"] == 20.0


def test_el_detalle_por_disparador_ordena_por_costo(db):
    with L.attributed_to("operacion", "x"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=0.1)
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=0.9)
    filas = spend.spend_detail(db, trigger="x")
    assert [f["costo_usd"] for f in filas] == [0.9, 0.1]


# ─────────────────────────────────────────────────────────────────────────────
# El rango va por FECHAS: la pregunta es si cuadra con la factura
# ─────────────────────────────────────────────────────────────────────────────

def _fila(db, cuando, costo=1.0):
    db.add(LLMCall(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=costo,
                   trigger_kind="operacion", trigger_detail="op",
                   created_at=cuando))
    db.commit()


def test_el_dia_final_entra_completo(db):
    """La trampa: quien pide «hasta el 16» quiere lo del 16, no lo anterior a su
    medianoche. Tomar la fecha tal cual dejaría fuera todo el último día —el que más se
    mira— y el error sería invisible porque el total seguiría siendo plausible."""
    from datetime import date, datetime

    _fila(db, datetime(2026, 8, 16, 23, 59, 58), costo=5.0)
    res = spend.spend_summary(db, desde=date(2026, 8, 1), hasta=date(2026, 8, 16))
    assert res["costo_total_usd"] == 5.0
    assert res["hasta"] == "2026-08-16"


def test_el_dia_inicial_entra_desde_su_medianoche(db):
    from datetime import date, datetime

    _fila(db, datetime(2026, 8, 1, 0, 0, 1), costo=3.0)
    assert spend.spend_summary(db, desde=date(2026, 8, 1),
                               hasta=date(2026, 8, 31))["costo_total_usd"] == 3.0


def test_lo_de_fuera_del_rango_no_entra(db):
    from datetime import date, datetime

    _fila(db, datetime(2026, 7, 31, 23, 59, 59), costo=9.0)   # un segundo antes
    _fila(db, datetime(2026, 9, 1, 0, 0, 0), costo=9.0)       # un segundo después
    _fila(db, datetime(2026, 8, 15, 12, 0, 0), costo=1.0)     # dentro
    res = spend.spend_summary(db, desde=date(2026, 8, 1), hasta=date(2026, 8, 31))
    assert res["costo_total_usd"] == 1.0
    assert res["llamadas_totales"] == 1


def test_sin_rango_toma_los_ultimos_treinta_dias(db):
    from datetime import datetime, timedelta, timezone

    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    _fila(db, ahora - timedelta(days=5), costo=2.0)
    _fila(db, ahora - timedelta(days=90), costo=99.0)
    assert spend.spend_summary(db)["costo_total_usd"] == 2.0


def test_el_detalle_respeta_el_mismo_rango(db):
    from datetime import date, datetime

    _fila(db, datetime(2026, 8, 16, 20, 0, 0), costo=4.0)
    _fila(db, datetime(2026, 6, 1, 20, 0, 0), costo=4.0)
    filas = spend.spend_detail(db, desde=date(2026, 8, 1), hasta=date(2026, 8, 16),
                               trigger="op")
    assert len(filas) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Los dos defectos que el propio registro destapó en producción
# ─────────────────────────────────────────────────────────────────────────────

class _Usage:
    input_tokens = 1000
    output_tokens = 500


class _Resp:
    usage = _Usage()


def test_el_juez_registra_su_costo_y_no_cero(db, monkeypatch):
    """El primer informe medido en producción mostró once llamadas del juez a $0,00.

    El juez es la mitad de las llamadas de un informe: registrado sin dólares, el total
    publicado era la mitad del real — justo la cifra que se mira para decidir.
    """
    from shared.narrative import numeric_guard as G

    class _Cliente:
        class messages:
            @staticmethod
            def create(**kw):
                r = _Resp()
                r.content = [type("C", (), {"text": '{"unsupported": []}'})()]
                return r

    monkeypatch.setattr("shared.llm.budget.budget_allows", lambda: True)
    with L.attributed_to("endpoint", "GET /informe"):
        G.verify_figures(_Cliente(), "claude-sonnet-4-6", "{}", "un texto",
                         module="brand_intel", template="t")

    fila = db.query(LLMCall).filter(LLMCall.purpose == L.PURPOSE_GUARD).one()
    assert fila.cost_usd > 0, "el juez no puede quedar registrado en cero"
    assert fila.module == "brand_intel"
    assert fila.trigger_detail == "GET /informe"


def test_account_suma_al_techo_diario_y_registra_a_la_vez(db, monkeypatch):
    """Tenerlas separadas es lo que permitió que nueve sitios pusieran una y olvidaran
    la otra; el techo diario no podía cortarlos porque para el contador no existían."""
    visto = {}

    def _falso_record_usage(model, tin, tout):
        visto["techo"] = (model, tin, tout)
        return 0.05

    monkeypatch.setattr("shared.llm.budget.record_usage", _falso_record_usage)
    L.account(_Resp(), model="claude-sonnet-4-6", purpose=L.PURPOSE_VISION,
              module="brand_intel", template="pdf_vision")
    assert visto["techo"] == ("claude-sonnet-4-6", 1000, 500)
    fila = db.query(LLMCall).one()
    assert fila.cost_usd == 0.05
    assert fila.tokens_in == 1000 and fila.tokens_out == 500


def test_account_nunca_lanza_con_una_respuesta_rara(db):
    assert L.account(object(), model="m", purpose=L.PURPOSE_OTHER) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Las DOS rutas del motor registran, no solo la que se probó
# ─────────────────────────────────────────────────────────────────────────────

def test_las_dos_rutas_del_motor_registran(db, monkeypatch):
    """La ruta legacy contaba contra el techo diario pero NO aparecía en el panel.

    El test estructural no lo caza porque valida por ARCHIVO: `claude_engine.py` nombra la
    contabilidad en su ruta cerebro, así que pasa aunque un camino interno no registre. La
    cobertura por archivo no implica cobertura por camino, y esta es la diferencia.
    """
    import ast
    import inspect

    from shared.narrative import claude_engine as CE

    fuente = inspect.getsource(CE.NarrativeEngine)
    arbol = ast.parse("class X:\n" + "\n".join(
        "    " + ln for ln in fuente.splitlines()[1:]))

    def registra(nombre_metodo: str) -> bool:
        for n in ast.walk(arbol):
            if isinstance(n, ast.FunctionDef) and n.name == nombre_metodo:
                return any(
                    isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == "record_call"
                    for c in ast.walk(n)
                )
        raise AssertionError(f"no se encontró {nombre_metodo}")

    assert registra("_generate_guarded"), "la ruta cerebro dejó de registrar"
    assert registra("_result_from_response"), "la ruta legacy dejó de registrar"


# ─────────────────────────────────────────────────────────────────────────────
# Las etiquetas: el producto, no el endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_la_etiqueta_reusa_el_nombre_que_el_operador_ya_ve(monkeypatch):
    """Las operaciones NO tienen tabla propia: se lee su `label` del registro de la
    consola. Duplicarlo garantizaría que un día el panel y el interruptor de al lado
    llamen distinto a la misma tarea."""
    from shared.observability import etiquetas
    from shared.operations.service import OPERATIONS

    falsa = type("Op", (), {"label": "Brief de mercado"})()
    monkeypatch.setitem(OPERATIONS, "market-brief", falsa)
    assert etiquetas.etiqueta_disparador("market-brief") == "Brief de mercado"


def test_la_etiqueta_de_una_ruta_nombra_el_producto():
    from shared.observability import etiquetas

    e = etiquetas.etiqueta_disparador("GET /api/v1/products/banking/deep_dive/report")
    assert "Deep Dive" in e and "/api/" not in e


def test_lo_no_reconocido_se_devuelve_TAL_CUAL(sin_inventar=None):
    """Una ruta nueva sale fea pero cierta. Un «Otro» la escondería entre las demás y un
    nombre inventado afirmaría algo que nadie declaró."""
    from shared.observability import etiquetas

    cruda = "GET /api/v1/modulo-que-no-existe/algo"
    assert etiquetas.etiqueta_disparador(cruda) == cruda


def test_desconocido_se_explica_en_vez_de_parecer_un_origen():
    from shared.observability import etiquetas

    assert "anterior al registro" in etiquetas.etiqueta_disparador("desconocido")


def test_el_resumen_trae_la_etiqueta_junto_a_la_clave(db):
    """La clave técnica NO se pierde: es lo que hace falta para depurar."""
    with L.attributed_to("endpoint", "GET /api/v1/products/banking/deep_dive/report"):
        L.record_call(purpose=L.PURPOSE_NARRATIVE, model="m", cost_usd=1.0,
                      module="banking")
    fila = spend.spend_summary(db)["por_disparador"][0]
    assert fila["clave"] == "GET /api/v1/products/banking/deep_dive/report"
    assert fila["etiqueta"] != fila["clave"]
    assert "Deep Dive" in fila["etiqueta"]


def test_el_motivo_se_traduce_a_lo_que_significa(db):
    from shared.observability import etiquetas

    assert etiquetas.etiqueta_motivo("guard_numerico") == "Verificación de cifras"
    assert etiquetas.etiqueta_motivo("narrativa") == "Redacción del análisis"
