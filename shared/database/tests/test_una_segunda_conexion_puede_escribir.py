"""Una SEGUNDA conexión puede commitear con un lector dentro de su transacción.

**El defecto que esto cierra, medido.** La instrumentación de la plataforma escribe en su
propia sesión corta a propósito: el registro de gasto del modelo (``llm_ledger.record_call``)
y el contador de herramientas (``uso_de_herramientas.registrar_uso``) tienen que sobrevivir a
que la ruta falle después y su transacción se revierta — la llamada ya ocurrió y ya se pagó.

Contra ``POST /api/v1/research`` en SQLite eso no funcionaba: **seis corridas por HTTP dejaban
UNA fila**, y las cinco perdidas salían por el log con su aviso. Con ``journal_mode=WAL`` y
``busy_timeout`` las seis quedan registradas. Producción es PostgreSQL y ahí no ocurre; esto
vigila que la paridad de desarrollo no se pierda otra vez.

**Qué pinta este test, exactamente.** La PROPIEDAD que el arreglo aporta: en el modo por
defecto, commitear exige subir a EXCLUSIVE y no se puede mientras otra conexión tiene la base
tomada dentro de una transacción abierta, aunque solo la esté leyendo; con WAL sí se puede. No
reproduce la mecánica interna de la ruta de research —no se logró en un test corto, y decir
que sí sería afirmar más de lo verificado—; la comprobación de esa ruta se hizo de punta a
punta con las cifras de arriba. El control negativo de abajo es lo que le da dientes: sin los
PRAGMA, la misma escritura falla con «database is locked».
"""
import pathlib

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event, text

from shared.database.session import aplicar_pragmas_sqlite


def _motor(ruta: pathlib.Path, con_pragmas: bool):
    """Un motor SQLite de FICHERO. Tiene que ser de fichero: una base en memoria no tiene
    bloqueo de fichero y el defecto no se reproduce — el test pasaría en verde contra el
    código roto, que es exactamente el modo de fallar de un test ciego."""
    e = create_engine(f"sqlite:///{ruta}",
                      connect_args={"check_same_thread": False, "timeout": 1})
    if con_pragmas:
        # La MISMA función que usa la aplicación, no una copia: dos implementaciones de la
        # misma regla es cómo se cuela un falso verde.
        event.listen(e, "connect",
                     lambda dbapi_connection, _r: aplicar_pragmas_sqlite(dbapi_connection))
    md = MetaData()
    t = Table("corridas", md, Column("id", Integer, primary_key=True),
              Column("nota", String(40)))
    md.create_all(e)
    return e, t


def _escribir_con_un_lector_dentro(motor, tabla):
    """La instrumentación deja su fila mientras otra conexión tiene una transacción abierta
    en la que ya leyó. Sin WAL, el commit no consigue el EXCLUSIVE y salta el bloqueo."""
    peticion = motor.connect()
    peticion.exec_driver_sql("BEGIN")
    peticion.exec_driver_sql("select count(*) from corridas").fetchall()

    instrumentacion = motor.connect()
    try:
        instrumentacion.execute(tabla.insert().values(nota="la corrida contada"))
        instrumentacion.commit()
    finally:
        instrumentacion.close()
        peticion.rollback()
        peticion.close()


def test_los_pragmas_dejan_la_base_en_WAL(tmp_path):
    motor, _ = _motor(tmp_path / "con.db", con_pragmas=True)
    with motor.connect() as c:
        assert c.execute(text("pragma journal_mode")).scalar() == "wal"
        assert c.execute(text("pragma busy_timeout")).scalar() > 0


def test_la_corrida_se_registra_con_un_lector_dentro(tmp_path):
    motor, tabla = _motor(tmp_path / "con.db", con_pragmas=True)
    _escribir_con_un_lector_dentro(motor, tabla)
    with motor.connect() as c:
        assert [r[0] for r in c.execute(text("select nota from corridas"))] == [
            "la corrida contada"]


def test_SIN_los_pragmas_el_defecto_REAPARECE(tmp_path):
    """El control que le da dientes al de arriba. Sin esto, el test anterior podría estar
    pasando por cualquier otra razón —o el arreglo podría haberse quitado— y nadie se
    enteraría."""
    motor, tabla = _motor(tmp_path / "sin.db", con_pragmas=False)
    with pytest.raises(Exception) as exc:
        _escribir_con_un_lector_dentro(motor, tabla)
    assert "locked" in str(exc.value).lower(), (
        f"se esperaba el bloqueo de SQLite y salió otra cosa: {exc.value}")
