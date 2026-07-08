import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from shared.config.settings import settings
from shared.narrative.lang_context import get_request_lang

logger = logging.getLogger(__name__)

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
    "early_warning_reading": (
        "Interpreta el CONJUNTO de señales de alerta temprana YA detectadas para esta entidad "
        "(no es un reporte de estado ni una relista). Contexto:\n{context}\n\n"
        "Máximo 130 palabras, UN SOLO párrafo. Las banderas y sus cifras ya vienen dadas en "
        "'flags'; tu trabajo es LEER EL PATRÓN: qué COMBINACIÓN de banderas es la que más pesa "
        "(una combinación puede importar más que la suma de sus partes), qué la matiza para "
        "esta entidad, y el 'y por tanto' de qué conviene vigilar. Si una sola bandera domina, "
        "dilo. REGLA DURA: usa EXCLUSIVAMENTE las cifras servidas en 'flags' (valor/umbral); NO "
        "inventes números, umbrales ni comparaciones que no estén en el contexto; si una "
        "relación no está dada, exprésala en palabras SIN número. NO afirmes fraude ni causas "
        "ocultas: estas señales son un COMPLEMENTO del rating/índice, no un veredicto, y no "
        "detectan contabilidad fraudulenta. No repitas la lista textual; sintetiza."
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
        "concentration_hhi). HONESTIDAD: lente de IMPORTANCIA y CONTRIBUCIÓN — NO valor exportado "
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

CACHE_TTL_SECONDS = 3600  # 1 hour


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


class NarrativeEngine:
    """Engine for generating AI-powered narratives using Claude and SCQA framework."""

    def __init__(self):
        self._cache: dict[str, tuple[NarrativeResult, float]] = {}
        self._client = None

    def _get_client(self):
        if self._client is None and settings.ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            except ImportError:
                logger.warning("anthropic package not installed, using fallback templates")
        return self._client

    def _cache_key(self, context: dict, template: str, mode: str, lang: str,
                   axis: Optional[str] = None, audience: Optional[str] = None) -> str:
        content = (json.dumps(context, sort_keys=True, default=str)
                   + template + mode + lang + (axis or "") + (audience or ""))
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[NarrativeResult]:
        if key in self._cache:
            result, cached_at = self._cache[key]
            if time.time() - cached_at < CACHE_TTL_SECONDS:
                result.from_cache = True
                return result
            del self._cache[key]
        return None

    def _set_cache(self, key: str, result: NarrativeResult):
        self._cache[key] = (result, time.time())

    def _build_result(self, response) -> NarrativeResult:
        """NarrativeResult from a Claude response — token/cost accounting, no caching."""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)
        return NarrativeResult(
            text=response.content[0].text,
            tokens_used=input_tokens + output_tokens,
            cost_estimate=cost,
            model_used=settings.ANTHROPIC_MODEL,
        )

    def _result_from_response(self, response, cache_key: str, template: str) -> NarrativeResult:
        """Build, cache and return a NarrativeResult (legacy route)."""
        result = self._build_result(response)
        self._set_cache(cache_key, result)
        logger.info(
            "Narrative generated: template=%s, tokens=%d, cost=$%.4f",
            template, result.tokens_used, result.cost_estimate,
        )
        return result

    def _generate_guarded(self, client, system: str, user: str, max_tokens: int,
                          context_str: str, cache_key: str, template: str,
                          context: Optional[dict] = None) -> NarrativeResult:
        """Cerebro generation + numeric guardrail: generate, verify every figure traces
        to the context, and regenerate ONCE if any is unsupported. Two layers feed the
        check: a DETERMINISTIC computation (deltas vs median, range bounds, value↔period,
        weighted contributions — modes the LLM judge proved unreliable on) plus the LLM
        judge for the rest. Caches and returns the final result with ``guard_unsupported``
        recording figures still unverified (if the regen also failed) — best-effort, never
        blanks the insight."""
        from shared.narrative.numeric_guard import (
            CORRECTION_NOTICE, deterministic_unsupported, verify_figures)

        def _gen(user_msg):
            resp = client.messages.create(
                model=settings.ANTHROPIC_MODEL, max_tokens=max_tokens,
                system=system, messages=[{"role": "user", "content": user_msg}],
            )
            return self._build_result(resp)

        guard_model = settings.ANTHROPIC_GUARD_MODEL

        def _check(text: str) -> list:
            # determinista primero (gratis, garantía mecánica) + juez LLM (semántico)
            det = deterministic_unsupported(context or {}, text)
            llm = verify_figures(client, guard_model, context_str, text)
            seen, merged = set(), []
            for f in det + llm:
                if f not in seen:
                    seen.add(f)
                    merged.append(f)
            return merged

        result = _gen(user)
        bad = _check(result.text)
        if bad:
            logger.warning("Guardrail (%s): cifras sin respaldo %s — regenerando una vez",
                           template, bad)
            try:
                corrected = _gen(user + CORRECTION_NOTICE.format(bad="; ".join(bad)))
                # acumula tokens/costo de ambas llamadas (transparencia)
                corrected.tokens_used += result.tokens_used
                corrected.cost_estimate += result.cost_estimate
                corrected.guard_unsupported = _check(corrected.text)
                if corrected.guard_unsupported:
                    logger.warning("Guardrail (%s): persisten cifras tras regenerar: %s",
                                   template, corrected.guard_unsupported)
                result = corrected
            except Exception as e:  # noqa: BLE001 — best-effort; sirve el original marcado
                logger.error("Regeneración del guardrail falló: %s", e)
                result.guard_unsupported = bad
        self._set_cache(cache_key, result)
        logger.info("Narrative (cerebro) template=%s tokens=%d guard_flags=%d",
                    template, result.tokens_used, len(result.guard_unsupported))
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
            text = ("Esta sección sintetiza la información cuantitativa del período "
                    "presentada en este informe. El análisis cualitativo ampliado se "
                    "incorpora en la versión completa del producto.")
        return NarrativeResult(
            text=text,
            model_used="static_fallback",
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
            return cached

        # Try Claude API
        client = self._get_client()
        if not client:
            logger.info("No API key, using fallback template for '%s'", template)
            result = self._generate_fallback(context, template)
            self._set_cache(cache_key, result)
            return result

        context_str = json.dumps(context, indent=2, ensure_ascii=False, default=str)
        max_tokens = 4096 if mode == "deep" else 2048 if mode == "detailed" else 1024

        if axis:  # ── ruta cerebro: system ensamblado + template thin ──
            from shared.narrative.cerebro import AXIS_DOCTRINE, DEEP_DIRECTIVE, build_system
            thin = THIN_TEMPLATES.get(template)
            if not thin or axis not in AXIS_DOCTRINE:
                # axis sin doctrina o template sin thin → ruta legacy (nunca KeyError:
                # generate_report_narratives no tiene try/except propio).
                logger.warning("Cerebro no aplicable (axis=%s, template=%s); ruta legacy",
                               axis, template)
            else:
                system = build_system(axis, audience, mode)
                user_body = thin.format(context=context_str)
                if mode == "deep":  # override de longitud al final → gana sobre el tope del thin
                    user_body = f"{user_body}\n\n{DEEP_DIRECTIVE}"
                user = _apply_lang(user_body, lang)
                try:
                    return self._generate_guarded(
                        client, system, user, max_tokens, context_str, cache_key, template,
                        context=context)
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

        # Aun en la ruta legacy (market_brief, cross_compare, deal_outlook, etc.) se aplica el
        # registro de voz: español latinoamericano neutro corporativo-consultivo, sin la
        # doctrina/Barra del cerebro pero con el MISMO tono que el resto de la plataforma.
        from shared.narrative.cerebro import REGISTER_NEUTRO

        try:
            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                system=REGISTER_NEUTRO,
                messages=[{"role": "user", "content": prompt}],
            )
            return self._result_from_response(response, cache_key, template)

        except Exception as e:
            logger.error("Claude API error: %s. Falling back to static template.", e)
            result = self._generate_fallback(context, template)
            self._set_cache(cache_key, result)
            return result


# Singleton instance
narrative_engine = NarrativeEngine()
