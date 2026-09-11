"""Una base que rechaza UNA escritura concreta, para probar el ORDEN de las escrituras.

El 2026-09-10 PostgreSQL rechazó el marcador de dedup de las alertas (clave de 119
caracteres en un VARCHAR(100)) con la notificación ya comprometida, y cada barrido volvió a
avisar lo mismo. SQLite no aplica el largo, así que en los tests la base rechaza por un
listener. Lo que se verifica no es el motivo —ese lo vigila
`shared/tests/test_lo_que_sqlite_no_vigila.py`— sino que **cualquier** motivo por el que una
de las dos escrituras no entre se lleve a la otra.

No es un archivo de tests (no empieza con ``test_``): lo importan los de cada consumidor
del buzón de dedup, para que el rechazo sea el mismo en todos.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator, List

from sqlalchemy import event
from sqlalchemy.orm import Session

from shared.notifications.service import Notification
from shared.settings.models import AppSetting

MOTIVO = "value too long for type character varying(100)"


def marcador(prefijo: str) -> Callable[[Any], bool]:
    """¿La fila es un marcador de dedup bajo *prefijo*?"""
    con_separador = prefijo.rstrip(":") + ":"
    return lambda o: isinstance(o, AppSetting) and str(o.key).startswith(con_separador)


def notificacion(o: Any) -> bool:
    """¿La fila es un aviso in-app?"""
    return isinstance(o, Notification)


@contextmanager
def rechaza(db: Session, es_la_fila: Callable[[Any], bool]) -> Iterator[List[str]]:
    """Mientras dure el bloque, todo flush con una fila nueva que cumpla *es_la_fila* falla.

    Devuelve la lista de rechazos: el test tiene que exigir que no esté vacía. Un listener
    que nunca dispara —un prefijo mal escrito— deja el test en verde sin probar nada.
    """
    rechazos: List[str] = []

    def _antes_del_flush(session: Session, flush_context: Any, instances: Any) -> None:
        filas = [o for o in session.new if es_la_fila(o)]
        if filas:
            rechazos.append(type(filas[0]).__name__)
            raise RuntimeError(MOTIVO)

    event.listen(db, "before_flush", _antes_del_flush)
    try:
        yield rechazos
    finally:
        event.remove(db, "before_flush", _antes_del_flush)
