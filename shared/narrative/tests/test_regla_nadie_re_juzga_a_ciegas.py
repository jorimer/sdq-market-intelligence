"""A un texto lo juzga quien tiene el contexto con el que se escribió. Nadie más.

**El defecto que esto cierra costó tres informes vetados y dos arreglos que no arreglaron
nada.** El guard corría DOS veces con contextos distintos:

    el MOTOR, al generar ....... el contexto de la sección — 133 números, CON `razones`
    la SUPERFICIE, al entregar .. `snapshot.payload`        —  55 números, SIN `razones`

Las relaciones (`razones`, `comparaciones`) se computan DENTRO del constructor de contexto de
la sección; no existen en el snapshot. Así, la razón 1,32 servida —que el modelo escribió como
«132 % del promedio del sistema»— pasaba el chequeo del motor y era marcada por el
ensamblador, que nunca vio ese número. La ruta del PDF era peor todavía: juzgaba contra
`scoring_result`, que ni siquiera trae los promedios del sistema.

Servir la cifra en el contexto (#947) y enseñarle al guard la familia de formas (#949)
arreglaron el lado que ya funcionaba. Por eso la cura no es otra regla del guard: es que la
superficie deje de juzgar y se ENTERE, por `shared/narrative/hallazgos_pendientes`.

Esta regla es estructural porque la lección escrita ya falló siete veces en este repo: nada
impide que alguien vuelva a llamar a los chequeos deterministas desde una ruta de entrega
—«total, es gratis»— y reintroduzca el defecto entero.

**Qué queda afuera del barrido, a propósito:** las superficies de ENTREGA de narrativa. No el
motor (que es quien debe juzgar), no `numeric_guard` (que los define), no los tests.
"""
import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: Las rutas que ENTREGAN informes narrados. Si aparece otra, va acá.
SUPERFICIES = (
    RAIZ / "shared" / "products" / "assembler.py",
    RAIZ / "shared" / "products" / "router.py",
    RAIZ / "modules" / "banking_score" / "api" / "router_reports.py",
)

#: Los chequeos que SOLO pueden correrse con el contexto que produjo el texto.
JUICIOS = {
    "deterministic_uncited_figures",
    "deterministic_unsupported",
    "deterministic_direction_errors",
    "deterministic_ratio_errors",
    "secciones_con_cifra_sin_respaldo",
    "verify_figures",
}


def _llamadas(arbol: ast.AST) -> set:
    nombres = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                nombres.add(f.id)
            elif isinstance(f, ast.Attribute):
                nombres.add(f.attr)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            nombres.update(a.asname or a.name for a in n.names)
    return nombres


def test_las_superficies_existen():
    """Prueba negativa del barrido: un rename dejaría este test verde sin mirar nada."""
    faltan = [str(s) for s in SUPERFICIES if not s.exists()]
    assert not faltan, f"el barrido apunta a archivos que ya no existen: {faltan}"


def test_ninguna_superficie_de_entrega_vuelve_a_juzgar_el_texto():
    ofensores = {}
    for s in SUPERFICIES:
        usados = _llamadas(ast.parse(s.read_text(), filename=str(s))) & JUICIOS
        if usados:
            ofensores[s.name] = sorted(usados)
    assert not ofensores, (
        f"Estas superficies de entrega vuelven a juzgar el texto: {ofensores}. No tienen el "
        "contexto con el que se generó —tienen el snapshot— y juzgar con él veta prosa "
        "CORRECTA: pasó tres veces con cifras reales. El hallazgo llega por "
        "`shared/narrative/hallazgos_pendientes`, desde el motor.")


def test_la_funcion_del_juicio_ciego_no_volvio():
    """`secciones_con_cifra_sin_respaldo` se eliminó: solo podía usarse mal."""
    motor = (RAIZ / "shared" / "narrative" / "claude_engine.py").read_text()
    assert "def secciones_con_cifra_sin_respaldo" not in motor, (
        "volvió la función que re-juzgaba en la superficie. El hallazgo viaja por canal.")


def test_el_motor_SI_juzga():
    """El contrapeso. Sin él, esta regla se satisface borrando el guard entero."""
    motor = ast.parse((RAIZ / "shared" / "narrative" / "claude_engine.py").read_text())
    usados = _llamadas(motor) & JUICIOS
    assert {"deterministic_uncited_figures", "deterministic_direction_errors"} <= usados, (
        f"el motor dejó de correr los chequeos deterministas: {sorted(usados)}")
