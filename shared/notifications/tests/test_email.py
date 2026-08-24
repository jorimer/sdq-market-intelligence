"""El emisor de correo — y sobre todo qué hace cuando NO puede mandar.

Vive acá y no en `shared/alerts/tests/`: allá el fixture del digest tiene `configurado` y
`enviar` parcheados, así que un test del emisor escrito ahí mediría el doble y no el código.
"""
import pytest

from shared.config.settings import settings
from shared.notifications import email as mail


@pytest.fixture(autouse=True)
def limpio(monkeypatch):
    """Entorno sin correo, para que ningún test dependa del .env de quien lo corre."""
    for campo, valor in (("SMTP_HOST", ""), ("SMTP_USER", ""), ("SMTP_PASSWORD", ""),
                         ("SMTP_FROM", "")):
        monkeypatch.setattr(settings, campo, valor)


def test_sin_host_no_hay_canal():
    """Es la comprobación que decide si `email` se ofrece. Sin host no hay a dónde
    conectarse, y cualquier otra verificación sería teatro."""
    assert mail.configurado() is False
    assert "servidor de correo (host)" in mail.diagnostico()["falta"]


def test_sin_host_enviar_devuelve_False_sin_intentar(monkeypatch):
    llamadas = []
    monkeypatch.setattr(mail.smtplib, "SMTP", lambda *a, **k: llamadas.append(a))
    assert mail.enviar("cliente@sdq.do", "asunto", "cuerpo") is False
    assert llamadas == []


def test_con_host_pero_sin_remitente_lo_DECLARA(monkeypatch):
    """«No configurado» y «configurado sin remitente» piden acciones distintas, y un solo
    booleano las confunde."""
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.ejemplo.do")
    d = mail.diagnostico()
    assert d["configurado"] is True
    assert d["remitente"] is None
    assert any("remitente" in f for f in d["falta"])


def test_con_host_y_sin_remitente_no_manda(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.ejemplo.do")
    assert mail.enviar("cliente@sdq.do", "asunto", "cuerpo") is False


def test_el_usuario_SMTP_sirve_de_remitente(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.ejemplo.do")
    monkeypatch.setattr(settings, "SMTP_USER", "alertas@sdq.do")
    assert mail.remitente() == "alertas@sdq.do"


def test_destinatario_vacio_no_manda(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.ejemplo.do")
    monkeypatch.setattr(settings, "SMTP_FROM", "alertas@sdq.do")
    assert mail.enviar("", "asunto", "cuerpo") is False
    assert mail.enviar("   ", "asunto", "cuerpo") is False


def test_un_servidor_inalcanzable_devuelve_False_y_NO_levanta(monkeypatch):
    """Best-effort: un SMTP caído no puede abortar un barrido de alertas ni dejar a los
    demás destinatarios sin su correo."""
    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "SMTP_PORT", 1)
    monkeypatch.setattr(settings, "SMTP_FROM", "alertas@sdq.do")
    monkeypatch.setattr(mail, "TIMEOUT_SEGUNDOS", 1)
    assert mail.enviar("cliente@sdq.do", "asunto", "cuerpo") is False


def test_el_mensaje_lleva_texto_plano_aunque_haya_html(monkeypatch):
    """Un correo que solo existe en HTML es un correo que a veces llega vacío: el texto plano
    es el que se lee en un reloj, en un cliente que bloquea HTML y en el preview."""
    capturado = {}

    class _SMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            pass

        def login(self, u, p):
            pass

        def send_message(self, msg):
            capturado["msg"] = msg

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.ejemplo.do")
    monkeypatch.setattr(settings, "SMTP_FROM", "alertas@sdq.do")
    monkeypatch.setattr(mail.smtplib, "SMTP", _SMTP)

    assert mail.enviar("cliente@sdq.do", "Asunto", "cuerpo plano",
                       html="<p>cuerpo rico</p>") is True
    msg = capturado["msg"]
    assert msg["To"] == "cliente@sdq.do"
    assert msg["From"] == "alertas@sdq.do"
    tipos = {p.get_content_type() for p in msg.walk()}
    assert "text/plain" in tipos and "text/html" in tipos
