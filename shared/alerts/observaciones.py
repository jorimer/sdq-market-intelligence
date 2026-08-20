"""Lo último que vimos de cada cosa vigilada — el insumo de toda regla de TRANSICIÓN.

**Por qué hace falta.** Cambio de banda, brecha, cambio de posición, validación vencida y
publicación nueva afirman todas un CAMBIO, y un cambio necesita un antes. Banca lo resuelve
recomputando el período anterior, pero eso es caro y solo funciona donde el motor sabe pedir
un corte previo; los demás ejes no tienen esa forma. Acá se guarda simplemente lo último que
el barrido observó.

**Por qué en `AppSetting` y no en una tabla nueva.** El volumen es una fila por cosa
vigilada (no por evento), el KV ya está compartido entre workers y ya lo usa el dedup. Una
tabla más para guardar un escalar por clave es infraestructura sin nada que la justifique.

**La regla que gobierna este módulo: nunca inventar un antes.** Si no hay observación previa,
:func:`leer` devuelve ``None`` y las reglas de transición callan — que es correcto: la
primera vez que se mira algo no hay noticia, hay estado. Devolver un default (0, False, "")
convertiría cada primera corrida en una tormenta de alertas falsas sobre cambios que nunca
ocurrieron.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from shared.settings.models import AppSetting

logger = logging.getLogger("sdq.alerts.observaciones")

PREFIJO = "alert_obs"


def clave(sector_key: str, subject: str, metrica: str) -> str:
    """Identidad de la cosa observada. Misma forma que la clave de dedup para que las dos
    se puedan leer juntas cuando haya que diagnosticar por qué algo no avisó."""
    return f"{PREFIJO}:{sector_key}:{subject}:{metrica}"


def leer(db: Session, k: str) -> Optional[Any]:
    """Última observación, o ``None`` si nunca se vio.

    Un valor ilegible cuenta como «nunca se vio»: ante la duda es preferible callar una
    transición real que inventar una que no pasó.
    """
    row = db.query(AppSetting).filter(AppSetting.key == k).first()
    if row is None or row.value is None:
        return None
    try:
        return json.loads(str(row.value))
    except (ValueError, TypeError):
        logger.warning("alerts: observación ilegible en %s", k)
        return None


def guardar(db: Session, k: str, valor: Any) -> None:
    """Deja *valor* como la última observación de *k*."""
    payload = json.dumps(valor, ensure_ascii=False, sort_keys=True)
    row = db.query(AppSetting).filter(AppSetting.key == k).first()
    if row is not None:
        row.value = payload  # type: ignore[assignment]
        row.is_secret = False  # type: ignore[assignment]
    else:
        db.add(AppSetting(key=k, value=payload, is_secret=False))
    db.commit()


def transicion(db: Session, k: str, valor_actual: Any) -> Optional[Any]:
    """Devuelve el valor PREVIO y deja registrado el actual, en una sola operación.

    Se guarda siempre —haya o no cambio— porque lo que interesa es la última observación,
    no la última alerta: si solo se guardara al disparar, un valor que va A→B→A dejaría el
    registro en A y el segundo retorno a A parecería un cambio.
    """
    previo = leer(db, k)
    guardar(db, k, valor_actual)
    return previo
