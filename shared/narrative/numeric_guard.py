"""Guardrail numérico anti-alucinación para la ruta cerebro.

El estándar epistémico exige cero cifras inventadas (regla dura). El prompt lo pide,
pero un dígito puede deslizarse de forma estocástica. El sensor del piloto encontró tres
modos: (a) una cifra inexistente en la serie ("83.42" donde el real era 82.42); (b) un
valor real de la serie atribuido al período equivocado ("83.45 en marzo" cuando 83.45 es
de junio); (c) un claim relativo mal calculado ("11 puntos sobre la mediana" cuando la
resta da 3.77). Este guardrail lo convierte en una verificación mecánica: un modelo capaz
(Sonnet) juzga si TODA cifra del análisis se traza al contexto — comprobando la
correspondencia cifra↔período y la aritmética de los claims derivados, y tolerando
redondeos, derivaciones correctas, el telón macro BCRD y fechas/ordinales (que no son
cifras de dato). Devuelve las cifras NO respaldadas.

Es best-effort: si la verificación falla (API, parseo), devuelve [] y no bloquea — el
guardrail nunca debe empeorar la salida ni romper el endpoint.
"""
import json
import logging
import re
from typing import List

logger = logging.getLogger("sdq.narrative.numeric_guard")

_JUDGE_SYSTEM = (
    "Sos un verificador numérico estricto y preciso. Tu ÚNICA tarea es detectar cifras "
    "del ANÁLISIS que NO estén respaldadas por el CONTEXTO. No evalúas estilo ni calidad."
)

_JUDGE_USER = (
    "CONTEXTO (datos que tenía el analista):\n{context}\n\n"
    "ANÁLISIS a verificar:\n{text}\n\n"
    "Verificá CADA cifra del análisis. Hacé la aritmética vos mismo cuando haga falta.\n\n"
    "Una cifra está RESPALDADA si:\n"
    "- aparece en el contexto (exacta o redondeada), o\n"
    "- es una derivación de cifras del contexto que vos verificás correcta (resta, suma, "
    "razón, ×100, ÷100, diferencia entre percentiles, puntos porcentuales, aporte = "
    "score×peso, promedio ponderado), o\n"
    "- proviene del telón macro oficial ('contexto_oficial_bcrd') si está presente, o\n"
    "- es una fecha, año, trimestre, conteo (n=…) u ordinal de lista (no es una cifra de dato).\n\n"
    "Marcá como NO respaldada toda cifra que CONTRADIGA el contexto o que no pueda trazarse "
    "a él. Prestá atención especial a estos dos modos de error (NO los pases por alto):\n"
    "1) CORRESPONDENCIA CIFRA↔PERÍODO: si el análisis atribuye un valor a un período "
    "concreto (un año, trimestre o mes: 'marzo-2023', 'jun-2024', 'Q1 2025', 'cierre de "
    "marzo', 'dic-2024'), ese valor DEBE coincidir con el de ESE período en la serie. Un "
    "valor que existe en la serie pero corresponde a OTRO período del que se le asigna está "
    "MAL ATRIBUIDO → marcalo (p. ej. citar 83.45 como 'cierre de marzo' cuando 83.45 es el "
    "de junio y el de marzo es 83.12).\n"
    "2) CLAIMS RELATIVOS/DERIVADOS: toda afirmación del tipo 'N puntos por encima/debajo de "
    "la mediana/percentil/pico', 'subió/cayó N puntos', 'aporta N puntos' DEBE ser "
    "aritméticamente correcta contra sus bases del contexto. Computá la operación: si el N "
    "declarado no coincide (más allá de redondeo) → marcalo (p. ej. '11 puntos por encima "
    "de la mediana 82.65' cuando el score es 86.42 y la diferencia real es 3.77).\n\n"
    "Sé preciso: no marques redondeos legítimos, derivaciones correctas, ni el telón BCRD. "
    "Pero SÍ marcá los dos modos de arriba — son el objetivo.\n\n"
    "Devolvé SOLO un objeto JSON, sin texto alrededor:\n"
    "{{\"unsupported\": [\"<cifra> — <motivo breve>\", ...]}}\n"
    "Si todas están respaldadas: {{\"unsupported\": []}}"
)

CORRECTION_NOTICE = (
    "\n\nCORRECCIÓN OBLIGATORIA: en una versión previa de este análisis aparecieron "
    "cifras que NO están en el contexto: {bad}. Reescribí el análisis SIN inventar ni "
    "alterar ninguna cifra; usá EXCLUSIVAMENTE números del contexto (o derivaciones "
    "explícitas de ellos). Si no tenés una cifra, no la des."
)


def _parse_unsupported(raw: str) -> List[str]:
    """Extract the ``unsupported`` list from the judge's JSON reply (tolerant)."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    items = data.get("unsupported") or []
    return [str(x) for x in items if str(x).strip()][:20]


def verify_figures(client, model: str, context_str: str, text: str) -> List[str]:
    """Return the figures in *text* not supported by *context_str* (``[]`` if all OK
    or if the check can't run). Best-effort: never raises."""
    if not text.strip():
        return []
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": _JUDGE_USER.format(
                context=context_str, text=text)}],
        )
        return _parse_unsupported(resp.content[0].text)
    except Exception as e:  # noqa: BLE001 — best-effort; the guardrail must not break generation
        logger.warning("Guardrail numérico no pudo verificar (se sirve sin verificar): %s", e)
        return []
