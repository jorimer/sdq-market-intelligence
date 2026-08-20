"""De un evento aprobado a la bandeja del cliente: a quién, por qué canal, y cuándo callar.

**El modo de falla dominante de este producto es el ruido**, no el falso negativo. Un cliente
que recibe la misma señal cada trimestre deja de leer todas, y ahí el producto muere sin dar
un solo error. Por eso hay tres filtros antes del canal —severidad, disparador, dedup— y el
tope por barrido.

**El dedup no es «avisá cada N horas»**: es *avisá una vez mientras la condición siga rota, y
volvé a avisar si se resolvió y recayó*. La segunda mitad es la que importa y la que se
olvida: sin :func:`resolver`, una cobertura que se arregla y vuelve a caer queda muda. Se usa
el buzón promovido en `shared/notifications/dedup.py`, que ya tenía esa semántica probada en
la auditoría de frescura.

**El acceso se re-verifica acá**, no solo al suscribir: una vigilancia sobrevive al fin del
contrato, y una alerta de un eje ajeno filtra el dato que se le cobra a otro.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Sequence

from sqlalchemy.orm import Session

from shared.alerts import service
from shared.alerts.models import AlertSubscription
from shared.alerts.reglas import AlertEvent, severidad_alcanza
from shared.notifications.dedup import Dedup
from shared.notifications.service import notification_service

logger = logging.getLogger("sdq.alerts.entrega")

# Prefijo propio: la frescura de una operación y una alerta del mismo eje pueden llamarse
# igual y no deben pisarse el marcador.
DEDUP = Dedup("alert_sent")

# Cuánto callar sobre una condición que sigue rota. Generoso a propósito: la mayoría de los
# ejes publica con cadencia trimestral, así que un intervalo corto solo lograría repetir el
# mismo aviso sobre el mismo dato. Lo que reabre el aviso no es el reloj — es que la
# condición se resuelva y vuelva a romperse (:func:`resolver`).
RENOTIFICAR_HORAS = 24 * 45

# Tope de avisos por usuario y barrido. El excedente se RESUME en una línea, no se trunca en
# silencio: un corte callado se lee como que no pasó nada más.
MAX_POR_USUARIO_POR_BARRIDO = 10

# Ruta interna a la que navega el click. La bandeja de alertas todavía no tiene pantalla
# propia; el catálogo es donde el cliente puede actuar sobre lo que se le avisa.
ACTION_URL = "/products"


def _clave(evento: AlertEvent, user_id: str) -> str:
    """Identidad de (condición, destinatario). Por-usuario porque la entrega lo es: que a
    uno ya se le haya avisado no dice nada sobre otro que acaba de suscribirse."""
    return f"{evento.clave_dedup}:{user_id}"


def _alcanza(sub: AlertSubscription, evento: AlertEvent) -> bool:
    """¿Esta vigilancia quiere este evento? Severidad mínima y disparadores elegidos."""
    if not severidad_alcanza(evento.severidad, str(sub.min_severity)):
        return False
    codigos = list(sub.rule_codes) if sub.rule_codes else None
    return codigos is None or evento.codigo in codigos


def entregar(db: Session, evento: AlertEvent,
             subs: Sequence[AlertSubscription],
             *, entregados_por_usuario: Dict[str, int] | None = None,
             evento_id: str | None = None) -> Dict[str, Any]:
    """Entrega *evento* a las vigilancias que lo alcanzan. Devuelve el detalle de qué pasó
    con cada una — entregadas, calladas por dedup, filtradas y suspendidas — porque el
    barrido tiene que poder explicar por qué una vigilancia no recibió nada.

    ``entregados_por_usuario`` lleva la cuenta a través de varios eventos del mismo barrido
    para que el tope sea por barrido y no por evento. ``evento_id`` es la fila persistida del
    evento; sin ella no se puede encolar correo (la entrega apunta al evento, no lo copia).
    """
    cupo = entregados_por_usuario if entregados_por_usuario is not None else {}
    vivas, suspendidas = service.entregables(db, subs)

    entregadas: List[str] = []
    calladas: List[str] = []
    filtradas: List[str] = []
    excedidas: List[str] = []

    for sub in vivas:
        uid = str(sub.user_id)
        if not _alcanza(sub, evento):
            filtradas.append(uid)
            continue
        clave = _clave(evento, uid)
        if DEDUP.avisado_recientemente(db, clave, RENOTIFICAR_HORAS):
            calladas.append(uid)
            continue
        if cupo.get(uid, 0) >= MAX_POR_USUARIO_POR_BARRIDO:
            excedidas.append(uid)
            continue
        try:
            canales = list(sub.channels or [])
            if service.CANAL_INAPP in canales:
                notification_service.create(
                    db, user_id=uid, type=_tipo(evento.severidad), title=evento.titulo,
                    body=_cuerpo(evento), action_url=ACTION_URL)
            if service.CANAL_EMAIL in canales and evento_id:
                # El correo no se manda desde acá aunque sea "inmediato": se ENCOLA. Una
                # conexión SMTP dentro del barrido lo vuelve tan lento como el servidor de
                # correo, y un SMTP caído se comería el aviso sin dejar rastro. La fila
                # pendiente es a la vez la cola del digest y la del reintento.
                _encolar_email(db, evento_id, uid, str(sub.digest))
            DEDUP.marcar(db, clave)
            cupo[uid] = cupo.get(uid, 0) + 1
            entregadas.append(uid)
        except Exception as e:  # noqa: BLE001
            # Aislado por destinatario: un transitorio de base con uno no puede abortar la
            # entrega a los demás ni dejar marcadores a medias (que causarían re-spam).
            db.rollback()
            logger.warning("alerts: no se pudo entregar %s a %s: %s", evento.clave_dedup, uid, e)

    return {"entregadas": entregadas, "calladas": calladas, "filtradas": filtradas,
            "excedidas": excedidas,
            "suspendidas": [s["id"] for s in suspendidas]}


def resolver(db: Session, claves_dedup: Iterable[str], user_ids: Iterable[str]) -> int:
    """La condición dejó de darse → limpiar su marcador para poder re-avisar si recae.

    Sin esto el dedup sería una mordaza con vencimiento: la señal más valiosa —algo que se
    arregló y volvió a romperse dentro de la ventana— sería justo la que no se avisa.
    """
    n = 0
    usuarios = list(user_ids)
    for clave in claves_dedup:
        for uid in usuarios:
            DEDUP.limpiar(db, f"{clave}:{uid}")
            n += 1
    return n


def _tipo(severidad: str) -> str:
    """Severidad de la alerta → tipo del buzón (info | warning | error | success)."""
    return {"alta": "error", "media": "warning"}.get(severidad, "info")


def _cuerpo(evento: AlertEvent) -> str:
    """El cuerpo lleva la afirmación y **por qué la regla existe**. Una alerta que no puede
    decir de dónde sale su umbral es una regla que sonó porque sí."""
    partes = [evento.cuerpo]
    if evento.basis:
        partes.append(f"Señal a monitorear · {evento.basis}")
    return "\n\n".join(partes)


def _encolar_email(db: Session, evento_id: str, user_id: str, digest: str) -> None:
    """Deja la entrega por correo PENDIENTE. Idempotente por (evento, usuario, canal)."""
    from shared.alerts.models import AlertDelivery

    ya = (db.query(AlertDelivery)
          .filter(AlertDelivery.event_id == evento_id,
                  AlertDelivery.user_id == user_id,
                  AlertDelivery.canal == service.CANAL_EMAIL)
          .one_or_none())
    if ya is not None:
        return
    db.add(AlertDelivery(event_id=evento_id, user_id=user_id,
                         canal=service.CANAL_EMAIL, digest=digest,
                         enviado_at=None, intentos=0))
    db.commit()
