"""El canal máquina-a-máquina: `alert.raised`.

Reusa entera la máquina de webhooks de la Data API —firma HMAC-SHA256, entrega en hilo
aparte, bitácora de intentos, autodesactivación a los N fallos— porque ya está probada y
duplicarla sería un segundo lugar donde arreglar el mismo bug.

**Tres diferencias con el webhook de «hay dato nuevo», y las tres son deliberadas:**

1. **Este aviso SÍ lleva su contenido.** El de la Data API decide que no —solo dice qué
   cambió y el cliente vuelve con su llave— para no crear un segundo canal de datos con sus
   propios permisos. Una ALERTA es otra cosa: un aviso que no dice qué pasó no es una
   alerta, es una invitación a sondear. La diferencia es de propósito, no una inconsistencia,
   y por eso el tipo de evento es propio.

2. **`alert.raised` NUNCA lo matchea `"*"`.** Un webhook viejo registrado con «todos los
   eventos» empezaría a recibir contenido de alertas que nadie pidió, por un canal cuya
   semántica es distinta. Hay que nombrarlo explícitamente. Ver :func:`suscrito`.

3. **Se entrega POR DUEÑO, no en difusión.** `dispatch` avisa a todos los webhooks
   suscritos: correcto para «se recalculó el snapshot de macro», desastroso para una alerta,
   que es de un cliente concreto y puede nombrar entidades que otro no compró. Acá se
   resuelven los webhooks cuya llave pertenece al usuario alcanzado, y el acceso se
   re-verifica antes (`shared.alerts.entrega`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from shared.alerts.models import AlertEventRow
from shared.data_api.models import ApiKey, ApiWebhook

logger = logging.getLogger("sdq.alerts.webhook")

EVENTO = "alert.raised"


def suscrito(hook: ApiWebhook) -> bool:
    """¿Este webhook pidió las alertas, por su nombre?

    El comodín NO alcanza, a propósito: ``"*"`` se registró para los avisos de dato nuevo,
    que no llevan contenido. Dejar que arrastre también las alertas mandaría cifras y
    nombres de entidad a un endpoint que nunca los pidió.
    """
    pedidos = {e.strip() for e in str(hook.events or "").split(",") if e.strip()}
    return EVENTO in pedidos


def hooks_de(db: Session, user_id: str) -> List[ApiWebhook]:
    """Webhooks ACTIVOS de *user_id* suscritos a alertas, con su llave viva.

    Revocar la llave corta también los avisos, sin que nadie tenga que acordarse de borrar
    el webhook — misma regla que en la Data API.
    """
    filas = (db.query(ApiWebhook)
             .join(ApiKey, ApiKey.id == ApiWebhook.api_key_id)
             .filter(ApiWebhook.active.is_(True),
                     ApiKey.user_id == user_id,
                     ApiKey.active.is_(True),
                     ApiKey.revoked_at.is_(None))
             .all())
    return [h for h in filas if suscrito(h)]


def tiene_canal(db: Session, user_id: str) -> bool:
    """¿Este usuario puede recibir alertas por webhook HOY?

    Es el gate del canal, igual que ``email.configurado()`` para el correo: ofrecerle el
    canal a quien no registró ningún endpoint lo deja esperando avisos que no tienen a dónde
    ir. La diferencia es que este gate es POR USUARIO y aquel es del despliegue.
    """
    try:
        return bool(hooks_de(db, user_id))
    except Exception as e:  # noqa: BLE001 — un error acá no puede tumbar la watchlist
        logger.warning("alerts: no se pudieron resolver los webhooks de %s: %s", user_id, e)
        return False


def cuerpo(evento: AlertEventRow) -> Dict[str, Any]:
    """El payload. Lleva la afirmación COMPLETA y su procedencia.

    Va lo que sostiene la alerta —relaciones computadas, cifras, procedencia por variable,
    frescura— porque un consumidor máquina no puede leer prosa y necesita poder decidir. NO
    va la narrativa de reporte: eso es el producto, y no se regala por un canal lateral.
    """
    return {
        "event": EVENTO,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "alert": {
            "id": str(evento.id),
            "codigo": evento.codigo,
            "sector_key": evento.sector_key,
            "subject": str(evento.subject or "") or None,
            "periodo": evento.periodo,
            "severidad": evento.severidad,
            "titulo": evento.titulo,
            "cuerpo": evento.cuerpo,
            # Por qué existe la regla. Sin esto el consumidor recibe un umbral sin saber
            # de dónde salió, que es lo mismo que no recibirlo.
            "basis": evento.basis,
            "relaciones": dict(evento.relaciones or {}),
            "valores": dict(evento.valores or {}),
            "procedencia": dict(evento.procedencia or {}),
            # Tres estados, como en todo el resto: true / false / null (indeterminado).
            # Solo `true` llega acá —el gate no publica lo demás—, pero viaja explícito
            # para que el consumidor no tenga que asumirlo.
            "frescura": evento.frescura,
        },
        "hint": ("Señal a monitorear. No es un pronóstico ni una probabilidad: "
                 "ver `basis` para el criterio que la origina."),
    }


def entregar(db: Session, evento: AlertEventRow, user_id: str, *,
             background: bool = True) -> int:
    """Manda *evento* a los webhooks de alerta de *user_id*. Devuelve cuántos se despacharon.

    No levanta: la red del cliente no puede abortar un barrido. Los fallos los cuenta y los
    registra la máquina de la Data API, que además desactiva sola un endpoint muerto.
    """
    import threading

    from shared.data_api.webhooks import _deliver

    try:
        hooks = hooks_de(db, user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("alerts: webhooks de %s ilegibles: %s", user_id, e)
        return 0
    if not hooks:
        return 0

    from shared.database.session import SessionLocal

    payload = cuerpo(evento)
    for hook in hooks:
        if background:
            threading.Thread(target=_deliver,
                             args=(SessionLocal, str(hook.id), EVENTO, payload),
                             daemon=True).start()
        else:
            _deliver(SessionLocal, str(hook.id), EVENTO, payload)
    return len(hooks)
