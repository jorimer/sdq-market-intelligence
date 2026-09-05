"""Una fuente detrás de un WAF se declara en DOS lados, o el proxy la rechaza.

**El defecto que lo obligó.** Con la credencial de la CMF cargada, el proxy configurado y el
código del backend ya arreglado, «Probar conexión» seguía fallando: el Worker devolvía 403
porque `api.cmfchile.cl` no estaba en su lista de destinos permitidos. Un 403 que **no viene
del emisor** y que no se distingue de uno suyo si no se mira la cabecera de reenvío.

Cada lado, por separado, estaba bien. Lo que faltaba era el cruce, y hasta hoy no se podía
comprobar: el fuente del Worker vivía en OTRO repositorio, el de la aplicación predecesora
donde nació el banking score. Ahora vive en `infrastructure/cloudflare-worker-proxy/` y los
dos lados se pueden leer juntos.

La regla: si `KNOWN_PROVIDERS` declara `needs_proxy: True`, el host de su `baseUrl` tiene que
estar en `ALLOWED_TARGET_HOSTS`. Sin esto, agregar la próxima fuente detrás de un WAF vuelve a
costar el mismo día de diagnóstico, porque el síntoma —403— acusa al emisor equivocado.
"""
import pathlib
import re
from urllib.parse import urlparse

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]
WORKER = RAIZ / "infrastructure" / "cloudflare-worker-proxy" / "worker.js"


def _sin_comentarios(js: str) -> str:
    """Saca comentarios de línea y de bloque.

    Hace falta porque dentro del propio arreglo hay comentarios que explican por qué está
    cada host, y un barrido de literales que no los descarte leería su prosa como si fueran
    destinos permitidos.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", js)


def hosts_del_worker(js: str) -> set:
    """Los destinos que el Worker acepta reenviar, leídos de `ALLOWED_TARGET_HOSTS`.

    Se recorta el arreglo por su corchete de cierre y recién ahí se extraen los literales:
    barrer el archivo entero traería todos los strings del Worker, y el guard pasaría en
    verde por contener de más en vez de por contener lo correcto.
    """
    m = re.search(r"ALLOWED_TARGET_HOSTS\s*=\s*\[", js)
    if not m:
        raise AssertionError("no se encontró ALLOWED_TARGET_HOSTS en el Worker")
    resto = js[m.end():]
    fin = resto.index("]")
    return set(re.findall(r'"([^"]+)"', _sin_comentarios(resto[:fin])))


def fuentes_que_declaran_waf() -> list:
    from shared.settings.service import KNOWN_PROVIDERS

    return [s for s in KNOWN_PROVIDERS if s.get("needs_proxy")]


def test_el_worker_esta_en_ESTE_repo():
    """Si vuelve a mudarse, el guard se queda mudo y hay que enterarse acá, no en producción."""
    assert WORKER.is_file(), (
        f"no está {WORKER}: sin el fuente del Worker, el cruce entre el catálogo y la lista "
        "de destinos no se puede comprobar y la próxima fuente detrás de un WAF vuelve a "
        "fallar con un 403 que acusa al emisor equivocado")


@pytest.mark.parametrize("fuente", fuentes_que_declaran_waf(),
                         ids=lambda s: str(s["provider"]))
def test_toda_fuente_detras_de_un_WAF_esta_en_la_lista_del_worker(fuente):
    permitidos = hosts_del_worker(WORKER.read_text(encoding="utf-8"))
    host = urlparse(str(fuente["baseUrl"])).hostname
    assert host, f"{fuente['provider']} declara needs_proxy pero su baseUrl no tiene host"
    assert host in permitidos, (
        f"{fuente['provider']} va por el proxy pero '{host}' no está en ALLOWED_TARGET_HOSTS "
        f"({sorted(permitidos)}). El Worker devolvería 403 SIN cabecera de reenvío: un "
        "rechazo del proxy que se lee como si lo hubiera dado el emisor. Agregalo en "
        "infrastructure/cloudflare-worker-proxy/worker.js Y desplegalo (wrangler deploy): "
        "commitearlo no lo despliega")


def test_el_barrido_ENCUENTRA_fuentes():
    """Un `parametrize` vacío sale SKIPPED, no FAILED: el guard de arriba pasaría sin mirar."""
    fuentes = fuentes_que_declaran_waf()
    assert len(fuentes) >= 2, (
        f"solo se detectaron {[s['provider'] for s in fuentes]}: se esperaban al menos el SIB "
        "y la CMF. El lector de KNOWN_PROVIDERS se quedó ciego")


def test_el_lector_del_worker_ENCUENTRA_hosts():
    """Contraprueba del parser: si deja de reconocer el arreglo, el cruce pasa vacío."""
    permitidos = hosts_del_worker(WORKER.read_text(encoding="utf-8"))
    assert "apis.sb.gob.do" in permitidos, (
        f"el lector devolvió {permitidos}: no está reconociendo ALLOWED_TARGET_HOSTS")


def test_el_lector_NO_confunde_un_comentario_con_un_host():
    """Dentro del arreglo hay prosa explicando cada host. No puede colarse como destino."""
    js = '''
      const ALLOWED_TARGET_HOSTS = [
        "apis.sb.gob.do",
        // ojo: "no.soy.un.host" vive en un comentario
        /* tampoco "yo.tampoco.soy" */
        "api.cmfchile.cl",
      ];
      const OTRA_COSA = ["no.pertenezco.a.la.lista"];
    '''
    assert hosts_del_worker(js) == {"apis.sb.gob.do", "api.cmfchile.cl"}
