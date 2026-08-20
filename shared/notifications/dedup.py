"""Anti-spam de avisos recurrentes: no repetir el mismo hasta que la condición se resuelva.

Promovido desde `shared/operations/freshness.py`, donde nació vigilando la frescura de las
fuentes y donde funcionó bien. Ahora tiene un segundo consumidor —la entrega de alertas— y
un guard con dos copias es un guard que diverge; este repo ya pagó cinco veces esa cuenta.

**La semántica es la que importa, no el almacenamiento.** No es un "avisá cada N horas":
es *avisá una vez mientras la condición siga rota, y volvé a avisar si se resolvió y recayó*.
Por eso hay tres operaciones y no dos — sin :func:`limpiar`, una condición que se arregla y
se vuelve a romper queda muda hasta que expire el intervalo, que es justo cuando el aviso
valía más.

Persiste en ``AppSetting`` (KV compartido entre workers): un marcador en memoria haría que
cada réplica de uvicorn avisara por su cuenta.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from shared.settings.models import AppSetting


class Dedup:
    """Buzón de marcadores bajo un prefijo propio.

    El prefijo aísla a los consumidores entre sí: la frescura de una operación y una alerta
    del mismo eje pueden llamarse igual y no deben pisarse el marcador.
    """

    def __init__(self, prefijo: str) -> None:
        self.prefijo = prefijo.rstrip(":")

    def _key(self, clave: str) -> str:
        return f"{self.prefijo}:{clave}"

    def avisado_recientemente(self, db: Session, clave: str, intervalo_horas: float) -> bool:
        """¿Ya se avisó por *clave* dentro de su última cadencia?

        Un marcador ilegible (valor corrupto, formato viejo) cuenta como «no avisado»: ante
        la duda, avisar de más es recuperable y avisar de menos no.
        """
        row = db.query(AppSetting).filter(AppSetting.key == self._key(clave)).first()
        if not row or not row.value:
            return False
        try:
            ultimo = datetime.fromisoformat(str(row.value))
        except (ValueError, TypeError):
            return False
        return (datetime.now(timezone.utc) - ultimo).total_seconds() < intervalo_horas * 3600

    def marcar(self, db: Session, clave: str) -> None:
        key = self._key(clave)
        ahora = datetime.now(timezone.utc).isoformat()
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            # `AppSetting` está declarado con el estilo legacy `Column`, así que el checker
            # ve `Column[str]` donde el código usa un `str`. Mismo trato que en
            # `shared/settings/service.py`: la deuda es del modelo, no de este módulo.
            row.value = ahora  # type: ignore[assignment]
            row.is_secret = False  # type: ignore[assignment]
        else:
            db.add(AppSetting(key=key, value=ahora, is_secret=False))
        db.commit()

    def limpiar(self, db: Session, clave: str) -> None:
        """La condición se resolvió → borrar el marcador para poder re-avisar si recae."""
        row = db.query(AppSetting).filter(AppSetting.key == self._key(clave)).first()
        if row:
            db.delete(row)
            db.commit()
