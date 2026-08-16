"""La prosa que llega al lector no lleva coletillas sobre el método.

Este defecto ya apareció DOS VECES en superficies distintas: primero como «lectura mecánica,
no proyección» en los márgenes de §Alerta Temprana, y después como «(4 variables entran al
cálculo como control estadístico y no admiten lectura causal.)» al cierre de la propensión.
La primera se arregló con un test atado a `_prosa_margenes`; la segunda nació en otro módulo
y ese test no la vio — el patrón conocido de «un guard existe en un motor y falta en el otro».

Por eso el guard es ESTRUCTURAL: lee el código de todos los productores de prosa declarados
y veta el vocabulario, en vez de comprobar una salida concreta de una función concreta.

**Qué se veta y qué no.** Se veta la salvedad sobre el MÉTODO, que le pide al lector que
desconfíe de la frase que acaba de leer. NO se veta declarar el ALCANCE de una cifra —
«(severidad media, fuera del índice)» es obligatorio por doctrina: dice que el dato existe y
que el índice no lo cubre. La diferencia es que el alcance informa sobre el DATO y la coletilla
informa sobre el instrumento.

Dónde vive la información que se saca de la prosa: los controles siguen publicándose en
`explicar()["controles_no_narrables"]` → `controles_sin_lectura_causal`, que es donde cumplen
su función real (impedir que el MODELO narre un control como si fuera una causa).
"""
import ast
import inspect
import textwrap
from typing import Dict, Set, Tuple

from modules.banking_score import early_warning, propension_quiebra

# Funciones cuya salida LEE UN HUMANO en el informe.
PRODUCTORES_DE_PROSA: Dict[object, Tuple[str, ...]] = {
    early_warning: (
        "_prosa_margenes", "format_alerts_text", "_expresar", "_horizonte",
        # los mensajes de las reglas se renderizan como viñetas del informe
        "rule_growth", "rule_funding", "rule_coverage", "rule_morosidad", "rule_solvency",
        "rule_liquidity", "rule_concentration", "rule_morosidad_nivel", "rule_capital_erosion",
    ),
    propension_quiebra: ("prosa", "_situacion", "_frase_valor", "_cifra", "_expresar"),
}

# Funciones que producen texto pero NO para el informe. Cada exclusión lleva su motivo: sin
# eso, la lista se vuelve el agujero por donde vuelve el defecto.
NO_VAN_AL_INFORME: Dict[object, Dict[str, str]] = {
    early_warning: {},
    propension_quiebra: {
        "formato": "volcado diagnóstico de consola: AUC, Brier y coeficientes. Es "
                   "metodológico A PROPÓSITO y no lo lee un cliente.",
        "uso_admitido": "barandilla que se le pasa al MODELO para acotar lo que puede "
                        "afirmar; no se imprime.",
    },
}

COLETILLAS_VETADAS: Tuple[str, ...] = (
    "lectura mecánica", "no proyección", "extrapolación", "meramente",
    "control estadístico", "lectura causal", "no admiten lectura",
    "a título ilustrativo", "con las debidas reservas", "de carácter indicativo",
)

# Vocabulario del INSTRUMENTO que se coló en la prosa del lector. Va aparte de las coletillas
# porque el defecto es distinto: la coletilla pide desconfianza, la jerga no se entiende. Cada
# una salió al informe alguna vez —«tasa base» solo asomaba cuando la entidad se apartaba del
# promedio, que es el caso que más se lee y el que no estaba en la muestra revisada—.
JERGA_DEL_MODELO: Tuple[str, ...] = (
    "tasa base", "log-odds", "logodds", "coeficiente", "odds ratio", "regresión",
    "variable dependiente", "p-valor", "intervalo de confianza", "estandarizad",
)

# Nombres que delatan a un productor de prosa. Si aparece uno nuevo, tiene que declararse
# en una de las dos listas de arriba — es la pregunta «¿qué queda afuera?» hecha test.
PISTAS_DE_PROSA: Tuple[str, ...] = ("prosa", "format", "_expresar", "_frase", "_situacion",
                                    "_cifra", "_horizonte", "rule_", "uso_admitido")


_Func = (ast.FunctionDef, ast.AsyncFunctionDef)


def _funciones(modulo) -> Dict[str, ast.AST]:
    """Todas las funciones del módulo POR NOMBRE, incluidas las anidadas.

    Se resuelve por AST y no con ``getattr`` porque varias de las que escriben prosa viven
    dentro de otra —``_situacion`` está dentro de ``prosa``— y por atributo no existen.
    """
    arbol = ast.parse(textwrap.dedent(inspect.getsource(modulo)))
    return {n.name: n for n in ast.walk(arbol) if isinstance(n, _Func)}


def _literales_sin_docstring(nodo) -> Set[str]:
    """Cadenas escritas dentro de la función, excluyendo su docstring.

    El docstring queda fuera porque ahí SÍ se explica el método —es su lugar—, y vetarlo
    obligaría a documentar la regla sin poder nombrarla.
    """
    cuerpo = list(nodo.body)
    if (cuerpo and isinstance(cuerpo[0], ast.Expr)
            and isinstance(cuerpo[0].value, ast.Constant)
            and isinstance(cuerpo[0].value.value, str)):
        cuerpo = cuerpo[1:]
    out: Set[str] = set()
    for stmt in cuerpo:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                out.add(n.value)
    return out


def _anidadas_en(nodo) -> Set[str]:
    """Nombres de las funciones definidas DENTRO de *nodo* (a cualquier profundidad)."""
    return {n.name for n in ast.walk(nodo) if isinstance(n, _Func) and n is not nodo}


def test_ningun_productor_de_prosa_escribe_una_coletilla_de_metodo():
    ofensas = []
    for modulo, funciones in PRODUCTORES_DE_PROSA.items():
        porNombre = _funciones(modulo)
        faltantes = [n for n in funciones if n not in porNombre]
        assert not faltantes, (
            f"{modulo.__name__}: {faltantes} ya no existen. Un nombre viejo en la lista hace "
            f"que el guard pase sin mirar nada — actualizalo o sacalo.")
        for nombre in funciones:
            for texto in _literales_sin_docstring(porNombre[nombre]):
                bajo = texto.lower()
                for veto in COLETILLAS_VETADAS:
                    if veto in bajo:
                        ofensas.append(
                            f"{modulo.__name__}.{nombre}: «{veto}» en {texto[:70]!r}")
    assert not ofensas, (
        "una salvedad sobre el método le avisa al lector que desconfíe de la frase que acaba "
        "de leer, y en esa sala no todos son técnicos:\n  " + "\n  ".join(ofensas))


def test_ningun_productor_de_prosa_deja_jerga_del_modelo_sin_traducir():
    """La aspiración es lenguaje de negocio que EXPLICA lo técnico, no que lo cita. Un comité
    que lee «0.7 veces la tasa base» no sabe contra qué se compara; «0.7 veces esa referencia»,
    detrás de «el promedio del sistema», sí."""
    ofensas = []
    for modulo, funciones in PRODUCTORES_DE_PROSA.items():
        porNombre = _funciones(modulo)
        for nombre in funciones:
            for texto in _literales_sin_docstring(porNombre[nombre]):
                bajo = texto.lower()
                for jerga in JERGA_DEL_MODELO:
                    if jerga in bajo:
                        ofensas.append(
                            f"{modulo.__name__}.{nombre}: «{jerga}» en {texto[:70]!r}")
    assert not ofensas, (
        "jerga del instrumento en la prosa del lector; nombrá la cosa en términos del "
        "negocio:\n  " + "\n  ".join(ofensas))


def test_las_claves_del_contexto_no_le_ensenan_jerga_al_modelo():
    """El agujero por el que se escapó la jerga después de limpiar la prosa determinista.

    El párrafo del informe lo escribe el MODELO, y el nombre de cada clave del contexto es
    texto que el modelo lee y copia. `veces_la_tasa_base` le enseñó el término: el Deep Dive
    de BPD (2025-12-31) publicó «(0.97 veces la tasa base)» aunque `prosa()` no emite ese
    paréntesis en ese rango —solo aparece si la entidad se aparta más de 0.15 de la
    referencia—. La prosa estaba limpia y el informe no.

    Es el mismo patrón de siempre: el guard cubría un motor (el determinista) y faltaba en el
    otro (el del modelo). Al escribir el glob hay que preguntarse qué queda afuera, y lo que
    quedaba afuera era el canal por donde sale el texto que el cliente lee.
    """
    from modules.banking_score import products
    constructores = ("_propension_para_modelo",)
    ofensas = []
    for nombre in constructores:
        nodo = _funciones(products)[nombre]
        for n in ast.walk(nodo):
            if not isinstance(n, ast.Dict):
                continue
            for k in n.keys:
                if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                    continue
                legible = k.value.replace("_", " ").lower()
                for jerga in JERGA_DEL_MODELO:
                    if jerga in legible:
                        ofensas.append(f"products.{nombre}: clave «{k.value}» dice «{jerga}»")
    # `early_warning` sirve el panel y las relaciones por el mismo canal
    for nombre in ("panel_para_modelo", "relaciones_para_modelo"):
        nodo = _funciones(early_warning)[nombre]
        for n in ast.walk(nodo):
            if not isinstance(n, ast.Dict):
                continue
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    legible = k.value.replace("_", " ").lower()
                    for jerga in JERGA_DEL_MODELO:
                        if jerga in legible:
                            ofensas.append(
                                f"early_warning.{nombre}: clave «{k.value}» dice «{jerga}»")
    assert not ofensas, (
        "el nombre de la clave es texto que el modelo copia al informe:\n  "
        + "\n  ".join(ofensas))


def test_todo_productor_de_prosa_esta_declarado_en_alguna_lista():
    """El glob del guard anterior dejaba módulos afuera y por eso el defecto volvió. Acá, una
    función nueva que huela a prosa rompe el test hasta que alguien decida si va al informe."""
    sin_declarar = []
    for modulo, cubiertas in PRODUCTORES_DE_PROSA.items():
        porNombre = _funciones(modulo)
        conocidas = set(cubiertas) | set(NO_VAN_AL_INFORME[modulo])
        # una anidada dentro de una declarada ya queda barrida por su madre
        for madre in list(conocidas):
            if madre in porNombre:
                conocidas |= _anidadas_en(porNombre[madre])
        for nombre in porNombre:
            if nombre not in conocidas and any(p in nombre for p in PISTAS_DE_PROSA):
                sin_declarar.append(f"{modulo.__name__}.{nombre}")
    assert not sin_declarar, (
        f"{sin_declarar}: declaralas en PRODUCTORES_DE_PROSA (si el texto sale al informe) o "
        f"en NO_VAN_AL_INFORME con su motivo. Un productor sin declarar es el hueco por el que "
        f"la coletilla vuelve.")


def test_los_controles_siguen_publicandose_aunque_no_se_narren():
    """Sacar la coletilla no puede volverse esconder el dato: la lista tiene que seguir
    saliendo por el canal donde hace su trabajo, que es acotar al MODELO."""
    from modules.banking_score.products import _propension_para_modelo
    ctx = _propension_para_modelo({
        "propension": 0.02, "veces_la_base": 1.1, "tasa_base": 0.0182,
        "empujan_al_alza": [], "empujan_a_la_baja": [],
        "controles_no_narrables": ["la cobertura de provisiones"],
        "uso_admitido": "PROPENSIÓN por BANDA", "prosa": "…"})
    assert ctx["controles_sin_lectura_causal"] == ["la cobertura de provisiones"]


def test_la_declaracion_de_alcance_NO_esta_vetada():
    """El contraejemplo que fija el límite: «fuera del índice» debe poder escribirse. Si un
    veto futuro lo alcanzara, estaríamos borrando una declaración de brecha —lo contrario de
    lo que este test protege—."""
    for veto in COLETILLAS_VETADAS:
        assert veto not in "concentración elevada (top-10) (severidad media, fuera del índice)"


# ── La TERCERA superficie: la plantilla ──

# Vocabulario del instrumento que el lector no debe ver en §Alerta Temprana. Cada uno salió
# publicado alguna vez. `_lista_mecanismos` y las CONSECUENCIA/ANCLA_2003 son la contraparte:
# lo que sí se dice.
JERGA_DE_ALERTA_TEMPRANA: Tuple[str, ...] = (
    "precursor", "calibrad", "vector de convergencia", "índice de salud", "fuera del índice",
    "severidad", "proxy visible", "señal se activa", "complemento del rating",
    "banda baja", "banda media", "banda alta",
)


def test_la_plantilla_le_prohibe_al_modelo_el_vocabulario_de_instrumento():
    """La fuente que estuvo dos días sin revisar. El párrafo de §10 lo escribe el MODELO, y la
    plantilla le decía «interpretá la posición frente a los PRECURSORES» y que
    'relaciones_computadas' trae «cuántos CONVERGEN hacia su umbral». De ahí salieron, literal,
    «los siete indicadores calibrados» y «el único vector de convergencia».

    Tres superficies alimentan esa sección —plantilla, nombres de clave y bloque
    determinista— y arreglar dos deja la tercera publicando. Este test cubre la plantilla."""
    from shared.narrative.claude_engine import THIN_TEMPLATES
    t = THIN_TEMPLATES["early_warning_reading"]
    bajo = t.lower()
    # La plantilla PUEDE nombrar la jerga para PROHIBIRLA; lo que no puede es usarla como su
    # propio vocabulario. Se exige que aparezca dentro de la instrucción de prohibición.
    assert "no escribas" in bajo, "la plantilla debe vetar explícitamente el vocabulario"
    veto = bajo.split("no escribas", 1)[1][:400]
    for jerga in ("precursor", "indicador calibrado", "vector de convergencia", "índice"):
        assert jerga in veto, f"la plantilla no le prohíbe «{jerga}» al modelo"
    assert "no reportes conteos" in bajo, (
        "sin esto el modelo narra «de siete señales, una converge» — el instrumento, no el "
        "banco; los conteos están para que ELIJA el sujeto, no para publicarlos")


def test_la_plantilla_exige_el_razonamiento_de_la_propension_no_solo_el_veredicto():
    """«Ubica al banco en línea con el promedio sistémico» es la conclusión sin el argumento.
    El comité necesita contra qué se comparó y QUÉ COMBINACIONES se buscaron —incluido que no
    apareciera ninguna, que es un hallazgo y no una omisión—."""
    from shared.narrative.claude_engine import THIN_TEMPLATES
    t = THIN_TEMPLATES["early_warning_reading"]
    assert "COMBINACIONES" in t, "el chequeo cruzado tiene que salir al informe"
    assert "NO se omite" in t, "que ninguna combinación aparezca ES el hallazgo"
    assert "NO alcanza" in t, "la plantilla debe rechazar el veredicto sin razonamiento"


def test_el_bloque_determinista_de_alerta_temprana_no_lleva_jerga():
    """La superficie que sí estaba cubierta, ahora con el vocabulario completo del caso."""
    from modules.banking_score.early_warning import format_alerts_text
    alerta = {"code": "concentracion", "label": "Concentración elevada (top-10)",
              "severity": "media", "value": 50.9, "threshold": 30.0,
              "basis": "Los préstamos vinculados fueron el mecanismo central del fraude "
                       "(proxy visible)", "metric": "top-10 / cartera total %"}
    for bloque in (format_alerts_text({"alerts": [alerta], "score": 100.0, "band": "alta"}),
                   format_alerts_text({"alerts": [alerta], "score": 100.0, "band": "alta",
                                       "con_narrativa": True})):
        bajo = bloque.lower()
        for jerga in JERGA_DE_ALERTA_TEMPRANA:
            assert jerga not in bajo, f"«{jerga}» llegó al informe: {bloque[:120]!r}"


def test_toda_senal_tiene_su_consecuencia_de_negocio():
    """Una señal sin consecuencia se publica como comparación de números: la regla sabe que
    50,9 > 30,0 y el comité necesita saber que eso significa depender de diez contrapartes.
    Una señal nueva sin su lectura rompe acá en vez de salir muda al informe."""
    from modules.banking_score.early_warning import ANCLA_2003, CONSECUENCIA, SIGNAL_META
    faltan = [c for c in SIGNAL_META if not CONSECUENCIA.get(c)]
    assert not faltan, f"{faltan}: sin consecuencia de negocio, la viñeta no dice nada"
    sin_ancla = [c for c in SIGNAL_META if c not in ANCLA_2003]
    assert not sin_ancla, f"{sin_ancla}: declarala aunque sea vacía, para que sea una decisión"
