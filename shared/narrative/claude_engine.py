import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from shared.cache import cache_get, cache_set
from shared.observability.llm_ledger import PURPOSE_NARRATIVE, record_call
from shared.config.settings import settings
from shared.llm.budget import budget_allows, record_usage
from shared.narrative.lang_context import get_request_lang
from shared.narrative.sanitize import (
    flag_register_violations, normalize_number_format, strip_meta_commentary,
)

logger = logging.getLogger(__name__)

# ── Reintento de sección ante fallos TRANSITORIOS del API ──────────────────────
# Un Deep Dive premium fanea sus 6 secciones con asyncio.gather; cada sección hace
# 2-4 llamadas al API (generación + juez numérico + posible regeneración). Esa ráfaga
# concurrente puede rozar el rate/overload por-organización de Anthropic: el SDK ya
# reintenta 4 veces por-request (max_retries=4), pero las 6 secciones reintentan EN
# FASE y no se desincronizan, así que un subconjunto agota los reintentos del SDK
# dentro de la misma ventana y cae a estático → degradación PARCIAL (p.ej. 4/6). La
# banca nunca degrada porque genera SECUENCIAL (jamás dispara la ráfaga).
#
# Este reintento a nivel de SECCIÓN, con backoff exponencial + JITTER, da headroom
# extra ADEMÁS del SDK y —clave— desfasa las secciones entre sí para que dejen de
# competir en lockstep. Es puramente aditivo: sólo puede convertir una sección que
# HABRÍA caído a estático en una real; nunca al revés. Sólo reintenta errores
# transitorios (rate limit, overload/5xx, timeout, corte de red); los permanentes
# (auth, 400, 404) se propagan de una — reintentar no los arregla, sólo demora el
# fallback.
_TRANSIENT_RETRY_ATTEMPTS = 3          # intentos de sección, ADEMÁS de los del SDK
_TRANSIENT_RETRY_BASE_SECONDS = 2.0    # backoff base; crece exponencial + jitter


def _is_transient_anthropic_error(exc: Exception) -> bool:
    """¿El error del API es transitorio (reintentar puede resolverlo)?"""
    import anthropic
    if isinstance(exc, (anthropic.RateLimitError, anthropic.APITimeoutError,
                        anthropic.APIConnectionError, anthropic.InternalServerError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        # 429 rate limit, 529 overloaded, 5xx del servidor.
        return getattr(exc, "status_code", None) in (429, 500, 502, 503, 504, 529)
    return False


def _call_with_transient_retry(fn, *, label: str):
    """Ejecuta ``fn`` (que hace la llamada bloqueante al API) reintentando SÓLO ante
    errores transitorios, con backoff exponencial + jitter. Corre dentro de
    ``asyncio.to_thread`` (worker thread), así que ``time.sleep`` bloqueante es correcto
    y no toca el event loop. Re-lanza el último error si se agotan los intentos o si el
    error no es transitorio (para que el caller degrade a estático como siempre)."""
    import random
    last_exc: Optional[Exception] = None
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= _TRANSIENT_RETRY_ATTEMPTS or not _is_transient_anthropic_error(exc):
                raise
            delay = _TRANSIENT_RETRY_BASE_SECONDS * (2 ** attempt) + random.uniform(0, 1.5)
            logger.warning(
                "API transitorio en %s (intento %d/%d): %s — reintento de sección en %.1fs",
                label, attempt + 1, _TRANSIENT_RETRY_ATTEMPTS, exc, delay,
            )
            time.sleep(delay)
    assert last_exc is not None  # inalcanzable; el loop siempre retorna o relanza
    raise last_exc


# Directiva que fuerza el idioma de salida. Va al FINAL del prompt (la última
# instrucción manda), así no hay que reescribir los ~16 templates por idioma:
# Claude genera nativo en el idioma destino respetando esta orden.
_LANG_DIRECTIVE = {
    "en": (
        "\n\nIMPORTANT: Write your ENTIRE response in English, regardless of any "
        "language mentioned above. Keep proper nouns, acronyms (IRMP, IAI, IRC, SIB, "
        "BCRD, NPL, ROA, ROE…) and every figure exactly as given."
    ),
    "fr": (
        "\n\nIMPORTANT : Rédige TOUTE ta réponse en français, quelle que soit la "
        "langue indiquée ci-dessus. Conserve les noms propres, les sigles (IRMP, IAI, "
        "IRC, SIB, BCRD, NPL, ROA, ROE…) et tous les chiffres tels quels."
    ),
}


def _apply_lang(prompt: str, lang: str) -> str:
    """Anexa la directiva de idioma si no es el default (es)."""
    directive = _LANG_DIRECTIVE.get(lang)
    return prompt + directive if directive else prompt

# Prompt templates using SCQA (Situation-Complication-Question-Answer) framework
TEMPLATES = {
    "executive_summary": (
        "Eres un analista financiero senior especializado en banca dominicana. "
        "Usa el framework SCQA (Situation-Complication-Question-Answer) de McKinsey.\n\n"
        "Genera un resumen ejecutivo en español para el siguiente contexto:\n"
        "{context}\n\n"
        "Estructura: Situación actual → Complicaciones identificadas → "
        "Pregunta clave → Respuesta/Recomendación. "
        "Tono profesional, conciso, máximo 500 palabras."
    ),
    "risk_assessment": (
        "Eres un analista de riesgo crediticio especializado en el sector bancario dominicano. "
        "Usa el framework SCQA.\n\n"
        "Genera una evaluación de riesgo en español para:\n{context}\n\n"
        "Incluye: factores de riesgo principales, mitigantes, perspectiva, "
        "y comparación con benchmarks del sector. Máximo 600 palabras."
    ),
    # Resumen ejecutivo de un boletín de SISTEMA (wire / datawatch). Existe porque
    # `executive_summary` resolvía a `banking_summary`, que es la plantilla POR ENTIDAD: a un
    # reporte sin banco se le entregaba un `scoring_result` en ceros y el modelo —bien— se
    # negaba a analizar, dejando la disculpa impresa como cuerpo del PDF. Peor en DataWatch:
    # esa disculpa convivía con una sección de Tendencias completa y con cifras reales sobre
    # el MISMO período, que se lee como bug en vivo y no como función pendiente. Esta
    # plantilla lee el sistema (benchmarks sectoriales), que es lo que el reporte sí tiene.
    "system_summary": (
        "Eres el analista jefe de un boletín sobre el SISTEMA bancario dominicano en su "
        "conjunto. El sujeto es el SISTEMA, no una entidad: no existe ni se espera un banco "
        "individual, y no debes pedir datos de entidad ni señalar su ausencia.\n\n"
        "Datos del sistema:\n{context}\n\n"
        "Escribe el resumen ejecutivo en formato SCQA (situación, complicación, pregunta, "
        "respuesta). Apóyate en los promedios sectoriales y de los grupos de pares que trae "
        "el contexto (capitalización, morosidad, rentabilidad, eficiencia, liquidez) y en los "
        "límites regulatorios cuando ayuden a dimensionar. Da la lectura del sistema: qué "
        "sostiene su solidez agregada, dónde está la tensión y qué vigilar en el próximo "
        "corte. Máximo 400 palabras. Usa SOLO cifras del contexto; ninguna inventada."
    ),
    "trend_analysis": (
        "Eres un analista financiero especializado en tendencias del sector bancario dominicano.\n\n"
        "Analiza las tendencias para:\n{context}\n\n"
        "Incluye: evolución temporal, drivers principales, comparación con pares, "
        "y proyección a corto plazo. Formato SCQA. Máximo 500 palabras."
    ),
    "recommendation": (
        "Eres un asesor financiero senior para instituciones bancarias dominicanas.\n\n"
        "Genera recomendaciones en español basadas en:\n{context}\n\n"
        "Estructura: diagnóstico breve → 3-5 recomendaciones priorizadas → "
        "impacto esperado. Máximo 400 palabras."
    ),
    "comparative": (
        "Eres un analista de benchmarking del sector bancario dominicano.\n\n"
        "Realiza un análisis comparativo para:\n{context}\n\n"
        "Compara métricas clave, identifica fortalezas y debilidades relativas, "
        "y posiciona en el contexto del sector. Formato SCQA. Máximo 500 palabras."
    ),
    "cross_compare": (
        "Eres un analista de benchmarking de inteligencia económica de República "
        "Dominicana y el Caribe.\n\n"
        "Compara los elementos de este contexto (cada uno con su score 0-100 y su "
        "desglose por dimensión):\n{context}\n\n"
        "El campo 'eje' indica el índice comparado. Contrasta los scores generales y "
        "por dimensión; identifica fortalezas y debilidades RELATIVAS entre los "
        "elementos (quién lidera y en qué dimensión, quién queda rezagado y por qué) "
        "y cierra con una lectura accionable. Formato SCQA. Usa SOLO las cifras del "
        "contexto, no inventes ninguna. Máximo 450 palabras."
    ),
    "market_brief": (
        "Eres el economista jefe de una firma de inteligencia económica de "
        "República Dominicana. Redacta un BRIEF DE MERCADO ejecutivo que sintetiza "
        "el estado del país a través de todos los ejes monitoreados:\n{context}\n\n"
        "El contexto trae, por eje, su score/banda y cifras clave (financiero, "
        "macro-fiscal, regulatorio/IRMP, comercio, social/IDM, ESG/clima, sectorial). "
        "Estructura: (1) un PANORAMA de 2-3 frases; (2) las SEÑALES por eje, integradas "
        "en una narrativa (no una lista plana) — destaca fortalezas, tensiones y "
        "divergencias entre ejes; (3) una CONCLUSIÓN accionable. Conecta los ejes entre "
        "sí (p. ej. cómo el pulso macro o el riesgo regulatorio condiciona lo sectorial "
        "y comercial). Usa SOLO las cifras del contexto, nunca inventes ninguna; si un "
        "eje viene sin dato, omítelo sin inventarlo. Tono ejecutivo y conciso. "
        "Máximo 700 palabras. Formato Markdown con encabezados."
    ),
    "deal_outlook": (
        "Eres un Managing Director de banca de inversión / corporate development de SDQ "
        "Consulting evaluando un deal:\n{context}\n\n"
        "El 'score' (0-100) sale de una RÚBRICA DECLARADA (no un modelo entrenado) anclada "
        "a la inteligencia real de la plataforma: IRMP (riesgo regulatorio/político del país), "
        "IAI (atractivo del sector) e IRC (clima). Los 'drivers' traen cada componente con su "
        "valor, origen (analista vs eje) y contribución. Genera un análisis ejecutivo (3-5 "
        "frases): (1) lectura general de cierre/atractivo, (2) drivers positivos clave, "
        "(3) el riesgo/preocupación principal, (4) UNA recomendación accionable para subir la "
        "probabilidad de cierre. Apóyate en el 'contexto_ejes' cuando exista. Usa SOLO las "
        "cifras del contexto, nunca inventes. Aclara que es una lectura de rúbrica, no de un "
        "modelo entrenado. Conciso, sin jerga. Máximo 220 palabras."
    ),
    "sector_outlook": (
        "Eres el economista jefe de una firma de análisis financiero en República Dominicana.\n\n"
        "Genera una perspectiva sectorial basada en:\n{context}\n\n"
        "Incluye: contexto macroeconómico, tendencias regulatorias, "
        "perspectivas por segmento (banca múltiple, AAP, bancos de ahorro), "
        "riesgos y oportunidades. Formato SCQA. Máximo 800 palabras.\n"
        "Si el contexto incluye 'contexto_oficial_bcrd' (informes del Banco Central, "
        "p. ej. Estabilidad Financiera), apóyate en él para el panorama macro/sistémico "
        "y cítalo explícitamente (nombre del informe y período)."
    ),
    "social_outlook": (
        "Eres un economista del desarrollo analizando el Índice de Desarrollo "
        "Multidimensional (IDM) de una región de la República Dominicana.\n\n"
        "Contexto:\n{context}\n\n"
        "Escribe en español, máximo 450 palabras, formato SCQA, con estos bloques:\n"
        "1) **Lectura**: el score IDM de la región, su banda y su posición en la "
        "distribución (usa el rank y la dispersión provistos — distribución > promedio).\n"
        "2) **Fortalezas y rezagos**: las dimensiones que más suman y las que más "
        "lastran (salud/educación/nivel de vida/inclusión), citando sus scores.\n"
        "3) **Desigualdad**: qué dice la posición de la región frente a las demás.\n"
        "4) **Qué vigilar**: prioridades de desarrollo.\n"
        "Reglas: doctrina = bienestar multidimensional, distribución > promedio; NO "
        "inventes cifras fuera del contexto; respeta la procedencia (real vs rúbrica "
        "declarada) y NO sobre-interpretes una dimensión marcada como rúbrica."
    ),
    "trade_outlook": (
        "Eres el economista jefe de una firma de análisis en República Dominicana, "
        "analizando la RESILIENCIA del comercio exterior (no el volumen).\n\n"
        "Contexto (datos de Aduanas/DGA por capítulo arancelario):\n{context}\n\n"
        "Escribe en español, máximo 450 palabras, formato SCQA, con estos bloques:\n"
        "1) **Lectura**: el score de resiliencia y qué refleja (diversificación + "
        "dependencia de importaciones).\n"
        "2) **Concentración exportadora**: qué capítulos dominan (cita las participaciones "
        "provistas) y qué riesgo implica esa concentración.\n"
        "3) **Dependencia**: lectura de la dependencia de importaciones y su implicación.\n"
        "4) **Qué vigilar**: señales y vulnerabilidades.\n"
        "Reglas: doctrina = diversificación > volumen, medir dependencia no solo apertura; "
        "NO inventes cifras fuera del contexto; cita los números provistos; reconoce que NO "
        "hay detalle por país socio."
    ),
    "climate_outlook": (
        "Eres un analista de riesgo climático evaluando la RESILIENCIA CLIMÁTICA "
        "(IRC) de un país frente a un panel Caribe/LatAm.\n\n"
        "Contexto:\n{context}\n\n"
        "Escribe en español, máximo 450 palabras, formato SCQA, con estos bloques:\n"
        "1) **Lectura**: el IRC del país, su banda y su posición en el panel (usa el "
        "rank y la dispersión — distribución > promedio).\n"
        "2) **Fortalezas y vulnerabilidades**: las dimensiones que más suman y las que "
        "más lastran (riesgo físico/transición/capacidad adaptativa/gobernanza), citando "
        "sus scores.\n"
        "3) **Exposición física vs descarbonización**: lee el huracán y la dependencia "
        "fósil del país.\n"
        "4) **Qué vigilar**: prioridades de adaptación/transición.\n"
        "Reglas: NO inventes cifras fuera del contexto; cita los números y la fuente "
        "real provista por dimensión (HURDAT2/Ember/ND-GAIN); mayor IRC = más resiliente."
    ),
    "indicator_insight": (
        "Eres un analista de calificación de riesgo bancario en República Dominicana. "
        "Analiza EN DETALLE un único indicador financiero de una entidad, a partir de "
        "datos reales del SIB.\n\n"
        "Contexto:\n{context}\n\n"
        "Escribe en español, máximo 350 palabras, con estos 4 bloques claros:\n"
        "1) **Lectura del nivel actual**: qué dice el valor y su score, e interpretación.\n"
        "2) **Tendencia**: evolución en los trimestres provistos y drivers probables.\n"
        "3) **Posición vs pares**: frente a la mediana del sector y del mismo tipo de entidad "
        "(usa el percentil provisto).\n"
        "4) **Implicaciones y qué vigilar**: riesgos o fortalezas y señales a monitorear.\n"
        "Reglas: NO inventes cifras fuera del contexto; cita los números provistos; "
        "respeta la dirección del indicador (si 'lower'/'higher'/'target' es mejor)."
    ),
    "subcomponent_focus": (
        "Eres un analista de calificación de riesgo bancario en República Dominicana. "
        "Analiza EN PROFUNDIDAD UN sub-componente del rating de una entidad —NO todo el "
        "banco— a partir de datos reales del SIB.\n\n"
        "Contexto (solo los indicadores de este sub-componente):\n{context}\n\n"
        "Escribe en español, máximo 200 palabras, enfocado EXCLUSIVAMENTE en este "
        "sub-componente, con estos bloques:\n"
        "1) **Lectura**: el score del sub-componente y qué refleja.\n"
        "2) **Impulsor y lastre**: el indicador que más lo sube y el que más lo baja, "
        "con sus valores y scores.\n"
        "3) **Vs pares**: posición frente a la mediana del sector/tipo si se provee.\n"
        "4) **Veredicto**: una conclusión puntual y qué vigilar.\n"
        "Reglas: NO repitas el panorama global del banco ni otros sub-componentes; "
        "NO inventes cifras; cita SOLO los números provistos; respeta la dirección de "
        "cada indicador (si menor/mayor es mejor)."
    ),
    "entity_rating": (
        "Eres un analista de calificación de riesgo bancario en República Dominicana. "
        "Explica EL FUNDAMENTO del rating de una entidad, a partir de datos reales del SIB.\n\n"
        "Contexto:\n{context}\n\n"
        "Escribe en español, máximo 400 palabras, con estos bloques:\n"
        "1) **Lectura del rating**: qué significa el rating y el score global, y cómo se "
        "posiciona vs los pares (usa el percentil provisto).\n"
        "2) **Fortalezas**: los sub-componentes/indicadores que más impulsan el rating.\n"
        "3) **Debilidades**: los sub-componentes/indicadores que más lo lastran.\n"
        "4) **Trayectoria y qué vigilar**: evolución del score y señales a monitorear.\n"
        "Reglas: NO inventes cifras fuera del contexto; cita los números provistos; "
        "pondera según los pesos de cada sub-componente. "
        "Si se incluye 'contexto_oficial_bcrd' (informes del Banco Central), úsalo solo "
        "como telón de fondo sistémico y cítalo brevemente; el foco sigue siendo la entidad."
    ),
}

# Thin task templates — ruta cerebro (activada por axis=). La persona y las reglas
# comunes viven en el `system` (shared/narrative/cerebro.py); el thin solo lleva la
# tarea, la forma y los guardarraíles específicos del template (topes, dirección del
# indicador, percentil, peso de sub-componente, BCRD como telón). La regla "no inventes
# cifras" NO se repite aquí: vive en EPISTEMIC_STANDARD del cerebro y sigue activa.
THIN_TEMPLATES = {
    # Motor de Research Custom (orquestador v2): responde una PREGUNTA LIBRE del comprador
    # circunscrita EXCLUSIVAMENTE a los resultados ya computados por los motores del sistema
    # (pasados en 'datos'). Genérico por eje: la persona/doctrina la pone build_system(axis).
    "research_answer": (
        "Respondé la PREGUNTA del comprador (campo 'pregunta') usando EXCLUSIVAMENTE los "
        "resultados ya computados por los motores del sistema para las entidades/ejes "
        "involucrados (campo 'datos'). NO es un reporte de estado: es la respuesta a esa "
        "pregunta concreta.\nContexto:\n{context}\n\n"
        "Máximo 450 palabras. Estructura: abrí con el VEREDICTO que responde la pregunta; "
        "respaldalo con las cifras REALES del contexto que correspondan al eje (rating/score/"
        "sub-componentes/percentil vs pares/trayectoria/alertas/sensibilidades); cerrá con el "
        "'y por tanto' accionable para la audiencia. REGLA DURA DE CIFRAS: usá SOLO los números "
        "servidos en 'datos'; NO inventes ni derives cifras que no estén dadas; si la relación "
        "que querés expresar no está precalculada, decila en palabras SIN número. PROCEDENCIA: "
        "sobre datos marcados 'real' construí con firmeza; sobre 'rúbrica declarada' no "
        "construyas conclusión fuerte y nómbrala como tal. BRECHA (crítico): si la pregunta "
        "pide algo que 'datos' NO cubre —p.ej. una proyección o escenario a futuro que ningún "
        "motor computa— DECILO explícitamente como límite del análisis; NO lo rellenes con "
        "conocimiento general ni con una estimación propia."
    ),
    # Research tema-primero: SÍNTESIS CROSS-DOMINIO. Integra el resultado de VARIOS motores
    # (entidad + macro/monetario/regulatorio/externo) alrededor de la pregunta — lo que un
    # solo producto no puede. Estructura por la pregunta/decisión, no por dimensiones de rating.
    "research_synthesis": (
        "Sos un analista senior de SDQ. Respondé la PREGUNTA del comprador ('pregunta') "
        "INTEGRANDO el resultado de los distintos motores del sistema en 'dominios' (cada uno "
        "trae dato REAL ya computado: una entidad, el macro, el monetario, etc.). El valor de "
        "este informe —y por lo que se paga— es la SÍNTESIS entre dominios: los mecanismos de "
        "transmisión que conectan un motor con otro, no la ficha de ninguno.\nContexto:\n{context}\n\n"
        "Estructurá la respuesta EXACTAMENTE con estos encabezados markdown:\n"
        "## Tesis — el veredicto que responde la pregunta, en 3-4 frases.\n"
        "## Mecanismos de transmisión — los CANALES cross-dominio por los que la pregunta se "
        "resuelve (p.ej. cómo la postura monetaria del sistema golpea el fondeo de la entidad, "
        "cómo la presión externa se conecta con su liquidez). Este es el núcleo: conectá los "
        "motores, no los recites por separado. Nombrá el dominio de cada cifra.\n"
        "## Posición y evidencia — las cifras reales que sostienen la tesis, de cada motor.\n"
        "## Disparadores y monitoreo — orientado a la DECISIÓN del comprador: qué vigilar, qué "
        "umbrales, qué cambiaría el veredicto.\n\n"
        "REGLA DURA DE CIFRAS: usá SOLO los números de 'dominios'; no inventes ni derives lo "
        "que no está servido; si una relación no está dada, decila en palabras SIN número. "
        "PROCEDENCIA: sobre dato 'real' construí con firmeza; sobre 'rúbrica' nómbrala. BRECHA: "
        "lo que la pregunta pide y ningún motor computa (proyecciones/escenarios a futuro), "
        "DECILO como límite; no lo estimes. Extensión: hasta ~700 palabras, denso, sin relleno."
    ),
    "early_warning_reading": (
        "Sos un analista senior de riesgo bancario escribiendo para un comité de crédito. "
        "Escribí como le hablarías a un director que decide una línea y no es técnico en "
        "riesgo. Contexto:\n{context}\n\n"
        "Máximo 150 palabras, UN SOLO párrafo, prosa, nunca viñetas.\n"
        "IDIOMA: el del negocio, no el del instrumento. NO escribas 'precursor', 'indicador "
        "calibrado', 'vector de convergencia', 'señal encendida', 'bandera', 'índice', "
        "'severidad', 'el motor', 'el modelo mide'. Nombrá las cosas como un banquero: la "
        "morosidad, la cobertura de provisiones, el capital, los depósitos, la concentración "
        "en los mayores deudores.\n"
        "NO REPORTES CONTEOS. 'de siete señales, una converge' es una descripción del "
        "instrumento; escribila como 'lo único que se está moviendo es la cobertura de "
        "provisiones'. Los conteos de 'relaciones_computadas' están para que ELIJAS bien el "
        "sujeto y no inventes superlativos — no son material para narrar.\n"
        "Tu trabajo es la LECTURA, no el cálculo: si nada está por encima de su umbral, lo "
        "relevante es cuánto margen hay y hacia dónde se mueve —un banco lejos y alejándose no "
        "es lo mismo que uno lejos pero acercándose—; si algo lo está, qué combinación pesa y "
        "qué la matiza. Cerrá con el 'y por tanto' de qué vigilar antes del próximo corte.\n"
        "REGLA DURA: usá EXCLUSIVAMENTE las cifras del contexto. Los superlativos y el orden "
        "(cuál llegaría antes, cuántos se acercan) vienen resueltos en 'relaciones_computadas' "
        "— COPIALOS, no los deduzcas del panel. Si una relación no está dada, exprésala en "
        "palabras SIN número. Los plazos al umbral son CONDICIONALES: escribilos como 'de "
        "sostenerse el ritmo…', nunca como un pronóstico, y NO agregues rótulos de salvedad "
        "entre paréntesis (el condicional ya lo dice; una advertencia extra solo genera "
        "desconfianza). NO afirmes fraude ni causas ocultas.\n"
        "PROPENSIÓN — ES EL NÚCLEO DE LA SECCIÓN, no una cláusula al pasar. Si el contexto "
        "trae 'propension', dedicale al menos un tercio del párrafo: es el modelo entrenado "
        "sobre las quiebras REALES del sistema dominicano y responde la pregunta desde el "
        "desenlace en vez de desde umbrales. Decí TRES cosas, no una: (a) en qué se parece y "
        "en qué NO se parece esta entidad a las que salieron, con la comparación concreta; "
        "(b) qué COMBINACIONES de deterioro se buscaron y si aparecieron —están en "
        "'lectura_de_referencia'; que no aparezca ninguna NO se omite, ES el hallazgo: el "
        "chequeo se corrió y volvió limpio, y eso es lo que distingue a este modelo de una "
        "suma de señales sueltas—; y (c) dónde queda parada. 'Ubica al banco en línea con el "
        "promedio' a secas NO alcanza: es la conclusión sin el razonamiento que la sostiene. "
        "Escribí desde el BANCO, no desde el modelo: qué le está pasando a la entidad, contra "
        "qué se compara, qué consecuencia tiene. Nada de 'factor', 'coeficiente' ni "
        "'log-odds'. Las variables "
        "listadas en 'controles_sin_lectura_causal' NO se narran como causa —son control "
        "estadístico— y la cifra se presenta según 'uso_admitido': si dice BANDA, no la "
        "publiques como probabilidad puntual de la entidad. 'lectura_de_referencia' es la "
        "versión determinista: podés mejorar la redacción, no cambiar lo que afirma.\n"
        "EL HORIZONTE es CUÁNTO FALTA para llegar al umbral, no una fecha ni un margen. "
        "Escribilo como 'tomaría <horizonte>', 'en <horizonte>' o 'dentro de <horizonte>'. "
        "NUNCA como 'X antes de que…' ni 'el margen desaparecería <horizonte>': eso salió "
        "publicado como «el margen desaparecería alrededor de 3.5 años antes de que las "
        "reservas dejen de cubrir», que no significa nada.\n"
        "FORMATO DE LAS CIFRAS: cada señal trae sus campos ya redactados —'valor_expresado',"
        "'umbral_expresado', 'hace_12m_expresado', 'horizonte'—. Copiá ESAS cadenas TAL CUAL "
        "('2,0 veces', '50,9%', 'alrededor de 3,5 años'); NO uses los campos numéricos crudos "
        "('value', 'threshold') ni reformatees el separador decimal — el informe usa PUNTO "
        "decimal, y mezclar '2.3' con '2,3' en el mismo párrafo se lee como un error de datos."
    ),
    "banking_forensic": (
        "Escribe una LECTURA RETROSPECTIVA de una entidad financiera que SALIÓ del sistema, "
        "sobre dato mensual real de la SB (Cronología SB). NO es una calificación emitida en su "
        "momento. La NATURALEZA de la salida ya la determinó el modelo y viene en el contexto "
        "como 'naturaleza_salida' (quiebra | no_quiebra | indeterminada). ADAPTA la lectura a esa "
        "naturaleza — NO asumas quiebra.\nContexto:\n{context}\n\n"
        "• Si naturaleza_salida = 'quiebra' → 'anatomía de la quiebra', con estos encabezados:\n"
        "  ## Lectura central — el veredicto en 3-4 frases: cuándo empezó el deterioro detectable "
        "('onset') y cuántos meses antes del colapso (si no hubo onset, dilo: punto ciego).\n"
        "  ## Anatomía del deterioro — el salto de morosidad, el agotamiento de la cobertura, la "
        "fuga de depósitos; nombra cifras y fechas del contexto.\n"
        "  ## Qué marcó el modelo — el cluster de Alerta Temprana que convergió y cuándo.\n"
        "  ## Lección — el 'y por tanto': si el cluster llegó tarde o no llegó, los ratios "
        "detectan insolvencia, no fraude.\n"
        "• Si naturaleza_salida = 'no_quiebra' → la entidad NO quebró; su salida fue por OTRAS "
        "causas (fusión, absorción, cambio de nombre). Encabezados:\n"
        "  ## Lectura central — la entidad NO quebró: al salir sus ratios eran sanos (usa "
        "morosidad_al_salir_pct y cobertura_al_salir_pct del contexto); la salida no fue por "
        "insolvencia.\n"
        "  ## Perfil al momento de salir — la trayectoria SANA de morosidad, cobertura y "
        "depósitos; por qué es incompatible con una quiebra.\n"
        "  ## Naturaleza de la salida — fusión, absorción o cambio de nombre; el análisis se "
        "incluye por completitud del universo histórico, no como caso de quiebra.\n"
        "  PROHIBIDO el vocabulario de quiebra ('colapso', 'anatomía de la quiebra', 'deterioro "
        "terminal', 'onset'): la entidad no quebró.\n"
        "• Si naturaleza_salida = 'indeterminada' → no se puede afirmar quiebra ni descartarla. "
        "Encabezados:\n"
        "  ## Lectura central — salida sin cluster de deterioro; naturaleza no concluyente desde "
        "el dato.\n"
        "  ## Qué muestra el dato — la trayectoria disponible y sus límites.\n"
        "  ## Naturaleza de la salida — pudo ser fusión/renombre o un colapso no legible en los "
        "ratios (fraude ocultado).\n\n"
        "REGLA DURA DE CIFRAS: usá SOLO los números del contexto (onset, lead_months, morosidad, "
        "cobertura, fuga de depósitos, ratios al salir, fechas); NO inventes ni derives cifras que "
        "no estén dadas; si una relación no está, exprésala en palabras SIN número. LÍMITES: el "
        "capital regulatorio Basilea no existe en el balance contable pre-2004 → no cites "
        "solvencia Basel; el apalancamiento patrimonio/activos es un proxy. No afirmes fraude "
        "como hecho probado salvo que el contexto lo marque. Máximo ~600 palabras, denso, sin "
        "relleno."
    ),
    "entity_rating": (
        "Explica el FUNDAMENTO del rating de esta entidad, a partir de datos reales del SIB.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 400 palabras. No cubras los cuatro puntos por igual: ve profundo en la "
        "tensión que más condiciona la decisión de la audiencia. Apóyate en: lectura del "
        "rating y posición vs pares (usa el percentil), el/los sub-componente(s) que más "
        "impulsan y los que más lastran (pondera por su peso), y la trayectoria del score. "
        "Si hay 'contexto_oficial_bcrd', úsalo solo como telón sistémico y cítalo breve.\n\n"
        "CIFRAS DERIVADAS: 'cifras_derivadas' YA trae calculado todo lo derivado — aporte y "
        "gap al techo por sub-componente, líder vs la suma del resto, deltas vs mediana/p75, "
        "pares que lo superan (aprox), rango de 12 trimestres (mín/máx con período), "
        "variaciones del score actual (vs máx, mín, trimestre anterior, mismo trimestre del "
        "año previo) y los cortes de marzo. REGLA DURA DE DERIVADOS: NO calcules de memoria "
        "ningún número derivado (comparaciones tipo 'mayor que la suma de…', conteos de pares "
        "'N entidades lo superan', deltas entre períodos, el mínimo/máximo/piso/techo de la "
        "serie, distancia al techo). Usa EXCLUSIVAMENTE el valor servido en 'cifras_derivadas' "
        "o 'tendencia_score'. Si la relación que querés expresar no está precalculada, decila "
        "en palabras SIN número (p. ej. 'está en el tope de su grupo', no 'lo superan 3'). Al "
        "citar el score de un período usa EXACTAMENTE el de 'tendencia_score' para ese período.\n\n"
        "SUPERLATIVOS: para 'el mayor gap / el más débil / la mayor pérdida potencial' entre "
        "sub-componentes usa 'componente_mayor_gap_al_techo'; para ordinales de peso ('el 2º "
        "de mayor peso') lee 'componentes_por_peso_desc' completo (no omitas Diversificación "
        "aunque pese poco); para 'la mayor caída' usa 'mayor_caida_intertrimestral'. NO "
        "declares un superlativo (mayor/menor/el más…) que no coincida con el valor servido."
    ),
    "indicator_insight": (
        "Analiza un único indicador financiero de la entidad (datos reales SIB) — para una "
        "decisión, no un reporte de estado.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. COMIENZA por el veredicto: ¿qué dice este indicador sobre la "
        "solidez o la capacidad de pago, y cuál es la tensión que importa? Recién después "
        "respaldalo con el nivel y su lectura, la trayectoria (no un punto suelto) y la "
        "posición vs la mediana del sector y del mismo tipo (usa el percentil). INTERPRETÁ el "
        "tecnicismo por lo que significa, no como cifra suelta; no recorras los ángulos por "
        "igual —ve profundo en el que más condiciona la decisión—. Cierra con la implicación y "
        "qué vigilar. Respeta la dirección del indicador (si 'lower'/'higher'/'target' es "
        "mejor). Usa SOLO las cifras del contexto."
    ),
    "subcomponent_focus": (
        "Analiza EN PROFUNDIDAD UN sub-componente del rating —NO todo el banco— (datos SIB).\n"
        "Contexto (solo los indicadores de este sub-componente):\n{context}\n\n"
        "Máximo 200 palabras, enfocado EXCLUSIVAMENTE en este sub-componente. Cubre: qué "
        "refleja su score, el indicador que más lo sube y el que más lo baja (con sus valores "
        "y scores), "
        "posición vs pares si se provee, y un veredicto puntual con qué vigilar. NO repitas el "
        "panorama global del banco ni otros sub-componentes."
    ),
    "sector_outlook": (
        "Explica el FUNDAMENTO del atractivo de inversión (IAI) de este sector.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. No cubras las cinco dimensiones por igual: ve profundo en la que "
        "más condiciona la decisión de la audiencia. Apóyate en: lectura del IAI y su banda, "
        "la(s) dimensión(es) que más impulsan y las que más lastran (pondera por su peso vía "
        "'cifras_derivadas'), y la aceleración (SGPS) como nivel vs trayectoria. PROCEDENCIA: "
        "apóyate con firmeza en las dimensiones 'real' (sector, exposición macro); sobre las de "
        "'rúbrica declarada' (negocios, talento, regulatoria) no construyas conclusión fuerte y "
        "nómbralas como rúbrica cuando sean material.\n\n"
        "CIFRAS DERIVADAS: 'cifras_derivadas' YA trae el aporte y el gap al techo por dimensión, "
        "el líder vs la suma del resto, la dimensión de mayor gap y el orden por peso. Copia esos "
        "valores; NO recalcules aportes ni declares un superlativo (mayor/menor/el más…) que no "
        "coincida con lo servido. Si una relación no está precalculada, exprésala en palabras sin "
        "número."
    ),
    "sector_positioning": (
        "Sitúa el índice en CONTEXTO —cómo se compara y cómo evoluciona— para una decisión. "
        "Esta es la capa que separa el Insight del Pulse: no la foto, sino el movimiento.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 300 palabras. COMIENZA por el veredicto de posición: ¿el nivel es fuerte/medio/débil "
        "EN CONTEXTO y la trayectoria MEJORA o se DETERIORA? Respalda con lo que el contexto traiga: "
        "(a) TRAYECTORIA —la serie histórica ('trayectoria'): dirección, ritmo, punto de inflexión— "
        "si está; (b) POSICIÓN relativa —rank, distancia al líder/media del panel— si está; y "
        "(c) la DIMENSIÓN que más mueve la posición. NO repitas el diagnóstico del assessment: acá "
        "el foco es «dónde está parado vs su propio pasado y vs otros». Si no hay serie ni panel, "
        "decilo y quedate en la lectura de dimensiones, sin fabricar una tendencia. Usa SOLO las "
        "cifras del contexto; respeta la dirección del índice."
    ),
    "sector_decision": (
        "CIERRE ACCIONABLE para la audiencia — conciso y preciso. NO re-describas el índice ni "
        "repitas el panorama ya expuesto (resumen, dimensiones, banda): eso ya se dijo.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 180 palabras. UNA postura clara: la palanca o decisión de MAYOR RETORNO dada la "
        "tensión central ya identificada. Indica POR QUÉ es la de mayor retorno y, si aplica, qué la "
        "ejecuta. Cierra con la señal que confirmaría o refutaría que va por buen camino. Sin "
        "recitar indicadores ni recorrer dimensiones; cita solo la cifra que justifica la "
        "decisión. Usa SOLO las cifras del contexto; respeta la dirección del índice y la "
        "procedencia (real vs rúbrica declarada)."
    ),
    "economic_structure_outlook": (
        "Lee la ESTRUCTURA de la economía dominicana y QUÉ LA MUEVE — para una decisión, no un "
        "resumen neutral.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. EMPIEZA POR EL VEREDICTO: ¿qué TIPO de crecimiento es este y cuál es "
        "la tensión central? (p. ej. «crecimiento real pero de composición frágil: lo empujan "
        "servicios livianos mientras el sector más grande se contrae»). El dato RESPALDA esa "
        "conclusión, no al revés. Idea rectora: TAMAÑO (peso en el Valor Agregado) ≠ APORTE "
        "(contribución = peso × crecimiento). NO recorras los 17 sectores ni recites tres cifras "
        "por cada uno: nombra SOLO los 2-3 que mueven la lectura —el motor que más aporta (con su "
        "cuota del crecimiento) y el lastre grande que resta (p. ej. construcción)— y di QUÉ "
        "SIGNIFICAN, no solo cuánto valen. Cierra con la implicación: qué hace frágil o robusto a "
        "este crecimiento y qué lo cambiaría. Usa EXCLUSIVAMENTE las cifras del contexto "
        "(total_va_growth_pct, structure_top_weight, growth_drivers, growth_drags, "
        "concentration_hhi_sectors). HONESTIDAD: lente de IMPORTANCIA y CONTRIBUCIÓN — NO valor exportado "
        "(joyería/oro) ni atractividad (IAI); no las mezcles. Dato anual agregado del BCRD; sin "
        "score sintético. Si una cifra no está, dilo; no inventes."
    ),
    "economic_structure_mechanism": (
        "PROFUNDIZA en el MECANISMO detrás del cuadro sectorial — la capa que la lectura breve no "
        "abre. No repitas el panorama general; ASUME que ya se presentó.\n"
        "Contexto:\n{context}\n\n"
        "Toma la tensión central (típicamente el sector grande que arrastra —construcción— y el "
        "motor mediano que empuja —financiero—) y desarrolla la CADENA CAUSAL: POR QUÉ se contrae "
        "o se acelera (canales de crédito, inversión pública/fiscal, ciclo de tasas, demanda "
        "post-pandemia) y QUÉ ARRASTRA CONSIGO por encadenamiento (materiales, empleo de baja "
        "calificación, servicios profesionales en obra). CUANTIFICA LA ASIMETRÍA con las cifras "
        "del contexto: si el lastre revierte a crecimiento +X%, su contribución pasa de A a B —un "
        "swing de Y pp sobre el crecimiento total—; compáralo con el aporte de los motores y di "
        "cuál palanca rinde más. Sé explícito sobre lo que el dato NO desglosa (p. ej. el canal "
        "exacto de la contracción) y qué inferencia es plausible vs verificada. CIERRA con los "
        "INDICADORES ADELANTADOS a vigilar (crédito privado, permisos de construcción, gasto de "
        "capital público, llegadas de turistas) que confirmarían o refutarían la lectura. Usa SOLO "
        "cifras del contexto; ninguna inventada. Estructura en secciones con encabezados Markdown."
    ),
    "economic_structure_decision": (
        "CIERRE ACCIONABLE para el formulador de política — conciso y preciso. NO re-describas la "
        "estructura ni recites cifras sector por sector.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 200 palabras. UNA sola idea rectora: la palanca de MAYOR RETORNO sobre el "
        "crecimiento agregado, dado el cuadro de motores y lastres ya expuesto. Nómbrala, di POR "
        "QUÉ es la de mayor retorno (peso × reversión potencial) y qué la ejecuta (instrumentos "
        "concretos: inversión pública, crédito hipotecario, permisos). Distingue «sostener los "
        "motores» de «revertir el lastre» y TOMA PARTIDO por la de mayor impacto. Termina con la "
        "señal que confirmaría o refutaría que la palanca está funcionando. Cita solo la cifra que "
        "justifica la palanca. Usa SOLO cifras del contexto. Lente de contribución, no valor "
        "exportado ni IAI."
    ),
    "banking_summary": (
        "Resumen ejecutivo de la SOLIDEZ de esta entidad para una decisión de exposición.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. EMPIEZA POR EL VEREDICTO: el rating, qué tan sólida es la entidad y "
        "cuál es la tensión que más condiciona su capacidad de pago. Luego respáldalo: el "
        "sub-componente que más sostiene la solidez y el que más la limita (pondera por su peso; "
        "un indicador fuerte en un sub-componente de bajo peso no rescata el rating) y la "
        "trayectoria del score (nivel vs dirección). NO recorras los cinco sub-componentes uno por "
        "uno ni recites todos los indicadores: nombra los 2-3 que mueven la lectura e INTERPRETÁ "
        "qué significan para la solidez —no cites el ratio suelto—. Cierra con el 'y por tanto' para "
        "el comité: qué implica para la exposición y qué señal vigilar antes del próximo corte. Usa "
        "SOLO las cifras del contexto; ninguna inventada."
    ),
    "banking_comparative": (
        "Posición RELATIVA de la entidad frente a sus pares —no su perfil aislado.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 300 palabras. La CONCLUSIÓN primero: ¿esta entidad lidera, está en la media o "
        "rezagada frente a pares de su mismo tipo, y en QUÉ dimensión se juega la diferencia? "
        "Respalda con la comparación que importa (no toda la tabla): dónde su ventaja es real y "
        "dónde su rezago es material para la solidez. INTERPRETÁ la diferencia (qué significa una "
        "peor morosidad o cobertura frente al par), no solo el número. Si incluís una tabla "
        "comparativa, que sea markdown estándar y corta. Usa SOLO las cifras del contexto; "
        "ninguna inventada."
    ),
    "banking_risk": (
        "PROFUNDIZA en el RIESGO forward de la entidad — la capa que el resumen no abre. No "
        "repitas el panorama; asume que ya se presentó.\n"
        "Contexto:\n{context}\n\n"
        "Toma el sub-componente o indicador que más condiciona la solidez y desarrolla la CADENA "
        "CAUSAL del riesgo: qué lo deteriora (calidad de cartera, presión de rentabilidad, "
        "descalce de liquidez, concentración), por qué canal golpearía la capacidad de pago y qué "
        "lo amortigua (mitigantes reales del contexto). CUANTIFICA LA ASIMETRÍA: qué tan caro es "
        "equivocarse hacia cada lado para el comité y a qué umbral una señal pasa de vigilancia a "
        "acción. Interpreta cada tecnicismo por su significado prudencial, no como cifra suelta. "
        "Si el contexto trae 'sensibilidades', ANCLA el umbral de acción en su 'riesgos_baja' "
        "(el indicador, el valor crudo 'umbral_fmt' que hace perder banda y el 'delta_overall' que "
        "cuesta al score) — es el nivel exacto en que la vigilancia pasa a acción. "
        "Cierra con los INDICADORES ADELANTADOS a vigilar antes del próximo corte y qué los movería. "
        "Usa SOLO las cifras del contexto; ninguna inventada. Estructura en secciones con "
        "encabezados Markdown."
    ),
    "banking_recommendation": (
        "CIERRE ACCIONABLE para el comité de crédito — conciso y preciso. NO re-describas la entidad.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 180 palabras. UNA postura clara de exposición: aprobar, ajustar/limitar o declinar "
        "la línea, dado el cuadro de solidez y riesgo ya expuesto. Indica POR QUÉ (la tensión que la "
        "condiciona) y, si aplica, qué condición la haría viable. Si el contexto trae "
        "'sensibilidades', nombra la palanca de mayor retorno de su 'palancas_alza' (indicador + "
        "umbral 'umbral_fmt' + 'delta_overall' que suma) como la condición cuantificada. Termina con "
        "la señal que confirmaría o refutaría la postura antes del próximo corte. Sin recitar ratios; "
        "cita solo la cifra que justifica la decisión. Usa SOLO las cifras del contexto."
    ),
    "banking_operating_env": (
        "Lee el ENTORNO OPERATIVO macro y cómo incide en el perfil de riesgo de ESTA "
        "entidad — el telón sistémico que el análisis de la entidad no abre.\n"
        "Contexto (factores macro reales del BCRD vía 'entorno_macro'):\n{context}\n\n"
        "Máximo 250 palabras. EMPIEZA POR EL VEREDICTO: ¿el entorno macro es un viento de "
        "cola o de frente para la solidez de un banco, y cuál es el factor que más pesa "
        "(inflación, actividad/IMAE, tasa de política, tipo de cambio, reservas)? Luego "
        "conéctalo al canal bancario: cómo cada factor material transmite a la calidad de "
        "cartera, el margen, el costo de fondeo o la liquidez —INTERPRETA el mecanismo, no "
        "recites la serie—. NO recorras los factores uno por uno: nombra los 2-3 que mueven "
        "la lectura y su dirección (favorable/adverso). Distingue lo que es entorno (común a "
        "todos los bancos) de lo idiosincrático de la entidad. Cierra con qué factor macro "
        "vigilar como señal adelantada. Este entorno es un TELÓN sistémico y NO forma parte "
        "del score standalone de la entidad (que mide fortaleza propia); no lo presentes como "
        "componente del rating. Usa SOLO las cifras de 'entorno_macro'; ninguna inventada; si "
        "un factor viene 'n/d', no lo cites."
    ),
    "banking_support_context": (
        "Lee el SOPORTE ESTRUCTURAL y el TECHO SOBERANO de esta entidad — la capa estilo "
        "Fitch (VR/GSR/IDR) que el score standalone deliberadamente NO incorpora.\n"
        "Contexto ('soporte_soberano': soporte estatal, importancia sistémica, techo soberano):\n"
        "{context}\n\n"
        "Máximo 250 palabras. REGLA DURA: esto es CONTEXTO, NO un componente del score SDQ. "
        "El SDQ mide fortaleza financiera STANDALONE RELATIVA dentro de RD y NO es un rating "
        "de crédito; NO afirmes que el soporte o el techo 'suben' o 'bajan' la calificación "
        "SDQ, ni inventes una nota ajustada. EMPIEZA por el veredicto: ¿esta entidad es "
        "sistémica y/o estatal, y qué implicaría eso para su solvencia efectiva en clave "
        "comparable? Desarrolla los tres ejes con las cifras del contexto: (1) soporte "
        "estatal (state_owned) — propiedad y su lectura; (2) importancia sistémica (cuota de "
        "activos/depósitos, rank) — too-big-to-fail; (3) techo soberano (rating, agencia, "
        "as_of) — que ancla cualquier lectura crediticia comparable, y por qué la fortaleza "
        "standalone puede exceder ese techo (no es crédito absoluto). SOPORTE = DOS PATAS: "
        "PROPENSIÓN (voluntad — de la propiedad estatal o del tamaño sistémico) Y CAPACIDAD "
        "(habilidad del soberano para costearlo). Sigue el 'support_assessment' del contexto: "
        "si el soberano es de grado ESPECULATIVO (score < 55, p.ej. BB), la capacidad está "
        "ACOTADA y el soporte es INCIERTO, no asumido —un rescate lo paga el soberano, no la "
        "doctrina—; NO presentes soporte 'plausible/probable' para un banco en un soberano "
        "débil sin decir en la misma frase que su capacidad fiscal lo limita. Para una entidad "
        "PRIVADA, deja claro que no hay respaldo derivado de propiedad. Cierra con la lectura "
        "práctica: para una contraparte local el standalone es la referencia; para comparación "
        "internacional faltarían incorporar el techo y el régimen de soporte. Usa SOLO las "
        "cifras del contexto; si un eje viene vacío, dilo sin inventar."
    ),
    "banking_compare": (
        "Compara las entidades del contexto entre sí — para una decisión de asignación o "
        "exposición.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 300 palabras. COMIENZA por el veredicto: cuál entidad lidera, cuál queda rezagada y "
        "en QUÉ dimensión se juega la diferencia que importa para la solidez. Respalda con la "
        "comparación material (no toda la tabla); interpreta qué significa cada brecha para la "
        "capacidad de pago, no solo el número. Cierra con la implicación de decisión. Usa SOLO las "
        "cifras del contexto; ninguna inventada."
    ),
    "banking_system": (
        "Lee la SALUD del sistema bancario (o del tipo de entidad) del contexto — perspectiva de "
        "sistema, no de una entidad.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. COMIENZA por el veredicto: ¿qué tan sólido y disperso está el sistema "
        "y cuál es la tensión que importa (concentración en la cola débil, dispersión "
        "líder-rezagado)? Respalda con la distribución (promedio, rango, líderes/rezagadas) "
        "interpretando qué significa, no recitando el ranking. Si hay 'contexto_oficial_bcrd', "
        "úsalo como telón sistémico y cita breve. Cierra con la señal a vigilar. Usa SOLO las "
        "cifras del contexto."
    ),
    "system_pulse": (
        "Entrega una PERSPECTIVA DE SISTEMA del sector bancario dominicano (nivel abierto, "
        "audiencia de mercado), a partir del agregado anonimizado:\n{context}\n\n"
        "Es una lectura de SISTEMA, no de una entidad: NUNCA nombres ni perfiles una entidad "
        "individual; no hay identificadores en el contexto y no debes inventarlos. Máximo 350 "
        "palabras, formato SCQA.\n"
        "Lee en este orden de prioridad: (1) SALUD AGREGADA — el score promedio del sistema y el "
        "peso del núcleo sólido (bandas Fuerte/Adecuado) frente a la cola de riesgo "
        "(Vigilancia/Crítico); (2) TRAYECTORIA — usa 'tendencia_score' (nivel actual vs. período "
        "previo) para distinguir un techo estabilizado de un piso en ascenso; (3) ESTRUCTURA — la "
        "concentración ('concentracion_activos': CR5/CR10/HHI) como condicionante de la estabilidad "
        "sistémica. Cierra con el 'y por tanto' para un inversionista: qué dice el agregado sobre el "
        "riesgo de contagio y dónde mirar.\n\n"
        "CIFRAS DERIVADAS: 'cifras_derivadas' YA trae el share por banda, la cola de riesgo, el "
        "núcleo sólido, la variación del score vs. el período previo y la concentración. Copia esos "
        "valores; NO recalcules porcentajes ni declares un superlativo (mayor/menor/el más…) que no "
        "coincida con lo servido. Si una relación no está precalculada, exprésala en palabras sin "
        "número. Trabajas con un AGREGADO: no exijas ni supongas desglose por entidad ni por "
        "dimensión que el sistema no provee — lee con firmeza lo que el agregado sí permite."
    ),
    "pension_pulse": (
        "Entrega una PERSPECTIVA DE SISTEMA del sistema dominicano de pensiones (SIPEN), a "
        "partir del agregado y de la dispersión entre AFP:\n{context}\n\n"
        "Máximo 350 palabras, formato SCQA. Es una lectura de SISTEMA con su dispersión, no un "
        "ranking del mes.\n"
        "Lee en este orden de prioridad: (1) SALUD AGREGADA — la rentabilidad del sistema (CCI/SDP) "
        "leída CONTRA SU PROMEDIO HISTÓRICO y AJUSTADA POR RIESGO, y el tamaño/trayectoria del fondo "
        "si se provee; (2) DISPERSIÓN ENTRE AFP — usa 'afp_rentabilidad' (líder, rezagada y la brecha "
        "entre ambas) como diferenciación competitiva, sin convertirlo en una carrera mensual; "
        "(3) ESTRUCTURA — cobertura y densidad de cotización como fragilidad del modelo si están en "
        "el contexto. Cierra con el 'y por tanto' para la audiencia.\n\n"
        "RENTABILIDAD NOMINAL: no afirmes rentabilidad real ni descuentes inflación si no está en "
        "el contexto. CIFRAS: usa solo las del contexto; si una relación (brecha, promedio) no está "
        "precalculada, exprésala en palabras sin número. Trabajas con un agregado + dispersión: no "
        "exijas desglose que el contexto no provee."
    ),
    "pension_peer_positioning": (
        "Sitúa a esta AFP frente a las 7 del sistema usando la TABLA DE PARES servida "
        "(dato real SIPEN), dimensión por dimensión:\n{context}\n\n"
        "Máximo 300 palabras. NO repitas el fundamento del ISA; aquí el foco es la POSICIÓN "
        "COMPETITIVA con NÚMEROS de los pares. Lee: (1) en qué dimensiones LIDERA y en cuáles "
        "REZAGA, citando el valor de los pares relevantes (líder y promedio del grupo), no en "
        "abstracto; (2) la BRECHA concreta con el líder donde más rezaga y qué la explica; (3) "
        "qué la diferencia estructuralmente del resto. El score de cada dimensión es POSICIÓN "
        "RELATIVA (peer min-max). Usa SOLO las cifras de la tabla; no inventes valores de pares "
        "que no estén. Cierra con el 'y por tanto' competitivo para la audiencia."
    ),
    "pension_portfolio_context": (
        "Lee la COMPOSICIÓN DE LA CARTERA de inversiones del sistema de pensiones (SIPEN, "
        "Cuadro 6.1 — dato real) como CONTEXTO DE RIESGO del ahorro que administra esta AFP:\n"
        "{context}\n\n"
        "Máximo 300 palabras. Es dónde está invertido el fondo del afiliado (nivel sistema, no "
        "por-AFP). Lee: (1) la CONCENTRACIÓN SOBERANA (Ministerio de Hacienda + Banco Central) y "
        "qué implica para la exposición del ahorro al riesgo del Estado y la profundidad financiera; "
        "(2) la exposición al SISTEMA FINANCIERO (banca) como fondeo institucional; (3) la "
        "DIVERSIFICACIÓN al sector privado/real (empresas, fideicomisos, fondos de inversión). "
        "Cierra con el 'y por tanto' para la audiencia. FOTO trimestral; NO juicio crediticio de "
        "un emisor. Usa solo las cifras del contexto (montos RD$ y %)."
    ),
    "pension_entity": (
        "Explica el FUNDAMENTO del Índice de Solidez (ISA) de esta AFP, con dato real de SIPEN.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. NO es un rating crediticio. El ENCUADRE lo define el contexto, no "
        "este prompt: si el contexto trae una 'band' y su 'note' indica que la SOLVENCIA está "
        "incorporada (estados financieros de SIPEN), nombra la banda absoluta de solidez (p.ej. "
        "'banda Adecuada') y trátala como una lectura de solidez con dato — NO digas que la "
        "solvencia es una brecha ni que las bandas están diferidas. Si en cambio el 'note' indica "
        "que para esta AFP la solvencia es una BRECHA declarada (sin estados financieros), dilo con "
        "claridad, NO inventes cifras de solvencia y NO afirmes solidez o fragilidad absoluta. "
        "Apóyate en: el score y (si hay) la banda, la posición relativa (rank), la(s) dimensión(es) "
        "que más la impulsan y las que más la lastran (pondera por su peso), y dónde lidera o rezaga "
        "frente a sus pares. Rentabilidad, escala, costo, riesgo y —cuando está— solvencia son dato "
        "SIPEN real.\n\n"
        "COBERTURA: si el 'coverage' es < 1 el índice es PARCIAL; nómbralo solo si es material. "
        "RENTABILIDAD: si el contexto trae 'rentabilidad_real_pct' + 'inflacion_interanual_pct', "
        "lee la rentabilidad en términos REALES (lo que gana el afiliado sobre la inflación), no "
        "solo la nominal — es la magnitud económica que importa; cita nominal e inflación como "
        "respaldo y usa 'trayectoria_rentabilidad_real' para la evolución. Léela vs su promedio, "
        "no como ranking del mes. Usa solo cifras del contexto; si una relación no está "
        "precalculada, exprésala sin número."
    ),
    "pension_cartera": (
        "Lee la COMPOSICIÓN DE LA CARTERA DE INVERSIONES de los fondos de pensiones "
        "(SIPEN, Cuadro 6.1 del boletín — dato real), por emisor y sub-sector:\n{context}\n\n"
        "Máximo 350 palabras, formato SCQA. Es la lectura de DÓNDE está invertido el ahorro "
        "previsional del país (el mayor bloque institucional), no un ranking ni un juicio "
        "crediticio de un emisor.\n"
        "Lee en este orden: (1) CONCENTRACIÓN SOBERANA — el peso de la deuda pública (Ministerio "
        "de Hacienda) y del Banco Central: los fondos como tenedor dominante de papel del Estado, "
        "y qué implica para la profundidad financiera y la exposición soberana del ahorro; "
        "(2) EXPOSICIÓN AL SISTEMA FINANCIERO — bancos y asociaciones (fondeo institucional a la "
        "banca); (3) SECTOR PRIVADO/REAL — empresas, fideicomisos y fondos de inversión como "
        "diversificación. Cierra con el 'y por tanto' para la audiencia.\n\n"
        "CIFRAS: usa solo las del contexto (montos RD$ y %); NO recalcules porcentajes ni declares "
        "un superlativo (mayor/menor/el más…) que no coincida con lo servido. Es una FOTO trimestral "
        "(no una serie). No emitas juicio de riesgo crediticio de un emisor individual; lee "
        "concentración, diversificación y rol institucional."
    ),
    "pension_system_indicator": (
        "Explica EN PROFUNDIDAD un SOLO indicador del sistema dominicano de pensiones "
        "(SIPEN, dato real), no el sistema entero:\n{context}\n\n"
        "Máximo 220 palabras. Lee: (1) el nivel actual y qué significa para la salud del "
        "sistema; (2) la TENDENCIA (la serie provista) — dirección, aceleración o reversión a "
        "la media, sin sobreinterpretar un mes; (3) el 'y por tanto' para la audiencia. RENTABILIDAD "
        "es NOMINAL (no afirmes real ni descuentes inflación si no está en el contexto). Usa solo "
        "las cifras del contexto; si una relación no está precalculada, exprésala sin número."
    ),
    "pension_afp_dimension": (
        "Explica EN PROFUNDIDAD una SOLA dimensión del Índice de Solidez (ISA) de una AFP "
        "(SIPEN, dato real), no el ISA completo:\n{context}\n\n"
        "Máximo 220 palabras. NO es un rating crediticio ni un veredicto absoluto: el score de la "
        "dimensión es POSICIÓN RELATIVA (peer min-max) entre las AFP. Lee: (1) el valor real de la "
        "AFP en esta dimensión y su POSICIÓN frente a los pares (rank); (2) la TENDENCIA si se "
        "provee; (3) qué implica para la solidez relativa y el 'y por tanto' para la audiencia. "
        "PROCEDENCIA: si la dimensión es SOLVENCIA y es brecha declarada (sin estados financieros), "
        "dilo y NO inventes cifra. Usa solo las cifras del contexto."
    ),
    "pension_cartera_item": (
        "Explica EN PROFUNDIDAD una SOLA posición de la cartera de inversiones de los fondos de "
        "pensiones (SIPEN, Cuadro 6.1 del boletín — dato real), no la cartera entera:\n{context}\n\n"
        "Máximo 220 palabras. Lee: (1) el peso de esta posición (emisor o sub-sector) en la cartera "
        "y qué implica su concentración; (2) su NATURALEZA — deuda pública (exposición soberana del "
        "ahorro), Banco Central, banca (fondeo institucional) o sector privado/real (diversificación); "
        "(3) el 'y por tanto' para la audiencia. Es una FOTO trimestral; NO emitas juicio de riesgo "
        "crediticio del emisor. Usa solo las cifras del contexto (montos RD$ y %)."
    ),
    "insurance_pulse": (
        "Entrega una PERSPECTIVA DE MERCADO del sector asegurador dominicano (nivel abierto, "
        "audiencia de mercado), a partir del agregado de la SIS:\n{context}\n\n"
        "Máximo 350 palabras, formato SCQA. Es una lectura de MERCADO, no de una aseguradora "
        "individual: no perfiles una compañía por su nombre salvo para ilustrar el líder o el "
        "rezagado del agregado. Lee en orden de prioridad: (1) SALUD AGREGADA — el nivel de "
        "solidez del mercado (ISF promedio, peso del núcleo sólido frente a la cola en "
        "vigilancia); (2) DISPERSIÓN — quién lidera y quién rezaga y por cuánto, como "
        "diferenciación competitiva; (3) ESTRUCTURA — concentración y mezcla de ramos como "
        "condicionante de la estabilidad del mercado. Cierra con el 'y por tanto' para la "
        "audiencia. Usa SOLO las cifras del contexto; si una relación no está precalculada, "
        "exprésala en palabras sin número."
    ),
    "insurance_market_context": (
        "Lee la ESTRUCTURA y la MEZCLA del mercado asegurador dominicano (dato real SIS) como "
        "CONTEXTO de la posición de esta aseguradora:\n{context}\n\n"
        "Máximo 300 palabras. Es una lectura de MERCADO (nivel sistema), no de una aseguradora. "
        "Lee: (1) la CONCENTRACIÓN del mercado (quién domina, cuota) y qué implica para la "
        "competencia y el poder de tarifa; (2) la MEZCLA de ramos y la dispersión de solidez "
        "entre compañías (núcleo sólido frente a cola débil); (3) el 'y por tanto' para la "
        "audiencia. No perfiles una aseguradora por su nombre si el contexto es agregado. Usa "
        "SOLO las cifras del contexto; si una relación no está precalculada, exprésala sin número."
    ),
    "insurance_peer_positioning": (
        "Sitúa a esta aseguradora frente a las del mercado usando la TABLA DE PARES servida "
        "(dato real SIS), dimensión por dimensión:\n{context}\n\n"
        "Máximo 300 palabras. NO repitas el fundamento del ISF; aquí el foco es la POSICIÓN "
        "COMPETITIVA con NÚMEROS de los pares. Lee: (1) en qué dimensiones LIDERA y en cuáles "
        "REZAGA, citando el valor de los pares relevantes (líder y promedio del grupo), no en "
        "abstracto; (2) la BRECHA concreta con el líder donde más rezaga y qué la explica; (3) "
        "qué la diferencia estructuralmente del resto. El score de cada dimensión es POSICIÓN "
        "RELATIVA entre las aseguradoras. Recuerda la dirección: MENOR siniestralidad es mejor. "
        "Usa SOLO las cifras de la tabla; no inventes valores de pares que no estén. Cierra con "
        "el 'y por tanto' competitivo para la audiencia."
    ),
    "insurance_entity": (
        "Explica el FUNDAMENTO del Índice de Solidez de la Aseguradora (ISF), con dato real de "
        "la SIS.\nContexto:\n{context}\n\n"
        "Máximo 350 palabras. NO es un rating de crédito ni un dictamen de solvencia. Apóyate "
        "en: el score y la banda de solidez, la posición relativa (rank) frente a las "
        "aseguradoras, y la(s) dimensión(es) que más la impulsan y las que más la lastran "
        "(pondera por su peso). Las cinco dimensiones son solvencia regulatoria (PTA/margen, "
        "Ley 146-02; ≥ 1 = cumple), siniestralidad (loss ratio; MENOR es mejor), liquidez "
        "regulatoria (disponible/mínimo; ≥ 1 = cumple), escala (activos) y resultado técnico "
        "(sobre primas). INTERPRETA cada tecnicismo por lo que significa para la capacidad de "
        "pagar siniestros y sostener resultado, no como cifra suelta. No cubras las cinco por "
        "igual: ve profundo en la tensión que más condiciona la decisión de la audiencia. Usa "
        "SOLO las cifras del contexto; si una relación no está precalculada, exprésala en "
        "palabras sin número."
    ),
    "risk_assessment": (
        "Explica el FUNDAMENTO del riesgo macro-político (IRMP) de este país.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. DIRECCIÓN: mayor score = MENOR riesgo (un score alto es bueno; la "
        "dimensión de mayor gap al techo es la que MÁS aporta al riesgo). No cubras las cinco "
        "dimensiones por igual: ve profundo en la que más condiciona la decisión de la audiencia, "
        "ponderando por su peso vía 'cifras_derivadas'. Sitúa al país en su panel regional. "
        "PROCEDENCIA: apóyate con firmeza en lo real (WGI/oficial); sobre lo de 'rúbrica "
        "declarada' no construyas conclusión fuerte y nómbralo cuando sea material.\n\n"
        "CIFRAS DERIVADAS: 'cifras_derivadas' YA trae el aporte y el gap al techo por dimensión, "
        "el líder vs la suma del resto, la dimensión de mayor gap y el orden por peso. Copia esos "
        "valores; NO recalcules aportes ni declares un superlativo (mayor/menor/el más…) que no "
        "coincida con lo servido. Si una relación no está precalculada, exprésala en palabras sin "
        "número."
    ),
    "trade_outlook": (
        "Explica el FUNDAMENTO de la resiliencia comercial del país.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. DIVERSIFICACIÓN > VOLUMEN: ve profundo en la concentración de la "
        "canasta exportadora (HHI, capítulos dominantes y sus shares) y en la dependencia de "
        "importaciones, según lo que más condiciona la decisión de la audiencia — no restates "
        "los totales. Usa EXCLUSIVAMENTE las cifras del contexto (resilience_score, hhi_exports, "
        "export_diversification, import_dependency, shares de los top capítulos); NO inventes "
        "cifras ni detalle por país socio (no disponible). Si una cifra no está, dilo."
    ),
    "energy_outlook": (
        "Explica el FUNDAMENTO de la resiliencia del sector eléctrico (IRSE).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Ve profundo en lo que más condiciona la decisión de la audiencia "
        "entre las DOS dimensiones con dato real: adecuación de capacidad (ritmo de expansión "
        "del parque vs demanda ~4%/año) y calidad de servicio (backlog de reclamaciones en "
        "meses). Usa EXCLUSIVAMENTE las cifras del contexto (irse_score, coverage, capacity_mw, "
        "capacity_growth_cagr_3y, service_backlog_months, contribuciones por dimensión). "
        "PROCEDENCIA/HONESTIDAD: la TRANSICIÓN energética (renovable/carbono) es BRECHA declarada "
        "sin dato confiable — NO afirmes nada cuantitativo sobre renovables ni intensidad de "
        "carbono, y aclara que el índice cubre 2 de 3 dimensiones (coverage). Si una cifra no "
        "está, dilo; no inventes."
    ),
    "tourism_outlook": (
        "Explica el FUNDAMENTO de la tracción de demanda del sector turismo (ITT).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Ve profundo en lo que más condiciona la decisión de la "
        "audiencia entre las dimensiones con dato real: demanda total y demanda extranjera "
        "(CAGR a 3 años de las llegadas de no residentes), resiliencia/recuperación (nivel "
        "vs pico pre-pandemia) y diversificación de mercados (concentración por región "
        "emisora). Usa EXCLUSIVAMENTE las cifras del contexto (itt_score, coverage, "
        "nonresident_arrivals, foreign_arrivals, recovery_vs_prepandemic_pct, "
        "top_origin_region, top_origin_share_pct, y el CAGR/score por dimensión). Distingue "
        "VOLUMEN/CRECIMIENTO de DIVERSIFICACIÓN (riesgo de origen): una demanda fuerte puede "
        "convivir con alta concentración de un mercado. HONESTIDAD: el índice mide DEMANDA, "
        "no oferta — NO hay ocupación hotelera, ingresos por turismo (divisas) ni gasto "
        "(el BCRD discontinuó esas series estructuradas en 2018-2019; hoy solo viven en PDFs "
        "narrativos, sin serie limpia); no los afirmes. Dato anual agregado "
        "nacional, sin backtest. Si una cifra no está, dilo; no inventes."
    ),
    "telecom_outlook": (
        "Explica el FUNDAMENTO del desarrollo del sector telecom (IDT).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Distingue ALCANCE (penetración) de CALIDAD (banda ancha) según lo "
        "que más condiciona la decisión de la audiencia. Usa EXCLUSIVAMENTE las cifras del "
        "contexto (idt_score, mobile_penetration, internet_penetration, broadband_share, "
        "revenue_growth, contribuciones por dimensión). La móvil suele estar saturada (>100/100) "
        "y el margen está en internet/banda ancha — léelo así. HONESTIDAD: sé explícito con la "
        "ANTIGÜEDAD del boletín (período del contexto); no proyectes ni inventes cifras más "
        "recientes. Si una cifra no está, dilo."
    ),
    "free_zones_outlook": (
        "Explica el FUNDAMENTO de la atractividad del sector de zonas francas (IZF).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Ve profundo en lo que más condiciona la decisión de la audiencia "
        "entre las dimensiones con dato real: dinamismo exportador, atracción de inversión, "
        "generación de empleo y productividad (exportaciones por empresa). Cada una se mide por "
        "su ritmo de crecimiento (CAGR a 3 años) contra un objetivo. Usa EXCLUSIVAMENTE las "
        "cifras del contexto (izf_score, coverage, niveles del último año —empresas, empleos, "
        "exportaciones US$, inversión US$— y el CAGR/score por dimensión). Distingue ESCALA "
        "(niveles) de DINAMISMO (crecimiento). HONESTIDAD: dato anual agregado nacional de la "
        "CNZFE; sin desglose por sub-sector industrial ni validación retrospectiva de resultados. Si una cifra no "
        "está, dilo; no inventes."
    ),
    "construction_outlook": (
        "Explica el FUNDAMENTO de la coyuntura del sector construcción (ICC).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Ve profundo en lo que más condiciona la decisión de la audiencia "
        "entre las dimensiones con dato real: producción del sector (crecimiento real del PIB "
        "de construcción, BCRD), flujo de permisos (CAGR a 3 años de m² licenciados, MIVHED), "
        "diversificación tipológica y amplitud geográfica (HHI). Usa EXCLUSIVAMENTE las cifras "
        "del contexto (icc_score, coverage, construction_gdp_growth_3y_pct, los niveles del año "
        "—permits, sqm_licensed, investment_licensed_mm_dop, top_typology/top_province— y el "
        "score/metric por dimensión). Distingue actividad LÍDER (permisos, lo que viene) de "
        "PRODUCCIÓN realizada (PIB, lo ya hecho): si divergen, esa divergencia es la lectura. "
        "HONESTIDAD: dato anual agregado nacional; permisos MIVHED desde 2022 (historia corta "
        "para ese flujo); la inversión licenciada es NOMINAL en RD$ (no ejecutada), no la "
        "confundas con inversión real ni con el PIB; sin validación retrospectiva de resultados. Si una cifra no "
        "está, dilo; no inventes."
    ),
    "social_outlook": (
        "Explica el FUNDAMENTO del desarrollo (IDM) de esta región.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Ve profundo en la dimensión que más condiciona la decisión de la "
        "audiencia, ponderando por su peso vía 'cifras_derivadas'. LEE DESIGUALDAD: sitúa la "
        "región en la distribución (rank, dispersión). PROCEDENCIA: apóyate en lo 'real'; sobre "
        "lo 'parcial'/'rúbrica declarada' no construyas conclusión fuerte, y aclara cuando una "
        "brecha venga de un dato nacional aplicado plano (no diferenciación regional real).\n\n"
        "CIFRAS DERIVADAS: 'cifras_derivadas' YA trae el aporte y el gap al techo por dimensión, "
        "el líder vs la suma del resto, la dimensión de mayor gap y el orden por peso. Copia esos "
        "valores; NO recalcules aportes ni declares un superlativo (mayor/menor/el más…) que no "
        "coincida con lo servido. Si una relación no está precalculada, exprésala sin número."
    ),
    "macro_trend": (
        "Analiza la tendencia de UNA serie macroeconómica (dato real BCRD).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 300 palabras. Distingue NIVEL de MOMENTUM (cambio y aceleración); lee la "
        "dirección correcta de la serie (si subir es bueno o malo). Usa EXCLUSIVAMENTE las "
        "cifras del contexto (latest_value, change, pct_change, acceleration, recent_observations); "
        "NO inventes valores ni proyecciones. Conecta con la implicación para la audiencia."
    ),
    "macro_snapshot": (
        "Analiza la COYUNTURA macroeconómica del período (dato real BCRD).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. No repases todas las series: ve a las señales tempranas "
        "('signals') y a los 'top_movers' que más mueven la aguja por aceleración, y conecta con "
        "la decisión de la audiencia. Usa EXCLUSIVAMENTE las cifras del contexto; NO inventes "
        "valores. Si 'contexto_oficial_bcrd' incluye la última decisión de política monetaria del "
        "BCRD, señala la postura vigente —nivel de la TPM y sentido de la decisión— y conéctala con "
        "la coyuntura; el resto del contexto oficial úsalo como telón y cítalo breve."
    ),
    "mp_evaluation": (
        "Evalúa la POSTURA de política monetaria del BCRD y su impacto macro (dato real BCRD).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 380 palabras. Lee la 'trayectoria_reciente' y el 'ciclo' (holds/cortes/alzas, "
        "nivel de TPM actual vs 12 y 24 decisiones atrás) para caracterizar la FASE del ciclo "
        "(restrictiva, neutral, de distensión o de ajuste). Valora la coherencia de la "
        "'postura_actual' con el 'contexto_macro' (inflación vs meta, actividad): dado el balance "
        "de riesgos, ¿la postura es adecuada, rezagada o anticipada? Comenta el IMPACTO y la "
        "transmisión esperados (crédito, actividad, tipo de cambio). Conecta con la decisión de la "
        "audiencia. Usa EXCLUSIVAMENTE las cifras del contexto; NO inventes valores. Si "
        "'has_data' es falso, dilo en una línea."
    ),
    "fiscal_pulse": (
        "Analiza el PULSO FISCAL del Gobierno Central (dato real Hacienda/DGII).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 300 palabras. Foco en la trayectoria del déficit (deficit_ultimos_12m), el "
        "balance entre ingresos y gastos y las top líneas de recaudación — no cada punto "
        "mensual. Usa EXCLUSIVAMENTE las cifras del contexto; NO inventes valores. Si "
        "'has_data' es falso, dilo en una línea. Conecta con la implicación para la audiencia."
    ),
    "climate_outlook": (
        "Explica el FUNDAMENTO de la resiliencia climática (IRC) de este país.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. DIRECCIÓN: mayor score = mayor resiliencia / menor riesgo (la "
        "dimensión de mayor gap al techo es la que más fragiliza). Ve profundo en la dimensión "
        "que más condiciona la decisión de la audiencia, ponderando por su peso vía "
        "'cifras_derivadas'. El IRC es 100% dato real (HURDAT2/Ember/ND-GAIN) — apóyate con "
        "firmeza. LEE DISTRIBUCIÓN: sitúa al país en el panel (rank, dispersión).\n\n"
        "CIFRAS DERIVADAS: 'cifras_derivadas' YA trae el aporte y el gap al techo por dimensión, "
        "el líder vs la suma del resto, la dimensión de mayor gap y el orden por peso. Copia esos "
        "valores; NO recalcules aportes ni declares un superlativo (mayor/menor/el más…) que no "
        "coincida con lo servido. Si una relación no está precalculada, exprésala sin número."
    ),
    # Informe de Contexto de Mercado (brand_intel): tres secciones narradas por el cerebro
    # sobre lo que el motor determinista (engines/explain.py + service) YA calculó. El LLM
    # sintetiza; nunca decide causalidad ni recalcula el reparto explicadas/competitivas.
    "brand_context_executive": (
        "Redacta el RESUMEN EJECUTIVO del Informe de Contexto de Mercado del trimestre: la "
        "síntesis de qué le pasó a la marca y a su entorno entre las olas del contexto — NO "
        "un conteo de hallazgos ni un inventario de secciones.\nContexto:\n{context}\n\n"
        "Máximo 180 palabras, 1-2 párrafos corridos, sin encabezados ni viñetas. ABRE con la "
        "lectura del trimestre (qué movió la aguja y de quién es el movimiento: entorno, "
        "categoría o marca), respáldala con las 2-3 cifras que más importan y cierra con el "
        "foco del próximo trimestre. NO enumeres las conclusiones del proveedor una por una "
        "ni digas cuántas fueron explicadas: sintetiza. REGLA DURA DE CIFRAS: usa SOLO "
        "números servidos en el contexto; no derives ni inventes ninguno. REGLA DURA DE "
        "CAUSALIDAD: la lectura entorno-vs-marca de cada movimiento ya viene decidida en el "
        "contexto ('explicadas'/'competitivas'); no la recalcules ni la contradigas."
    ),
    "brand_context_reading": (
        "Redacta la LECTURA DEL TRIMESTRE del Informe de Contexto de Mercado: lo que el "
        "estudio del proveedor concluye, leído con los datos de entorno de SDQ.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras, prosa corrida (viñetas solo si agrupan de verdad; SIN "
        "encabezados — el documento ya titula la sección). El lector "
        "YA LEYÓ el informe del proveedor: NO repitas sus conclusiones una por una ni uses "
        "el patrón «el proveedor concluye X / lectura SDQ Y». Estructura por GRUPOS de "
        "lectura: (1) el entorno del período, declarado UNA vez con sus valores; (2) qué "
        "movimientos de consumo/gasto ese entorno ayuda a explicar ('explicadas' — sintetiza "
        "el mecanismo común; cita textual al proveedor SOLO cuando la cifra sostiene el "
        "argumento, máximo 2-3 citas en toda la sección); (3) qué movimientos el entorno NO "
        "explica ('competitivas' — la negativa es la lectura: percepción es dinámica "
        "competitiva, accionable por la marca; léelas por grupo y dirección, no una frase "
        "por conclusión). REGLA DURA DE CAUSALIDAD: el reparto explicadas/competitivas y la "
        "lectura de cada una ya vienen decididos por el motor determinista; sintetiza y "
        "prioriza, NUNCA recalcules, amplíes ni contradigas ese reparto. REGLA DURA DE "
        "CIFRAS: usa SOLO números servidos en el contexto; no derives ni inventes ninguno."
    ),
    "brand_context_priorities": (
        "Redacta la sección QUÉ MOVER Y QUÉ NO del Informe de Contexto de Mercado: la "
        "agenda accionable del trimestre cruzada con la disciplina de señal (qué movimiento "
        "puede sostener una decisión).\nContexto:\n{context}\n\n"
        "Máximo 300 palabras, SIN encabezados (el documento ya titula la sección). "
        "Integra en UNA lectura: (1) los puntos que el trimestre "
        "justifica discutir ('agenda'), en su orden de prioridad; (2) la disciplina de "
        "umbral: qué movimientos superan el mínimo detectable de la muestra y cuáles no "
        "alcanzan para decidir ('filtro_senal' — si ningún indicador superó su umbral, esa "
        "continuidad ES la lectura del trimestre); (3) los riesgos que podrían invalidar la "
        "lectura ('escenarios'), como reserva declarada, no como pronóstico propio. Cierra "
        "con el reparto de foco del próximo trimestre: qué mover, qué no tocar y qué esperar "
        "a confirmar con la próxima ola. NO inventes prioridades que no estén en 'agenda'; "
        "si la agenda viene vacía, dilo: el trimestre no justifica una discusión "
        "extraordinaria.\n"
        "REGLA DURA DE SIGNIFICANCIA: en 'filtro_senal', «publishable» dice que la base "
        "sostiene publicar el NIVEL de la métrica; NO dice que ningún movimiento sea "
        "significativo. Qué se movió y con qué veredicto está COMPUTADO en "
        "'veredictos_de_movimiento' — copialo. Está PROHIBIDO escribir que una MÉTRICA "
        "«supera su umbral mínimo detectable»: lo que supera un umbral es un MOVIMIENTO "
        "entre dos olas. Del filtro de señal se dice qué decisión podría sostener la base, "
        "nunca qué cambió.\n"
        "REGLA DURA DE COMPARABILIDAD: comparar el NIVEL de dos indicadores distintos "
        "está PROHIBIDO salvo que la pareja venga servida en "
        "'brechas_entre_indicadores'. Esas son peldaños consecutivos del embudo —una "
        "escalera anidada—, y por eso su hueco es una subpoblación con margen de error "
        "y sujeto ya computados: copiá la brecha, su margen, su veredicto y su "
        "'sujeto_de_la_brecha', no los redactes de nuevo. Para cualquier otra pareja "
        "—por ejemplo fidelidad contra opinión de marca— la diferencia NO tiene margen "
        "estimable con este instrumento: no la enunciés como distancia, ni la califiques "
        "de alta o baja una respecto de la otra, ni construyas una recomendación sobre "
        "ella. Los niveles se reportan uno al lado del otro, sin relación entre ellos. "
        "REGLA DURA DE CIFRAS: usa SOLO números servidos en el contexto "
        "(umbrales, movimientos, bases muestrales); no derives ni inventes ninguno."
    ),
    "brand_sdq_proposals": (
        "Redacta la sección PLANES DERIVADOS DE LA EVIDENCIA del Informe de Contexto de "
        "Mercado: propuestas de acción que se desprenden EXCLUSIVAMENTE de lo medido en "
        "este mismo informe, sin recurso a ninguna fuente externa."
        "\nContexto:\n{context}\n\n"
        "Máximo 320 palabras, SIN encabezados de ningún nivel —el documento ya titula la "
        "sección y repetirlo la duplica—. Propón entre DOS y CUATRO planes, cada uno con "
        "esta anatomía en prosa continua: la observación que lo "
        "motiva —citando la cifra del contexto que la sostiene—, la acción concreta, y el "
        "indicador con el que se verificará junto al movimiento mínimo que lo validaría "
        "tomado de 'umbrales_de_decision'. Un plan cuya verificación no puedas anclar a "
        "un indicador con umbral servido NO se propone: proponer sin forma de verificar es "
        "exactamente lo que este informe reprocha a un plan.\n"
        "REGLA DURA DE EVIDENCIA: cada propuesta nace de 'evidencia_de_venta' o "
        "'evidencia_de_percepcion'. Está PROHIBIDO proponer sobre conocimiento general de "
        "la categoría, sobre buenas prácticas de marketing o sobre lo que suele funcionar: "
        "si la evidencia del contexto no sostiene la propuesta, la propuesta no existe. "
        "REGLA DURA DE SIGNIFICANCIA: el veredicto de cada movimiento viene COMPUTADO en "
        "'veredictos_de_movimiento' — copialo, no lo deduzcas. Un movimiento listado "
        "en 'no_detectables' NO puede ser la premisa de un plan: si lo mencionás, "
        "nombralo como no distinguible del azar y presentalo como motivo de "
        "SEGUIMIENTO, nunca como hallazgo. Está PROHIBIDO decir que una MÉTRICA «se "
        "distingue del azar» o «supera su umbral»: lo que supera un umbral es un "
        "MOVIMIENTO, y el «publishable» del bloque de umbrales solo dice que la base "
        "sostiene publicar el nivel. Si 'n_detectables' es 0, la sección lo DECLARA y "
        "las propuestas se apoyan en niveles, en brechas del instrumento o en el "
        "expediente — nunca en un cambio inexistente. "
        "REGLA DURA DE COMPARABILIDAD: comparar el NIVEL de dos indicadores distintos "
        "está PROHIBIDO salvo que la pareja venga servida en "
        "'brechas_entre_indicadores'. Esas son peldaños consecutivos del embudo —una "
        "escalera anidada—, y por eso su hueco es una subpoblación con margen de error "
        "y sujeto ya computados: copiá la brecha, su margen, su veredicto y su "
        "'sujeto_de_la_brecha', no los redactes de nuevo. Para cualquier otra pareja "
        "—por ejemplo fidelidad contra opinión de marca— la diferencia NO tiene margen "
        "estimable con este instrumento: no la enunciés como distancia, ni la califiques "
        "de alta o baja una respecto de la otra, ni construyas una recomendación sobre "
        "ella. Los niveles se reportan uno al lado del otro, sin relación entre ellos. "
        "REGLA DURA DE CIFRAS: usa solo los números servidos; no derives ni estimes "
        "magnitudes de impacto que ningún motor computó — si no puedes dimensionar el "
        "retorno, dilo en palabras sin número.\n"
        "NO DUPLIQUES lo ya comprometido: 'compromisos_ya_registrados' trae lo que el "
        "cliente y SDQ ya tienen en seguimiento; una propuesta que repita uno de ellos no "
        "aporta. Si una brecha del instrumento ('brechas_del_instrumento') impide medir "
        "algo relevante, la propuesta legítima es incorporar ese dato, y así se formula. "
        "Cierra declarando que estas propuestas se registran en el mismo expediente que "
        "los planes del cliente y se evalúan ola tras ola con idéntico criterio."
    ),
    "brand_sdq_proposals_practice": (
        "Redacta la sección PLANES CON PRÁCTICA SECTORIAL ANCLADA EN LA EVIDENCIA del "
        "Informe de Contexto de Mercado. A diferencia de la sección anterior —que se "
        "limita a lo que el dato indica por sí solo— aquí SÍ puedes incorporar práctica "
        "sectorial acreditada, bajo una condición que no admite excepción: la práctica "
        "aporta el CÓMO, y el dato del contexto debe acreditar que la situación que esa "
        "práctica atiende EXISTE en este negocio.\nContexto:\n{context}\n\n"
        "Máximo 320 palabras, SIN encabezados de ningún nivel. Propón entre DOS y TRES "
        "planes. Cada uno se estructura así, en prosa continua: (1) la cifra del contexto "
        "que acredita la situación —sin ella la propuesta no existe—; (2) la práctica "
        "sectorial que la atiende, DECLARANDO de forma expresa que es una práctica del "
        "sector y no una lectura de los datos del cliente («la práctica sectorial en "
        "servicio rápido indica que…», «es una convención de la categoría, no una "
        "conclusión de su información»); (3) la acción concreta que resulta de aplicar "
        "esa práctica a esta situación; (4) el indicador con el que se verificará y el "
        "movimiento mínimo que lo validaría, tomados de 'umbrales_de_decision'.\n"
        "REGLA DURA DE SIGNIFICANCIA: el veredicto de cada movimiento viene COMPUTADO en "
        "'veredictos_de_movimiento' — copialo, no lo deduzcas. Un movimiento listado "
        "en 'no_detectables' NO puede ser la premisa de un plan: si lo mencionás, "
        "nombralo como no distinguible del azar y presentalo como motivo de "
        "SEGUIMIENTO, nunca como hallazgo. Está PROHIBIDO decir que una MÉTRICA «se "
        "distingue del azar» o «supera su umbral»: lo que supera un umbral es un "
        "MOVIMIENTO, y el «publishable» del bloque de umbrales solo dice que la base "
        "sostiene publicar el nivel. Si 'n_detectables' es 0, la sección lo DECLARA y "
        "las propuestas se apoyan en niveles, en brechas del instrumento o en el "
        "expediente — nunca en un cambio inexistente. "
        "REGLA DURA DE COMPARABILIDAD: comparar el NIVEL de dos indicadores distintos "
        "está PROHIBIDO salvo que la pareja venga servida en "
        "'brechas_entre_indicadores'. Esas son peldaños consecutivos del embudo —una "
        "escalera anidada—, y por eso su hueco es una subpoblación con margen de error "
        "y sujeto ya computados: copiá la brecha, su margen, su veredicto y su "
        "'sujeto_de_la_brecha', no los redactes de nuevo. Para cualquier otra pareja "
        "—por ejemplo fidelidad contra opinión de marca— la diferencia NO tiene margen "
        "estimable con este instrumento: no la enunciés como distancia, ni la califiques "
        "de alta o baja una respecto de la otra, ni construyas una recomendación sobre "
        "ella. Los niveles se reportan uno al lado del otro, sin relación entre ellos. "
        "REGLA DURA DE CIFRAS: usa solo los números servidos en el contexto. "
        "No atribuyas a una práctica ningún IMPACTO NUMÉRICO que no "
        "esté servido en el contexto: nada de «suele elevar la frecuencia un 15%» ni "
        "rangos inventados de retorno — si no puedes dimensionar el efecto con una cifra "
        "del contexto, exprésalo en palabras SIN número. No cites estudios, casos ni "
        "marcas concretas como evidencia salvo que aparezcan en "
        "'practicas_en_el_expediente', que recoge lo que los propios documentos del "
        "cliente ya afirman; una práctica que no puedas atribuir ni al expediente ni a "
        "convención general declarada como tal, no se propone. Una cifra tomada de "
        "'practicas_en_el_expediente' se atribuye AL DOCUMENTO que la afirma, con su "
        "lámina, y NO se le aplica el reparo de base muestral: es un dato declarado "
        "por el cliente, no una medición del tracker, y confundir ambos orígenes "
        "desdibuja de dónde viene cada número. No repitas las propuestas "
        "de la sección anterior ('propuestas_ya_formuladas') ni los compromisos ya "
        "registrados: esta sección COMPLEMENTA, no reformula.\n"
        "Cierra recordando que la separación entre ambas secciones es deliberada: lo que "
        "aquí se propone incorpora criterio externo, y por eso se distingue de lo que el "
        "dato sostiene por sí mismo."
    ),
    "brand_wave_comparison": (
        "Redacta la sección LA OLA CONTRA SUS DOS REFERENCIAS del Informe de Contexto de "
        "Mercado: cada indicador núcleo leído contra la ola anterior y contra la ola de "
        "referencia interanual.\nContexto:\n{context}\n\n"
        "Máximo 300 palabras, prosa corrida, SIN encabezados. La lectura que esta sección "
        "aporta y ninguna otra da es la SEPARACIÓN entre movimiento de trimestre y "
        "movimiento de ciclo: un indicador que cae contra la ola anterior pero sube contra "
        "el año pasado describe estacionalidad, no deterioro; uno que cae contra ambas "
        "describe deterioro sostenido. Esa clasificación viene servida en el campo "
        "'combined' de cada indicador de 'indicadores_comparados' —deterioro_sostenido, mejora_sostenida, estacional, "
        "solo_interanual, solo_intertrimestral, sin_movimiento_detectable—: úsala, NO la "
        "deduzcas. Prioriza los 2-3 indicadores cuya lectura combinada más importa y "
        "agrega el resto; no recorras la tabla. DECLARA LA DISTANCIA REAL de la referencia "
        "interanual: el campo 'marco' trae los meses efectivos, y cuando no son doce el "
        "lector necesita saberlo porque condiciona la lectura de estacionalidad — dilo en "
        "la misma frase en que uses la comparación. DISCIPLINA DE UMBRAL: un movimiento "
        "cuyo 'is_finding' es falso NO es un hallazgo, venga de la comparación que venga; "
        "si ningún indicador supera su mínimo detectable en ninguna de las dos bases, esa "
        "continuidad ES la lectura y así se dice. Si un indicador viene sin base muestral "
        "('base_n' nulo, veredicto 'unscoreable'), su movimiento se lee como trayectoria y "
        "NO puede sostener un veredicto: decláralo. REGLA DURA DE CIFRAS: usa solo los "
        "números servidos (valor, delta, umbral, meses de distancia); ninguno se recalcula."
    ),
    "brand_sales_reading": (
        "Redacta la sección LA VENTA DEL PERÍODO del Informe de Contexto de Mercado: la "
        "lectura de la facturación del operador cruzada con lo que el estudio de mercado "
        "mostró.\nContexto:\n{context}\n\n"
        "Máximo 320 palabras, 3-4 párrafos de prosa corrida, SIN encabezados ni listas. "
        "ABRE con la lectura que solo este cruce permite: de dónde viene el movimiento de "
        "facturación —afluencia o gasto por visita— usando "
        "'composicion_del_crecimiento'; una encuesta no observa transacciones, así que "
        "esta descomposición es el aporte central de la sección. Sigue con el gasto REAL "
        "('cheque_real'): un cheque nominalmente estable con inflación positiva es una "
        "caída del poder adquisitivo por visita, y esa es la lectura, no el nominal. "
        "Cubre después la dispersión que el agregado oculta: la plaza y el canal que se "
        "apartan ('por_plaza', 'por_canal', 'plazas_en_contraccion'), priorizando los 2-3 "
        "casos que más se juegan y agregando el resto — NO recorras todas las plazas ni "
        "todos los canales. Cierra conectando con la percepción del estudio: cuando una "
        "plaza crece en venta sin sostén de preferencia declarada, o cuando el canal que "
        "crece es el que registró deterioro de servicio, ESA tensión es la lectura. "
        "REGLA DURA DE CIFRAS: usa SOLO los números servidos; el reparto entre tráfico y "
        "cheque, el cheque real y las variaciones por plaza y canal YA vienen calculados "
        "por el motor determinista — nárralos, NUNCA los recalcules ni derives cifras "
        "nuevas. DECLARA LAS BRECHAS que el contexto trae: si 'ventana_comparable' "
        "excluye jornadas, dilo; si 'cheque_real' indica que el índice de precios no "
        "cubre el tramo, dilo en la misma frase en que uses la cifra real; si "
        "'consistencia' no reconcilia, publica el desglose por canal con esa reserva."
    ),
    "brand_sales_projection": (
        "Redacta la sección LA VENTA QUE VIENE del Informe de Contexto de Mercado: el "
        "pronóstico de tráfico y cheque por local, con lo que el propio modelo declara "
        "sobre su precisión.\nContexto:\n{context}\n\n"
        "Máximo 300 palabras, 3 párrafos de prosa corrida, SIN encabezados ni listas. "
        "ABRE con el reparto de la incertidumbre: usa "
        "'pct_incertidumbre_venta_que_aporta_el_trafico' para decir cuál de los dos "
        "componentes gobierna el pronóstico. Si el tráfico domina, la lectura es que "
        "discutir el pronóstico de venta es discutir afluencia, y el cheque es la parte "
        "predecible. Sigue con la precisión medida: el error del tráfico y el del cheque "
        "contra 'error_de_la_vara_trafico_pct', que es lo que se obtendría sin modelo. "
        "Cierra con la dispersión entre locales, priorizando los 2-3 casos que más se "
        "juegan — NO recorras los treinta.\n"
        "REGLA DURA DE COBERTURA: el informe NO puede hablar de la red entera con la "
        "precisión del agregado. Menciona SIEMPRE cuántos locales de "
        "'locales_en_el_panel' son proyectables, y nombra los de "
        "'locales_no_proyectables_con_motivo' con su motivo. Un local excluido que no se "
        "nombra desaparece sin aviso y el documento afirma una cobertura que no tiene.\n"
        "REGLA DURA DE BANDA: cada local trae SU banda en 'banda_lo_pct' y 'banda_hi_pct', "
        "y son distintas entre locales porque su dispersión difiere. NUNCA presentes una "
        "banda única como si valiera para todos, y NUNCA cites un punto proyectado sin su "
        "banda: un pronóstico sin banda se lee como una promesa.\n"
        "REGLA DURA DE SESGO: si 'pct_jornadas_en_que_el_real_supero_al_pronostico' se "
        "aparta de 50, dilo explícitamente con esa cifra. Un pronóstico que corre corto y "
        "no lo declara induce a leer cada superación como un logro.\n"
        "REGLA DURA DE CIFRAS: usa SOLO los números servidos. El reparto de la "
        "incertidumbre, los errores, las bandas y la calibración YA vienen calculados por "
        "el motor determinista — nárralos, NUNCA los recalcules ni derives cifras nuevas, "
        "y no proyectes tú ningún valor que el contexto no traiga.\n"
        "PROHIBIDO: presentar el pronóstico como lo que va a pasar. Es lo que ocurriría de "
        "sostenerse el patrón reciente, y el horizonte es el de 'horizonte_dias'. Si "
        "'varianza_de_la_venta' está, puedes apoyarte en ella para explicar POR QUÉ el "
        "modelo funciona, pero sin convertir la explicación en el centro de la sección."
    ),
    "brand_plan_readiness": (
        "Redacta la sección EL PLAN BAJO EL INSTRUMENTO del Informe de Contexto de "
        "Mercado: la lectura ESTRATÉGICA del plan que el cliente compartió, cruzada con "
        "lo que el instrumento de medición puede certificar hoy.\nContexto:\n{context}\n\n"
        "Máximo 300 palabras, 2-4 párrafos de prosa corrida, SIN encabezados ni listas. "
        "EL LECTOR ES EL DUEÑO DEL PLAN: él lo escribió — jamás se lo repitas punto por "
        "punto, no enumeres sus metas ni sus acciones, no lo describas. Tu aporte es la "
        "SÍNTESIS con juicio: (1) qué apuesta hace el plan como estrategia y en qué se "
        "juega, leída desde 'metas_extraidas' y 'acciones_del_plan' de forma agregada, y "
        "cómo conversa con la tensión que el trimestre mostró — SIN repetir lo que las "
        "otras secciones ya narraron; (2) qué puede CERTIFICAR el instrumento hoy: usa "
        "los veredictos mecánicos de 'compromisos_medibles' y prioriza los 2-3 que más "
        "se juegan — el resto agrégalo (la nota del motor ya trae el conteo), nunca en "
        "inventario; (3) qué falta para medir el resto y A QUIÉN pedírselo, agregado "
        "por tipo de brecha: cortes del tracker → al proveedor en la próxima entrega; "
        "series → a la carga SDQ; fuentes externas → al cliente o sus plataformas. "
        "IMPARCIALIDAD: un corte sin cargar es un hueco de NUESTRA base — atribúyelo a "
        "la carga SDQ, nunca al proveedor ni al cliente. REGLA DURA DE VEREDICTOS: el "
        "estado evaluable/inevaluable y el mínimo detectable ya vienen calculados; "
        "nárralos y priorízalos, NUNCA los recalcules ni los contradigas — la "
        "aritmética muestral no es tuya. REGLA DURA DE CIFRAS: usa SOLO números "
        "servidos en el contexto; un compromiso que no esté en el contexto NO existe."
    ),
    "deal_outlook": (
        "Explica el FUNDAMENTO del score de atractivo/cierre de este deal.\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Es una RÚBRICA declarada anclada a IRMP/IAI/IRC, NO una "
        "probabilidad ni modelo entrenado — dilo si es material. Ve profundo en el driver que "
        "más condiciona la decisión de la audiencia, ponderando por su peso vía "
        "'cifras_derivadas'. SÉ HONESTO con la confianza: nombra qué drivers son juicio del "
        "analista vs dato de eje, y si falta un driver clave.\n\n"
        "CIFRAS DERIVADAS: 'cifras_derivadas' YA trae el aporte y el gap al techo por driver, "
        "el líder vs la suma del resto, el de mayor gap y el orden por peso. Copia esos valores; "
        "NO recalcules aportes ni declares un superlativo que no coincida con lo servido. NO "
        "inventes cifras del deal que no estén en el contexto."
    ),
}

# Static fallback prose for when the API key is unavailable or a call fails. Self-
# contained (NO `{}` placeholders → nunca se filtran tokens crudos a un PDF) y sin
# encabezado redundante (el render ya rotula la sección). Texto profesional y neutro.
STATIC_FALLBACKS = {
    "executive_summary": (
        "Este resumen integra los indicadores financieros del período evaluado en una "
        "lectura ejecutiva del perfil de la entidad: solidez de capital, calidad de la "
        "cartera, eficiencia, liquidez y diversificación, ponderados según la metodología "
        "de calificación SDQ. El detalle por dimensión se desarrolla en las secciones "
        "siguientes."
    ),
    "risk_assessment": (
        "El perfil de riesgo se evalúa integrando la solidez financiera, la calidad de la "
        "cartera, la liquidez y la diversificación de la entidad, contrastados con los "
        "parámetros del sector según la metodología SDQ. El detalle se desarrolla en las "
        "secciones de este informe."
    ),
    "banking_summary": (
        "Este resumen integra los indicadores financieros del período en una lectura ejecutiva "
        "del perfil de la entidad: solidez de capital, calidad de la cartera, eficiencia, "
        "liquidez y diversificación, ponderados según la metodología de calificación SDQ. El "
        "detalle por dimensión se desarrolla en las secciones siguientes."
    ),
    "banking_comparative": (
        "Esta sección sitúa a la entidad frente a sus pares del mismo tipo, contrastando los "
        "sub-componentes de la calificación para distinguir sus ventajas relativas de sus "
        "rezagos materiales, según la metodología SDQ."
    ),
    "banking_risk": (
        "El perfil de riesgo se evalúa integrando la solidez financiera, la calidad de la "
        "cartera, la liquidez y la diversificación de la entidad, contrastados con los "
        "parámetros del sector según la metodología SDQ. El detalle se desarrolla en las "
        "secciones de este informe."
    ),
    "banking_recommendation": (
        "Esta sección sintetiza la lectura del período en una postura de exposición para el "
        "comité, fundamentada en la solidez y el perfil de riesgo de la entidad según la "
        "metodología SDQ."
    ),
    "banking_operating_env": (
        "El entorno operativo macroeconómico —inflación, actividad, tasas de política, tipo "
        "de cambio y reservas del BCRD— constituye el telón sistémico común a todas las "
        "entidades del sistema. Se presenta como contexto y no forma parte de la calificación "
        "standalone de la entidad, que mide su fortaleza financiera propia."
    ),
    "banking_support_context": (
        "El soporte estatal, la importancia sistémica y el techo soberano de la República "
        "Dominicana constituyen una capa de contexto estructural, presentada de forma "
        "separada. No forman parte de la calificación SDQ standalone —que mide fortaleza "
        "financiera relativa dentro del sistema dominicano, no riesgo de crédito absoluto—; "
        "encuadran cómo se leería la entidad en clave comparable internacional."
    ),
}

# Modelo reportado por ``_generate_fallback`` cuando la narrativa IA NO se generó (sin API
# key, error de red, rate-limit sostenido o corte de presupuesto): el ÚNICO marcador
# confiable de degradación, agnóstico a la causa. Todo consumidor que necesite distinguir
# "narrativa real" de "relleno estático" debe compararse contra esta constante o usar
# ``is_static_fallback_text`` (que además cubre el caso en que solo se conserva el texto).
STATIC_FALLBACK_MODEL = "static_fallback"

# Texto neutro que sirve ``_generate_fallback`` cuando NO hay un fallback por-template en
# ``STATIC_FALLBACKS``. Es la fuente única: el render lo toma de aquí y el detector lo compara
# contra aquí, así nunca se desincronizan. En un producto premium este párrafo es JUSTO la
# señal de "Deep Dive hueco" que NO debe salir a cliente.
STATIC_FALLBACK_GENERIC = (
    "Esta sección sintetiza la información cuantitativa del período presentada en este "
    "informe. El análisis cualitativo ampliado se incorpora en la versión completa del "
    "producto."
)

# Conjunto de TODOS los textos que el motor puede emitir como fallback estático (el genérico
# + los por-template). Se compara con match EXACTO (tras strip) para no tener falsos positivos:
# ni las Limitaciones, ni los bullets de alerta, ni la metodología, ni las muestras curadas
# coinciden con estos strings, así que solo una degradación real del motor los reproduce.
_STATIC_FALLBACK_TEXTS = frozenset(
    {STATIC_FALLBACK_GENERIC} | {v.strip() for v in STATIC_FALLBACKS.values()}
)


def is_static_fallback_text(text: object) -> bool:
    """¿*text* es un relleno estático emitido por el motor (narrativa degradada)?

    Se usa cuando solo se conserva el TEXTO de la sección (los productos devuelven
    ``{sección: str}`` y descartan ``NarrativeResult.model_used``). Match exacto contra los
    fallbacks conocidos → cero falsos positivos sobre prosa real o secciones legítimamente
    estáticas (limitaciones, metodología, muestras curadas)."""
    if not isinstance(text, str):
        return False
    return text.strip() in _STATIC_FALLBACK_TEXTS


def degraded_sections(narratives: dict, sections) -> list:
    """Nombres de *sections* cuyo texto en *narratives* es un fallback estático.

    El detector central de degradación para el ensamblado de reportes: alimenta tanto el
    log de ops como la decisión de fallar-cerrado en productos premium."""
    n = narratives or {}
    return [s for s in sections if is_static_fallback_text(n.get(s))]


def secciones_con_cifra_sin_respaldo(narratives: dict, sections, context: dict) -> dict:
    """`{sección: [hallazgos]}` de las secciones cuyo texto AFIRMA cifras que el contexto no
    sostiene.

    Es el gemelo de `degraded_sections` para el otro modo de entregar un informe malo. Aquél
    detecta una sección HUECA —fácil de ver—; éste detecta una sección LLENA con un número que
    nadie puede respaldar, que es peor: se lee como un hallazgo y viaja citado.

    **Solo corre los checks DETERMINISTAS**, y eso es una limitación que hay que declarar: son
    gratis y mecánicos, así que pueden vivir en la ruta de entrega sin costo ni latencia ni
    variabilidad. El juez semántico del motor ve cosas que éstos no —y por eso el motor además
    se niega a propagar a la caché compartida lo que él marcó—. Los dos filtros se necesitan:
    ninguno cubre al otro.
    """
    from shared.narrative.numeric_guard import (deterministic_uncited_figures,
                                                deterministic_unsupported)

    n, ctx = narratives or {}, context or {}
    out = {}
    for s in sections:
        texto = n.get(s)
        if not isinstance(texto, str) or not texto.strip():
            continue
        hallazgos = deterministic_unsupported(ctx, texto) + deterministic_uncited_figures(ctx, texto)
        if hallazgos:
            out[s] = hallazgos
    return out


class NarrativeSinRespaldoError(RuntimeError):
    """La narrativa afirma cifras que el contexto NO sostiene, en secciones de análisis de un
    producto premium.

    No se entrega. El caso que la motiva llegó a un PDF de rating REAL: el guard marcó la
    cifra, el texto sobrevivió a la regeneración y el informe se emitió igual con
    `guard_flags=1`, porque la marca no tenía ningún consumidor — era una etiqueta en un log.

    Es peor que la degradación, y por eso falla igual de cerrado: un informe hueco se nota; un
    número inventado se cita.
    """

    def __init__(self, hallazgos: dict):
        self.hallazgos = dict(hallazgos)
        super().__init__(
            "La narrativa afirma cifras que el contexto no sostiene en "
            + ", ".join(f"{s} ({len(v)})" for s, v in sorted(self.hallazgos.items()))
            + ". El informe no se entrega con una cifra que no se puede respaldar.")


class NarrativeDegradedError(RuntimeError):
    """La narrativa IA cayó al fallback estático en secciones de ANÁLISIS de un producto
    premium (Insight/Deep Dive). Degradación transitoria (rate-limit/outage del API o corte
    de presupuesto): el reporte NO se entrega hueco. El llamador la traduce a un error de
    reintento en español, en vez de completar un PDF de cliente con relleno."""

    def __init__(self, sections):
        self.sections = list(sections)
        super().__init__(
            "Narrativa IA no disponible por límite temporal del servicio de análisis en "
            f"{len(self.sections)} sección(es): {', '.join(self.sections)}."
        )


CACHE_TTL_SECONDS = 3600  # 1 hour

# Namespace de la L2 compartida (Redis). Versionado: subir a v2 invalida todo el
# namespace si cambia el formato serializado o la semántica de la clave.
_L2_NS = "narr:v1:"


def _legacy_system() -> str:
    """System de la ruta legacy (market_brief, cross_compare, deal_outlook, etc.).

    Aplica el registro de voz Y la disciplina anti-fabricación/incertidumbre — hallazgo del
    2026-07-17: esta ruta corría con SOLO el registro de voz, sin la regla dura que prohíbe
    inventar cifras ni la distinción dato/inferencia/conjetura. No hay razón de producto
    para que esa garantía exista en 6 ejes y no en el resto. Deliberadamente SIN
    BARRA_DE_INSIGHT ni CEREBRO_IDENTITY: la profundidad analítica del cerebro es una
    decisión de producto aparte; "no fabricar" aplica siempre.
    """
    from shared.narrative.cerebro import (
        DIRECTION_DISCIPLINE, EPISTEMIC_STANDARD, INDICATOR_SEMANTICS, NO_META_COMMENTARY,
        REGISTER_NEUTRO, SCOPE_DISCIPLINE)
    return (REGISTER_NEUTRO + "\n\n" + EPISTEMIC_STANDARD
            + "\n\n" + DIRECTION_DISCIPLINE + "\n\n" + INDICATOR_SEMANTICS
            + "\n\n" + SCOPE_DISCIPLINE + "\n\n" + NO_META_COMMENTARY)


def _uses_cerebro(template: str, axis: Optional[str]) -> bool:
    """¿Esta (plantilla, eje) va por la ruta cerebro? Fuente ÚNICA de la decisión.

    La consultan tanto ``generate`` (para ejecutar) como ``_recipe_fingerprint`` (para
    cachear). Duplicar la condición sería exactamente el modo de falla que este cambio
    viene a cerrar: la huella describiría una receta distinta de la que se ejecuta.
    """
    from shared.narrative.cerebro import AXIS_DOCTRINE
    return bool(axis) and template in THIN_TEMPLATES and axis in AXIS_DOCTRINE


@dataclass
class NarrativeResult:
    text: str
    tokens_used: int = 0
    cost_estimate: float = 0.0
    model_used: str = ""
    timestamp: float = field(default_factory=time.time)
    from_cache: bool = False
    # Cifras del output que el guardrail numérico no pudo trazar al contexto tras
    # regenerar (cerebro). Vacío = verificado limpio o ruta sin guardrail.
    guard_unsupported: list = field(default_factory=list)
    # True cuando el modelo se quedó SIN PRESUPUESTO de tokens: el texto está cortado, no
    # terminado. Un PDF entregado a mitad de oración —pasó con Perspectiva Sectorial— es
    # peor que un error visible: parece el documento final.
    truncated: bool = False


class NarrativeEngine:
    """Engine for generating AI-powered narratives using Claude and SCQA framework."""

    def __init__(self):
        self._cache: dict[str, tuple[NarrativeResult, float]] = {}
        self._client = None
        # El semáforo se liga al event loop en el primer uso; se recrea si el loop cambia
        # (p. ej. cada asyncio.run() de los tests abre un loop nuevo). Así evitamos el
        # error "bound to a different event loop" de un singleton creado al importar.
        self._sem: Optional[asyncio.Semaphore] = None
        self._sem_loop = None

    def _get_sem(self) -> asyncio.Semaphore:
        # Cota de llamadas CONCURRENTES al API (secciones en asyncio.gather). Es el techo real
        # de throughput; configurable vía NARRATIVE_MAX_CONCURRENCY. El semáforo se liga al
        # loop en el 1er uso y se recrea si el loop cambia (asyncio.run de los tests).
        loop = asyncio.get_running_loop()
        raw = getattr(settings, "NARRATIVE_MAX_CONCURRENCY", 10)
        # Un valor inválido (0, negativo, no-int) cae al default 10 — nunca estrangula a <1.
        cap = raw if isinstance(raw, int) and raw >= 1 else 10
        if self._sem is None or self._sem_loop is not loop:
            self._sem = asyncio.Semaphore(cap)
            self._sem_loop = loop
        return self._sem

    def _get_client(self):
        if self._client is None and settings.ANTHROPIC_API_KEY:
            try:
                import anthropic
                # max_retries alto: con más concurrencia, un 429 transitorio se reintenta con
                # backoff (SDK) en vez de caer al fallback estático. Absorbe picos de rate.
                self._client = anthropic.Anthropic(
                    api_key=settings.ANTHROPIC_API_KEY, max_retries=4)
            except ImportError:
                logger.warning("anthropic package not installed, using fallback templates")
        return self._client

    def _recipe_fingerprint(self, template: str, mode: str, axis: Optional[str],
                            audience: Optional[str]) -> str:
        """Huella de CÓMO se produce el texto: system ensamblado + plantilla + modelo + guard.

        La clave de caché hashea la PREGUNTA (contexto, plantilla, modo, idioma, eje,
        audiencia) pero no la RECETA, así que asume "misma pregunta ⇒ misma respuesta". Es
        falso cada vez que cambiamos un prompt, el modelo o el guardrail: la caché seguía
        sirviendo el texto viejo —hasta 1 h en Redis, que sobrevive al deploy— y un arreglo
        de cara al cliente quedaba sin efecto en silencio. Pasó de verdad: `NO_META_COMMENTARY`
        (#580), el veto de léxico visceral y `DIRECTION_DISCIPLINE` (#631) se desplegaron sin
        que ninguna entrada cacheada se invalidara.

        Al hashear el system REAL, un cambio de prompt rota solas las entradas afectadas: no
        hay bump que recordar (el que existía nunca se movió) y —a diferencia de namespear
        por el SHA del deploy— NO se tira la caché entera en cada despliegue. Esa distinción
        importa: esta caché existe para que la descarga no espere ~15-90 s, y en régimen
        normal (misma receta, mismo dato) el HIT sigue siendo HIT.
        """
        from shared.narrative.cerebro import DEEP_DIRECTIVE, build_system
        from shared.narrative.numeric_guard import GUARD_VERSION

        parts = [settings.ANTHROPIC_MODEL or "", GUARD_VERSION]
        if _uses_cerebro(template, axis) and axis:  # `and axis` es redundante: estrecha el tipo
            parts += [build_system(axis, audience, mode), THIN_TEMPLATES[template]]
            if mode == "deep":
                parts.append(DEEP_DIRECTIVE)
        else:
            parts += [_legacy_system(),
                      TEMPLATES.get(template) or TEMPLATES["executive_summary"]]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def _cache_key(self, context: dict, template: str, mode: str, lang: str,
                   axis: Optional[str] = None, audience: Optional[str] = None) -> str:
        content = (json.dumps(context, sort_keys=True, default=str)
                   + template + mode + lang + (axis or "") + (audience or "")
                   + self._recipe_fingerprint(template, mode, axis, audience))
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[NarrativeResult]:
        if key in self._cache:
            result, cached_at = self._cache[key]
            if time.time() - cached_at < CACHE_TTL_SECONDS:
                result.from_cache = True
                return result
            del self._cache[key]
        # L2 compartida (Redis): una narrativa generada por OTRO worker sirve acá.
        # Antes cada worker uvicorn tenía su copia y un deploy vaciaba todo.
        raw = cache_get(_L2_NS + key)
        if raw:
            try:
                data = json.loads(raw)
                result = NarrativeResult(
                    text=data["text"],
                    tokens_used=int(data.get("tokens_used") or 0),
                    cost_estimate=float(data.get("cost_estimate") or 0.0),
                    model_used=str(data.get("model_used") or ""),
                    from_cache=True,
                    guard_unsupported=list(data.get("guard_unsupported") or []),
                )
                self._cache[key] = (result, time.time())  # promover a L1
                return result
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("Entrada L2 corrupta (se ignora): %s", e)
        return None

    def _set_cache(self, key: str, result: NarrativeResult):
        self._cache[key] = (result, time.time())
        if result.guard_unsupported:
            # Lo que el guard marcó NO viaja a la caché compartida. Escribirlo ahí es cómo un
            # texto con una cifra sin respaldo sobrevive a la corrida que lo produjo y se
            # sirve —idéntico y en silencio— a todos los informes que vengan: la caché no
            # tiene TTL. Queda en L1 por-worker para no re-pagar la generación dentro de la
            # misma corrida, que de todos modos el gate del ensamblador va a frenar.
            logger.warning("Narrativa con %d hallazgo(s) del guard: no se propaga a la caché "
                           "compartida (%s)", len(result.guard_unsupported),
                           "; ".join(map(str, result.guard_unsupported))[:200])
            return
        if result.model_used == STATIC_FALLBACK_MODEL:
            # El fallback estático es un degradado transitorio (sin API key, error,
            # presupuesto): se cachea solo por-worker, no se propaga a los demás.
            return
        try:
            payload = json.dumps({
                "text": result.text,
                "tokens_used": result.tokens_used,
                "cost_estimate": result.cost_estimate,
                "model_used": result.model_used,
                "guard_unsupported": result.guard_unsupported,
            }, ensure_ascii=False)
            cache_set(_L2_NS + key, payload, CACHE_TTL_SECONDS)
        except (TypeError, ValueError) as e:  # payload no serializable — solo L1
            logger.warning("No se pudo serializar narrativa a L2 (se omite): %s", e)

    def _build_result(self, response) -> NarrativeResult:
        """NarrativeResult from a Claude response — token/cost accounting, no caching.

        Punto único de extracción del texto para AMBAS rutas (cerebro y legacy): aquí se
        aplica la red de seguridad ``strip_meta_commentary`` que garantiza que ningún
        meta-comentario del modelo (auto-corrección "espera —", duda, tags de razonamiento)
        llegue al render. Si el sanitizador interviene, se LOGuea a nivel WARNING: es señal
        de que el prompt anti-meta falló y de que la fuga merece revisión, no un silencio.
        """
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        # Contabilidad central: registra el gasto del día (Redis) y devuelve el costo
        # estimado con la tarifa DEL MODELO (antes estaba hardcodeada la de Sonnet).
        cost = record_usage(settings.ANTHROPIC_MODEL, input_tokens, output_tokens)
        text, removed = strip_meta_commentary(response.content[0].text)
        if removed:
            logger.warning(
                "Meta-comentario del modelo removido de la narrativa (%d fragmento(s)): %s. "
                "Revisar el prompt anti-meta si recurre.",
                len(removed), removed,
            )
        # Formato de casa: la prosa del modelo y las tablas del motor deben escribir el
        # MISMO número igual. Va acá y no en cada render porque este es el punto único por
        # el que pasan AMBAS rutas — en el render habría que acordarse de llamarlo por
        # superficie, y la que se olvide vuelve a publicar el documento contradiciéndose.
        text, formato = normalize_number_format(text)
        if formato:
            logger.info(
                "Formato numérico normalizado en la narrativa (%s). Si recurre mucho, "
                "reforzar la instrucción de formato en el prompt.", "; ".join(formato),
            )
        # Lint de REGISTRO: marca (no borra) el léxico visceral/coloquial. La corrección va en
        # el prompt (REGISTER_NEUTRO); esto lo hace observable si algo se cuela al informe.
        register_flags = flag_register_violations(text)
        if register_flags:
            logger.warning(
                "Registro impropio en la narrativa (%d marca(s)): %s. Léxico visceral/coloquial "
                "que no pertenece a un informe tier-1; reforzar REGISTER_NEUTRO si recurre.",
                len(register_flags), register_flags,
            )
        # Corte por PRESUPUESTO: la API lo declara en `stop_reason`. Sin este chequeo el
        # texto truncado viaja como si estuviera terminado y se imprime a mitad de oración.
        truncated = getattr(response, "stop_reason", None) == "max_tokens"
        if truncated:
            logger.warning(
                "Narrativa TRUNCADA por presupuesto de tokens (%d de salida): el texto está "
                "cortado, no terminado. Subir el modo de la sección o acortar la plantilla.",
                output_tokens,
            )
        return NarrativeResult(
            text=text,
            tokens_used=input_tokens + output_tokens,
            cost_estimate=cost,
            model_used=settings.ANTHROPIC_MODEL,
            truncated=truncated,
        )

    def _result_from_response(self, response, cache_key: str, template: str,
                              axis: Optional[str] = None) -> NarrativeResult:
        """Build, cache and return a NarrativeResult (legacy route).

        Registra igual que la ruta cerebro. Sin esta línea el gasto de la ruta legacy sí
        contaba contra el techo diario —``_build_result`` llama a ``record_usage``— pero
        NO aparecía atribuido en el panel: el total se veía menor de lo real y el
        disparador quedaba sin dueño. El test estructural no lo cazaba porque valida por
        ARCHIVO, y este archivo nombra la contabilidad en su otra ruta.
        """
        result = self._build_result(response)
        self._set_cache(cache_key, result)
        logger.info(
            "Narrative generated: template=%s, tokens=%d, cost=$%.4f",
            template, result.tokens_used, result.cost_estimate,
        )
        record_call(purpose=PURPOSE_NARRATIVE, model=result.model_used or "",
                    cost_usd=result.cost_estimate, tokens_out=result.tokens_used,
                    module=axis, template=template, cache_hit=False,
                    detail={"ruta": "legacy"})
        return result

    def _generate_guarded(self, client, system: str, user: str, max_tokens: int,
                          context_str: str, cache_key: str, template: str,
                          context: Optional[dict] = None,
                          axis: Optional[str] = None) -> NarrativeResult:
        """Cerebro generation + numeric guardrail: generate, verify every figure traces
        to the context, and regenerate ONCE if any is unsupported. Two layers feed the
        check: a DETERMINISTIC computation (deltas vs median, range bounds, value↔period,
        weighted contributions — modes the LLM judge proved unreliable on) plus the LLM
        judge for the rest. Caches and returns the final result with ``guard_unsupported``
        recording figures still unverified (if the regen also failed) — best-effort, never
        blanks the insight."""
        from shared.narrative.numeric_guard import (
            CORRECTION_NOTICE, DIRECTION_CORRECTION_NOTICE,
            deterministic_direction_errors, deterministic_uncited_figures,
            deterministic_unsupported, verify_figures)

        def _gen(user_msg):
            resp = _call_with_transient_retry(
                lambda: client.messages.create(
                    model=settings.ANTHROPIC_MODEL, max_tokens=max_tokens,
                    system=system, messages=[{"role": "user", "content": user_msg}],
                ),
                label=f"cerebro:{template}",
            )
            return self._build_result(resp)

        guard_model = settings.ANTHROPIC_GUARD_MODEL

        def _check(text: str) -> tuple:
            """``(cifras_sin_respaldo, comparaciones_invertidas)`` — se devuelven POR
            SEPARADO porque piden correcciones distintas: una cifra sin respaldo se corrige
            no inventando; una dirección invertida se corrige cambiándole el signo SIN tocar
            los números (y sin borrar la comparación)."""
            # determinista primero (gratis, garantía mecánica) + juez LLM (semántico).
            # `deterministic_unsupported` lee la forma del contexto de banca; en un módulo
            # con otra forma devuelve `[]` sin haber mirado nada. `deterministic_uncited`
            # no conoce ninguna forma y cubre ese hueco: toda cifra citada tiene que estar
            # entre los números del contexto, sea cual sea su estructura.
            det = (deterministic_unsupported(context or {}, text)
                   + deterministic_uncited_figures(context or {}, text))
            # El juez contabiliza su PROPIA llamada (ver `verify_figures`): registrarla
            # desde acá la anotaba sin dólares, y el juez es la mitad de las llamadas de
            # un informe. Se le pasan eje y plantilla para que su fila quede atribuida
            # igual que la de la narrativa que verifica.
            llm = verify_figures(client, guard_model, context_str, text,
                                 module=axis, template=template)
            seen, merged = set(), []
            for f in det + llm:
                if f not in seen:
                    seen.add(f)
                    merged.append(f)
            return merged, deterministic_direction_errors(context or {}, text)

        result = _gen(user)
        bad, wrong_dir = _check(result.text)
        if bad or wrong_dir:
            logger.warning("Guardrail (%s): cifras sin respaldo %s | dirección invertida %s "
                           "— regenerando una vez", template, bad, wrong_dir)
            try:
                notice = ""
                if bad:
                    notice += CORRECTION_NOTICE.format(bad="; ".join(bad))
                if wrong_dir:
                    notice += DIRECTION_CORRECTION_NOTICE.format(bad="; ".join(wrong_dir))
                corrected = _gen(user + notice)
                # acumula tokens/costo de ambas llamadas (transparencia)
                corrected.tokens_used += result.tokens_used
                corrected.cost_estimate += result.cost_estimate
                still_bad, still_dir = _check(corrected.text)
                corrected.guard_unsupported = still_bad + still_dir
                if corrected.guard_unsupported:
                    logger.warning("Guardrail (%s): persisten hallazgos tras regenerar: %s",
                                   template, corrected.guard_unsupported)
                result = corrected
            except Exception as e:  # noqa: BLE001 — best-effort; sirve el original marcado
                logger.error("Regeneración del guardrail falló: %s", e)
                result.guard_unsupported = bad + wrong_dir
        self._set_cache(cache_key, result)
        logger.info("Narrative (cerebro) template=%s tokens=%d guard_flags=%d",
                    template, result.tokens_used, len(result.guard_unsupported))
        # El costo acumulado ya incluye la regeneración cuando el guard la disparó: se
        # registra una sola fila por sección con el total real, no el de la primera
        # llamada. Contar solo la primera escondería justo el costo del guard.
        record_call(purpose=PURPOSE_NARRATIVE, model=result.model_used or "",
                    cost_usd=result.cost_estimate, tokens_out=result.tokens_used,
                    module=axis, template=template, cache_hit=False,
                    detail={"guard_flags": len(result.guard_unsupported),
                            "truncada": result.truncated})
        return result

    def _generate_fallback(self, context: dict, template: str) -> NarrativeResult:
        """Generate narrative from static templates when API key is unavailable."""
        fallback = STATIC_FALLBACKS.get(template)
        if fallback:
            text = fallback
        else:
            # Texto neutro y profesional (NUNCA instrucciones de dev ni tokens crudos en
            # un PDF de cliente). El aviso para el desarrollador va al log, no al render.
            logger.warning("Narrativa sin motor IA (template=%s): se sirvió texto estático "
                           "neutro. Configurar ANTHROPIC_API_KEY para narrativa completa.",
                           template)
            text = STATIC_FALLBACK_GENERIC
        return NarrativeResult(
            text=text,
            model_used=STATIC_FALLBACK_MODEL,
        )

    async def generate(
        self,
        context: dict,
        template: str = "executive_summary",
        mode: str = "standard",
        lang: Optional[str] = None,
        axis: Optional[str] = None,
        audience: Optional[str] = None,
    ) -> NarrativeResult:
        """Generate a narrative using Claude AI or fallback templates.

        Args:
            context: Dictionary with data to include in the narrative.
            template: One of the predefined template names.
            mode: 'standard' (1024 tok) · 'detailed' (2048, default per page) ·
                'deep' (4096 + DEEP_DIRECTIVE, the opt-in "full analysis" version that
                overrides the thin template's word cap). Cache key namespaces by mode.
            lang: 'es'|'en'|'fr'. If None, uses the request language (X-Lang header
                via the global dependency), defaulting to 'es'.
            axis: when set, activates the "cerebro" route — an assembled `system`
                prompt (identity + axis doctrine + epistemic standard + audience frame
                + insight bar) plus a thin task template. When None, the legacy route
                (single user message, fat template) is used unchanged.
            audience: audience key for the cerebro frame; falls back to the axis default
                if None/unknown. Ignored on the legacy route.

        Returns:
            NarrativeResult with generated text and metadata.
        """
        lang = (lang or get_request_lang() or "es")
        cache_key = self._cache_key(context, template, mode, lang, axis, audience)
        cached = self._get_cached(cache_key)
        if cached:
            logger.info("Narrative cache hit for template=%s lang=%s axis=%s", template, lang, axis)
            # El HIT también se registra, con costo cero. Sin él no se distingue «nadie
            # pidió esto» de «lo pidieron cien veces y la caché lo absorbió», que es la
            # diferencia que decide si la caché vale lo que ocupa.
            record_call(purpose=PURPOSE_NARRATIVE, model=cached.model_used or "",
                        cost_usd=0.0, module=axis, template=template, cache_hit=True,
                        detail={"lang": lang, "mode": mode})
            return cached

        # Try Claude API
        client = self._get_client()
        if not client:
            logger.info("No API key, using fallback template for '%s'", template)
            result = self._generate_fallback(context, template)
            self._set_cache(cache_key, result)
            return result

        # Corte SUAVE de presupuesto: sobre el techo diario no se paga una llamada
        # nueva — se sirve el fallback estático SIN cachearlo (al liberarse el
        # presupuesto, la próxima request regenera de verdad).
        if not budget_allows():
            logger.warning("Narrativa degradada a estático por presupuesto LLM "
                           "(template=%s, axis=%s)", template, axis)
            return self._generate_fallback(context, template)

        context_str = json.dumps(context, indent=2, ensure_ascii=False, default=str)
        max_tokens = 4096 if mode == "deep" else 2048 if mode == "detailed" else 1024

        if axis:  # ── ruta cerebro: system ensamblado + template thin ──
            from shared.narrative.cerebro import DEEP_DIRECTIVE, build_system
            if not _uses_cerebro(template, axis):
                # axis sin doctrina o template sin thin → ruta legacy (nunca KeyError:
                # generate_report_narratives no tiene try/except propio). La decisión la
                # toma `_uses_cerebro`, la MISMA que consulta la huella de caché.
                logger.warning("Cerebro no aplicable (axis=%s, template=%s); ruta legacy",
                               axis, template)
            else:
                system = build_system(axis, audience, mode)
                user_body = THIN_TEMPLATES[template].format(context=context_str)
                if mode == "deep":  # override de longitud al final → gana sobre el tope del thin
                    user_body = f"{user_body}\n\n{DEEP_DIRECTIVE}"
                user = _apply_lang(user_body, lang)
                try:
                    # El cliente Anthropic es SÍNCRONO/bloqueante. Corrido directo dentro de
                    # un asyncio.gather bloquearía el event loop y serializaría las secciones
                    # (el motivo por el que #491 quedó inefectivo). asyncio.to_thread lo mueve
                    # a un worker thread → el gather paraleliza de verdad. Todo el flujo con
                    # guard (generación + verificación + regeneración, incluida la llamada
                    # bloqueante de numeric_guard.verify_figures) corre en ese thread. El
                    # semáforo acota la concurrencia para no rozar el rate limit.
                    async with self._get_sem():
                        return await asyncio.to_thread(
                            self._generate_guarded,
                            client, system, user, max_tokens, context_str, cache_key,
                            template, context, axis)
                except Exception as e:  # noqa: BLE001
                    logger.error("Claude API error (cerebro): %s. Fallback estático.", e)
                    result = self._generate_fallback(context, template)
                    self._set_cache(cache_key, result)
                    return result

        # ── ruta legacy (los otros módulos / templates sin thin) — sin cambios ──
        prompt_template = TEMPLATES.get(template)
        if not prompt_template:
            logger.warning("Unknown template '%s', using executive_summary", template)
            prompt_template = TEMPLATES["executive_summary"]

        prompt = _apply_lang(prompt_template.format(context=context_str), lang)

        legacy_system = _legacy_system()

        try:
            # to_thread + semáforo: mismo motivo que la ruta cerebro — liberar el event loop
            # para que el gather de secciones no se serialice, con la concurrencia acotada.
            async with self._get_sem():
                response = await asyncio.to_thread(
                    _call_with_transient_retry,
                    lambda: client.messages.create(
                        model=settings.ANTHROPIC_MODEL,
                        max_tokens=max_tokens,
                        system=legacy_system,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    label=f"legacy:{template}",
                )
            return self._result_from_response(response, cache_key, template, axis)

        except Exception as e:
            logger.error("Claude API error: %s. Falling back to static template.", e)
            result = self._generate_fallback(context, template)
            self._set_cache(cache_key, result)
            return result


# Singleton instance
narrative_engine = NarrativeEngine()
