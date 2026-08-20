"""REGLA ESTRUCTURAL: un ratio con el PATRIMONIO en el denominador declara qué hace si es ≤ 0.

**El caso, tres veces en tres motores.** Cuando el patrimonio no es positivo, un ratio que lo
lleva en el denominador deja de significar lo que su nombre dice — y el defecto no se ve,
porque el número sigue saliendo:

- **`cambiaria._apalancamiento`** (encontrado en producción el 2026-08-20). `pasivos /
  patrimonio` con patrimonio negativo da un número negativo, y como la escala del
  apalancamiento es INVERTIDA, el clamp lo manda al techo: Placidoiv publicaba **100 sobre
  100** con patrimonio de −1.459 % de sus activos. El peor estado entraba por la puerta del
  mejor.
- **`fiduciaria._apalancamiento`**: el mismo, en el módulo espejo.
- **`engine.calc_roe`**: `utilidad / patrimonio_promedio` con los dos negativos da un ROE
  POSITIVO — el banco insolvente que pierde plata aparece rentable. Lo encontró este test
  antes de existir, al enumerar los denominadores.

Y el motor de bancos **ya tenía** la cura para los ratios de capital desde `d4c3806`
(2026-06-22), cuando el mismo defecto producía un swing de 30 puntos en BPD. Ninguno de los
submodelos escritos después la copió.

**Por qué un test y no una lección.** Este repo ya acumuló varias instancias de «un guard
existe en un motor y falta en el otro», y la lección escrita no alcanzó ninguna de las veces.
Lo que funciona es leer el código con `ast` y exigir la regla o una excepción declarada.

**La regla.** Toda función de `modules/banking_score/scoring/` que divida por el patrimonio
tiene que nombrar el guard (`patrimonio_es_positivo`) en su propio cuerpo — o estar en
`GUARD_EN_OTRO_LADO` diciendo dónde vive y por qué ahí.

**Qué queda fuera, y por qué** (declarado, no omitido): los ratios con el patrimonio en el
NUMERADOR (`capitalizacion`, `patrimonio_activos`, `solvencia`). Ahí un patrimonio negativo
produce un ratio negativo que las curvas ya mandan al piso, que es la lectura correcta: el
indicador dice «mal» y significa «mal».
"""
import ast
import pathlib

SCORING = pathlib.Path(__file__).resolve().parents[1] / "scoring"

#: Cómo se llama, en este repo, la función que divide declarando un default seguro.
_DIVISION = "_safe_div"

#: El guard compartido que la regla exige nombrar.
GUARD = "patrimonio_es_positivo"

#: Funciones que dividen por patrimonio y cuyo guard vive en OTRO lado, con el motivo. Entrar
#: acá se defiende en revisión; dividir por patrimonio y no estar ni guardado ni acá, un test
#: rojo.
GUARD_EN_OTRO_LADO = {
    "engine.calc_roe": (
        "el guard vive en `engine._indicator_available`, que declara `roe` NO DISPONIBLE "
        "cuando `patrimonio_promedio` no es positivo. Tiene que estar ahí y no en el "
        "indicador: `calculate_all_indicators` sobrescribe el `available` que devuelva la "
        "función, así que un guard adentro no llegaría a la salida."
    ),
}


def _denominadores_de_patrimonio(func: ast.FunctionDef) -> bool:
    """True si la función divide por algo que se llama patrimonio.

    Mira el SEGUNDO argumento de `_safe_div` —el denominador— y no el primero: los ratios con
    el patrimonio en el numerador (capitalización, solvencia) no tienen este problema, y
    barrerlos a todos por igual haría que la regla pida guards donde no hacen falta.
    """
    for nodo in ast.walk(func):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == _DIVISION and len(nodo.args) >= 2):
            continue
        if "patrimonio" in ast.dump(nodo.args[1]).lower():
            return True
        # El denominador puede venir por una variable local: se resuelve mirando si esa
        # variable se asignó desde algo que menciona patrimonio en la misma función.
        if isinstance(nodo.args[1], ast.Name):
            objetivo = nodo.args[1].id
            for asig in ast.walk(func):
                if (isinstance(asig, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == objetivo
                                for t in asig.targets)
                        and "patrimonio" in ast.dump(asig.value).lower()):
                    return True
    return False


def _funciones_que_dividen_por_patrimonio():
    """``[(modulo.funcion, cuerpo_fuente)]`` de todo `scoring/`."""
    salida = []
    for ruta in sorted(SCORING.glob("*.py")):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef) and _denominadores_de_patrimonio(nodo):
                salida.append((f"{ruta.stem}.{nodo.name}", ast.dump(nodo)))
    return salida


# ── La regla ──────────────────────────────────────────────────────

def test_todo_ratio_dividido_por_patrimonio_declara_que_hace_si_es_negativo():
    desprotegidas = []
    for nombre, cuerpo in _funciones_que_dividen_por_patrimonio():
        if GUARD in cuerpo or nombre in GUARD_EN_OTRO_LADO:
            continue
        desprotegidas.append(nombre)
    assert not desprotegidas, (
        f"Estas funciones dividen por el patrimonio sin declarar qué hacen cuando no es "
        f"positivo: {desprotegidas}. Con patrimonio negativo el ratio cambia de signo o de "
        f"significado, y el número sigue saliendo — que es lo que lo vuelve invisible. Usá "
        f"`{GUARD}` o declarala en `GUARD_EN_OTRO_LADO` con el motivo."
    )


def test_el_glob_alcanza_a_los_tres_motores():
    """Un glob que no ve un motor da verde sin proteger nada.

    Los tres submodelos tienen ratios divididos por patrimonio; si alguno deja de aparecer en
    esta lista, o se renombró o el detector dejó de reconocer su forma — y en los dos casos la
    regla dejó de aplicarse ahí sin que nadie se entere.
    """
    modulos = {n.split(".")[0] for n, _ in _funciones_que_dividen_por_patrimonio()}
    assert {"cambiaria", "fiduciaria", "engine"} <= modulos, modulos


def test_las_excepciones_declaradas_siguen_existiendo():
    """Un renombre no puede dejar una excepción huérfana protegiendo a nadie."""
    presentes = {n for n, _ in _funciones_que_dividen_por_patrimonio()}
    fantasmas = [n for n in GUARD_EN_OTRO_LADO if n not in presentes]
    assert not fantasmas, (
        f"Declaradas en `GUARD_EN_OTRO_LADO` pero ya no dividen por patrimonio: {fantasmas}. "
        "Sacalas de la lista o corregí el nombre."
    )


def test_el_numerador_no_cuenta():
    """La regla pide guard donde hace falta, no en todas partes.

    `capitalizacion` y `patrimonio_activos` llevan el patrimonio ARRIBA: con patrimonio
    negativo dan un ratio negativo que las curvas mandan al piso, que es la lectura correcta.
    Pedirles guard sería ruido, y el ruido es cómo un guard se termina desactivando.
    """
    nombres = {n for n, _ in _funciones_que_dividen_por_patrimonio()}
    assert "cambiaria._capitalizacion" not in nombres
    assert "engine.calc_patrimonio_activos" not in nombres
    assert "engine.calc_solvencia" not in nombres
