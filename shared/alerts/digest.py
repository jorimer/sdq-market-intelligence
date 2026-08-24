"""El resumen por correo: lo pendiente de cada cliente, en UN mensaje, con su cadencia.

**Por qué el correo se encola y no se manda en el barrido.** Una conexión SMTP dentro del
barrido lo vuelve tan lento como el servidor de correo, y un SMTP caído se comería el aviso
sin dejar rastro. La fila `AlertDelivery` pendiente es a la vez la cola del resumen y la del
reintento — que son la misma cosa: lo que no salió, sigue pendiente.

**Por qué un correo por cliente y no uno por alerta.** Tres señales del mismo trimestre son
tres correos que el cliente archiva sin leer. El modo de falla dominante de este producto es
el ruido, no el falso negativo.

**El acceso se re-verifica también acá.** Entre el barrido y el envío pueden pasar días: si
el contrato venció en el medio, el correo saldría con dato que ya no le corresponde. Se reusa
``service.entregables``, que es el mismo gate de la entrega in-app.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Dict, List, Sequence, Tuple

from sqlalchemy.orm import Session

from shared.alerts import service
from shared.alerts.models import AlertDelivery, AlertEventRow, AlertSubscription
from shared.auth.models import User
from shared.config.settings import settings
from shared.notifications import email as mail
from shared.notifications.dedup import Dedup

logger = logging.getLogger("sdq.alerts.digest")

# Cadencia de "ya le mandé el resumen". El semanal se apoya en el mismo buzón de dedup que el
# resto del módulo — la semántica que hacía falta ya estaba resuelta ahí.
DEDUP = Dedup("alert_digest")
HORAS_SEMANAL = 24 * 7

# Tras varios intentos fallidos se deja de reintentar. Un destino que rebota siempre no puede
# reintentarse eterno, pero la fila NO se borra: queda con su `ultimo_error` para que se pueda
# ver por qué ese cliente no recibe nada. Un descarte silencioso se lee como "no pasó nada".
MAX_INTENTOS = 5

# Tope de alertas listadas en un correo. El excedente se RESUME en una línea con el total,
# nunca se corta en silencio.
MAX_EN_CORREO = 20

ASUNTO_UNA = "SDQ · {titulo}"
ASUNTO_VARIAS = "SDQ · {n} señales de tus vigilancias"
PIE = ("—\nRecibís esto porque vigilás estos ejes en SDQ Market Intelligence.\n"
       "Administrá o dá de baja tus vigilancias en {url}/products")


def _pendientes(db: Session) -> Dict[str, List[AlertDelivery]]:
    """Entregas por correo sin enviar, agrupadas por usuario."""
    filas = (db.query(AlertDelivery)
             .filter(AlertDelivery.canal == service.CANAL_EMAIL,
                     AlertDelivery.enviado_at.is_(None),
                     AlertDelivery.intentos < MAX_INTENTOS)
             .order_by(AlertDelivery.created_at.asc())
             .all())
    out: Dict[str, List[AlertDelivery]] = {}
    for f in filas:
        out.setdefault(str(f.user_id), []).append(f)
    return out


def _toca_enviar(db: Session, user_id: str, entregas: Sequence[AlertDelivery]) -> bool:
    """¿Le corresponde recibir el resumen ahora?

    ``inmediato`` y ``diario`` salen en cada corrida (la operación es diaria); ``semanal``
    solo si pasó una semana desde el último. Si el cliente tiene vigilancias con cadencias
    distintas manda la más frecuente de lo pendiente: acumular una señal inmediata hasta el
    domingo sería peor que mandar el resumen antes.
    """
    cadencias = {str(e.digest) for e in entregas}
    if cadencias & {"inmediato", "diario"}:
        return True
    return not DEDUP.avisado_recientemente(db, user_id, HORAS_SEMANAL)


def _cubierta(sub_por_clave: Dict[Tuple[str, str], AlertSubscription],
              evento: AlertEventRow) -> bool:
    """¿Alguna vigilancia VIGENTE del usuario sigue alcanzando a este evento?"""
    sector = str(evento.sector_key)
    return ((sector, str(evento.subject or "")) in sub_por_clave
            or (sector, "") in sub_por_clave)


def _cuerpo(eventos: Sequence[AlertEventRow], total: int) -> str:
    lineas: List[str] = []
    for e in eventos:
        lineas.append(f"• {e.titulo}")
        lineas.append(f"  {e.cuerpo}")
        if e.basis:
            lineas.append(f"  Señal a monitorear · {e.basis}")
        lineas.append("")
    if total > len(eventos):
        lineas.append(f"(+{total - len(eventos)} señales más en la plataforma)")
        lineas.append("")
    lineas.append(PIE.format(url=settings.APP_PUBLIC_URL.rstrip("/")))
    return "\n".join(lineas)


def enviar_digests(db: Session) -> Dict[str, Any]:
    """Manda el resumen pendiente de cada cliente. Devuelve el detalle de qué pasó.

    Nunca levanta por un destinatario: un SMTP que rebota con uno no puede dejar a los demás
    sin su correo. Lo que falla queda pendiente con su ``ultimo_error``, que es lo que hace
    diagnosticable «este cliente no recibe nada».
    """
    if not mail.configurado(db):
        # No es un error: es un despliegue sin correo. Se declara para que la consola de
        # operaciones pueda decir por qué la cola no baja, en vez de mostrar cero y punto.
        return {"enviados": 0, "usuarios": 0, "pendientes": sum(
            len(v) for v in _pendientes(db).values()), "smtp": mail.diagnostico(db)}

    enviados = 0
    usuarios = 0
    fallidos = 0
    diferidos = 0
    sin_acceso = 0

    for user_id, entregas in _pendientes(db).items():
        if not _toca_enviar(db, user_id, entregas):
            diferidos += len(entregas)
            continue
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if user is None or not bool(user.is_active) or not str(user.email or "").strip():
            continue

        # Mismo gate que la entrega in-app: entre el barrido y el envío pueden pasar días.
        subs = (db.query(AlertSubscription)
                .filter(AlertSubscription.user_id == user_id).all())
        vivas, _ = service.entregables(db, subs)
        por_clave = {(str(s.sector_key), str(s.subject or "")): s for s in vivas}

        ids = [str(e.event_id) for e in entregas]
        eventos = {str(e.id): e for e in db.query(AlertEventRow)
                   .filter(AlertEventRow.id.in_(ids)).all()}

        vigentes: List[AlertDelivery] = []
        for entrega in entregas:
            ev = eventos.get(str(entrega.event_id))
            if ev is None or not _cubierta(por_clave, ev):
                # Ya no le corresponde: se marca como resuelta (no pendiente eterna) sin
                # mandar nada, y se declara el motivo.
                entrega.enviado_at = _ahora()
                entrega.ultimo_error = "sin_acceso_al_enviar"
                sin_acceso += 1
                continue
            vigentes.append(entrega)
        db.commit()
        if not vigentes:
            continue

        lista = [eventos[str(e.event_id)] for e in vigentes][:MAX_EN_CORREO]
        asunto = (ASUNTO_UNA.format(titulo=lista[0].titulo) if len(vigentes) == 1
                  else ASUNTO_VARIAS.format(n=len(vigentes)))
        ok = mail.enviar(str(user.email), asunto, _cuerpo(lista, len(vigentes)), db=db)

        ahora = _ahora()
        for entrega in vigentes:
            entrega.intentos = int(entrega.intentos or 0) + 1
            if ok:
                entrega.enviado_at = ahora
                entrega.ultimo_error = None
            else:
                entrega.ultimo_error = "envio_fallido"
        db.commit()

        if ok:
            DEDUP.marcar(db, user_id)
            enviados += len(vigentes)
            usuarios += 1
        else:
            fallidos += len(vigentes)

    return {"enviados": enviados, "usuarios": usuarios, "fallidos": fallidos,
            "diferidos": diferidos, "sin_acceso": sin_acceso}


def _ahora() -> _dt.datetime:
    """UTC naive: las columnas DateTime lo son (parity SQLite↔Postgres)."""
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


DIGEST_OP_NAME = "alerts-digest"


def _run(params, user_id, set_phase) -> Dict[str, Any]:
    from shared.database.session import SessionLocal

    db = SessionLocal()
    try:
        set_phase("enviando resúmenes por correo")
        return enviar_digests(db)
    finally:
        db.close()


def register_digest_operation() -> None:
    """Registra el envío de resúmenes (idempotente). Diaria: el `semanal` se resuelve por
    cliente dentro de la corrida, no con una segunda operación."""
    from shared.operations.service import Operation, register_operation

    register_operation(Operation(
        DIGEST_OP_NAME, "Resúmenes de alertas por correo",
        "Manda a cada cliente, en un solo correo, las señales de sus vigilancias que todavía "
        "no salieron. Respeta la cadencia elegida y re-verifica el acceso antes de enviar. "
        "Sin SMTP configurado no hace nada y lo declara.",
        _run, default_interval_hours=24,
    ))


register_digest_operation()
