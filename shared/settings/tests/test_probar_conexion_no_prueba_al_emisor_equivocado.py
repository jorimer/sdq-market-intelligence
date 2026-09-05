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
    assert '"apikey"' in fuente and "Ocp-Apim-Subscription-Key" not in fuente
