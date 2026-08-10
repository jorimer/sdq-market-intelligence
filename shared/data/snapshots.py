"""Instantáneas comiteadas: camino offline DECLARADO para fuentes inalcanzables.

Algunas fuentes se pueden leer desde una máquina y no desde producción. Pasó con dos a
la vez el 2026-08-09: ``siuben.gob.do`` da ``ConnectTimeout`` desde la salida de Railway
(el descubrimiento por ``datos.gob.do`` sí llega, así que es ese host y no la red), y el
tablero Power BI del MINERD empezó a devolver ``400`` a todo el mundo tras muchas
llamadas anónimas. El dato existe y se puede capturar; lo que no se puede es capturarlo
*desde allá*.

La salida es la que el propio :mod:`shared.data.powerbi` ya prescribía para las APIs
internas frágiles: **mantener una instantánea comiteada como camino offline**. Se captura
donde la fuente responde, se versiona, y producción la usa cuando el vivo falla.

**El riesgo de esto es conocido y está atendido.** En este repo ya pasó que un camino de
respaldo se volvió el camino permanente sin que nadie lo notara (los "promedios del
sistema" hardcodeados). Por eso una instantánea acá:

* **lleva su fecha de captura** y la devuelve junto con las filas — quien la consume sabe
  que está leyendo una foto y de cuándo;
* **nunca se usa en silencio**: :func:`live_or_snapshot` devuelve la procedencia, y quien
  llama la publica en el resultado de la operación;
* **envejece a la vista**: :func:`snapshot_age_days` permite que la auditoría de frescura
  la trate como lo que es, un dato viejo, y no como una sincronización exitosa.

Una instantánea NO es una fuente. Es una fuente que hoy no podemos alcanzar, congelada,
con la fecha en la que dejó de moverse.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("sdq.data.snapshots")

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

LIVE = "live"
SNAPSHOT = "snapshot"


class SnapshotMissing(RuntimeError):
    """No hay instantánea comiteada para esa clave."""


def _path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.json"


def write_snapshot(name: str, rows: List[Any], *, source: str, note: str = "") -> Path:
    """Escribe la instantánea con su procedencia. La usa el script de captura, no la app.

    Las filas se guardan como listas (no tuplas) porque JSON no distingue, y quien lee
    las vuelve a normalizar."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.now(timezone.utc).date().isoformat(),
        "source": source,
        "note": note,
        "n_rows": len(rows),
        "rows": [list(r) if isinstance(r, tuple) else r for r in rows],
    }
    path = _path(name)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("[snapshots] %s: %d filas capturadas", name, len(rows))
    return path


def read_snapshot(name: str) -> Dict[str, Any]:
    """Lee la instantánea comiteada. Levanta si no existe — un vacío silencioso acá
    volvería a producir el "la fuente no publicó" que ya nos costó una tarde."""
    path = _path(name)
    if not path.exists():
        raise SnapshotMissing(
            f"no hay instantánea comiteada para '{name}' (esperada en {path.name}); "
            "capturarla con scripts/refresh_social_snapshots.py donde la fuente responda")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("rows"):
        raise SnapshotMissing(f"la instantánea '{name}' está vacía")
    return data


def snapshot_age_days(name: str, today: Optional[date] = None) -> Optional[int]:
    """Días desde la captura, o ``None`` si no hay instantánea o no trae fecha."""
    try:
        data = read_snapshot(name)
    except SnapshotMissing:
        return None
    try:
        captured = date.fromisoformat(str(data.get("captured_at")))
    except (TypeError, ValueError):
        return None
    return ((today or datetime.now(timezone.utc).date()) - captured).days


def live_or_snapshot(name: str, fetch: Callable[[], List[Any]], *,
                     source: str) -> Tuple[List[Any], str]:
    """Intenta el vivo; si falla, cae a la instantánea. Devuelve ``(filas, procedencia)``.

    La procedencia es ``"live"`` o ``"snapshot:AAAA-MM-DD"`` — **nunca se pierde**. Si
    fallan los dos, se propaga el error del VIVO, no el de la instantánea: el problema a
    resolver es que la fuente no se alcanza, y el respaldo ausente es una consecuencia.
    """
    live_error: Exception
    try:
        rows = fetch()
        if rows:
            return rows, LIVE
        live_error = RuntimeError("la fuente devolvió cero filas")
    except Exception as e:  # noqa: BLE001 — se decide con el respaldo en la mano
        live_error = e

    logger.warning("[snapshots] %s: el vivo falló (%s); usando la instantánea",
                   name, live_error)
    try:
        data = read_snapshot(name)
    except SnapshotMissing:
        raise live_error from None
    rows = [tuple(r) if isinstance(r, list) else r for r in data["rows"]]
    return rows, f"{SNAPSHOT}:{data.get('captured_at', 'sin fecha')}"
