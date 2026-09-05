"""Probar una fuente prueba ESA fuente, y si no se puede, lo dice.

**El defecto que lo obligó.** Al cargar la credencial de la CMF de Chile, el botón «Probar
conexión» devolvió «✕ HTTP 500 (SIB)». La clave estaba perfecta: `test_connection` tiene
ramas para los proveedores con contrato propio (BCRD, JurisAI) y **todo lo demás cae al
camino del SIB**, que arma `…/indicadores/principales` con un header de suscripción de Azure
APIM. Contra `api.cmfchile.cl` eso es una ruta inexistente.

Lo caro no fue el 500: fue la ETIQUETA. Un error que dice «SIB» sobre una prueba a la CMF
manda a revisar la credencial —o a sospechar del emisor— cuando lo que estaba mal era contra
quién se probaba. Un mensaje que nombra al emisor equivocado es peor que uno genérico.
"""
import ast
import inspect
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[3]
SERVICE = RAIZ / "shared" / "settings" / "service.py"


def _ramas_declaradas() -> set:
    """Los proveedores que tienen su propia rama de prueba en `test_connection`."""
    from shared.settings import service

    arbol = ast.parse(inspect.getsource(service.test_connection).lstrip())
    fuera = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Compare):
            continue
        izq = nodo.left
        if (isinstance(izq, ast.Attribute) and izq.attr == "provider"
                and nodo.comparators and isinstance(nodo.comparators[0], ast.Constant)):
            fuera.add(nodo.comparators[0].value)
    return fuera


def test_la_CMF_tiene_su_propia_rama():
    """Su contrato es otro: la credencial va en la QUERY STRING, no en un header de Azure."""
    assert "cmf_chile" in _ramas_declaradas(), (
        "sin su rama, la CMF se prueba con las rutas del SIB y el operador ve «HTTP 500 "
        "(SIB)» sobre una credencial que puede estar perfecta")


def test_el_barrido_ENCUENTRA_las_ramas():
    """Si el lector deja de reconocer los `if`, el test de arriba pasa sin mirar nada."""
    ramas = _ramas_declaradas()
    assert len(ramas) >= 3, f"solo se detectaron {ramas}: el barrido se quedó ciego"


def test_el_camino_por_defecto_NO_se_atribuye_al_SIB():
    """El fallback usa el contrato del SIB, pero solo puede FIRMAR como SIB cuando lo es.

    Para cualquier otro proveedor el mensaje tiene que decir que se probó con un contrato
    ajeno, que es la información que le falta a quien mira la pantalla.
    """
    fuente = SERVICE.read_text(encoding="utf-8")
    i = fuente.index('origin = "proxy Cloudflare"')
    bloque = fuente[i:i + 700]
    assert 'payload.provider == "sb_do"' in bloque, (
        "la etiqueta «SIB» se aplica sin comprobar que el proveedor SEA el SIB")
    assert "contrato del SIB" in bloque, (
        "un proveedor sin rama propia tiene que ver que se lo probó con un contrato ajeno")


def test_la_prueba_de_la_CMF_no_gasta_la_cuota_en_un_reporte_pesado():
    """La cuota es de 100 llamadas DIARIAS: la prueba consulta la UF, que existe siempre.

    Un cuadro de adecuación de capital de un mes concreto puede no estar publicado todavía
    y haría fallar una credencial que está bien.
    """
    from shared.settings import service

    fuente = inspect.getsource(service._test_cmf_connection)
    assert "recursos_api/uf" in fuente
    assert "adecuacion" not in fuente
    # Y CON período: la ruta pelada devuelve 500 cuando la credencial es válida, porque el
    # emisor no documenta ninguna forma de `/uf` sin fecha. El síntoma engaña — el 500
    # aparece justo cuando la clave está bien.
    assert "recursos_api/uf/2024/01" in fuente
    # Y la credencial viaja como parámetro, no como header de suscripción.
    assert "apikey=" in fuente and "Ocp-Apim-Subscription-Key" not in fuente


class TestElDiagnosticoDiceLoQueElEmisorDijo:
    """Un «HTTP 500» pelado mandó a revisar tres veces una credencial que estaba bien.

    Lo que faltaba no era otro intento: era el CUERPO de la respuesta. La CMF publica sus
    propios códigos —421 «API key no valida», 420 cuota superada, 422 no suministrada— y el
    WAF que tiene delante devuelve una página «Web Page Blocked!» con la IP que vio. Todo
    eso estaba llegando y se descartaba para imprimir el número de HTTP.
    """

    def test_distingue_el_bloqueo_del_WAF_de_un_rechazo_de_la_CMF(self):
        """No es lo mismo: si bloquea el WAF, la credencial NI SIQUIERA se evaluó."""
        import inspect

        from shared.settings import service

        fuente = inspect.getsource(service._test_cmf_connection)
        assert "Web Page Blocked" in fuente
        # La frase vive en una CONSTANTE justamente para que se la pueda buscar: incrustada
        # en la llamada se parte por ancho de línea y deja de existir en el fuente.
        assert "no se llegó a evaluar" in service.MSG_WAF_BLOQUEO
        assert "MSG_WAF_BLOQUEO" in fuente

    def test_transcribe_el_mensaje_del_emisor(self):
        import inspect

        from shared.settings import service

        fuente = inspect.getsource(service._test_cmf_connection)
        assert '"Mensaje"' in fuente, (
            "la CMF explica el rechazo en el cuerpo; imprimir solo el HTTP tira esa "
            "información justo cuando hace falta")

    def test_usa_el_proxy_cuando_esta_configurado(self):
        """La CMF también está detrás de un WAF que bloquea IPs de datacenter — medido, no
        supuesto: desde escritorio responde 421/422 y desde el datacenter, 500 con bloqueo."""
        import inspect

        from shared.settings import service

        fuente = inspect.getsource(service._test_cmf_connection)
        assert "use_proxy" in fuente and "X-Proxy-Secret" in fuente


class TestLaCredencialNoSeFiltraNiSeEsconde:
    def test_la_apikey_se_redacta_antes_de_mostrarse(self):
        """Los cuerpos de error repiten la URL consultada, y esa URL lleva la clave."""
        from shared.settings.service import _redactar

        salido = _redactar("URL: api.cmfchile.cl/x?apikey=abc123secreto&formato=json")
        assert "abc123secreto" not in salido
        assert "REDACTADA" in salido

    def test_un_error_sin_JSON_muestra_el_cuerpo_igual(self):
        """Tres vueltas se perdieron mostrando solo el número de HTTP mientras la respuesta
        traía la explicación. Un diagnóstico que descarta la evidencia no es diagnóstico."""
        import inspect

        from shared.settings import service

        fuente = inspect.getsource(service._test_cmf_connection)
        assert "_redactar(cuerpo_txt)" in fuente

    def test_distingue_al_proxy_que_NO_reenvio(self):
        """El Worker marca lo que reenvía con `X-Proxy-Status`: sin esa marca, un error es
        del proxy y la petición nunca llegó al emisor."""
        import inspect

        from shared.settings import service

        fuente = inspect.getsource(service._test_cmf_connection)
        assert "_has_proxy_relay" in fuente
        assert "api.cmfchile.cl" in service.MSG_PROXY_NO_REENVIO
