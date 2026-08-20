"""Correo saliente — el canal que hace que el cliente se entere sin abrir la app.

**Por qué SMTP y no el SDK de un proveedor.** SendGrid, Resend, SES y Postmark exponen todos
SMTP. Con `smtplib` (biblioteca estándar) el emisor no queda casado con ninguno, no suma una
dependencia al lock —que ya tiene su propio problema en macOS— y el dueño puede cambiar de
proveedor moviendo tres variables de entorno.

**La regla que gobierna este módulo: sin configuración NO hay canal.** :func:`configurado`
es lo que decide si `email` aparece en la lista de canales elegibles. Ofrecer un canal que no
entrega deja al cliente esperando avisos que nunca salen, y eso no falla: DESAPARECE. Es la
misma decisión que en la fase A, cuando `email` se rechazaba con su motivo en vez de
aceptarse en silencio.

**Es best-effort y NUNCA levanta hacia el llamador.** Un SMTP caído no puede abortar un
barrido de alertas ni dejar a medias las entregas de los demás destinatarios. Devuelve
``False`` y registra; quien llama decide si reintenta (el digest lo hace: la fila queda
pendiente y el barrido siguiente la retoma).
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

from shared.config.settings import settings

logger = logging.getLogger("sdq.notifications.email")

TIMEOUT_SEGUNDOS = 15


def configurado() -> bool:
    """¿Hay un servidor de correo al que mandarle? Sin host no hay canal.

    Se mira SOLO el host: usuario y contraseña son opcionales (un relay interno o un SMTP
    de pruebas puede no pedirlos), pero sin host no hay a dónde conectarse y cualquier otra
    comprobación sería teatro.
    """
    return bool((settings.SMTP_HOST or "").strip())


def remitente() -> str:
    """Casilla de origen. ``SMTP_FROM`` si está; si no, el usuario SMTP."""
    return (settings.SMTP_FROM or settings.SMTP_USER or "").strip()


def enviar(destinatario: str, asunto: str, texto: str,
           html: Optional[str] = None) -> bool:
    """Manda un correo. Devuelve si salió; **no levanta**.

    ``texto`` es obligatorio y ``html`` opcional a propósito: el cuerpo de texto plano es el
    que se lee en un reloj, en un cliente que bloquea HTML y en el preview del teléfono. Un
    correo que solo existe en HTML es un correo que a veces llega vacío.
    """
    if not configurado():
        logger.debug("email: sin SMTP_HOST configurado, no se envía a %s", destinatario)
        return False
    origen = remitente()
    if not origen:
        logger.warning("email: SMTP_HOST está configurado pero no hay remitente "
                       "(SMTP_FROM ni SMTP_USER); no se envía.")
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
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT,
                          timeout=TIMEOUT_SEGUNDOS) as smtp:
            if settings.SMTP_STARTTLS:
                smtp.starttls(context=ssl.create_default_context())
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
        logger.info("email: enviado a %s (%s)", destinatario, asunto)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort: nunca aborta a quien llama
        logger.warning("email: no se pudo enviar a %s: %s", destinatario, e)
        return False


def diagnostico() -> dict:
    """Qué falta para que el canal exista. Lo consume la consola de operaciones.

    Devuelve hechos, no un veredicto binario: «no configurado» y «configurado sin remitente»
    piden acciones distintas, y un solo booleano las confunde.
    """
    return {
        "configurado": configurado(),
        "host": settings.SMTP_HOST or None,
        "puerto": settings.SMTP_PORT,
        "starttls": bool(settings.SMTP_STARTTLS),
        "usuario_set": bool(settings.SMTP_USER),
        "password_set": bool(settings.SMTP_PASSWORD),
        "remitente": remitente() or None,
        "falta": _falta(),
    }


def _falta() -> list:
    pendiente = []
    if not configurado():
        pendiente.append("SMTP_HOST")
    if configurado() and not remitente():
        pendiente.append("SMTP_FROM (o SMTP_USER)")
    return pendiente
