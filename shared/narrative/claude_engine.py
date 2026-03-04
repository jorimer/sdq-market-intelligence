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
    "sector_outlook": (
        "Eres el economista jefe de una firma de análisis financiero en República Dominicana.\n\n"
        "Genera una perspectiva sectorial basada en:\n{context}\n\n"
        "Incluye: contexto macroeconómico, tendencias regulatorias, "
        "perspectivas por segmento (banca múltiple, AAP, bancos de ahorro), "
        "riesgos y oportunidades. Formato SCQA. Máximo 800 palabras."
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
                model=settings.CLAUDE_MODEL,
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
                model_used=settings.CLAUDE_MODEL,
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
