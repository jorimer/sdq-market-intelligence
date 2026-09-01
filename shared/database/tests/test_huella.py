"""La huella de la base se MIDE. Y donde no se puede medir, se dice — no se devuelve cero.

Salió de un aviso de memoria en el Postgres de producción (2026-08-21). La pregunta «¿por qué
crece?» tenía dos respuestas posibles: una conjetura razonada sobre qué tablas parecen
grandes, o el número que da el motor. Estos tests fijan que sea la segunda, y que las dos
salvedades que hacen honesto al número viajen con él.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database import huella


def _sesion_sqlite():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    return sessionmaker(bind=engine)()


def test_en_sqlite_declara_que_NO_APLICA_en_vez_de_devolver_ceros(monkeypatch):
    """«No se puede medir acá» y «no ocupa nada» son cosas distintas. Un cero se lee como la
    segunda y sería mentira: es la misma confusión que un dato ausente rellenado con 0.0."""
    monkeypatch.setattr(huella.settings, "DATABASE_URL", "sqlite:///./data/x.db")
    res = huella.huella_de_la_base(_sesion_sqlite())
    assert res["aplica"] is False
    assert res["motivo"], "no declaró POR QUÉ no aplica"
    assert "mb_base_completa" not in res, "devolvió un tamaño donde no puede medirlo"


def test_el_estado_del_pool_declara_que_es_de_UN_SOLO_proceso():
    """Cada worker web y el de Celery abren su propio pool; lo que ve Postgres es la suma.
    Sin esa salvedad, las cifras se leen como el total y subestiman el consumo real por un
    factor igual a la cantidad de procesos."""
    p = huella.estado_del_pool()
    assert "proceso" in p["alcance"].lower()
    assert p["techo_por_proceso"] >= 1


def test_el_techo_declarado_coincide_con_lo_configurado(monkeypatch):
    monkeypatch.setattr(huella.settings, "DB_POOL_SIZE", 5)
    monkeypatch.setattr(huella.settings, "DB_MAX_OVERFLOW", 5)
    assert huella.estado_del_pool()["techo_por_proceso"] == 10


def test_un_fallo_al_medir_NO_tumba_la_consola(monkeypatch):
    """Es un panel de diagnóstico: si falla justo cuando el motor está sufriendo —que es
    cuando se lo mira— tiene que decirlo, no romper la pantalla que lo contiene."""
    monkeypatch.setattr(huella.settings, "DATABASE_URL", "postgresql://x/y")

    class _DBRota:
        def execute(self, *a, **k):
            raise RuntimeError("motor ocupado")

        def rollback(self):
            pass

    res = huella.huella_de_la_base(_DBRota())
    assert res["aplica"] is True
    assert "error" in res
    assert res["conexiones"], "perdió el estado del pool, que sí se podía informar"


def test_las_tablas_sin_retencion_estan_declaradas_con_su_motivo():
    """Crecen para siempre A PROPÓSITO: son caché servible y evidencia de auditoría. Sin el
    motivo escrito al lado del tamaño, la lectura obvia de una tabla grande es «purgala», y
    eso borraría la evidencia de a quién cobrarle cada llamada al modelo."""
    assert set(huella.SIN_RETENCION) == {
        "product_report_cache", "llm_calls", "operation_runs"}
    assert all(motivo.strip() for motivo in huella.SIN_RETENCION.values())


def test_la_consulta_de_tamanos_es_valida_para_postgres():
    """El SQL vive en una constante y nadie lo corre en los tests (no hay Postgres acá); al
    menos que esté compilado y nombre las columnas que el consumidor lee."""
    sql = str(huella._SQL_TABLAS)
    for columna in ("pg_total_relation_size", "n_live_tup", "n_dead_tup", "relname"):
        assert columna in sql
    assert isinstance(huella._SQL_TABLAS, type(text("SELECT 1")))


def test_el_pool_declarado_no_CAMBIA_la_capacidad_de_hoy():
    """Declarar el número y cambiarlo son dos cosas distintas.

    Este cambio existe para MEDIR: hasta ahora el techo del pool era el default de
    SQLAlchemy (5 + 10), o sea un número que nadie eligió. Declararlo lo vuelve visible y
    ajustable por variable de entorno; bajarlo sin la medición sería sustituir el default de
    una biblioteca por una corazonada.

    El riesgo de bajarlo a ciegas no es teórico: una generación de narrativa tarda 15-90 s, y
    si la sesión se sostiene mientras el modelo responde, un techo de 10 hace que la 11ª
    petición espere hasta `pool_timeout` (30 s). Se pagaría en latencia de cliente para
    ahorrar memoria que todavía nadie contó.

    Si estás bajando estos valores: mirá primero `GET /api/v1/operations/base-de-datos`, que
    es lo que este mismo cambio agrega, y dejá la cifra observada en el mensaje del commit.
    """
    from shared.config.settings import Settings

    por_defecto = Settings()
    assert (por_defecto.DB_POOL_SIZE, por_defecto.DB_MAX_OVERFLOW) == (5, 10), (
        "el techo declarado dejó de coincidir con el que la app tenía de hecho. Si es "
        "deliberado, actualizá este test citando la medición que lo justifica."
    )
