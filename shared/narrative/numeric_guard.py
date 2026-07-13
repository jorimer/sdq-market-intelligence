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


# ── Verificación DETERMINISTA (cerebro banking) ─────────────────────────────────
# El juez LLM (aun Sonnet) no recomputa de forma fiable: deja pasar deltas mal
# calculados, valores reales atribuidos al período equivocado y rangos con el piso
# errado. Estos modos son MECÁNICOS — se computan en código y se verifican exacto.
# El detector opera sobre el contexto de entidad (forma de `ai_context_entity`):
# score_global, sub_componentes[{score,peso}], pares{sector,entity_type{median_score…}},
# tendencia_score[{periodo,score}]. Best-effort: si falta un campo, salta ese patrón.

_MONTH_TO_MM = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05",
    "junio": "06", "julio": "07", "agosto": "08", "septiembre": "09", "setiembre": "09",
    "octubre": "10", "noviembre": "11", "diciembre": "12",
}
_Q_TO_MM = {"1": "03", "2": "06", "3": "09", "4": "12"}
_NUM_WORDS = {
    "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
}
# Tolerancia: las cifras del cerebro son de 2 decimales; un claim "preciso" debe
# coincidir casi exacto. 0.3 absorbe redondeo a 1 decimal sin tragarse errores reales
# (15.7 vs 15, 6.2 vs 3.77, 88.96 vs 88.67 quedan fuera).
_TOL = 0.3
_DECIMAL = re.compile(r"\d+(?:\.\d+)?")


def _close(a: float, b: float, tol: float = _TOL) -> bool:
    return abs(a - b) <= tol


def _nums(s: str) -> List[float]:
    return [float(m) for m in _DECIMAL.findall(s)]


def _subset_sums(values: List[float], maxn: int = 6) -> set:
    """Todas las sumas de subconjuntos (≤ maxn elementos) — para 'aportan ~X combinados'."""
    sums = {0.0}
    for v in values[:maxn]:
        sums |= {s + v for s in sums}
    return sums


def _trend_by_month(trend: list, mm: str) -> List[float]:
    out = []
    for t in trend:
        p = str(t.get("periodo") or "")
        if len(p) >= 7 and p[5:7] == mm:
            try:
                out.append(float(t["score"]))
            except (TypeError, ValueError):
                continue
    return out


def deterministic_unsupported(context: dict, text: str) -> List[str]:
    """Cifras del *text* que CONTRADICEN el contexto por cómputo mecánico. Verifica:
    (1) delta vs mediana ligado a la base citada (pares/tipo vs sector),
    (2) rango sobre la ventana de 12T (piso/techo reales),
    (3) valor atado a un mes/trimestre contra la serie de ESE mes,
    (4) 'aporta(n) N puntos' que no es ningún aporte (score×peso) ni suma de aportes.
    Best-effort: nunca lanza; ante un campo ausente, salta el patrón."""
    flags: List[str] = []
    try:
        score = context.get("score_global")
        score = float(score) if score is not None else None
        subs = context.get("sub_componentes") or []
        pares = context.get("pares") or {}
        trend = context.get("tendencia_score") or []

        med_type = ((pares.get("entity_type") or {}).get("median_score"))
        med_sector = ((pares.get("sector") or {}).get("median_score"))
        med_type = float(med_type) if med_type is not None else None
        med_sector = float(med_sector) if med_sector is not None else None

        # (1) delta vs mediana — ligado a la base CITADA (el sustantivo inmediato tras
        #     "mediana"). Estricto cuando la base se nombra (pares/tipo vs sector);
        #     lenient si no hay qualifier (marca solo si no casa con NINGUNA base) para
        #     no dar falsos positivos cuando la frase es ambigua.
        if score is not None:
            d_type = abs(score - med_type) if med_type is not None else None
            d_sector = abs(score - med_sector) if med_sector is not None else None
            for m in re.finditer(
                r"(\d+(?:\.\d+)?)\s*(?:puntos?|pts?\.?)?\s*(?:por\s+)?"
                r"(?:encima|sobre|arriba|debajo|bajo)\s+(?:de\s+)?la\s+mediana"
                r"(?:\s+(?:de\s+sus\s+|de\s+su\s+|de\s+la\s+|de\s+los\s+|de\s+las\s+|"
                r"del\s+|de\s+)?(?P<obj>\w+))?", text, re.I):
                n = float(m.group(1))
                obj = (m.group("obj") or "").lower()
                if any(w in obj for w in ("sector", "sistema", "mercado")):
                    base, label = d_sector, "sector"
                elif any(w in obj for w in ("par", "tipo", "grupo", "categor",
                                            "multipl", "múltipl", "similar", "comparabl")):
                    base, label = d_type, "tipo"
                else:  # ambiguo → lenient: solo marca si no casa con ninguna base
                    cands = [d for d in (d_type, d_sector) if d is not None]
                    if cands and not any(_close(n, d) for d in cands):
                        flags.append(
                            f"{m.group(1)} puntos vs mediana: no casa con tipo "
                            f"({round(d_type, 2) if d_type is not None else '—'}) ni sector "
                            f"({round(d_sector, 2) if d_sector is not None else '—'})")
                    continue
                if base is None:
                    continue
                if not _close(n, base):
                    flags.append(
                        f"{m.group(1)} puntos vs mediana ({label}): real {round(base, 2)} "
                        f"({round(score, 2)}−{round(med_sector if label == 'sector' else med_type, 2)})")

        # (2) rango sobre la ventana — solo claims PRECISOS (con decimales) sobre 12T
        scores = []
        for t in trend:
            try:
                scores.append(float(t["score"]))
            except (TypeError, ValueError, KeyError):
                continue
        if scores:
            lo_w, hi_w = min(scores), max(scores)
            for m in re.finditer(
                r"(?:rango|oscil\w+|entre)\s+(?:de\s+)?(\d+\.\d+)\s*(?:[–\-]|a|y)\s*(\d+\.\d+)"
                r"[^.\n]{0,40}(?:trimestre|per[ií]odo|doce|12)", text, re.I):
                lo, hi = float(m.group(1)), float(m.group(2))
                lo, hi = min(lo, hi), max(lo, hi)
                if not _close(lo, lo_w, 0.15) or not _close(hi, hi_w, 0.15):
                    flags.append(
                        f"rango {m.group(1)}–{m.group(2)}: real {round(lo_w, 2)}–{round(hi_w, 2)} "
                        f"en la ventana")

        # (3) valor atado a mes contra la serie de ese mes. Formas conservadoras (mes
        #     completo, adyacencia estricta) para no falsear las descripciones de trend
        #     donde períodos y valores se alternan en secuencia.
        series = {str(t.get("periodo") or "")[:7]: t.get("score") for t in trend}
        _MONTHS = "|".join(_MONTH_TO_MM)

        #     forma A: 'VALUE (mes-AAAA)' / 'VALUE en mes AAAA' (valor → período inmediato)
        for m in re.finditer(
            r"(\d{2,3}\.\d+)\s*\(?(?:en\s+|de\s+)?(" + _MONTHS + r")[ \-]?(\d{4})",
            text, re.I):
            val, month, year = float(m.group(1)), m.group(2).lower(), m.group(3)
            period = f"{year}-{_MONTH_TO_MM[month]}"
            if period in series and series[period] is not None \
                    and not _close(val, float(series[period])):
                flags.append(
                    f"{m.group(1)} en {month}-{year}: real {series[period]} en ese período")
        #     forma C: 'mes AAAA (VALUE)' (período → valor PARENTÉTICO inmediato; estricta
        #     para no cruzar fronteras de cláusula)
        for m in re.finditer(
            r"(" + _MONTHS + r")[ \-]?(\d{4})\s*\((\d{2,3}\.\d+)\)", text, re.I):
            month, year, val = m.group(1).lower(), m.group(2), float(m.group(3))
            period = f"{year}-{_MONTH_TO_MM[month]}"
            if period in series and series[period] is not None \
                    and not _close(val, float(series[period])):
                flags.append(
                    f"{m.group(3)} atribuido a {month}-{year}: real {series[period]} "
                    f"en ese período")
        #     forma B: 'corte(s)/cierre(s) de marzo (V→V→V)' (mes sin año, secuencia)
        for m in re.finditer(
            r"(?:cortes?|cierres?)\s+de\s+(" + _MONTHS + r")\s*[^()\n]{0,20}\(([^)]*)\)",
            text, re.I):
            month = m.group(1).lower()
            month_scores = _trend_by_month(trend, _MONTH_TO_MM[month])
            for v in _nums(m.group(2)):
                if 40.0 <= v <= 100.0 and month_scores and \
                        not any(_close(v, ms) for ms in month_scores):
                    flags.append(
                        f"{v} como corte de {month}: no coincide con ningún {month} "
                        f"de la serie ({', '.join(str(x) for x in month_scores)})")

        # (5) comparación vs P75 — verifica DIRECCIÓN (debajo/encima) y magnitud
        if score is not None:
            p75_type = ((pares.get("entity_type") or {}).get("p75_score"))
            p75_sector = ((pares.get("sector") or {}).get("p75_score"))
            p75_type = float(p75_type) if p75_type is not None else None
            p75_sector = float(p75_sector) if p75_sector is not None else None
            for m in re.finditer(
                r"(?:(\d+(?:\.\d+)?)\s*(?:puntos?|pts?\.?)?\s*)?(?:por\s+)?"
                r"(?P<dir>encima|sobre|arriba|debajo|bajo)\s+(?:de\s+)?(?:el\s+|del\s+|la\s+)?"
                r"(?:p\.?\s?75|percentil\s*75)(?P<q>[^.,;\n]{0,30})", text, re.I):
                q = (m.group("q") or "").lower()
                base = p75_sector if "sector" in q else (p75_type if p75_type is not None
                                                         else p75_sector)
                if base is None:
                    continue
                d = (m.group("dir") or "").lower()
                above = d in ("encima", "sobre", "arriba")
                # dirección: margen de redondeo (0.05), no _TOL — un gap real de 0.15
                # invierte el lado aunque sea chico.
                if (above and score < base - 0.05) or (not above and score > base + 0.05):
                    flags.append(
                        f"'{d} del p75': el score {round(score, 2)} está del lado opuesto "
                        f"del p75 {round(base, 2)}")
                elif m.group(1) and not _close(float(m.group(1)), abs(score - base)):
                    flags.append(
                        f"{m.group(1)} vs p75: real {round(abs(score - base), 2)} "
                        f"({round(score, 2)} vs {round(base, 2)})")

        # (6) afirmación de EXTREMO ('el más bajo/alto', 'mínimo/máximo') sobre la ventana.
        #     Es errónea si EXISTE un valor estrictamente menor (para mínimo) o mayor (máximo)
        #     en la ventana — comparar contra el extremo con margen de redondeo, no _TOL.
        if scores:
            for m in re.finditer(
                r"(\d+\.\d+)\s*[,;:]?\s*(?:es\s+|fue\s+|sigue\s+siendo\s+)?"
                r"(?:el|la|un|una)?\s*(?:valor|punto|score|nivel|cierre)?\s*"
                r"(?P<ext>m[áa]s\s+baj[oa]|m[áa]s\s+alt[oa]|m[íi]nimo|m[áa]ximo|menor|"
                r"mayor|piso|techo)"
                r"\b[^.\n]{0,35}?(?:per[íi]odo|trimestre|doce|12|hist[óo]r|ventana|serie)",
                text, re.I):
                v = float(m.group(1))
                # ancla al dominio del score: el valor que dice ser el extremo de la
                # ventana DEBE ser un score de la ventana (si no, la frase habla de otra
                # métrica —ROE, eficiencia— que cae en el rango: no es nuestro asunto).
                if not any(_close(v, s, 0.3) for s in scores):
                    continue
                ext = m.group("ext").lower()
                is_min = ext.startswith(("más b", "mas b", "mín", "min", "menor", "piso"))
                target = min(scores) if is_min else max(scores)
                lower_exists = is_min and any(s < v - 0.05 for s in scores)
                higher_exists = (not is_min) and any(s > v + 0.05 for s in scores)
                if lower_exists or higher_exists:
                    flags.append(
                        f"{m.group(1)} como {'mínimo' if is_min else 'máximo'} de la ventana: "
                        f"real {round(target, 2)}")

        # (7) 'N trimestres (consecutivos) por debajo/encima de T' — todos del lado citado
        if scores:
            for m in re.finditer(
                r"(?P<cnt>\d+|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)"
                r"\s+trimestres?\s+(?:consecutiv\w+\s+)?(?:por\s+)?"
                r"(?P<dir>debajo|bajo|encima|sobre|arriba)\s+(?:de\s+)?(?P<thr>\d+(?:\.\d+)?)",
                text, re.I):
                tok = m.group("cnt").lower()
                n = int(tok) if tok.isdigit() else _NUM_WORDS.get(tok, 0)
                if not (1 <= n <= len(scores)):
                    continue
                thr = float(m.group("thr"))
                # ancla: el umbral debe caer en el rango del score (si no, la frase habla
                # de otra métrica —"eficiencia bajo 60", "ROE bajo 12"— no del score).
                if not (min(scores) - 3 <= thr <= max(scores) + 3):
                    continue
                below = (m.group("dir") or "").lower() in ("debajo", "bajo")
                last = scores[-n:]
                # margen de redondeo (0.05): un valor 0.24 al otro lado ya rompe el claim
                viol = any(v >= thr + 0.05 for v in last) if below \
                    else any(v <= thr - 0.05 for v in last)
                if viol:
                    side = "debajo" if below else "encima"
                    flags.append(
                        f"'{n} trimestres {side} de {m.group('thr')}': la serie reciente "
                        f"({', '.join(str(round(v, 2)) for v in last)}) no cumple")

        # (4) 'aporta(n) N puntos' que no traza a ningún aporte ni suma de aportes
        aportes = []
        for s in subs:
            try:
                aportes.append(float(s["score"]) * float(s["peso"]))
            except (TypeError, ValueError, KeyError):
                continue
        if aportes:
            allowed = _subset_sums(aportes) | set(aportes)
            for m in re.finditer(
                r"aport[ao]n?\s+(?:solo\s+|apenas\s+|~|unos?\s+)*(\d+\.\d+)\s*puntos?", text, re.I):
                n = float(m.group(1))
                if not any(_close(n, a) for a in allowed):
                    flags.append(
                        f"{m.group(1)} puntos de aporte: ningún score×peso ni suma de ellos "
                        f"lo respalda")
    except Exception as e:  # noqa: BLE001 — best-effort; jamás rompe la generación
        logger.warning("Chequeo determinista falló (se omite): %s", e)
        return flags
    # dedupe preservando orden
    seen, out = set(), []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def verify_figures(client, model: str, context_str: str, text: str) -> List[str]:
    """Return the figures in *text* not supported by *context_str* (``[]`` if all OK
    or if the check can't run). Best-effort: never raises."""
    if not text.strip():
        return []
    from shared.llm.budget import budget_allows, record_usage
    if not budget_allows():
        # Corte suave: sin presupuesto se omite el juez LLM; la capa DETERMINISTA
        # (deterministic_unsupported) sigue corriendo en el caller — el modo de
        # fallo mecánico queda cubierto igual.
        logger.warning("Juez LLM omitido por presupuesto (queda la capa determinista).")
        return []
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": _JUDGE_USER.format(
                context=context_str, text=text)}],
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            record_usage(model,
                         getattr(usage, "input_tokens", 0) or 0,
                         getattr(usage, "output_tokens", 0) or 0)
        return _parse_unsupported(resp.content[0].text)
    except Exception as e:  # noqa: BLE001 — best-effort; the guardrail must not break generation
        logger.warning("Guardrail numérico no pudo verificar (se sirve sin verificar): %s", e)
        return []
