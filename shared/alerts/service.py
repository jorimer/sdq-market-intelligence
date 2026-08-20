"""Watchlist: crear, listar, editar y dar de baja una vigilancia — con sus dos validaciones.

Las dos que importan y por qué:

**1. El sujeto se valida contra lo que el propio producto declara elegible.** Cada eje tiene
un tipo de sujeto distinto (banco, ISO3, provincia, expediente) y el contrato ya resolvió
dónde vive esa lista: ``scope_options()`` — lo que acepta ``snapshot(scope=…)``, detectado por
``getattr`` (ver `shared/products/contract.py`). Se reusa esa superficie en vez de inventar un
segundo catálogo de sujetos que se desincronizaría del primero. Un producto que NO la
implementa es de sujeto FIJO: ahí el único valor legítimo es «todo el eje».

**2. El nivel exigido lo determina el SUJETO, no una constante.** Vigilar el sistema sin
nombrar a nadie es Pulse; vigilar una entidad nombrada es Insight. Es la misma línea que
separa los niveles del catálogo (``Granularity.system`` NUNCA emite nombres de entidad), y
tenerla acá evita que la alerta se vuelva una puerta lateral al dato que se cobra aparte.

**El acceso se re-verifica en la ENTREGA, no solo al suscribir** (:func:`entregables`). Una
vigilancia sobrevive al fin del contrato; sin re-chequeo, el cliente que se dio de baja sigue
recibiendo producto. Por eso el helper existe desde la fase A aunque el motor llegue en la B:
es la pieza que más barato se olvida y más caro se paga.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from shared.alerts import reglas
from shared.alerts.models import TODO_EL_EJE, AlertEventRow, AlertSubscription
from shared.auth.models import User
from shared.products.access import can_access
from shared.products.registry import CATALOG_BY_KEY, get_product
from shared.products.tiers import ProductTier

logger = logging.getLogger("sdq.alerts")

# Canales con entrega REAL. El buzón in-app siempre; el correo **solo si hay un servidor
# configurado** (`shared/notifications/email.configurado`).
#
# Es una función y no una constante justamente por eso: si `email` fuera fijo, un despliegue
# sin SMTP aceptaría vigilancias por correo y el cliente quedaría esperando avisos que nunca
# salen. Un canal mudo no falla — desaparece. El webhook llega en la fase E.
CANAL_INAPP = "inapp"
CANAL_EMAIL = "email"
CANALES_PLANIFICADOS: Tuple[str, ...] = ("webhook",)


def canales_disponibles() -> Tuple[str, ...]:
    """Canales que HOY entregan de verdad, en este despliegue."""
    from shared.notifications.email import configurado

    return (CANAL_INAPP, CANAL_EMAIL) if configurado() else (CANAL_INAPP,)


def canales_no_configurados() -> Tuple[str, ...]:
    """Canales que existen en el código pero que este despliegue no puede usar. Se declaran
    en vez de callarse: «no lo ofrecemos» y «no está configurado» piden acciones distintas —
    la segunda la resuelve el dueño con tres variables de entorno."""
    from shared.notifications.email import configurado

    return () if configurado() else (CANAL_EMAIL,)

DIGESTS: Tuple[str, ...] = ("inmediato", "diario", "semanal")

# Tope de vigilancias por usuario. No es una cuota comercial: es el freno al modo de falla
# dominante del producto (ruido). Un cliente con 400 vigilancias no lee ninguna.
MAX_POR_USUARIO = 100


class AlertValidationError(ValueError):
    """Datos inválidos para una vigilancia. Mensaje en español, listo para el 422."""


def _normalizar_subject(subject: Optional[str]) -> str:
    """``None`` / vacío / espacios ⇒ ``TODO_EL_EJE``. Un solo lugar hace la traducción
    entre el ``null`` del JSON y la sentinela de base (ver ``models.TODO_EL_EJE``)."""
    return (subject or "").strip()


def sujetos_elegibles(db: Session, sector_key: str) -> Optional[List[Dict[str, str]]]:
    """Opciones de sujeto que el producto declara, o ``None`` si es de sujeto FIJO.

    ``None`` y ``[]`` son cosas distintas y la validación las trata distinto: ``None`` = «este
    eje no elige sujeto» (correcto, no es una brecha); ``[]`` = «elige, pero hoy no hay
    ninguno» (el universo está vacío y no se puede vigilar a nadie todavía).
    """
    producto = get_product(sector_key, db)
    if producto is None:
        return None
    fn = getattr(producto, "scope_options", None)
    if fn is None:
        return None
    try:
        opciones = fn() or []
    except Exception as e:  # noqa: BLE001 — un eje que falla al listar no rompe la watchlist
        logger.warning("alerts: no se pudieron leer los sujetos de '%s': %s", sector_key, e)
        return None
    return [
        {"value": str(o.get("value", "")), "label": str(o.get("label") or o.get("value", "")),
         "group": str(o.get("group") or "")}
        for o in opciones if o.get("value")
    ]


def tier_requerido(subject: str) -> ProductTier:
    """Nivel que hay que tener para vigilar esto. Sin sujeto = agregado del sistema (Pulse);
    con sujeto = entidad nombrada (Insight). Ver el docstring del módulo."""
    return ProductTier.pulse if subject == TODO_EL_EJE else ProductTier.insight


def _validar_eje(db: Session, sector_key: str) -> None:
    if sector_key not in CATALOG_BY_KEY:
        raise AlertValidationError(
            f"El eje '{sector_key}' no está en el catálogo de productos.")
    if get_product(sector_key, db) is None:
        # Suscribirse a un eje sin implementación es una promesa que no se puede cumplir.
        raise AlertValidationError(
            f"El eje «{CATALOG_BY_KEY[sector_key].display_name}» todavía no produce alertas.")


def _validar_sujeto(db: Session, sector_key: str, subject: str) -> None:
    elegibles = sujetos_elegibles(db, sector_key)
    nombre = CATALOG_BY_KEY[sector_key].display_name
    if subject == TODO_EL_EJE:
        return  # vigilar el eje entero siempre es legítimo
    if elegibles is None:
        raise AlertValidationError(
            f"«{nombre}» tiene un sujeto único: no se elige entidad. "
            f"Vigilá el eje completo (sin sujeto).")
    if not elegibles:
        raise AlertValidationError(
            f"«{nombre}» aún no tiene sujetos disponibles para vigilar.")
    if subject not in {o["value"] for o in elegibles}:
        raise AlertValidationError(
            f"'{subject}' no es un sujeto válido de «{nombre}».")


def _validar_vocabularios(rule_codes: Optional[Sequence[str]], min_severity: str,
                          channels: Sequence[str], digest: str) -> None:
    faltantes = reglas.desconocidos(list(rule_codes) if rule_codes else None)
    if faltantes:
        raise AlertValidationError(
            f"Disparador(es) desconocido(s): {', '.join(faltantes)}. "
            f"Disponibles: {', '.join(reglas.CODIGOS)}.")
    if min_severity not in reglas.SEVERIDADES:
        raise AlertValidationError(
            f"Severidad mínima inválida '{min_severity}'. "
            f"Use {' | '.join(reglas.SEVERIDADES)}.")
    if not channels:
        raise AlertValidationError("Elegí al menos un canal de entrega.")
    disponibles = canales_disponibles()
    invalidos = [c for c in channels if c not in disponibles]
    if invalidos:
        sin_configurar = [c for c in invalidos if c in canales_no_configurados()]
        if sin_configurar:
            raise AlertValidationError(
                f"El canal {', '.join(sin_configurar)} no está configurado en esta "
                f"instalación. Por ahora: {', '.join(disponibles)}.")
        planificados = [c for c in invalidos if c in CANALES_PLANIFICADOS]
        if planificados:
            raise AlertValidationError(
                f"El canal {', '.join(planificados)} todavía no entrega; se habilita más "
                f"adelante. Por ahora: {', '.join(disponibles)}.")
        raise AlertValidationError(
            f"Canal(es) inválido(s): {', '.join(invalidos)}. "
            f"Disponibles: {', '.join(disponibles)}.")
    if digest not in DIGESTS:
        raise AlertValidationError(
            f"Ritmo de entrega inválido '{digest}'. Use {' | '.join(DIGESTS)}.")


def _produce_alertas(sector_key: str) -> bool:
    """¿Hay un productor registrado para este eje? Import local a propósito: `motor` importa
    a este módulo, y a nivel de módulo el par se cerraría en ciclo."""
    from shared.alerts.motor import registered_sectors

    return sector_key in registered_sectors()


def serializar(row: AlertSubscription) -> Dict[str, Any]:
    """Forma pública de una vigilancia. ``subject`` sale como ``null`` cuando es todo el eje
    — la sentinela de base no se filtra a la API."""
    subject = str(row.subject or "")
    entry = CATALOG_BY_KEY.get(str(row.sector_key))
    return {
        "id": row.id,
        "sector_key": row.sector_key,
        "sector_label": entry.display_name if entry else row.sector_key,
        "subject": subject or None,
        "rule_codes": list(row.rule_codes) if row.rule_codes else None,
        "min_severity": row.min_severity,
        "channels": list(row.channels or []),
        "digest": row.digest,
        "active": bool(row.active),
        "suspended_reason": row.suspended_reason,
        "tier_requerido": tier_requerido(subject).value,
        # ¿Este eje ya tiene un productor enchufado al barrido? Un eje del catálogo puede
        # estar implementado como PRODUCTO y todavía no aportar señales. Se declara en vez
        # de callarse: una vigilancia muda presentada como activa se lee como que no pasó
        # nada, que es la lectura opuesta a la verdadera.
        "sector_produce_alertas": _produce_alertas(str(row.sector_key)),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def crear(db: Session, user: User, *, sector_key: str, subject: Optional[str] = None,
          rule_codes: Optional[List[str]] = None, min_severity: str = "media",
          channels: Optional[List[str]] = None,
          digest: str = "inmediato") -> AlertSubscription:
    """Crea una vigilancia validada. Levanta :class:`AlertValidationError` (422) o
    ``PermissionError`` con la decisión de acceso adjunta (402/404, la traduce el router)."""
    subject_n = _normalizar_subject(subject)
    canales = list(channels or ["inapp"])

    _validar_eje(db, sector_key)
    _validar_sujeto(db, sector_key, subject_n)
    _validar_vocabularios(rule_codes, min_severity, canales, digest)

    decision = can_access(db, user, sector_key, tier_requerido(subject_n))
    if not decision.allowed:
        raise PermissionError(decision)

    ya = (db.query(AlertSubscription)
          .filter(AlertSubscription.user_id == user.id,
                  AlertSubscription.sector_key == sector_key,
                  AlertSubscription.subject == subject_n)
          .one_or_none())
    if ya is not None:
        # Re-suscribir lo que ya se vigila NO es un error del cliente: es reactivar. Así el
        # botón "Vigilar" es idempotente y una vigilancia suspendida por acceso revocado
        # revive con la configuración que el usuario ya había elegido.
        ya.active = True
        ya.suspended_reason = None
        ya.rule_codes = list(rule_codes) if rule_codes else None
        ya.min_severity = min_severity
        ya.channels = canales
        ya.digest = digest
        db.commit()
        return ya

    total = (db.query(AlertSubscription)
             .filter(AlertSubscription.user_id == user.id).count())
    if total >= MAX_POR_USUARIO:
        raise AlertValidationError(
            f"Llegaste al máximo de {MAX_POR_USUARIO} vigilancias. "
            f"Dá de baja alguna antes de agregar otra.")

    row = AlertSubscription(
        user_id=user.id, sector_key=sector_key, subject=subject_n,
        rule_codes=list(rule_codes) if rule_codes else None,
        min_severity=min_severity, channels=canales, digest=digest,
        active=True, suspended_reason=None)
    db.add(row)
    db.commit()
    logger.info("alerts: vigilancia creada user=%s eje=%s sujeto=%r",
                user.id, sector_key, subject_n or "(todo el eje)")
    return row


def listar(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """Vigilancias del usuario, más recientes primero. Desempate por id: ``created_at``
    tiene resolución de segundos en SQLite y varias del mismo segundo quedarían en orden
    no determinista."""
    rows = (db.query(AlertSubscription)
            .filter(AlertSubscription.user_id == user_id)
            .order_by(AlertSubscription.created_at.desc(), AlertSubscription.id.desc())
            .all())
    return [serializar(r) for r in rows]


def obtener(db: Session, user_id: str, sub_id: str) -> Optional[AlertSubscription]:
    """La vigilancia PROPIA con ese id, o ``None``. No revela la existencia de ajenas."""
    return (db.query(AlertSubscription)
            .filter(AlertSubscription.id == sub_id,
                    AlertSubscription.user_id == user_id)
            .one_or_none())


def actualizar(db: Session, row: AlertSubscription, *, rule_codes: Optional[List[str]] = None,
               min_severity: Optional[str] = None, channels: Optional[List[str]] = None,
               digest: Optional[str] = None,
               active: Optional[bool] = None) -> AlertSubscription:
    """Edita la configuración de entrega. El eje y el sujeto NO se editan: cambiarlos es
    otra vigilancia (y otro chequeo de acceso), así que se da de baja y se crea."""
    nuevos_codigos = rule_codes if rule_codes is not None else (
        list(row.rule_codes) if row.rule_codes else None)
    _validar_vocabularios(
        nuevos_codigos,
        min_severity or str(row.min_severity),
        channels if channels is not None else list(row.channels or []),
        digest or str(row.digest))

    if rule_codes is not None:
        row.rule_codes = list(rule_codes) or None
    if min_severity is not None:
        row.min_severity = min_severity
    if channels is not None:
        row.channels = list(channels)
    if digest is not None:
        row.digest = digest
    if active is not None:
        row.active = active
        # Reactivar a mano limpia el motivo: si el acceso sigue caído, la ENTREGA lo vuelve
        # a suspender. El estado real lo decide el gate, no este setter.
        if active:
            row.suspended_reason = None
    db.commit()
    return row


def eliminar(db: Session, row: AlertSubscription) -> None:
    db.delete(row)
    db.commit()


def entregables(db: Session, subs: Sequence[AlertSubscription]
                ) -> Tuple[List[AlertSubscription], List[Dict[str, Any]]]:
    """Parte *subs* en (entregables, suspendidas) **re-verificando el acceso**.

    Por qué acá y no al suscribir: una vigilancia sobrevive al fin del contrato. Si el acceso
    solo se chequea al crearla, el cliente que se dio de baja sigue recibiendo el producto que
    dejó de pagar — y una alerta de un eje ajeno filtra el dato que se le cobra a otro.

    La suspensión se PERSISTE con su motivo en vez de borrar la fila: si el cliente renueva,
    vuelve a lo que ya había elegido. Y lo suspendido se devuelve LISTADO, no en silencio —
    un veto callado se lee como que el eje no tiene nada que avisar.
    """
    usuarios: Dict[str, Optional[User]] = {}
    ok: List[AlertSubscription] = []
    suspendidas: List[Dict[str, Any]] = []

    for sub in subs:
        if not bool(sub.active):
            continue
        uid = str(sub.user_id)
        if uid not in usuarios:
            usuarios[uid] = db.query(User).filter(User.id == uid).one_or_none()
        user = usuarios[uid]
        if user is None or not bool(user.is_active):
            _suspender(db, sub, "usuario_inactivo")
            suspendidas.append({"id": sub.id, "motivo": "usuario_inactivo"})
            continue
        decision = can_access(db, user, str(sub.sector_key),
                              tier_requerido(str(sub.subject or "")))
        if not decision.allowed:
            _suspender(db, sub, "acceso_revocado")
            suspendidas.append({"id": sub.id, "motivo": "acceso_revocado",
                                "outcome": decision.outcome.value})
            continue
        if sub.suspended_reason:
            # El acceso volvió: la vigilancia se reanuda sola, sin que el cliente
            # tenga que acordarse de reactivarla.
            sub.suspended_reason = None
            db.commit()
        ok.append(sub)
    return ok, suspendidas


def _suspender(db: Session, sub: AlertSubscription, motivo: str) -> None:
    if sub.suspended_reason == motivo and not bool(sub.active):
        return
    sub.active = False
    sub.suspended_reason = motivo
    db.commit()
    logger.info("alerts: vigilancia %s suspendida (%s)", sub.id, motivo)


def para_sujeto(db: Session, sector_key: str, subject: str) -> List[AlertSubscription]:
    """Vigilancias ACTIVAS que alcanzan a (*sector_key*, *subject*): las del sujeto exacto
    más las del eje entero. Es la consulta que la fase B hace por cada evento candidato."""
    return (db.query(AlertSubscription)
            .filter(AlertSubscription.sector_key == sector_key,
                    AlertSubscription.active.is_(True),
                    AlertSubscription.subject.in_([_normalizar_subject(subject), TODO_EL_EJE]))
            .all())


def serializar_evento(row: AlertEventRow) -> Dict[str, Any]:
    entry = CATALOG_BY_KEY.get(str(row.sector_key))
    return {
        "id": row.id, "codigo": row.codigo,
        "sector_key": row.sector_key,
        "sector_label": entry.display_name if entry else row.sector_key,
        "subject": str(row.subject or "") or None,
        "periodo": row.periodo, "severidad": row.severidad,
        "titulo": row.titulo, "cuerpo": row.cuerpo, "basis": row.basis,
        "relaciones": dict(row.relaciones or {}),
        "procedencia": dict(row.procedencia or {}),
        "frescura": row.frescura,
        "publicada": bool(row.publicada),
        "veto_motivo": row.veto_motivo, "veto_detalle": row.veto_detalle,
        "entregas": int(row.entregas or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def eventos_para(db: Session, user_id: str, *, limit: int = 50) -> Dict[str, Any]:
    """Historial de señales que TOCAN la watchlist del usuario, publicadas y vetadas.

    **Las vetadas van con las publicadas, no en un cajón aparte que nadie abre.** Un veto
    silencioso se lee como que el eje no tenía nada que avisar; el resumen por motivo es lo
    que convierte «no recibí nada» en «hay tres señales retenidas porque el dato que las
    sostiene no está vigente», que es información accionable y no ausencia de ella.
    """
    subs = (db.query(AlertSubscription)
            .filter(AlertSubscription.user_id == user_id,
                    AlertSubscription.active.is_(True))
            .all())
    if not subs:
        return {"events": [], "vetadas": {}, "total": 0, "sin_vigilancias": True}

    # Un eje vigilado entero alcanza a CUALQUIER sujeto suyo; uno vigilado por sujeto, solo
    # a ese. Se arma en dos filtros en vez de uno para no traer el eje completo cuando el
    # usuario solo pidió una entidad.
    ejes_completos = [str(s.sector_key) for s in subs
                      if str(s.subject or "") == TODO_EL_EJE]
    pares = [(str(s.sector_key), str(s.subject)) for s in subs
             if str(s.subject or "") != TODO_EL_EJE]

    condiciones: List[Any] = []
    if ejes_completos:
        condiciones.append(AlertEventRow.sector_key.in_(ejes_completos))
    for sector_key, subject in pares:
        condiciones.append(and_(AlertEventRow.sector_key == sector_key,
                                AlertEventRow.subject == subject))

    rows = (db.query(AlertEventRow)
            .filter(or_(*condiciones))
            .order_by(AlertEventRow.created_at.desc(), AlertEventRow.id.desc())
            .limit(limit).all())

    vetadas: Dict[str, int] = {}
    for r in rows:
        if not bool(r.publicada) and r.veto_motivo:
            vetadas[str(r.veto_motivo)] = vetadas.get(str(r.veto_motivo), 0) + 1

    return {"events": [serializar_evento(r) for r in rows],
            "vetadas": vetadas, "total": len(rows), "sin_vigilancias": False}
