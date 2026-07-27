"""Higiene de texto post-generación: quita el meta-comentario del modelo antes de que
llegue al render (PDF/Word/online).

MOTIVACIÓN (bug 2026-07-27, BPD full_rating, sección "Eficiencia y Rentabilidad"): el
modelo "pensó en voz alta" DENTRO de la prosa —"…por debajo del promedio sectorial…
espera —el ROA sectorial es 2.1 %…"— y ese "espera —" (auto-corrección) llegó al PDF de
cliente. NO era un bloque de razonamiento sin limpiar: la generación NO usa extended
thinking (no se pasa `thinking=` en ninguna llamada), así que `response.content[0].text`
ya es texto plano; el artefacto es literal en la respuesta.

Esta es la RED DE SEGURIDAD determinista (defensa en profundidad). La defensa primaria es
la instrucción de prompt (``NO_META_COMMENTARY`` en el system): que el modelo NO se
auto-corrija ni dude en voz alta. Este sanitizador GARANTIZA que, aun si el prompt falla,
ningún marcador de razonamiento/auto-corrección se renderice; y LOGuea cada intervención
para que la fuga sea observable (señal de que el prompt necesita refuerzo), no silenciosa.

Diseño conservador: se remueve SOLO el marcador meta (la interjección de auto-corrección o
el bloque de tags de razonamiento) y se normaliza el espacio/puntuación huérfana. NO se
borran oraciones completas ni cifras: perder contenido real sería peor que un empalme algo
áspero. Los patrones se anclan a interjecciones que no tienen lugar en prosa formal tier-1
(el REGISTER_NEUTRO ya proscribe apóstrofes retóricos y coloquialismos), minimizando el
falso positivo sobre español financiero legítimo.
"""
import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ── Bloques de razonamiento con tags (defensivo) ──────────────────────────────
# Aunque hoy NO se usa extended thinking, si alguna vez se activa —o si el modelo
# emite pseudo-tags— se remueve el bloque completo, no solo el tag de apertura.
_TAG_BLOCK = re.compile(
    r"<\s*(thinking|reasoning|reflection|scratchpad|thought|internal|analysis)\s*>"
    r".*?"
    r"<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# Tags huérfanos (apertura o cierre sueltos) del mismo vocabulario.
_TAG_STRAY = re.compile(
    r"<\s*/?\s*(thinking|reasoning|reflection|scratchpad|thought|internal|analysis)\s*>",
    re.IGNORECASE,
)
# Variante con corchetes: [thinking] … [/thinking] y sueltos.
_BRACKET_BLOCK = re.compile(
    r"\[\s*(thinking|reasoning|scratchpad)\s*\].*?\[\s*/\s*\1\s*\]",
    re.IGNORECASE | re.DOTALL,
)
_BRACKET_STRAY = re.compile(
    r"\[\s*/?\s*(thinking|reasoning|scratchpad)\s*\]",
    re.IGNORECASE,
)

# ── Interjecciones de auto-corrección / duda ("pensar en voz alta") ───────────
# El núcleo del bug. Marcadores que en prosa de informe solo aparecen cuando el modelo
# se corrige o duda a sí mismo. Se anclan a un límite de palabra y a la puntuación de
# interrupción típica (raya, coma, dos puntos, punto) para no morder verbos legítimos.
#
# Nota sobre "espera": es también verbo ("el mercado espera una baja"). Por eso NO se
# lista suelto: solo se captura cuando actúa como interjección seguida de raya/en-dash de
# interrupción ("… promedio sectorial… espera —el ROA…"), que es la forma del artefacto y
# no la del verbo. Cada captura se LOGuea para revisión humana.
_INTERJECTION_ALTS = [
    # español — auto-corrección explícita
    r"espera",
    r"esper[áa]te",
    r"aguanta",
    r"un moment[oo]",
    r"a\s+ver",
    r"veamos",
    r"d[ée]jame(?:\s+(?:ver|reconsiderar|pensar|revisar))?",
    r"perm[íi]teme(?:\s+(?:reconsiderar|revisar))?",
    r"me\s+corrijo",
    r"corrijo",
    r"correcci[óo]n",
    r"rectifico",
    r"me\s+equivoqu[ée]",
    r"pens[áa]ndolo\s+bien",
    r"ahora\s+que\s+(?:lo\s+pienso|reviso)",
    r"mejor\s+dicho",
    # inglés — CUALQUIER fuga en inglés dentro de un informe en español es meta
    r"wait",
    r"hold\s+on",
    r"let\s+me(?:\s+(?:reconsider|rethink|check|see))?",
    r"actually",
    r"scratch\s+that",
    r"on\s+second\s+thought",
    r"my\s+(?:mistake|bad|apolog(?:y|ies))",
    r"i\s+mean",
    r"oops",
    r"hmm+",
]
# La interjección: inicio-de-clausula (o principio del texto) + marcador + puntuación de
# interrupción (raya —/–, coma, dos puntos) que la desnuda como interjección, no como
# palabra de la oración. Consume la puntuación de interrupción para dejar un empalme limpio.
_INTERJECTION = re.compile(
    r"(?:(?<=^)|(?<=[\s—–\-.,;:…\"“”'‘’()]))"        # arranca en frontera de clausula
    r"(?:" + "|".join(_INTERJECTION_ALTS) + r")"       # el marcador meta
    r"\s*[—–]\s*"                                        # SEGUIDO de raya de interrupción
    ,
    re.IGNORECASE,
)
# Variante seguida de coma/dos-puntos en vez de raya: "wait, ", "corrección: ", "actually, ".
# Más restrictiva (menos alternativas) para no morder prosa: solo los marcadores que como
# palabra-inicial-de-frase seguida de coma son inequívocamente meta.
_UNAMBIGUOUS_COMMA_ALTS = [
    r"espera",
    r"esper[áa]te",
    r"un\s+moment[oo]",
    r"me\s+corrijo",
    r"corrijo",
    r"correcci[óo]n",
    r"me\s+equivoqu[ée]",
    r"pens[áa]ndolo\s+bien",
    r"wait",
    r"hold\s+on",
    r"scratch\s+that",
    r"on\s+second\s+thought",
    r"my\s+(?:mistake|bad|apolog(?:y|ies))",
    r"oops",
    r"hmm+",
]
_INTERJECTION_COMMA = re.compile(
    r"(?:(?<=^)|(?<=[.\n]\s)|(?<=[.\n]))"               # solo al inicio de una oración
    r"(?:" + "|".join(_UNAMBIGUOUS_COMMA_ALTS) + r")"
    r"\s*[,:]\s*"
    ,
    re.IGNORECASE,
)

# ── Auto-referencias del asistente (nunca en un informe) ──────────────────────
_SELF_REFERENCE = re.compile(
    r"[^.\n]*\b("
    r"como\s+(?:un\s+|una\s+)?(?:modelo\s+de\s+lenguaje|modelo\s+de\s+ia|ia|asistente\s+de\s+ia|asistente\s+virtual)"
    r"|as\s+an\s+ai(?:\s+(?:language\s+)?model|\s+assistant)?"
    r"|no\s+tengo\s+acceso\s+a"
    r"|i\s+don'?t\s+have\s+access"
    r")\b[^.\n]*\.?",
    re.IGNORECASE,
)


def _tidy(text: str) -> str:
    """Normaliza el espacio/puntuación huérfana que deja una remoción."""
    # espacio antes de puntuación de cierre. NO se incluye "%": en la tipografía de estos
    # informes la cifra lleva espacio fino antes del signo ("1.4 %"); tocarlo alteraría el
    # formato de una cifra, justo lo que el sanitizador promete no hacer.
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    # raya/en-dash huérfana pegada al inicio de clausula tras remover el marcador previo
    text = re.sub(r"(^|[.\n]\s*)[—–]\s*", r"\1", text)
    # elipsis + espacios colapsados: "…  el" → "… el"; "… …" → "…"
    text = re.sub(r"…\s*…", "…", text)
    # espacios múltiples a uno
    text = re.sub(r"[ \t]{2,}", " ", text)
    # espacio sobrante al principio de línea
    text = re.sub(r"(^|\n)[ \t]+", r"\1", text)
    # coma/raya duplicada por el empalme (", ," → ",")
    text = re.sub(r",\s*,", ",", text)
    return text.strip()


def strip_meta_commentary(text: str) -> Tuple[str, List[str]]:
    """Quita meta-comentario del modelo (auto-corrección, duda, tags de razonamiento,
    auto-referencias del asistente) de una narrativa.

    Devuelve ``(texto_limpio, removidos)`` donde ``removidos`` lista los fragmentos
    extraídos (para logging/telemetría). ``removidos`` vacío ⇒ el texto ya estaba limpio.
    Conservador por diseño: remueve el marcador, no la oración; nunca toca cifras.
    """
    if not text:
        return text, []

    removed: List[str] = []

    def _capture(pattern: re.Pattern, s: str, *, whole: bool = False) -> str:
        def _sub(m: re.Match) -> str:
            frag = m.group(0).strip()
            if frag:
                removed.append(frag)
            return "" if whole else " "
        return pattern.sub(_sub, s)

    # 1) bloques de razonamiento con tags/corchetes (remueve el contenido interno completo)
    text = _capture(_TAG_BLOCK, text, whole=True)
    text = _capture(_BRACKET_BLOCK, text, whole=True)
    # 2) tags/corchetes huérfanos
    text = _capture(_TAG_STRAY, text, whole=True)
    text = _capture(_BRACKET_STRAY, text, whole=True)
    # 3) auto-referencias del asistente (barre la clausula que las contiene)
    text = _capture(_SELF_REFERENCE, text, whole=True)
    # 4) interjecciones de auto-corrección / duda
    text = _capture(_INTERJECTION, text)
    text = _capture(_INTERJECTION_COMMA, text)

    if removed:
        text = _tidy(text)
    return text, removed
