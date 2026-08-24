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
import math
import re
import unicodedata
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sdq.narrative.numeric_guard")

# Versión de la LÓGICA del guardrail, para la huella de caché de la narrativa.
# Los prompts se cubren solos (la huella hashea el system ensamblado), pero un cambio en
# el CÓDIGO de este módulo —una regla nueva, un umbral distinto— no cambia ningún prompt y
# pasaría inadvertido: la caché seguiría sirviendo texto que el guard nuevo habría marcado.
# Es el único bump manual irreducible; por eso vive acá, junto a lo que describe.
GUARD_VERSION = "7"  # "7": la brecha invertida también se dice con VERBO (2026-08-24)

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

# Aviso PROPIO para la dirección invertida: acá las cifras SÍ están en el contexto y son
# correctas — lo que está mal es el sentido de la comparación. Reusar CORRECTION_NOTICE
# mandaría al modelo a "no inventar cifras", que no es el problema, y probablemente le
# haría borrar la comparación en vez de corregirle el signo.
DIRECTION_CORRECTION_NOTICE = (
    "\n\nCORRECCIÓN OBLIGATORIA: en una versión previa de este análisis una comparación "
    "quedó INVERTIDA respecto de los datos: {bad}. Las cifras son correctas; lo que está "
    "mal es el sentido. Reescribí esas afirmaciones con la dirección correcta (restá y "
    "mirá el signo antes de escribir 'por encima' / 'por debajo'), sin alterar ningún "
    "número y sin eliminar la comparación."
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


def _as_number(token: str) -> Optional[float]:
    """Un dígito o un numeral escrito en palabras ("ocho" → 8.0). ``None`` si no es ninguno.

    Existe porque el detector buscaba SOLO dígitos: «una caída de ocho puntos en doce meses»
    —dos cifras, cero dígitos— era literalmente invisible, y así llegó a la Recomendación de
    un informe de cliente.
    """
    t = (token or "").strip().lower().replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        v = _NUM_WORDS.get(t)
        return float(v) if v is not None else None


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


# ── Adaptador de FORMA del contexto ───────────────────────────────────────────
#
# El detector nació leyendo `ai_context_entity` (score_global / sub_componentes /
# tendencia_score[periodo]). La ruta de REPORTES arma su contexto con otros nombres
# (overall_score / sub_components / trayectoria_score[period_end]), así que los seis
# patrones no encontraban su insumo y devolvían [] — no por haber verificado, sino por no
# tener qué mirar. Con eso, la única capa viva en los informes de cliente era el juez LLM.
#
# Se resuelve acá, en el punto de lectura, y no pidiéndole a cada eje que renombre sus
# claves: la lección de este repo es que el guard atado a UNA forma reaparece muerto en el
# siguiente motor. `guard_coverage` publica qué insumos encontró para que "0 hallazgos" se
# pueda distinguir de "no miré nada".

_ALIAS_SCORE = ("score_global", "overall_score")
_ALIAS_SUBS = ("sub_componentes", "sub_components")
_ALIAS_TREND = ("tendencia_score", "trayectoria_score", "trayectoria", "tendencia")
_ALIAS_PERIODO = ("periodo", "period_end", "period")
_ALIAS_PESOS = ("pesos_sub_componentes", "pesos", "weights")


def _first(context: dict, names) -> Any:
    for n in names:
        v = context.get(n)
        if v not in (None, {}, []):
            return v
    return None


def _norm_trend(context: dict) -> List[Dict[str, Any]]:
    """La serie como ``[{"periodo": "YYYY-MM-DD", "score": float}, ...]``, venga como venga."""
    serie = _first(context, _ALIAS_TREND) or []
    if isinstance(serie, dict):  # {periodo: score}
        serie = [{"periodo": k, "score": v} for k, v in serie.items()]
    out: List[Dict[str, Any]] = []
    for p in serie:
        if not isinstance(p, dict):
            continue
        periodo = next((p[k] for k in _ALIAS_PERIODO if p.get(k) is not None), None)
        if periodo is None or p.get("score") is None:
            continue
        out.append({"periodo": str(periodo), "score": p["score"]})
    return out


def _norm_subs(context: dict) -> List[Dict[str, Any]]:
    """Sub-componentes como ``[{"score": float, "peso": float}, ...]``.

    La forma de reportes es un dict ``{nombre: score}`` sin pesos; sin ellos el patrón de
    aportes (score×peso) no puede computar nada, así que se buscan los pesos declarados en
    el propio contexto y, si no están, se devuelve vacío en vez de inventarlos.
    """
    subs = _first(context, _ALIAS_SUBS)
    if isinstance(subs, list):
        return [s for s in subs if isinstance(s, dict)]
    if isinstance(subs, dict):
        pesos = _first(context, _ALIAS_PESOS) or {}
        if not isinstance(pesos, dict):
            return []
        return [{"score": v, "peso": pesos[k]}
                for k, v in subs.items() if pesos.get(k) is not None and v is not None]
    return []


_ALIAS_TREND_SUB = ("trayectoria_sub", "tendencia_sub", "trayectorias_sub",
                    "trayectoria_sub_componente")


def _norm_series_map(context: dict) -> Dict[str, List[Dict[str, Any]]]:
    """TODAS las series del contexto: la global y la de cada sub-componente.

    Necesario para no gritar en falso. Un informe de entidad discute seis series a la vez
    (el score global y sus cinco dimensiones), y los patrones que atan un valor a un período
    o una caída a una ventana asumían que toda cifra era del score GLOBAL. Conectados a la
    ruta de reportes, eso marcaba prosa correcta: «desde 73.39 en junio 2024… en el
    sub-componente de solidez» se leía como un error del score global (74.81).

    La regla honesta es: un claim está sin respaldo si no lo sostiene NINGUNA serie conocida.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    g = _norm_trend(context)
    if g:
        out["global"] = g
    subs = _first(context, _ALIAS_TREND_SUB)
    if isinstance(subs, dict):
        for k, v in subs.items():
            s = _norm_trend({"tendencia_score": v})
            if s:
                out[str(k)] = s
    elif isinstance(subs, list):  # contexto de UNA dimensión (sección de sub-componente)
        s = _norm_trend({"tendencia_score": subs})
        if s:
            out["sub_componente"] = s
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Cifra citada que no está en el contexto — sin forma fija
# ─────────────────────────────────────────────────────────────────────────────
#
# Todo lo que sigue en este módulo lee la forma del contexto de banca: `score`, `pares`,
# `entity_type`, `median_score`. En un módulo con otra forma no encuentra nada y devuelve
# `[]` — que no es «está limpio», es «no miré». La prueba negativa sobre el informe de
# marca en producción: un texto con el 61 % donde el dato dice 84 %, un error de 2,3 %
# donde dice 7,4 % y un local inexistente pasaba con CERO banderas.
#
# Esta regla no conoce ninguna forma. Extrae los números del contexto, sea cual sea su
# estructura, y exige que toda cifra citada esté entre ellos.
#
# **La tolerancia tuvo que cambiar, y esa es la decisión de diseño.** El `_TOL = 0.3` del
# resto del módulo sirve con los pocos números de un contexto de banca; con los 156 de una
# sección de marca cubre el 57 % del rango 0-100 y el chequeo se vuelve decorativo. Acá la
# coincidencia es exacta a un decimal: medido, una cifra inventada en 0-100 escapa el
# 11,6 % de las veces en vez del 57 %.
#
# Se acepta el redondeo Y la truncación a un decimal. El informe real escribió «5,4 puntos»
# de un 5,47 del contexto: no es una cifra inventada, es otra convención de redondeo, y
# marcarla costaría una regeneración por un decimal. Medido: aceptarla baja el escape de
# 11,3 % a 11,6 % y elimina el único falso positivo de 73 cifras citadas en nueve secciones
# reales de producción.
#
# **Lo que NO hace, dicho para que no se le suponga alcance.** Dos cosas, las dos por
# medición y no por olvido:
#
# 1. No verifica NOMBRES PROPIOS. Un local inventado sigue pasando. Se probó —«toda entidad
#    citada existe en el contexto»— y midió 44 % de ruido sobre esas mismas nueve secciones:
#    títulos de informe, saltos de línea dentro de un nombre y capturas entre oraciones. Un
#    guard que marca casi todo se desactiva, y desactivado es peor que ausente.
# 2. No mira cifras en «puntos». Ver la nota de ``_CLAIM_UNIT``.
#
# Y el poder que sí tiene está medido, no supuesto: sobre el contexto más denso del repo
# (156 números), una cifra inventada en 0-100 escapa el 11,6 % de las veces. No es una
# garantía, es una red — la que hoy no existe en ningún módulo que no sea banca.

#: SOLO porcentajes, y la exclusión de «puntos» es el resultado de una medición, no una
#: omisión. Con «puntos» dentro, esta regla marcaba el 30 % de los casos limpios del corpus
#: de banca: «3,77 puntos por encima de la mediana» es score − mediana y «40 puntos» es
#: score × peso. Banca DERIVA sus relaciones en la narrativa —y la aritmética de esas
#: derivaciones ya la verifican los chequeos de arriba, que sí conocen su forma—; marca las
#: sirve precomputadas. El punto es la unidad de la relación derivada; el porcentaje, la de
#: la cifra citada.
#:
#: Medido sobre los dos corpus: con «puntos», 7 falsos positivos de 23 casos limpios de
#: banca; sin «puntos», CERO en banca y cero en las nueve secciones reales de marca, a
#: cambio de perder una de seis detecciones sobre un texto inventado.
_CLAIM_UNIT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|por\s+ciento)", re.I)


def context_values(context: Any) -> set:
    """Todos los números del contexto, en valor absoluto y SIN redondear.

    Recorre la estructura completa sin conocerla: dicts, listas y también los números
    incrustados en las glosas de texto, que el motor sirve y el modelo puede citar con
    todo derecho.

    Devuelve los valores crudos a propósito: quien compara decide la precisión. Fijarla acá
    fue lo que produjo el falso positivo — ver ``deterministic_uncited_figures``.
    """
    out: set = set()

    def _add(x: float) -> None:
        out.add(abs(float(x)))

    def _walk(o: Any) -> None:
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            _add(o)
        elif isinstance(o, str):
            for tok in re.findall(r"-?\d+(?:[.,]\d+)?", o):
                try:
                    _add(float(tok.replace(",", ".")))
                except ValueError:
                    continue
        elif isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, (list, tuple, set)):
            for v in o:
                _walk(v)

    _walk(context)
    return out


def context_figures(context: Any) -> set:
    """Los números del contexto a un decimal (redondeo y truncación).

    Se conserva para ``guard_coverage`` y para quien solo necesite saber SI hay cifras. La
    verificación de una cita ya no pasa por acá: usa ``context_values`` a la precisión que
    la cita declara.
    """
    out: set = set()
    for a in context_values(context):
        out.add(round(a, 1))
        out.add(math.floor(a * 10) / 10)
    return out


def _decimales(literal: str) -> int:
    """Decimales que DECLARA la cita: '69' → 0, '69,1' → 1, '69,46' → 2."""
    normal = literal.replace(",", ".")
    return len(normal.split(".", 1)[1]) if "." in normal else 0


def deterministic_uncited_figures(context: dict, text: str) -> List[str]:
    """Porcentajes y puntos del *text* que no aparecen en el contexto.

    La comparación se hace **a la precisión que declara la cita**: ``69%`` (cero decimales)
    está respaldado por cualquier valor del contexto que redondee —o trunque— a 69;
    ``69,1%`` sigue exigiendo el decimal. Es cómo lee un humano una cifra redondeada.

    Antes la comparación era SIEMPRE a un decimal, y eso vetaba citas correctas. El caso que
    lo destapó (Deep Dive de banca múltiple, Q1-2026): la trayectoria servida traía un
    cost-to-income de 69,1344% (jun-2024) y 69,4575% (dic-2024) — el guard "veía" 69,1 y 69,4,
    la narrativa dijo "69%" (=69,0), no matcheó, y el informe se vetó ENTERO: 157 s y ~US$1 de
    modelo para un error en pantalla. Había un 69 real y citable en el contexto.

    Contrapartida DECLARADA: un entero inventado (80%, 100%) ahora pasa si el contexto tiene
    algo en su banda de redondeo. Se acepta a sabiendas — este es el filtro mecánico y barato,
    y nunca fue el único: el juez semántico del motor corre aparte y ve lo que éste no (por eso
    el motor además se niega a propagar a la caché compartida lo que él marcó). Vetar prosa
    correcta no es "ser estricto": es negar el producto por un número que sí estaba.

    Best-effort y conservador: solo mira cifras con unidad de dato, y ante un contexto sin
    números no marca nada (sin insumo no hay verificación, y fingirla sería el mismo modo
    de falla que esta regla vino a cerrar).
    """
    flags: List[str] = []
    try:
        known = context_values(context)
        if not known:
            return []
        seen: set = set()
        for m in _CLAIM_UNIT.finditer(text or ""):
            literal = m.group(1)
            try:
                value = abs(float(literal.replace(",", ".")))
            except ValueError:
                continue
            dp = _decimales(literal)
            escala = 10 ** dp
            # Redondeo Y truncación, las dos formas legítimas de acortar una cifra.
            respaldada = any(
                round(x, dp) == value or math.floor(x * escala) / escala == value
                for x in known)
            if respaldada or m.group(0).strip() in seen:
                continue
            seen.add(m.group(0).strip())
            flags.append(f"{m.group(0).strip()}: no aparece en el contexto servido")
    except Exception:  # noqa: BLE001 — el guard nunca tumba la entrega
        logger.exception("deterministic_uncited_figures falló; se sigue sin esa capa")
    return flags


def guard_coverage(context: dict) -> Dict[str, bool]:
    """Qué insumos del chequeo determinista EXISTEN en este contexto.

    Sirve para la prueba negativa: ``[]`` hallazgos con cobertura vacía significa «el guard
    no miró nada», que es un modo de falla silencioso y distinto de «está limpio».
    """
    return {
        "score": _first(context, _ALIAS_SCORE) is not None,
        "serie": bool(_norm_trend(context)),
        "sub_componentes": bool(_norm_subs(context)),
        "pares": bool(context.get("pares")),
        "posiciones_dimension": bool(context.get("posiciones_dimension")),
        "comparaciones": bool(context.get("comparaciones")),
        # La única que no depende de la forma del contexto: si hay números, hay
        # verificación. Es la que hace que `[]` signifique «limpio» y no «no miré».
        "cifras_del_contexto": bool(context_figures(context)),
    }


def deterministic_unsupported(context: dict, text: str) -> List[str]:
    """Cifras del *text* que CONTRADICEN el contexto por cómputo mecánico. Verifica:
    (1) delta vs mediana ligado a la base citada (pares/tipo vs sector),
    (2) rango sobre la ventana de 12T (piso/techo reales),
    (3) valor atado a un mes/trimestre contra la serie de ESE mes,
    (4) 'aporta(n) N puntos' que no es ningún aporte (score×peso) ni suma de aportes.
    Best-effort: nunca lanza; ante un campo ausente, salta el patrón."""
    flags: List[str] = []
    try:
        score = _first(context, _ALIAS_SCORE)
        score = float(score) if score is not None else None
        subs = _norm_subs(context)
        pares = context.get("pares") or {}
        trend = _norm_trend(context)

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
        # Todas las series del informe (global + cada dimensión). Un valor atado a un
        # período solo está SIN RESPALDO si no coincide con NINGUNA de ellas: el informe
        # discute seis series a la vez y atribuirlas todas al score global marcaba prosa
        # correcta («73.39 en junio 2024 … en el sub-componente de solidez»).
        _mapa = _norm_series_map(context)

        def _algun_valor(period: str, val: float) -> bool:
            for s in _mapa.values():
                for t in s:
                    if str(t["periodo"])[:7] == period and _close(val, float(t["score"])):
                        return True
            return False

        #     forma A: 'VALUE (mes-AAAA)' / 'VALUE en mes AAAA' (valor → período inmediato)
        for m in re.finditer(
            # `mes DE año` es la forma natural en español y la que usan estos informes
            # ("74.30 en marzo de 2024"). El separador sólo aceptaba espacio o guion, así
            # que la preposición dejaba el patrón ciego — con una cifra INVENTADA delante.
            r"(\d{2,3}\.\d+)\s*\(?(?:en\s+|de\s+)?(" + _MONTHS + r")(?:\s+de\s+|[ \-])?(\d{4})",
            text, re.I):
            val, month, year = float(m.group(1)), m.group(2).lower(), m.group(3)
            period = f"{year}-{_MONTH_TO_MM[month]}"
            if period in series and series[period] is not None \
                    and not _algun_valor(period, val):
                flags.append(
                    f"{m.group(1)} en {month}-{year}: real {series[period]} en ese período")
        #     forma C: 'mes AAAA (VALUE)' (período → valor PARENTÉTICO inmediato; estricta
        #     para no cruzar fronteras de cláusula)
        for m in re.finditer(
            r"(" + _MONTHS + r")(?:\s+de\s+|[ \-])?(\d{4})\s*\((\d{2,3}\.\d+)\)", text, re.I):
            month, year, val = m.group(1).lower(), m.group(2), float(m.group(3))
            period = f"{year}-{_MONTH_TO_MM[month]}"
            if period in series and series[period] is not None \
                    and not _algun_valor(period, val):
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

        # (9) MAGNITUD DE LA CAÍDA sobre una ventana declarada: "una caída de N puntos en M
        #     meses/trimestres/cortes". Es el claim que resume la trayectoria en una sola
        #     cifra, así que es el que un comité cita — y el que salió mal:
        #
        #       §11 Recomendación, BPD 2025-12-31: «una caída sostenida de fortaleza
        #       financiera —OCHO PUNTOS en doce meses—», cuando el score global cedió 2.39
        #       en doce meses y ningún sub-componente cae más de 6.8. Sin referente.
        #
        #     Se escapaba por DOS razones a la vez: la cifra iba en PALABRAS (el detector
        #     busca dígitos) y la ventana también. `_NUM_WORDS` ya existía en el módulo,
        #     usado en un solo patrón.
        if len(scores) >= 2:
            _CNT = r"\d+(?:\.\d+)?|" + "|".join(_NUM_WORDS)
            for m in re.finditer(
                r"(?P<hedge>aproximadamente\s+|cerca\s+de\s+|casi\s+|unos?\s+|~\s*)?"
                r"(?P<n>" + _CNT + r")\s*puntos?\b"
                r"[^.;\n]{0,40}?\ben\s+(?P<m>" + _CNT + r")\s*"
                r"(?P<u>meses|trimestres?|cortes?|per[íi]odos?)",
                text, re.I):
                cantidad = _as_number(m.group("n"))
                ventana = _as_number(m.group("m"))
                if cantidad is None or ventana is None or ventana <= 0:
                    continue
                # meses → trimestres. La ventana se cuenta en INTERVALOS, no en puntos:
                # "seis trimestres" son 6 saltos, o sea 7 cortes.
                base = int(round(ventana / 3)) if m.group("u").lower().startswith("mes") \
                    else int(round(ventana))
                # "corte" y "trimestre" se usan como sinónimos en esta prosa ("6.79 puntos
                # en cuatro cortes" para un tramo de cuatro trimestres), así que la unidad
                # NO decide si el número cuenta puntos o saltos. Se aceptan las dos
                # lecturas y solo se marca si NINGUNA cuadra: un guard que discute el
                # off-by-one de un sinónimo es ruido que se aprende a ignorar.
                candidatos = {base, base - 1} if not m.group("u").lower().startswith("mes") \
                    else {base}
                candidatos = {s for s in candidatos if 1 <= s < len(scores)}
                if not candidatos:
                    continue
                # Un claim redondeado ("tres puntos") o con matizador admite más holgura que
                # uno con decimales; sin esa distinción el detector marcaría prosa correcta.
                tol = 1.0 if m.group("hedge") else (_TOL if "." in m.group("n") else 0.6)
                # (las locales llevan nombre propio: `n`/`s` ya están tomados por otros
                # patrones de esta misma función y mypy infiere el tipo del primer uso)
                # Contra TODAS las series: el informe habla del score global y de sus cinco
                # dimensiones. "6.79 puntos en doce meses" es correcto para calidad de
                # activos y falso para el global — atribuirlo al global marcaba prosa buena.
                deltas = []
                for nombre, serie in (_norm_series_map(context)
                                      or {"global": trend}).items():
                    vals = [float(t["score"]) for t in serie]
                    for saltos in candidatos:
                        if len(vals) > saltos:
                            deltas.append((nombre, abs(vals[-1] - vals[-(saltos + 1)]),
                                           vals[-(saltos + 1)], vals[-1]))
                if not deltas or any(_close(cantidad, d, tol) for _n, d, _a, _b in deltas):
                    continue
                nom, real, ini, fin = min(deltas, key=lambda x: abs(x[1] - cantidad))
                flags.append(
                    f"'{m.group('n')} puntos en {m.group('m')} {m.group('u')}': ninguna "
                    f"serie cede eso en esa ventana (la más cercana, {nom}, cede "
                    f"{round(real, 2)}: {round(ini, 2)} → {round(fin, 2)})")

        # (10) VENTANA de un tramo citado por sus extremos: "a lo largo de N cortes —de X a
        #      Y—". Verifica que el CONTEO case con la distancia real entre X e Y en la
        #      serie. Nace de que dos secciones del mismo informe anclaron la trayectoria en
        #      puntos distintos (el pico y el inicio de ventana) sin reconciliarlo: las dos
        #      eran correctas, pero nada garantizaba que lo fueran.
        if len(scores) >= 2:
            _CNT2 = r"\d+|" + "|".join(_NUM_WORDS)
            for m in re.finditer(
                r"(?P<n>" + _CNT2 + r")\s+(?P<u>cortes?|trimestres?|per[íi]odos?)"
                r"[^.;\n]{0,60}?\bde\s+(?P<a>\d{2,3}\.\d+)\s*(?:a|hasta|→|-)\s*"
                r"(?P<b>\d{2,3}\.\d+)",
                text, re.I):
                cuenta = _as_number(m.group("n"))
                if cuenta is None:
                    continue
                ia = next((i for i, s in enumerate(scores) if _close(s, float(m.group("a")))),
                          None)
                ib = next((i for i, s in enumerate(scores) if _close(s, float(m.group("b")))),
                          None)
                if ia is None or ib is None:
                    continue  # los extremos no son de esta serie: no es nuestro claim
                puntos = abs(ib - ia) + 1
                # Misma ambigüedad corte↔trimestre que en (9): se aceptan las dos lecturas
                # del conteo y solo se marca cuando ninguna cuadra. Así "ocho cortes de
                # 74.30 a 71.76" (real: 8 puntos) pasa y "seis cortes" para ese mismo tramo
                # se marca, que es la distinción que importa.
                if puntos not in (int(cuenta), int(cuenta) + 1):
                    unidad = m.group("u").lower()
                    flags.append(
                        f"'{m.group('n')} {unidad} de {m.group('a')} a {m.group('b')}': "
                        f"entre esos dos valores la serie tiene {puntos} cortes "
                        f"({puntos - 1} trimestres)")

        # (8) SUPERLATIVO TRANSVERSAL ('el mayor/más alto/líder … del sistema/panel') en una
        #     dimensión donde la entidad NO lidera. Lee ``posiciones_dimension`` {label:
        #     {rank,n,es_lider,lider_afp}} — el modo de error del Deep Dive de pensiones: rank
        #     global #1 mal-generalizado a "el mayor" en escala/solvencia que otro lidera.
        pos = context.get("posiciones_dimension") or {}
        if pos:
            # Sinónimos TRANSVERSALES: además de las dimensiones de pensiones (donde nació
            # el patrón) cubren las de banca (solidez/calidad/eficiencia/liquidez/
            # diversificación) y seguros (siniestralidad/técnico). Sin esto el patrón
            # reconocía la dimensión sólo en el vocabulario de pensiones.
            _SYN = {
                "escala": ("escala", "activos", "fondo", "aum", "tamaño", "tamano", "masa",
                           "primas", "cartera"),
                "solvencia": ("solvencia", "patrimon", "capital", "apalancam", "solidez",
                              "icap", "cobertura"),
                "rentabilidad": ("rentabilidad", "retorno", "rendimiento", "roa", "roe",
                                 "margen", "utilidad", "resultado"),
                "riesgo": ("riesgo", "volatil", "consistencia", "sharpe", "calidad",
                           "morosidad", "mora", "siniestral"),
                "costo": ("costo", "comisi", "eficien", "gasto"),
                "liquidez": ("liquidez", "liquid", "fondeo", "depósit", "deposit"),
                "diversificacion": ("diversificaci", "concentraci", "hhi", "herfindahl"),
            }

            def _group(label: str):
                low = label.lower()
                for g, kws in _SYN.items():
                    if any(k in low for k in kws):
                        return g
                return None

            not_led = {}
            for label, info in pos.items():
                if info and info.get("es_lider") is False:
                    kws = set(_SYN.get(_group(str(label)), ())) | {str(label).lower().split()[0]}
                    not_led[label] = (info, kws)

            # Léxico del superlativo. "sin precedente / nunca visto / inigualable" se suma
            # tras el hallazgo del Deep Dive de banca ("capacidad de absorción de pérdidas
            # sin precedente en el sistema"): un percentil 100 dice "el mejor de la muestra
            # ACTUAL", jamás "nunca visto en la historia del sistema" — es un salto de
            # alcance temporal, no solo un superlativo transversal.
            # El ámbito se amplía a los grupos de banca y seguros; antes sólo reconocía el
            # vocabulario de pensiones, así que en esos ejes no disparaba nunca.
            _SUPER = re.compile(
                r"(mayor|m[áa]s\s+alt[oa]|m[áa]s\s+baj[oa]|l[íi]der|dominante|"
                r"sin\s+precedente[s]?|nunca\s+vist[oa]|inigualable|insuperable|"
                r"sin\s+par(?:ang[óo]n)?|el\s+mejor|la\s+mejor)"
                # La ventana se queda en 50: ampliarla deja que un superlativo LEJANO se
                # coma el claim de otra dimensión ("la mayor base de activos con el índice
                # de solvencia más alto del panel" se anclaba en escala en vez de solvencia).
                r"[^.\n]{0,50}?(del\s+sistema|en\s+el\s+sistema|del\s+panel|del\s+mercado|"
                r"de\s+las\s+afp|entre\s+las\s+afp|de\s+la\s+banca|entre\s+los\s+bancos|"
                r"del\s+grupo|de\s+sus\s+pares|entre\s+sus\s+pares|del\s+sector|"
                r"de\s+las\s+aseguradoras|entre\s+las\s+aseguradoras)", re.I)
            for m in _SUPER.finditer(text):
                pre = text[max(0, m.start() - 30):m.start()].lower()
                if re.search(r"\b(no|tampoco|ni)\b|sin\s+ser", pre):
                    continue  # superlativo NEGADO ('no es el mayor') — no es una afirmación
                lo = max(0, m.start() - 70)
                window = text[lo:min(len(text), m.end() + 15)].lower()
                anchor = m.start() - lo  # posición del superlativo dentro de la ventana
                # Elegí la dimensión no-líder cuyo keyword esté MÁS CERCA del superlativo
                # (evita cruzar 'activos' de escala cuando el claim es de solvencia).
                best, best_dist = None, 10 ** 9
                for label, (info, kws) in not_led.items():
                    for k in kws:
                        idx = window.rfind(k, 0, anchor + (m.end() - m.start()))
                        if idx != -1 and abs(anchor - idx) < best_dist:
                            best, best_dist = (label, info), abs(anchor - idx)
                if best:
                    label, info = best
                    # `lider` es el campo transversal; `lider_afp` se conserva por el
                    # contexto de pensiones, que lo emite con ese nombre.
                    lider = info.get("lider") or info.get("lider_afp")
                    flags.append(
                        f"'{m.group(0).strip()}' en {label}: la entidad no lidera esa "
                        f"dimensión (rank {info.get('rank')}/{info.get('n')}; lidera "
                        f"{lider})")

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


# ─── Dirección de las comparaciones ──────────────────────────────────────────────
#
# Modo de error DISTINTO al de `deterministic_unsupported`: ahí la cifra no se traza al
# contexto; acá las DOS cifras están en el contexto y son correctas, pero el sentido de la
# comparación está invertido ("la mora de 1.67% se sitúa por debajo del promedio de pares
# (1.5%)"). El juez LLM no lo ve —corrió sobre ese texto y lo dejó pasar—, y no debería:
# comparar dos floats es decidible, así que se resuelve mecánicamente y con garantía.

# Indicador → clave del benchmark. Espeja el mapeo de ``shared/data/sib_client.py``; se
# replica acá a propósito para no acoplar el guardrail de narrativa (transversal) al
# cliente de datos de banca.
_BENCH_KEY = {
    "solvencia": "car",
    "morosidad": "npl",
    "roa": "roa",
    "roe": "roe",
    "margen_financiero": "nim",
    "cost_to_income": "cost_to_income",
    "liquidez_inmediata": "liquidity_ratio",
    "leverage": "leverage_ratio",
    "cobertura_provisiones": "coverage_ratio",
    "ltd": "ltd",
}

_MENOR = r"por\s+debajo|inferior(?:es)?\s+a|menor(?:es)?\s+(?:que|a)"
_MAYOR = r"por\s+encima|superior(?:es)?\s+a|supera|excede|mayor(?:es)?\s+(?:que|a)"
# El % era heredado de banca, donde todo indicador es porcentaje. En seguros y pensiones
# los scores van sin él ("solvencia 80", "80/100"), así que el detector no veía nada. Se
# acepta la cifra desnuda: lo que evita el falso positivo NO es el %, sino el pareo estricto
# —debe casar con un valor CONOCIDO a la precisión citada, entidad antes del marcador y
# referencia después, acotada al operando de ESE marcador—.
_CITED = re.compile(r"(\d+(?:[.,]\d+)?)\s*%?")


def _cited_matches(cited: str, value: float) -> bool:
    """¿La cifra citada *cited* es este *value*, a la precisión con que fue escrita?

    Comparar con una tolerancia absoluta fija no sirve acá: ``_TOL`` (0.3) se tragaría
    justo el caso real (1.67 vs 1.5 difieren 0.17). Se compara redondeando el valor a los
    decimales que el autor escribió — así "1.7" y "1.67" ambos casan con 1.67, pero 1.5 no.
    """
    txt = cited.replace(",", ".")
    decimals = len(txt.split(".")[1]) if "." in txt else 0
    try:
        return abs(round(value, decimals) - float(txt)) < 1e-9
    except (TypeError, ValueError):
        return False


def _direction_refs(context: dict) -> List[tuple]:
    """``[(indicador, valor_entidad, [(etiqueta_referencia, valor), ...]), ...]``.

    Tolerante por diseño: acepta las dos grafías de la clave de indicadores (``indicators``
    en las secciones de panorama, ``indicadores`` en las de sub-componente) y si no
    reconoce el indicador simplemente no lo evalúa — nunca inventa un veredicto.

    Vía PREFERENTE y agnóstica de eje: si el contexto trae ``comparaciones`` YA RESUELTAS
    (las que inyecta ``derived.comparaciones_vs_referencia``), se usan como índice tal cual.
    Eso hace que el detector cubra seguros y pensiones sin conocer su vocabulario: la vía de
    abajo depende de ``_BENCH_KEY``, que es el mapeo de BANCA, y por eso el guard estaba
    ciego fuera de ese eje. Con las comparaciones inyectadas, verificar la dirección es leer
    el mismo dato que el analista debía copiar.
    """
    comps = context.get("comparaciones")
    if isinstance(comps, list) and comps:
        por_indicador: Dict[str, tuple] = {}
        for c in comps:
            if not isinstance(c, dict):
                continue
            ind, val = c.get("indicador"), c.get("valor")
            etiqueta, ref = c.get("referencia"), c.get("valor_referencia")
            if ind is None or val is None or ref is None or not etiqueta:
                continue
            try:
                mio, referencia = float(val), float(ref)
            except (TypeError, ValueError):
                continue
            if ind not in por_indicador:
                por_indicador[ind] = (ind, mio, [])
            por_indicador[ind][2].append((str(etiqueta), referencia))
        if por_indicador:
            return list(por_indicador.values())

    inds = context.get("indicators") or context.get("indicadores") or {}
    # El chequeo de dirección espera un MAPA indicador→blob. Otro eje puede traer una
    # LISTA bajo la misma clave (brand_intel sirve sus indicadores comparados así), y
    # entonces `.items()` lanzaba: el guard quedaba desactivado por excepción, en
    # silencio, que es el peor de los desenlaces — un guard sin su input no falla,
    # desaparece. Ante una forma que no reconoce, el chequeo se salta explícitamente.
    if not isinstance(inds, dict):
        logger.info("Chequeo de dirección omitido: 'indicadores' no es un mapa "
                    "indicador→valores (%s).", type(inds).__name__)
        inds = {}
    bench = context.get("benchmarks") or {}
    sector = bench.get("sector_averages") or {}
    peers = bench.get("peer_groups") or {}
    out: List[tuple] = []
    for name, blob in inds.items():
        bkey = _BENCH_KEY.get(name)
        if not bkey or not isinstance(blob, dict):
            continue
        raw_val = blob.get("raw")
        if raw_val is None:
            continue
        try:
            raw = float(raw_val)
        except (TypeError, ValueError):
            continue
        refs = []
        if sector.get(bkey) is not None:
            try:
                refs.append(("promedio sectorial", float(sector[bkey])))
            except (TypeError, ValueError):
                pass
        for gname, grp in peers.items():
            if not isinstance(grp, dict):
                continue
            v = grp.get(f"{bkey}_avg")
            if v is None:
                continue
            try:
                refs.append((f"promedio {gname}", float(v)))
            except (TypeError, ValueError):
                pass
        if refs:
            out.append((name, raw, refs))
    return out


# ─── Dirección en la forma BRECHA ────────────────────────────────────────────────
#
# El chequeo de arriba exige que el VALOR DE LA REFERENCIA esté citado en la oración. Media
# biblioteca de frases reales no lo cita: enuncia la BRECHA y nombra la base.
#
#     «lo que sitúa este indicador 7.31 puntos porcentuales por debajo del promedio de
#      bancos múltiples»                       (Rating Completo BPD §5 — INVERTIDA)
#
# El 85.14 nunca aparece, así que ese pasaje era invisible: el guard existía y no veía nada.
# Y es la forma que el propio contexto INDUCE, porque ``comparaciones`` sirve ``brecha_pp``
# — el modelo copia la magnitud y redacta la palabra, que es la mitad que erra.
#
# Acá la referencia se reconoce por su ETIQUETA, no por su valor. Es igual de decidible: la
# etiqueta viene del contexto y el signo de la brecha también.

# Cola DISTINTIVA de la etiqueta: "promedio de bancos múltiples" → "bancos multiples". Sin
# recortar el prefijo, «9.8 puntos por debajo del GRUPO de bancos múltiples» —la misma base
# nombrada de otra manera, frase real del informe— no casaría con la etiqueta del contexto.
_LABEL_PREFIX = re.compile(r"^(?:promedio|mediana|media|grupo|panel)\s+(?:de|del|de\s+la)\s+",
                           re.I)
# Unidades en que se enuncia una brecha. Los puntos BÁSICOS son centésimas de punto
# porcentual: «46 puntos básicos por debajo del promedio del sistema» describe una brecha de
# 0.46 pp, y compararlo crudo contra brecha_pp no casaría nunca (falso negativo silencioso).
_GAP_UNIT = r"(?:puntos?\s+porcentuales|puntos?\s+b[áa]sicos|puntos?|pp\.?|p\.\s?p\.)"
_GAP_CLAIM = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(" + _GAP_UNIT + r")"
    # Cuña corta entre la magnitud y el marcador: "…puntos porcentuales POR DEBAJO", pero
    # también "…puntos DE DIFERENCIA por debajo". Acotada para no cruzar de cláusula.
    r"[^.;:]{0,30}?\b(por\s+debajo|por\s+encima|inferior(?:es)?\s+a|superior(?:es)?\s+a|"
    r"sobre|encima\s+d|debajo\s+d)\b"
    # Ventana derecha donde debe aparecer la etiqueta de la referencia.
    r"([^.;:]{0,90})",
    re.I,
)
_GAP_MENOR = ("por debajo", "inferior", "debajo d")

# Forma VERBO-PRIMERO: «supera EN 3.70 puntos porcentuales al promedio de su grupo».
#
# El patrón de arriba exige el marcador DESPUÉS de la unidad ("3.70 puntos POR DEBAJO"), que
# es solo una de las dos maneras de decirlo en español. La otra pone el verbo adelante, y por
# ese hueco salió publicada una inversión real: §7 de un Deep Dive de banca afirmó que la
# capitalización contable «supera en 3.70 puntos porcentuales al promedio de su grupo» cuando
# el contexto servía «por debajo … en 3.70 puntos porcentuales» — contradiciendo a la §2 y a
# la §10 del MISMO documento, que lo decían bien.
#
# Dos huecos en el mismo defecto, y los dos del tipo que este repo ya conoce:
#  1. `supera` y `excede` ya estaban en `_MAYOR` —el vocabulario del detector HERMANO— y
#     nunca se copiaron acá. Un guard existe en un motor y falta en el otro, dentro del
#     mismo archivo.
#  2. El orden verbo-primero no lo contemplaba ningún patrón.
_GAP_VERBO_MAYOR = r"supera|excede|sobrepasa|aventaja"
_GAP_VERBO_MENOR = r"es\s+inferior|queda\s+por\s+debajo|se\s+ubica\s+por\s+debajo"
# La CUÑA entre el verbo y el número se captura porque ahí suele ir la etiqueta: «supera EL
# PROMEDIO en 7.91 puntos porcentuales» la pone antes, «supera en 25.78 puntos porcentuales EL
# PROMEDIO DEL SISTEMA» la pone después. La ventana de referencia son las dos juntas.
_GAP_CLAIM_VERBO = re.compile(
    r"\b(" + _GAP_VERBO_MAYOR + r"|" + _GAP_VERBO_MENOR + r")\b"
    r"([^.;:]{0,40}?)\ben\s+(\d+(?:[.,]\d+)?)\s*(" + _GAP_UNIT + r")"
    r"([^.;:]{0,90})",
    re.I,
)

# Palabras que delatan que la cola de la frase nombra una REFERENCIA. Habilitan el pareo por
# magnitud única cuando el modelo PARAFRASEA la etiqueta ("al promedio de su grupo" por
# "promedio de bancos múltiples"): sin ellas, cualquier frase con un número y una unidad
# entraría a competir por una comparación del contexto.
_REFERENCIA_GENERICA = re.compile(
    r"\b(promedio|mediana|media|grupo|pares|sistema|panel|sector)\b", re.I)


def _norm(s: str) -> str:
    """Minúsculas sin acentos ni espacio redundante — para casar etiqueta contra prosa."""
    plano = unicodedata.normalize("NFD", str(s))
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", plano).strip().lower()


def _gap_index(context: dict) -> List[tuple]:
    """``[(indicador, cola_de_etiqueta, direccion, brecha_abs_pp), ...]`` del contexto.

    Solo desde ``comparaciones`` (dirección ya resuelta): es la única fuente que trae la
    ETIQUETA legible junto al signo, y es agnóstica de eje — banca, seguros, pensiones y
    brand_intel la inyectan igual. Las comparaciones "en línea" quedan fuera: ahí la brecha
    es inmaterial por definición y exigir un lado sería el error opuesto.
    """
    out: List[tuple] = []
    comps = context.get("comparaciones")
    if not isinstance(comps, list):
        return out
    for c in comps:
        if not isinstance(c, dict):
            continue
        ind, etiqueta, direccion = c.get("indicador"), c.get("referencia"), c.get("direccion")
        brecha = c.get("brecha_pp")
        if not etiqueta or direccion not in ("por encima", "por debajo") or brecha is None:
            continue
        try:
            b = abs(float(brecha))
        except (TypeError, ValueError):
            continue
        cola = _norm(_LABEL_PREFIX.sub("", str(etiqueta)))
        if len(cola) < 4:  # etiqueta demasiado genérica para parear sin ruido
            continue
        out.append((str(ind), cola, direccion, b))
    return out


def deterministic_direction_gap_errors(context: dict, text: str) -> List[str]:
    """Claims de BRECHA cuyo sentido contradice el signo servido en ``comparaciones``.

    Complementa a ``deterministic_direction_errors``, que solo ve la forma con el valor de
    referencia citado. Acá el pareo exige TRES coincidencias en la misma cláusula —magnitud
    igual a ``|brecha_pp|`` a la precisión escrita, unidad de brecha, y la etiqueta de la
    referencia a la derecha del marcador— y ante empate ambiguo (dos comparaciones con la
    misma magnitud y etiqueta pero dirección opuesta) NO marca. Best-effort: nunca lanza.
    """
    flags: List[str] = []
    try:
        idx = _gap_index(context)
        if not idx:
            return []
        plano = re.sub(r"\s+", " ", text)
        # Las dos formas de enunciar una brecha: "N puntos POR DEBAJO de X" (marcador después
        # de la unidad) y "SUPERA en N puntos a X" (verbo antes). Se normalizan al mismo
        # cuádruple para que el resto del chequeo sea uno solo.
        hallazgos_re = [(m.group(1), m.group(2), m.group(3), m.group(4))
                        for m in _GAP_CLAIM.finditer(plano)]
        hallazgos_re += [(m.group(3), m.group(4), m.group(1),
                          f"{m.group(2)} {m.group(5)}")
                         for m in _GAP_CLAIM_VERBO.finditer(plano)]
        for cifra, unidad, marcador, cola_txt in hallazgos_re:
            escala = 0.01 if "asic" in _norm(unidad) else 1.0  # puntos básicos → pp
            derecha = _norm(cola_txt)
            dijo = ("por debajo" if any(k in _norm(marcador) for k in _GAP_MENOR)
                    else "por encima")
            candidatos = [
                (ind, direccion) for ind, cola, direccion, brecha in idx
                if cola in derecha and _cited_matches(cifra, brecha / escala)
            ]
            if not candidatos and _REFERENCIA_GENERICA.search(derecha):
                # La etiqueta viene PARAFRASEADA ("al promedio de su grupo" por "promedio de
                # bancos múltiples"), así que el pareo por texto no la encuentra. Si la
                # MAGNITUD identifica una sola comparación del contexto, el caso sigue siendo
                # decidible; si identifica varias, se calla — igual que ante el empate de
                # abajo. Fue el segundo motivo por el que la inversión de §7 pasó entera.
                por_magnitud = [
                    (ind, direccion) for ind, _cola, direccion, brecha in idx
                    if _cited_matches(cifra, brecha / escala)
                ]
                if len(por_magnitud) == 1:
                    candidatos = por_magnitud
            if not candidatos:
                continue
            # Ambigüedad real (misma magnitud y misma base, direcciones opuestas): el guard
            # no puede decidir cuál se citaba, así que se calla. Gritar en falso lo vuelve
            # ruido que se aprende a ignorar — la disciplina del detector hermano.
            if len({d for _i, d in candidatos}) > 1:
                continue
            ind, correcta = candidatos[0]
            if dijo == correcta:
                continue
            flags.append(
                f"{ind}: se afirma una brecha de {cifra} {unidad} '{dijo}' de "
                f"'{cola_txt.strip()}', pero la dirección servida es '{correcta}'")
    except Exception as e:  # noqa: BLE001 — best-effort; jamás rompe la generación
        logger.warning("Chequeo de dirección por brecha no pudo completarse: %s", e)
        return flags
    seen, out = set(), []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def deterministic_direction_errors(context: dict, text: str) -> List[str]:
    """Comparaciones del *text* cuyo SENTIDO contradice los datos del contexto.

    Solo evalúa el subconjunto DECIDIBLE, y por eso puede dar garantía: exige reconocer,
    en la misma oración, el valor de la entidad y un valor de referencia CONOCIDO del MISMO
    indicador, con el valor de la entidad ANTES del marcador direccional y la referencia
    DESPUÉS —el orden que hace de la entidad el sujeto de la comparación— y ADEMÁS que esa
    referencia sea el operando de ESE marcador y no de uno posterior.

    Cada una de esas restricciones nació de un falso positivo REAL sobre PDFs de venta:
    umbrales prospectivos ("si la solvencia cae por debajo de 18%"), cláusulas encadenadas
    por punto y coma, filas de tabla pegadas a la frase siguiente, y sobre todo el patrón
    "X supera el mínimo (10%) PERO se sitúa por debajo del promedio (16.5%)", que es prosa
    correcta. Un guard que grita en falso se vuelve ruido que se aprende a ignorar, así que
    ante la duda NO marca. Best-effort: nunca lanza.
    """
    flags: List[str] = []
    try:
        refs = _direction_refs(context)
        if not refs:
            return []
        # Se corta SOLO por puntuación de fin de cláusula, nunca por salto de línea: una
        # oración larga viene envuelta en varias líneas y partirla ahí deja el sujeto en un
        # fragmento y la referencia en el siguiente (falso NEGATIVO — así se escapaba el
        # caso real de BPD al leerlo del PDF). Las filas de tabla, que no traen punto, no
        # necesitan corte: el pareo por MISMO indicador ya impide cruzar sus números.
        for sent in re.split(r"(?<=[.;:])\s+", re.sub(r"\s+", " ", text)):
            marks = sorted(
                [(m.start(), m.end(), kind)
                 for kind, pat in (("menor", _MENOR), ("mayor", _MAYOR))
                 for m in re.finditer(pat, sent, re.I)]
            )
            for i, (start, end, kind) in enumerate(marks):
                # La referencia debe ser el operando de ESTE marcador: la ventana derecha
                # termina donde empieza el siguiente. Sin ese corte, en "supera el mínimo
                # (10%) PERO se sitúa por debajo del promedio (16.5%)" —prosa correcta— el
                # 16.5 del segundo marcador se leía como operando de "supera" y se marcaba
                # un error inexistente. La ventana izquierda sí queda abierta: el sujeto se
                # enuncia una vez al principio y los marcadores siguientes lo eliden.
                stop = marks[i + 1][0] if i + 1 < len(marks) else len(sent)
                left, right = sent[:start], sent[end:stop]
                cited_l = _CITED.findall(left)
                cited_r = _CITED.findall(right)
                if not cited_l or not cited_r:
                    continue
                for name, raw, candidates in refs:
                    if not any(_cited_matches(c, raw) for c in cited_l):
                        continue
                    for label, ref in candidates:
                        # Si entidad y referencia son indistinguibles a la precisión
                        # citada, la dirección no es afirmable ni refutable: se salta.
                        if any(_cited_matches(c, raw) and _cited_matches(c, ref)
                               for c in cited_r):
                            continue
                        if not any(_cited_matches(c, ref) for c in cited_r):
                            continue
                        if (raw < ref) if kind == "menor" else (raw > ref):
                            continue
                        sentido = "por debajo" if kind == "menor" else "por encima"
                        flags.append(
                            f"{name}: se afirma que {raw} está {sentido} del {label} "
                            f"({ref}), pero es al revés")
    except Exception as e:  # noqa: BLE001 — best-effort; jamás rompe la generación
        logger.warning("Chequeo de dirección no pudo completarse: %s", e)
    # La forma BRECHA se verifica desde el MISMO punto de entrada, no como chequeo aparte:
    # un guard que hay que acordarse de llamar es el que termina faltando en la otra ruta —
    # el modo de falla que ya costó cinco instancias en este repo.
    flags += deterministic_direction_gap_errors(context, text)
    seen, out = set(), []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def verify_figures(client, model: str, context_str: str, text: str,
                   module: Optional[str] = None,
                   template: Optional[str] = None) -> List[str]:
    """Return the figures in *text* not supported by *context_str* (``[]`` if all OK
    or if the check can't run). Best-effort: never raises.

    Contabiliza su propia llamada. Antes solo sumaba al techo diario y el registro de
    gasto la anotaba desde el caller SIN dólares: el juez aparecía con costo cero justo
    cuando es la mitad de las llamadas de un informe —once de veinte en el primer informe
    medido— y por tanto el total publicado era la mitad del real. Se contabiliza acá, que
    es donde está la respuesta, y por la MISMA vía que los otros catorce sitios."""
    if not text.strip():
        return []
    from shared.llm.budget import budget_allows
    from shared.observability.llm_ledger import PURPOSE_GUARD, account
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
        account(resp, model=model, purpose=PURPOSE_GUARD,
                module=module, template=template)
        return _parse_unsupported(resp.content[0].text)
    except Exception as e:  # noqa: BLE001 — best-effort; the guardrail must not break generation
        logger.warning("Guardrail numérico no pudo verificar (se sirve sin verificar): %s", e)
        return []
