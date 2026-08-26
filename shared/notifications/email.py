"""Correo saliente — el canal que hace que el cliente se entere sin abrir la app.

**Por qué SMTP y no el SDK de un proveedor.** SendGrid, Resend, SES y Postmark exponen todos
SMTP. Con `smtplib` (biblioteca estándar) el emisor no queda casado con ninguno, no suma una
dependencia al lock —que ya tiene su propio problema en macOS— y el dueño puede cambiar de
proveedor moviendo cuatro campos.

**De dónde sale la configuración: del LLAVERO de la app, y el entorno es sólo el respaldo.**
La pantalla de Configuración escribe en ``AppSetting`` (contraseña cifrada con Fernet, como
la llave de Claude) y esto la lee de ahí; si no hay nada guardado, cae a las variables de
entorno. Vive así porque exigir un redeploy para encender el correo se lo entrega a quien
tenga acceso al panel de infraestructura, que no es necesariamente el dueño del producto.

**Un solo resolutor, y todo pasa por él.** :func:`_cfg` es el único lugar que sabe de dónde
sale un valor. Las cinco funciones públicas lo consultan; ninguna lee ``settings`` por su
cuenta. Es deliberado: el modo de falla dominante de este repo es el guard puesto en un
camino y olvidado en el otro, y con dos lectores distintos de la misma configuración
—``configurado()`` mirando el llavero y ``enviar()`` mirando el entorno— el canal se
anunciaría disponible y no entregaría nada.

**La regla que gobierna este módulo: sin configuración NO hay canal.** :func:`configurado`
es lo que decide si `email` aparece en la lista de canales elegibles. Ofrecer un canal que no
entrega deja al cliente esperando avisos que nunca salen, y eso no falla: DESAPARECE.

**Es best-effort y NUNCA levanta hacia el llamador.** Un SMTP caído no puede abortar un
barrido de alertas ni dejar a medias las entregas de los demás destinatarios. Devuelve
``False`` y registra; quien llama decide si reintenta (el digest lo hace: la fila queda
pendiente y el barrido siguiente la retoma).
"""
from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any, Dict, Optional

from shared.config.settings import settings

logger = logging.getLogger("sdq.notifications.email")

TIMEOUT_SEGUNDOS = 15

# El barrido entrega a muchos destinatarios seguidos; sin esta memoria cada uno abriría su
# propia sesión contra la base sólo para releer el mismo host.
TTL_CACHE_SEGUNDOS = 30.0
_cache: Optional[Dict[str, Any]] = None
# `None` = nunca se cargó. NO se usa 0.0 como centinela: `time.monotonic()` no tiene origen
# fijo, así que un 0.0 ataría la validez de la caché al uptime del proceso.
_cache_at: Optional[float] = None


def _del_entorno() -> Dict[str, Any]:
    return {
        "host": (settings.SMTP_HOST or "").strip(),
        "port": int(settings.SMTP_PORT or 587),
        "user": (settings.SMTP_USER or "").strip(),
        "password": settings.SMTP_PASSWORD or "",
        "from": (settings.SMTP_FROM or "").strip(),
        "starttls": bool(settings.SMTP_STARTTLS),
    }


def invalidar_cache() -> None:
    """La llama Configuración al guardar. Sin esto, encender el correo tardaría el TTL en
    surtir efecto y el botón «enviar prueba» diría que no hay canal justo después de que el
    admin acaba de configurarlo."""
    global _cache, _cache_at
    _cache, _cache_at = None, None


def _cfg(db: Any = None) -> Dict[str, Any]:
    """Configuración vigente. Con ``db`` lee sin caché; sin ``db`` abre su propia sesión.

    Que funcione sin ``db`` no es comodidad: es lo que hace imposible el olvido. Si pasar la
    sesión fuera obligatorio, cualquier llamador que no la tuviera a mano quedaría leyendo
    sólo el entorno y el canal se partiría en dos verdades.
    """
    global _cache, _cache_at
    if db is not None:
        try:
            return _leer_llavero(db)
        except Exception:  # noqa: BLE001
            # El llavero ilegible (tabla ausente en un despliegue cuya migración todavía no
            # corrió, base caída) NO puede tumbar a quien nos llama: el gate del canal vive
            # dentro del endpoint de alertas, y hacerlo estallar convertiría «no sé si hay
            # correo» en «la watchlist no responde». Se degrada al entorno y se registra.
            logger.warning("email: llavero ilegible; se usa el entorno", exc_info=True)
            try:
                db.rollback()  # la sesión queda envenenada tras el error; el llamador sigue usándola
            except Exception:  # noqa: BLE001
                pass
            return _del_entorno()

    ahora = time.monotonic()
    if _cache is not None and _cache_at is not None and (ahora - _cache_at) < TTL_CACHE_SEGUNDOS:
        return _cache

    from shared.database.session import SessionLocal

    propia = None
    try:
        propia = SessionLocal()
        valor = _leer_llavero(propia)
    except Exception:  # noqa: BLE001 — una base ilegible no puede reventar al emisor
        logger.warning("email: no se pudo leer la configuración guardada; se usa el entorno",
                       exc_info=True)
        valor = _del_entorno()
    finally:
        if propia is not None:
            propia.close()

    _cache, _cache_at = valor, ahora
    return valor


def _leer_llavero(db: Any) -> Dict[str, Any]:
    from shared.settings.service import get_smtp_config

    return dict(get_smtp_config(db))


def configurado(db: Any = None) -> bool:
    """¿Hay un servidor de correo al que mandarle? Sin host no hay canal.

    Se mira SOLO el host: usuario y contraseña son opcionales (un relay interno o un SMTP
    de pruebas puede no pedirlos), pero sin host no hay a dónde conectarse y cualquier otra
    comprobación sería teatro.
    """
    return bool(str(_cfg(db).get("host") or "").strip())


def remitente(db: Any = None) -> str:
    """Casilla de origen. El remitente configurado si está; si no, el usuario SMTP."""
    cfg = _cfg(db)
    return str(cfg.get("from") or cfg.get("user") or "").strip()


def enviar(destinatario: str, asunto: str, texto: str,
           html: Optional[str] = None, db: Any = None) -> bool:
    """Manda un correo. Devuelve si salió; **no levanta**.

    ``texto`` es obligatorio y ``html`` opcional a propósito: el cuerpo de texto plano es el
    que se lee en un reloj, en un cliente que bloquea HTML y en el preview del teléfono. Un
    correo que solo existe en HTML es un correo que a veces llega vacío.
    """
    cfg = _cfg(db)
    if not str(cfg.get("host") or "").strip():
        logger.debug("email: sin host configurado, no se envía a %s", destinatario)
        return False
    origen = str(cfg.get("from") or cfg.get("user") or "").strip()
    if not origen:
        logger.warning("email: hay host configurado pero no hay remitente "
                       "(remitente ni usuario); no se envía.")
        return False
    if not (destinatario or "").strip():
        return False

    msg = EmailMessage()
    msg["From"] = origen
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(str(cfg["host"]), int(cfg["port"]),
                          timeout=TIMEOUT_SEGUNDOS) as smtp:
            if cfg.get("starttls"):
                smtp.starttls(context=ssl.create_default_context())
            if cfg.get("user"):
                smtp.login(str(cfg["user"]), str(cfg.get("password") or ""))
            smtp.send_message(msg)
        logger.info("email: enviado a %s (%s)", destinatario, asunto)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort: nunca aborta a quien llama
        logger.warning("email: no se pudo enviar a %s: %s", destinatario, e)
        return False


def enviar_o_motivo(destinatario: str, asunto: str, texto: str,
                    html: Optional[str] = None, db: Any = None) -> tuple:
    """Como :func:`enviar`, pero devuelve ``(ok, motivo)`` con el error REAL del servidor.

    Existe para el botón «enviar prueba» de Configuración. El best-effort de :func:`enviar`
    es correcto durante un barrido —nadie está mirando— y es exactamente lo contrario de lo
    que hace falta cuando alguien acaba de pegar una llave y pregunta si sirve: ahí, «no se
    pudo» sin el motivo obliga a adivinar entre una llave mal copiada, un puerto bloqueado y
    un remitente sin verificar.
    """
    cfg = _cfg(db)
    if not str(cfg.get("host") or "").strip():
        return False, "Falta el servidor (host) de correo."
    origen = str(cfg.get("from") or cfg.get("user") or "").strip()
    if not origen:
        return False, "Falta el remitente: completá «De» o el usuario."
    if not (destinatario or "").strip():
        return False, "No hay destinatario: tu usuario no tiene correo cargado."

    msg = EmailMessage()
    msg["From"] = origen
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(str(cfg["host"]), int(cfg["port"]),
                          timeout=TIMEOUT_SEGUNDOS) as smtp:
            if cfg.get("starttls"):
                smtp.starttls(context=ssl.create_default_context())
            if cfg.get("user"):
                smtp.login(str(cfg["user"]), str(cfg.get("password") or ""))
            smtp.send_message(msg)
        return True, ""
    except Exception as e:  # noqa: BLE001 — el motivo ES el producto de esta función
        logger.warning("email: prueba fallida hacia %s: %s", destinatario, e)
        return False, str(e)


def diagnostico(db: Any = None) -> dict:
    """Qué falta para que el canal exista. Lo consume la consola de operaciones.

    Devuelve hechos, no un veredicto binario: «no configurado» y «configurado sin remitente»
    piden acciones distintas, y un solo booleano las confunde.
    """
    cfg = _cfg(db)
    return {
        "configurado": bool(str(cfg.get("host") or "").strip()),
        "host": str(cfg.get("host") or "") or None,
        "puerto": cfg.get("port"),
        "starttls": bool(cfg.get("starttls")),
        "usuario_set": bool(cfg.get("user")),
        "password_set": bool(cfg.get("password")),
        "remitente": (str(cfg.get("from") or cfg.get("user") or "").strip() or None),
        "falta": _falta(cfg),
    }


def _falta(cfg: Optional[Dict[str, Any]] = None) -> list:
    c = cfg if cfg is not None else _cfg()
    hay_host = bool(str(c.get("host") or "").strip())
    hay_remitente = bool(str(c.get("from") or c.get("user") or "").strip())
    pendiente = []
    if not hay_host:
        pendiente.append("servidor de correo (host)")
    if hay_host and not hay_remitente:
        pendiente.append("remitente («De» o usuario)")
    return pendiente
