"""El lector del frontend lee las claves que el backend REALMENTE emite.

**Este test existe porque me equivoqué exactamente acá.** Al escribir el lector de la vista
in-app supuse que la atribución venía «por componente» —``{componente, aportes: {ventana: n}}``—
y la forma real es la inversa: **por ventana**, con los aportes anidados adentro. El lector
compilaba, tipaba y devolvía una lista vacía en silencio: la tabla simplemente no habría
aparecido, que es el modo de falla de este repo («un motor sin su entrada no falla: DESAPARECE»).

Un test de frontend con una fixture escrita a mano NO lo habría atrapado: la fixture habría
tenido la forma equivocada, igual que el lector, y habría pasado en verde. Hace falta cruzar
contra la salida REAL de la función.

**Qué queda afuera:** la ruta del PDF, que consume la misma función desde Python y por eso no
puede desincronizarse por forma. El riesgo es exclusivo de la superficie que reimplementa el
acceso en otro lenguaje.
"""
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[3]
API_TS = RAIZ / "frontend" / "src" / "modules" / "platform" / "api.ts"


def _salida_real():
    """Lo que `aportes_al_cambio` emite de verdad, con una trayectoria de dos componentes."""
    from shared.narrative.derived import aportes_al_cambio
    trayectoria = {
        "solidez": [{"score": 70}, {"score": 72}, {"score": 74}, {"score": 75}, {"score": 80}],
        "calidad": [{"score": 60}, {"score": 58}, {"score": 57}, {"score": 56}, {"score": 55}],
    }
    return aportes_al_cambio(trayectoria, {"solidez": 0.38, "calidad": 0.34})


def _lector_ts() -> str:
    """El cuerpo de `reportAportes`, que es quien lee el payload en la vista in-app."""
    m = re.search(r"export function reportAportes\(.*?\n\}", API_TS.read_text(), re.S)
    assert m, "no se encontró reportAportes en el frontend — ¿se renombró?"
    return m.group(0)


def test_la_salida_real_tiene_la_forma_que_el_lector_espera():
    filas = _salida_real()
    assert filas, "la función no emitió nada: el test perdió su objeto"
    fila = filas[0]
    assert "ventana" in fila and isinstance(fila.get("aportes"), list), (
        f"la forma cambió: {sorted(fila)}. El lector del frontend espera filas POR VENTANA "
        "con los aportes anidados; actualizalo o esta tabla desaparecerá de la vista in-app "
        "sin ningún error.")


def test_el_lector_del_frontend_ACCEDE_a_las_claves_que_existen():
    """Se busca el ACCESO (`f.ventana`), no la palabra suelta.

    Buscar la palabra no tiene dientes: «ventana» aparece en el tipo, en los comentarios y en
    el nombre de la interfaz, así que un lector con la forma equivocada pasaba igual. Lo
    comprobé sustituyendo el lector por mi versión errónea — y el test seguía en verde.
    """
    lector = _lector_ts()
    fila = _salida_real()[0]
    aporte = fila["aportes"][0]
    for clave in ("ventana", "cambio_total", "aportes"):
        assert clave in fila, f"el backend dejó de emitir `{clave}`"
        assert re.search(rf"\bf\.{clave}\b", lector), (
            f"el lector del frontend no accede a `f.{clave}` — esa columna llegará vacía o la "
            "tabla entera desaparecerá sin ningún error")
    for clave in ("componente", "aporte_al_cambio"):
        assert clave in aporte, f"el backend dejó de emitir `{clave}` por aporte"
        assert re.search(rf"\ba\.{clave}\b", lector), (
            f"el lector del frontend no accede a `a.{clave}`")


def test_el_lector_no_lee_claves_inventadas():
    """El contrapeso. Sin él, la regla se satisface leyendo todo y no leyendo nada."""
    lector = _lector_ts()
    fila = _salida_real()[0]
    conocidas = set(fila) | set(fila["aportes"][0]) | {
        # nombres del propio lector, no del payload
        "report", "payload", "scoring_result", "aportes_al_cambio", "filas", "f", "a",
        "Array", "isArray", "number", "string", "typeof", "return", "export", "function",
        "const", "if", "map", "filter", "null", "VentanaDeCambio",
    }
    citadas = set(re.findall(r"f\.([a-z_]+)", lector)) | set(re.findall(r"a\.([a-z_]+)", lector))
    inventadas = sorted(citadas - conocidas)
    assert not inventadas, (
        f"el lector lee claves que el backend no emite: {inventadas} — devolverán `null` "
        "en silencio")
