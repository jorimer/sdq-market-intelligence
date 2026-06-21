import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from shared.config.settings import settings

logger = logging.getLogger(__name__)

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

# Static fallback templates when API key is not available
STATIC_FALLBACKS = {
    "executive_summary": (
        "**Resumen Ejecutivo**\n\n"
        "El análisis de los indicadores financieros muestra un desempeño {performance} "
        "del banco en el período evaluado. Los principales hallazgos incluyen "
        "niveles de solvencia {solvency_status} y calidad de activos {asset_quality_status}."
    ),
    "risk_assessment": (
        "**Evaluación de Riesgo**\n\n"
        "El perfil de riesgo del banco se clasifica como {risk_level}. "
        "Los indicadores de solidez financiera y calidad de cartera se encuentran "
        "{benchmark_comparison} los benchmarks del sector."
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

    def _cache_key(self, context: dict, template: str, mode: str) -> str:
        content = json.dumps(context, sort_keys=True, default=str) + template + mode
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

    def _generate_fallback(self, context: dict, template: str) -> NarrativeResult:
        """Generate narrative from static templates when API key is unavailable."""
        fallback = STATIC_FALLBACKS.get(template)
        if fallback:
            try:
                text = fallback.format(**context)
            except KeyError:
                text = fallback
        else:
            text = (
                f"Narrativa generada automáticamente para template '{template}'. "
                f"Configure ANTHROPIC_API_KEY para narrativas AI completas."
            )
        return NarrativeResult(
            text=text,
            model_used="static_fallback",
        )

    async def generate(
        self,
        context: dict,
        template: str = "executive_summary",
        mode: str = "standard",
    ) -> NarrativeResult:
        """Generate a narrative using Claude AI or fallback templates.

        Args:
            context: Dictionary with data to include in the narrative.
            template: One of the predefined template names.
            mode: 'standard' or 'detailed' for longer outputs.

        Returns:
            NarrativeResult with generated text and metadata.
        """
        cache_key = self._cache_key(context, template, mode)
        cached = self._get_cached(cache_key)
        if cached:
            logger.info("Narrative cache hit for template=%s", template)
            return cached

        # Try Claude API
        client = self._get_client()
        if not client:
            logger.info("No API key, using fallback template for '%s'", template)
            result = self._generate_fallback(context, template)
            self._set_cache(cache_key, result)
            return result

        prompt_template = TEMPLATES.get(template)
        if not prompt_template:
            logger.warning("Unknown template '%s', using executive_summary", template)
            prompt_template = TEMPLATES["executive_summary"]

        context_str = json.dumps(context, indent=2, ensure_ascii=False, default=str)
        prompt = prompt_template.format(context=context_str)

        max_tokens = 2048 if mode == "detailed" else 1024

        try:
            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            total_tokens = input_tokens + output_tokens
            # Approximate cost (Sonnet pricing)
            cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

            result = NarrativeResult(
                text=text,
                tokens_used=total_tokens,
                cost_estimate=cost,
                model_used=settings.ANTHROPIC_MODEL,
            )
            self._set_cache(cache_key, result)
            logger.info(
                "Narrative generated: template=%s, tokens=%d, cost=$%.4f",
                template, total_tokens, cost,
            )
            return result

        except Exception as e:
            logger.error("Claude API error: %s. Falling back to static template.", e)
            result = self._generate_fallback(context, template)
            self._set_cache(cache_key, result)
            return result


# Singleton instance
narrative_engine = NarrativeEngine()
