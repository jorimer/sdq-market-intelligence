"""El correo se configura DESDE LA APP, y el entorno es sólo el respaldo.

**De dónde sale esto (2026-08-24).** El canal `email` de las alertas estaba implementado,
probado y muerto: no aparecía en «Mis vigilancias» porque `SMTP_HOST` estaba vacío en
producción, y encenderlo exigía entrar al panel de infraestructura y redesplegar. El dueño
del producto no necesariamente tiene ese acceso — y la llave de Claude, que es el mismo tipo
de secreto, se configura desde la pantalla de Configuración desde siempre. Dos llaveros para
la misma clase de cosa es el tipo de incoherencia que termina en «pensé que estaba puesto».

**Qué protege cada test de acá**, en orden de qué tan callado sería el defecto:

1. que lo GUARDADO gane sobre el entorno (si no, la pantalla acepta datos y no hace nada);
2. que VACIAR el host apague el canal aunque el entorno lo tenga — «hay fila vacía» y «no
   hay fila» son cosas distintas, y confundirlas resucita un canal que alguien apagó;
3. que la contraseña NUNCA vuelva por la API;
4. que guardar sin re-tipear la contraseña no la BORRE (el modo de falla más probable de un
   formulario de secretos);
5. que el gate del canal en alertas lea el mismo llavero — un canal que se anuncia y no
   entrega es peor que uno ausente;
6. que la caché del emisor se invalide al guardar, o el botón «probar» mentiría durante su
   TTL justo después de configurar;
7. que un llavero ilegible degrade al entorno en vez de tumbar el API de alertas.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.config.settings import settings as app_settings
from shared.database.base import Base
from shared.notifications import email as mail
from shared.settings import service
from shared.settings.models import AppSetting, SectorApiConfig
from shared.settings.schemas import MASK, SettingsIn, SmtpIn


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__,
                                             SectorApiConfig.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_sin_nada_guardado_manda_el_entorno(db, monkeypatch):
    """El respaldo sigue vivo: una instalación que ya tenía SMTP por variables no se apaga
    al desplegar este cambio."""
    monkeypatch.setattr(app_settings, "SMTP_HOST", "smtp.entorno.do")
    monkeypatch.setattr(app_settings, "SMTP_FROM", "alertas@entorno.do")
    cfg = service.get_smtp_config(db)
    assert cfg["host"] == "smtp.entorno.do"
    assert mail.configurado(db) is True


def test_lo_guardado_le_GANA_al_entorno(db, monkeypatch):
    monkeypatch.setattr(app_settings, "SMTP_HOST", "smtp.entorno.do")
    service.set_smtp_config(db, host="smtp.resend.com", port=587, user="resend",
                            password="re_secreta", remitente="alertas@sdq.do")
    cfg = service.get_smtp_config(db)
    assert cfg["host"] == "smtp.resend.com"
    assert cfg["port"] == 587
    assert cfg["password"] == "re_secreta"


def test_vaciar_el_host_APAGA_el_canal_aunque_el_entorno_lo_tenga(db, monkeypatch):
    """El caso que distingue «fila vacía» de «fila ausente».

    Si el vacío delegara en el entorno, apagar el correo desde Configuración sería imposible
    en cualquier instalación que tenga las variables puestas: el admin lo apaga, la pantalla
    le dice que quedó apagado, y las alertas siguen saliendo.
    """
    monkeypatch.setattr(app_settings, "SMTP_HOST", "smtp.entorno.do")
    service.set_smtp_config(db, host="smtp.resend.com")
    assert mail.configurado(db) is True

    service.set_smtp_config(db, host="")
    assert service.get_smtp_config(db)["host"] == ""
    assert mail.configurado(db) is False


def test_la_contrasena_NUNCA_sale_por_la_API(db):
    service.set_smtp_config(db, host="smtp.resend.com", password="re_secreta")
    pub = service.get_smtp_public(db)
    assert pub["password_set"] is True
    assert "password" not in pub
    assert "re_secreta" not in str(pub)

    bloque = service.get_settings(db).smtp
    assert bloque.passwordSet is True
    assert "re_secreta" not in bloque.model_dump_json()


def test_guardar_SIN_retipear_la_contrasena_no_la_borra(db):
    """El modo de falla más probable de un formulario de secretos: la pantalla nunca recibe
    la contraseña guardada, así que reenvía el placeholder. Si eso la borrara, cambiar el
    remitente dejaría el canal sin llave y nadie se enteraría hasta la próxima entrega."""
    service.set_smtp_config(db, host="smtp.resend.com", password="re_secreta")
    service.update_settings(db, SettingsIn(smtp=SmtpIn(fromAddress="otra@sdq.do",
                                                       password=MASK)))
    assert service.get_smtp_config(db)["password"] == "re_secreta"
    assert service.get_smtp_config(db)["from"] == "otra@sdq.do"


def test_la_contrasena_VACIA_si_la_borra(db):
    """La otra mitad: si MASK y "" hicieran lo mismo, no habría forma de quitar una llave
    comprometida sin tocar la base."""
    service.set_smtp_config(db, host="smtp.resend.com", password="re_secreta")
    service.update_settings(db, SettingsIn(smtp=SmtpIn(password="")))
    assert service.get_smtp_config(db)["password"] == ""


def test_el_gate_del_canal_de_ALERTAS_lee_el_mismo_llavero(db, monkeypatch):
    """El punto de todo esto. Si el gate mirara el entorno y la pantalla escribiera en el
    llavero, el admin configuraría el correo y `email` seguiría sin ofrecerse."""
    from shared.alerts import service as alertas

    monkeypatch.setattr(app_settings, "SMTP_HOST", "")
    assert "email" not in alertas.canales_disponibles(db)

    service.set_smtp_config(db, host="smtp.resend.com", remitente="alertas@sdq.do")
    assert "email" in alertas.canales_disponibles(db)
    assert "email" not in alertas.canales_no_configurados(db)


def test_guardar_INVALIDA_la_cache_del_emisor(db, monkeypatch):
    """Sin la invalidación, el emisor serviría su copia vieja durante el TTL — o sea que el
    botón «enviar prueba» diría «no hay canal» justo después de configurarlo."""
    monkeypatch.setattr(app_settings, "SMTP_HOST", "")
    mail.invalidar_cache()
    assert mail.configurado() is False          # sin db: usa la caché de proceso
    service.set_smtp_config(db, host="smtp.resend.com")
    # La caché quedó invalidada; la relectura sin db abre su propia sesión (otra base en este
    # test), así que lo que se comprueba es que la memoria NO sobrevivió al guardado.
    assert mail._cache is None


def test_un_llavero_ILEGIBLE_degrada_al_entorno_y_no_tumba_nada(db, monkeypatch):
    """El gate del canal vive dentro del endpoint de alertas. Si una tabla ausente —un
    despliegue cuya migración no corrió— hiciera estallar la lectura, «no sé si hay correo»
    se convertiría en «la watchlist no responde»."""
    monkeypatch.setattr(app_settings, "SMTP_HOST", "smtp.entorno.do")

    def _explota(_db):
        raise RuntimeError("no such table: app_setting")

    monkeypatch.setattr(mail, "_leer_llavero", _explota)
    assert mail.configurado(db) is True          # cayó al entorno, no levantó
    assert mail.diagnostico(db)["host"] == "smtp.entorno.do"


def test_probar_smtp_devuelve_el_MOTIVO_cuando_falla(db, monkeypatch):
    """Un «no se pudo» sin motivo obliga a adivinar entre llave mal copiada, puerto bloqueado
    y remitente sin verificar. El motivo ES el producto de la prueba."""
    service.set_smtp_config(db, host="smtp.invalido.local", remitente="alertas@sdq.do")
    monkeypatch.setattr(mail, "enviar_o_motivo",
                        lambda *a, **k: (False, "Authentication failed"))
    r = service.probar_smtp(db, "ricardo@sdq.do")
    assert r["status"] == "error"
    assert "Authentication failed" in r["detail"]


def test_probar_smtp_sin_host_lo_dice_en_castellano(db, monkeypatch):
    monkeypatch.setattr(app_settings, "SMTP_HOST", "")
    service.set_smtp_config(db, host="")
    r = service.probar_smtp(db, "ricardo@sdq.do")
    assert r["status"] == "error"
    assert "servidor" in r["detail"].lower()
