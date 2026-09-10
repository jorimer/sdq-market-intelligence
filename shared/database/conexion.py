"""Los argumentos de conexión de TODO engine de la plataforma. Hoy fijan el reloj de la base.

**El hueco.** ``created_at`` y ``updated_at`` (``UUIDMixin``) los pone la BASE con
``server_default=func.now()``, y las columnas son ``timestamp`` sin zona. En SQLite eso es
``CURRENT_TIMESTAMP``, que es UTC. En PostgreSQL, ``now()`` es un ``timestamptz`` que al
guardarse en una columna sin zona se convierte al ``TimeZone`` **de la sesión** — un ajuste
del servidor, del rol o de la base que ningún archivo de este repo declaraba ni comprobaba.

Todo lo que filtra por fecha, en cambio, arma su rango en UTC desde Python (los paneles de
``shared/observability/``, el frontend con ``toISOString()``). Mientras el servidor esté en
UTC coinciden por casualidad; con otro huso, cada fila queda corrida unas horas contra el
rango que la busca, y lo que se pierde son las filas del borde del día. El síntoma —un
conteo algo más bajo— es indistinguible de uno verdadero.

**La cura.** Se fija ``TimeZone=UTC`` como parámetro de ARRANQUE de cada conexión
(``options=-c timezone=UTC``). Es un parámetro de arranque y no un ``SET`` en un evento de
conexión a propósito: un ``SET`` dentro de la transacción implícita de psycopg2 se deshace
con el ``rollback`` con que el pool devuelve la conexión, y el reloj volvería al del
servidor sin que nada fallara.

Los instantes guardados en columnas ``timestamptz`` no cambian con esto: solo cambia el huso
con que se los muestra. Lo que cambia es la HORA DE PARED que ``now()`` escribe en las
columnas sin zona, que son todas las del mixin.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.engine import make_url

#: Parámetro de arranque de libpq. Nombrado para que el test lo lea de acá y no lo copie.
OPCION_RELOJ_UTC = "-c timezone=UTC"


def connect_args_para(url: str) -> Dict[str, Any]:
    """Los ``connect_args`` que corresponden a ``url``. Todo engine se construye con esto.

    Si la URL ya trae ``options`` en su query se CONSERVAN: SQLAlchemy deja que
    ``connect_args`` pise la query, así que devolver solo la nuestra borraría en silencio
    las que el operador hubiera puesto en la URL.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return {"check_same_thread": False}
    if parsed.get_backend_name() != "postgresql":
        return {}
    previas = parsed.query.get("options")
    if isinstance(previas, tuple):
        previas = " ".join(previas)
    opciones = f"{previas} {OPCION_RELOJ_UTC}" if previas else OPCION_RELOJ_UTC
    return {"options": opciones}
