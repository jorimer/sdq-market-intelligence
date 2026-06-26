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
        "en una narrativa (no una lista plana) — destacá fortalezas, tensiones y "
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
        "ponderá según los pesos de cada sub-componente. "
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
        "serie, distancia al techo). Usá EXCLUSIVAMENTE el valor servido en 'cifras_derivadas' "
        "o 'tendencia_score'. Si la relación que querés expresar no está precalculada, decila "
        "en palabras SIN número (p. ej. 'está en el tope de su grupo', no 'lo superan 3'). Al "
        "citar el score de un período usá EXACTAMENTE el de 'tendencia_score' para ese período.\n\n"
        "SUPERLATIVOS: para 'el mayor gap / el más débil / la mayor pérdida potencial' entre "
        "sub-componentes usá 'componente_mayor_gap_al_techo'; para ordinales de peso ('el 2º "
        "de mayor peso') leé 'componentes_por_peso_desc' completo (no omitas Diversificación "
        "aunque pese poco); para 'la mayor caída' usá 'mayor_caida_intertrimestral'. NO "
        "declares un superlativo (mayor/menor/el más…) que no coincida con el valor servido."
    ),
    "indicator_insight": (
        "Analiza EN DETALLE un único indicador financiero de la entidad (datos reales SIB).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Cubre nivel actual y su lectura, tendencia en los trimestres "
        "provistos y drivers probables, posición vs la mediana del sector y del mismo tipo de "
        "entidad (usa el percentil), e implicaciones para la decisión de la audiencia. Respeta "
        "la dirección del indicador (si 'lower'/'higher'/'target' es mejor)."
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
        "el líder vs la suma del resto, la dimensión de mayor gap y el orden por peso. Copiá esos "
        "valores; NO recalcules aportes ni declares un superlativo (mayor/menor/el más…) que no "
        "coincida con lo servido. Si una relación no está precalculada, exprésala en palabras sin "
        "número."
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
        "el líder vs la suma del resto, la dimensión de mayor gap y el orden por peso. Copiá esos "
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
        "los totales. Usá EXCLUSIVAMENTE las cifras del contexto (resilience_score, hhi_exports, "
        "export_diversification, import_dependency, shares de los top capítulos); NO inventes "
        "cifras ni detalle por país socio (no disponible). Si una cifra no está, dilo."
    ),
    "energy_outlook": (
        "Explica el FUNDAMENTO de la resiliencia del sector eléctrico (IRSE).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Ve profundo en lo que más condiciona la decisión de la audiencia "
        "entre las DOS dimensiones con dato real: adecuación de capacidad (ritmo de expansión "
        "del parque vs demanda ~4%/año) y calidad de servicio (backlog de reclamaciones en "
        "meses). Usá EXCLUSIVAMENTE las cifras del contexto (irse_score, coverage, capacity_mw, "
        "capacity_growth_cagr_3y, service_backlog_months, contribuciones por dimensión). "
        "PROCEDENCIA/HONESTIDAD: la TRANSICIÓN energética (renovable/carbono) es BRECHA declarada "
        "sin dato confiable — NO afirmes nada cuantitativo sobre renovables ni intensidad de "
        "carbono, y aclara que el índice cubre 2 de 3 dimensiones (coverage). Si una cifra no "
        "está, dilo; no inventes."
    ),
    "telecom_outlook": (
        "Explica el FUNDAMENTO del desarrollo del sector telecom (IDT).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. Distingue ALCANCE (penetración) de CALIDAD (banda ancha) según lo "
        "que más condiciona la decisión de la audiencia. Usá EXCLUSIVAMENTE las cifras del "
        "contexto (idt_score, mobile_penetration, internet_penetration, broadband_share, "
        "revenue_growth, contribuciones por dimensión). La móvil suele estar saturada (>100/100) "
        "y el margen está en internet/banda ancha — léelo así. HONESTIDAD: sé explícito con la "
        "ANTIGÜEDAD del boletín (período del contexto); no proyectes ni inventes cifras más "
        "recientes. Si una cifra no está, dilo."
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
        "el líder vs la suma del resto, la dimensión de mayor gap y el orden por peso. Copiá esos "
        "valores; NO recalcules aportes ni declares un superlativo (mayor/menor/el más…) que no "
        "coincida con lo servido. Si una relación no está precalculada, exprésala sin número."
    ),
    "macro_trend": (
        "Analiza la tendencia de UNA serie macroeconómica (dato real BCRD).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 300 palabras. Distingue NIVEL de MOMENTUM (cambio y aceleración); lee la "
        "dirección correcta de la serie (si subir es bueno o malo). Usá EXCLUSIVAMENTE las "
        "cifras del contexto (latest_value, change, pct_change, acceleration, recent_observations); "
        "NO inventes valores ni proyecciones. Conectá con la implicación para la audiencia."
    ),
    "macro_snapshot": (
        "Analiza la COYUNTURA macroeconómica del período (dato real BCRD).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 350 palabras. No repases todas las series: ve a las señales tempranas "
        "('signals') y a los 'top_movers' que más mueven la aguja por aceleración, y conectá con "
        "la decisión de la audiencia. Usá EXCLUSIVAMENTE las cifras del contexto; NO inventes "
        "valores. Si hay 'contexto_oficial_bcrd', úsalo como telón y cítalo breve."
    ),
    "fiscal_pulse": (
        "Analiza el PULSO FISCAL del Gobierno Central (dato real Hacienda/DGII).\n"
        "Contexto:\n{context}\n\n"
        "Máximo 300 palabras. Foco en la trayectoria del déficit (deficit_ultimos_12m), el "
        "balance entre ingresos y gastos y las top líneas de recaudación — no cada punto "
        "mensual. Usá EXCLUSIVAMENTE las cifras del contexto; NO inventes valores. Si "
        "'has_data' es falso, dilo en una línea. Conectá con la implicación para la audiencia."
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
        "el líder vs la suma del resto, la dimensión de mayor gap y el orden por peso. Copiá esos "
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
        "el líder vs la suma del resto, el de mayor gap y el orden por peso. Copiá esos valores; "
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

        try:
            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=max_tokens,
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
