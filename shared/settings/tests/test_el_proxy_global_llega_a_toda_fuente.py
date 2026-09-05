"""El proxy global tiene que llegar a la fuente, y una cadena vacía no lo cancela.

**El defecto que lo obligó.** Con la credencial de la CMF cargada y el proxy de Cloudflare
configurado, «Probar conexión» respondía *«Un WAF bloqueó la petición antes de llegar a la
CMF (IP vista por el WAF: 152.55.177.181)»*: la petición salía DIRECTA desde el servidor y el
WAF del emisor la cortaba. El proxy estaba puesto y no se usaba.

La cadena es de cuatro eslabones y ninguno falla solo:

1. ``proxy_url`` es ``NOT NULL DEFAULT ''`` — toda fila nace con cadena vacía, nunca ``NULL``.
2. ``SectorApiOut.proxyUrl`` la publica tal cual, así que la API devuelve ``""``.
3. El editor por fuente **ya no tiene campo de proxy** —el proxy pasó a ser global— pero el
   formulario igual arrastra ``proxyUrl`` de la fila y «Probar conexión» manda el formulario
   entero. El payload viaja con ``proxyUrl: ""``.
4. ``test_connection`` leía ``payload.proxyUrl is not None`` como «el operador especificó un
   override», y ``""`` **no es** ``None``: el proxy global no se consultaba nunca.

Un ``""`` no puede significar «probá sin proxy», porque no hay ninguna casilla en la interfaz
que diga eso. Solo puede significar «esta fila no tiene proxy propio».

Y el SIB no lo destapó porque funciona por una HERENCIA: su fila conserva el ``proxy_url`` de
antes de que el proxy pasara a global (``_migrate_proxy_to_global`` lo copia a la
configuración global pero no lo borra de la fila). Cualquier fuente nueva detrás de un WAF
pisaba esta misma mina.
"""
import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.settings import service
from shared.settings.models import AppSetting, SectorApiConfig
from shared.settings.schemas import (
    SectorApiIn,
    SettingsIn,
    TestConnectionIn as ConnTestIn,
)

PROXY = "https://worker-global.workers.dev"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__, SectorApiConfig.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _Resp:
    """Lo mínimo que `_test_cmf_connection` le pide a una respuesta."""

    def __init__(self, status_code=200, text='{"UFs": []}', headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)


@pytest.fixture()
def espia(monkeypatch):
    """Registra por dónde salió la petición: el Worker (post) o el emisor (get)."""
    visto = {}

    def _post(url, **kw):
        visto["via"], visto["url"] = "proxy", url
        # El Worker marca todo lo que REENVÍA; sin la marca, el código lo lee como rechazo.
        return _Resp(headers={"X-Proxy-Status": "200"})

    def _get(url, **kw):
        visto["via"], visto["url"] = "directo", url
        return _Resp()

    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setattr(httpx, "get", _get)
    return visto


def _con_proxy_global_y_fuente_sin_proxy_propio(db):
    service.update_settings(db, SettingsIn(
        cloudflareProxyUrl=PROXY,
        cloudflareProxySecret="secreto-del-worker",
        sectorApis=[SectorApiIn(provider="cmf_chile", sector="banking", country="CL",
                                apiKey="clave-de-la-cmf", baseUrl="https://api.cmfchile.cl")],
    ))


def test_la_fila_NACE_con_cadena_vacia(db):
    """Si esto deja de ser cierto, el test de abajo dejó de reproducir el caso reportado.

    Es la premisa del defecto: la columna es ``NOT NULL DEFAULT ''``, así que el override
    que llega del formulario es ``""`` y no ``None``. Con ``None`` el código viejo ya
    funcionaba —por eso el SIB nunca lo destapó— y el guard quedaría vigilando el aire.
    """
    _con_proxy_global_y_fuente_sin_proxy_propio(db)
    fila = next(a for a in service.get_settings(db).sectorApis if a.provider == "cmf_chile")
    assert fila.proxyUrl == "", (
        f"la fila devolvió proxyUrl={fila.proxyUrl!r}: el guard de abajo ya no reproduce "
        "el payload que manda la interfaz")


def test_una_cadena_vacia_NO_cancela_el_proxy_global(db, espia):
    """El payload tal como lo arma la interfaz: arrastra el `proxyUrl` vacío de la fila."""
    _con_proxy_global_y_fuente_sin_proxy_propio(db)
    fila = next(a for a in service.get_settings(db).sectorApis if a.provider == "cmf_chile")

    service.test_connection(db, ConnTestIn(provider="cmf_chile", proxyUrl=fila.proxyUrl))

    assert espia.get("via") == "proxy", (
        f"la petición salió {espia.get('via')!r} hacia {espia.get('url')!r}: el proxy global "
        "estaba configurado y una cadena vacía lo canceló. Es lo que hacía que el WAF de la "
        "CMF cortara la prueba y el operador viera un bloqueo con la credencial correcta")
    assert espia["url"].startswith(PROXY)


def test_un_secreto_vacio_TAMPOCO_lo_cancela(db, espia):
    """La misma trampa del otro lado: hoy zafa porque el formulario no manda `proxySecret`."""
    _con_proxy_global_y_fuente_sin_proxy_propio(db)

    service.test_connection(db, ConnTestIn(provider="cmf_chile", proxyUrl="",
                                                 proxySecret=""))

    assert espia.get("via") == "proxy", (
        "un secreto vacío se leyó como «probá sin proxy», y no hay casilla en la interfaz "
        "que signifique eso")


def test_un_override_CON_contenido_sigue_ganando(db, espia):
    """El arreglo no puede borrar la semántica de override: lo que se escribe, manda."""
    _con_proxy_global_y_fuente_sin_proxy_propio(db)
    otro = "https://worker-de-prueba.workers.dev"

    service.test_connection(db, ConnTestIn(provider="cmf_chile", proxyUrl=otro,
                                                 proxySecret="otro-secreto"))

    assert espia["url"].startswith(otro), (
        f"salió por {espia['url']!r}: un override explícito dejó de tener efecto")


def test_la_CMF_esta_en_el_catalogo_y_declara_su_WAF(db):
    """Que esté detrás de un WAF no se deduce de ninguna parte: hay que declararlo.

    El valor práctico es `_known_base_url`: sin entrada en el catálogo, una fila sin URL
    base guardada hace fallar la prueba culpando a la credencial.
    """
    from shared.settings.service import KNOWN_PROVIDERS, _known_base_url

    cmf = next((p for p in KNOWN_PROVIDERS if p["provider"] == "cmf_chile"), None)
    assert cmf is not None, "la CMF no está en el catálogo"
    assert cmf["needs_proxy"] is True, "la CMF está detrás de un WAF: medido, no supuesto"
    assert _known_base_url("cmf_chile") == "https://api.cmfchile.cl"


def test_el_catalogo_no_pisa_la_fila_que_creo_el_operador(db):
    """En producción la fila `cmf_chile` ya existe, creada a mano. El sembrador no la toca."""
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(
        provider="cmf_chile", sector="banking", country="CL",
        apiKey="la-clave-del-operador", baseUrl="https://api.cmfchile.cl", enabled=True,
    )]))
    service.ensure_known_sources(db)
    filas = [a for a in service.get_settings(db).sectorApis if a.provider == "cmf_chile"]
    assert len(filas) == 1, "el catálogo duplicó la fuente que el operador ya tenía"
    assert filas[0].enabled is True and filas[0].apiKeySet is True, (
        "el sembrador pisó la fila existente y borró la credencial")
