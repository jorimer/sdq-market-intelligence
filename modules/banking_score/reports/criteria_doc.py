"""Documento de Criterios — la metodología del SDQ Rating, GENERADA del motor.

Por qué determinista y no narrado por IA: **la metodología no cambia por corrida**. Es
configuración, no análisis. Generarla desde las mismas constantes que el motor usa para
calificar (``weights``, ``rating_scale``, ``INDICATOR_META``) tiene una propiedad que
ningún texto redactado a mano o por un modelo puede dar: **no puede desviarse del motor**.
Si mañana se recalibra un peso, se agrega un indicador o se mueve un corte de la escala,
el documento se actualiza solo; una versión escrita miente desde ese momento y nadie se
entera. Es la misma doctrina que "la procedencia se GENERA del registro, no se escribe en
prosa".

Además, era el peor lugar posible para una alucinación: es el documento que dice CÓMO
calificamos. Antes se pedía a la IA narrar la plantilla ``banking_risk`` (por-banco) con un
``scoring_result`` vacío; el estándar epistémico hacía lo correcto —se negaba a fabricar—
pero el PDF de cliente terminaba siendo ese rechazo, con nombres de campos internos
(``umbral_fmt``, ``delta_overall``) a la vista.

Devuelve ``{section_key: markdown}``, el mismo contrato que ``narratives``: el renderer ya
interpreta títulos, tablas GFM y viñetas, así que no hace falta tocarlo.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from modules.banking_score.scoring.indicator_detail import INDICATOR_META
from modules.banking_score.scoring.rating_scale import RATING_SCALE
from modules.banking_score.scoring.weights import (
    CALIDAD_INDICATORS,
    DIVERSIFICACION_INDICATORS,
    EFICIENCIA_INDICATORS,
    LIQUIDEZ_INDICATORS,
    SOLIDEZ_INDICATORS,
    SUB_COMPONENT_WEIGHTS,
    WEIGHT_PROFILES,
)

# Sub-componente → sus indicadores, leído de las MISMAS listas que consume el motor: si se
# agrega un indicador al scoring, aparece en el documento sin tocar este archivo.
_SUB_INDICATOR_MAP: Dict[str, List[str]] = {
    "solidez": SOLIDEZ_INDICATORS,
    "calidad": CALIDAD_INDICATORS,
    "eficiencia": EFICIENCIA_INDICATORS,
    "liquidez": LIQUIDEZ_INDICATORS,
    "diversificacion": DIVERSIFICACION_INDICATORS,
}

logger = logging.getLogger("sdq.banking.criteria_doc")

SECTION_TITLES: Dict[str, str] = {
    "crit_marco": "Marco metodológico",
    "crit_componentes": "Sub-componentes y ponderación",
    "crit_indicadores": "Indicadores por sub-componente",
    "crit_escala": "Escala de calificación",
    "crit_fuentes": "Fuentes de dato y cadencia",
    "crit_validacion": "Validación empírica",
    "crit_limitaciones": "Alcance y limitaciones",
}

_SUB_LABELS: Dict[str, str] = {
    "solidez": "Solidez Financiera",
    "calidad": "Calidad de Activos",
    "eficiencia": "Eficiencia y Rentabilidad",
    "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
}

_ENTITY_TYPE_LABELS: Dict[str, str] = {
    "banca_multiple": "Banca Múltiple",
    "aap": "Asociaciones de Ahorros y Préstamos",
    "banco_ahorro_credito": "Bancos de Ahorro y Crédito",
    "corporacion_credito": "Corporaciones de Crédito",
    "cambiaria": "Intermediación Cambiaria",
    "fiduciaria": "Fiduciarias",
}

# Agregados DERIVADOS que ponderan en el sub-componente pero no tienen fuente de dato
# propia (se calculan de los indicadores listados), por eso no llevan ficha en el registro.
_COMPOSITE_NOTES: Dict[str, str] = {
    "calidad": (
        "Además de los anteriores, el sub-componente incorpora un **compuesto de calidad**: "
        "el promedio de las componentes disponibles de esta dimensión. No es un dato nuevo "
        "—se deriva de los indicadores de la tabla— y su función es estabilizar la "
        "dimensión cuando alguno de sus componentes no está disponible en el período."
    ),
}

_DIRECTION_LABELS: Dict[str, str] = {
    "higher": "Mayor es mejor",
    "lower": "Menor es mejor",
    "target": "Óptimo intermedio",
    "bell": "Óptimo intermedio",
}


def _pct(x: float) -> str:
    """40% en vez de 40.0% — los pesos son enteros salvo perfiles recalibrados."""
    v = x * 100
    return f"{v:.0f}%" if abs(v - round(v)) < 1e-9 else f"{v:.1f}%"


def _marco() -> str:
    return (
        "El **SDQ Rating** es una medida de **fortaleza financiera standalone** de entidades "
        "supervisadas por la Superintendencia de Bancos de la República Dominicana, "
        "construida exclusivamente sobre **dato público supervisado**.\n\n"
        "> No es un rating de crédito, no mide probabilidad de incumplimiento y no incorpora "
        "soporte soberano ni techo país. No es comparable con las escalas de las "
        "calificadoras internacionales.\n\n"
        "El puntaje global es un **promedio ponderado de cinco sub-componentes**, cada uno "
        "compuesto por indicadores calculados sobre los estados financieros y los reportes "
        "regulatorios de la entidad. Cada indicador se normaliza a una escala 0–100 mediante "
        "una función de puntuación propia de SDQ que fija los umbrales de suficiencia, y el "
        "puntaje global se mapea a un escalón de la escala SDQ.\n\n"
        "La metodología es **determinista y reproducible**: dos corridas sobre el mismo "
        "período y los mismos insumos producen el mismo puntaje. Este documento se genera "
        "**desde la configuración del propio motor**, de modo que refleja siempre la "
        "calibración vigente y no una descripción que pueda quedar desactualizada."
    )


def _componentes() -> str:
    rows = ["| Sub-componente | Peso base | Qué evalúa |",
            "|---|---|---|"]
    que = {
        "solidez": "Suficiencia y calidad del capital, apalancamiento y cobertura de pérdidas",
        "calidad": "Calidad de la cartera, concentración de deudores y sectorial, castigos",
        "eficiencia": "Rentabilidad sobre activos y capital, margen y eficiencia operativa",
        "liquidez": "Colchón de corto plazo y estructura de fondeo",
        "diversificacion": "Concentración de las fuentes de ingreso",
    }
    for key, peso in SUB_COMPONENT_WEIGHTS.items():
        rows.append(f"| {_SUB_LABELS.get(key, key)} | {_pct(peso)} | {que.get(key, '')} |")

    out = [
        "El puntaje global es el promedio ponderado de los cinco sub-componentes. Los pesos "
        "base corresponden a la Banca Múltiple:",
        "",
        "\n".join(rows),
        "",
        "### Recalibración por tipo de entidad",
        "",
        "El marco de cinco sub-componentes es universal, pero su **peso relativo se "
        "recalibra según el tipo de entidad supervisada**, porque el mismo indicador no "
        "informa lo mismo en modelos de negocio distintos: una Asociación de Ahorros y "
        "Préstamos es intensiva en hipotecas (la calidad del activo pesa más), mientras que "
        "en una fiduciaria la concentración de ingresos es estructural y no discrimina. "
        "Todos los perfiles suman 100%.",
        "",
    ]

    subs = list(SUB_COMPONENT_WEIGHTS.keys())
    header = "| Tipo de entidad | " + " | ".join(_SUB_LABELS[s] for s in subs) + " |"
    out.append(header)
    out.append("|---" * (len(subs) + 1) + "|")
    for etype, profile in WEIGHT_PROFILES.items():
        label = _ENTITY_TYPE_LABELS.get(etype, etype)
        out.append("| " + label + " | "
                   + " | ".join(_pct(profile.get(s, 0.0)) for s in subs) + " |")
    return "\n".join(out)


def _indicadores() -> str:
    # El conteo debe ser el de los indicadores que el documento REALMENTE lista, no
    # `len(INDICATOR_META)`: las listas del motor incluyen claves compuestas sin ficha en el
    # registro (p. ej. `composite_calidad`), así que ese total mentiría por exceso.
    bloques: List[str] = []
    n_listados = 0
    for sub, keys in _SUB_INDICATOR_MAP.items():
        presentes = [k for k in keys if k in INDICATOR_META]
        if not presentes:
            continue
        n_listados += len(presentes)
        bloques += ["", f"### {_SUB_LABELS.get(sub, sub)}", "",
                    "| Indicador | Definición | Unidad | Lectura |", "|---|---|---|---|"]
        for k in presentes:
            m = INDICATOR_META[k]
            bloques.append(
                f"| {m.get('label', k)} | {m.get('que', '')} | {m.get('unit', '')} "
                f"| {_DIRECTION_LABELS.get(m.get('direction', ''), '—')} |")
        # Los COMPUESTOS derivados no tienen fuente propia (se calculan de los anteriores),
        # así que no llevan ficha en el registro — pero SÍ ponderan en el sub-componente.
        # Callarlos haría que el documento describa menos componentes de las que se puntúan.
        derivados = [k for k in keys if k not in INDICATOR_META]
        if derivados:
            bloques += ["", _COMPOSITE_NOTES.get(
                sub, "Este sub-componente incluye además un agregado derivado de los "
                     "indicadores anteriores, sin fuente de dato propia.")]
    intro = (
        f"El motor evalúa **{n_listados} indicadores** agrupados en los cinco "
        "sub-componentes. Cada uno se normaliza a 0–100; la columna «Lectura» indica el "
        "sentido en que el valor crudo mejora el puntaje."
    )
    return "\n".join([intro] + bloques)


def _escala() -> str:
    rows = ["| Escalón | Puntaje | Lectura |", "|---|---|---|"]
    lectura = {
        "SDQ-AAA": "Fortaleza financiera excepcional",
        "SDQ-AA+": "Fortaleza muy alta",
        "SDQ-AA": "Fortaleza muy alta",
        "SDQ-AA-": "Fortaleza muy alta",
        "SDQ-A+": "Fortaleza alta",
        "SDQ-A": "Fortaleza alta",
        "SDQ-A-": "Fortaleza alta",
        "SDQ-BBB+": "Fortaleza adecuada",
        "SDQ-BBB": "Fortaleza adecuada",
        "SDQ-D": "Fortaleza débil o comprometida",
    }
    for tier, lo, hi in RATING_SCALE:
        rows.append(f"| **{tier}** | {lo:.0f} – {hi:.2f} | {lectura.get(tier, '')} |")
    return (
        f"El puntaje global (0–100) se mapea a **{len(RATING_SCALE)} escalones**. Los cortes "
        "son fijos: un mismo puntaje produce siempre el mismo escalón, sin juicio "
        "discrecional ni comité de override.\n\n"
        + "\n".join(rows)
    )


def _fuentes() -> str:
    return (
        "| Fuente | Qué aporta | Cadencia |\n"
        "|---|---|---|\n"
        "| Superintendencia de Bancos (API de estadísticas) | Balance, estado de resultados, "
        "indicadores regulatorios y de solvencia por entidad | Trimestral |\n"
        "| SIMBAD (portal público de la SB) | Respaldo cuando la API no expone un período | "
        "Trimestral |\n"
        "| Cronología SB (series históricas) | Balance y resultados mensuales por entidad "
        "desde 1947 — base del backtest histórico | Mensual (histórico) |\n"
        "| Banco Central de la República Dominicana | Telón macroeconómico del entorno "
        "operativo | Mensual / trimestral |\n\n"
        "El período de referencia es el **cierre trimestral** (`period_end`). La calificación "
        "se recomputa cuando entra dato nuevo del período; el histórico de cambios de escalón "
        "queda registrado como acciones de rating auditables.\n\n"
        "**Todo insumo es público y supervisado.** No se emplea información privada de la "
        "entidad, información no publicada ni estimaciones propias en reemplazo de un dato "
        "faltante: cuando un indicador no está disponible, se declara ausente y no se imputa."
    )


def _validacion(db=None) -> str:
    """Validación empírica. Lee el backtest VIVO si hay sesión; si no, describe el método
    sin inventar cifras — nunca se fabrica un Gini."""
    from modules.banking_score.sib_historical_backtest import FAILED_COHORT

    partes: List[str] = [
        "La capacidad discriminante del puntaje se evalúa por dos vías independientes.",
        "",
        "### 1. Backtest sobre el panel supervisado",
        "",
        "Se mide si un puntaje más bajo anticipa **deterioro financiero** en un horizonte "
        "posterior, con el coeficiente de **Gini** y su **intervalo de confianza por "
        "bootstrap**, más la tasa de deterioro por escalón (que debería crecer al bajar en "
        "la escala).",
    ]

    if db is not None:
        try:
            from modules.banking_score.validation.report import build_backtest_report
            rep = build_backtest_report(db)
            if rep.get("ok") and rep.get("gini") is not None:
                ci = rep.get("gini_ci") or [None, None]
                ci_txt = (f" (IC 95% bootstrap: {ci[0]:.4f} – {ci[1]:.4f})"
                          if ci[0] is not None else "")
                partes += [
                    "",
                    f"**Resultado vigente:** Gini = **{rep['gini']:.4f}**{ci_txt}, sobre "
                    f"{rep['n_observations']} observaciones y {rep['n_events']} eventos "
                    f"(tasa de eventos {rep['event_rate']:.1%}), con horizonte de "
                    f"{rep['horizon_quarters']} trimestres. Monotonía de la curva de "
                    f"deterioro por escalón: {'sí' if rep.get('monotonic') else 'no'}.",
                ]
                if rep.get("caveats"):
                    partes += ["", "Advertencias que acompañan a esta medición:", ""]
                    partes += [f"- {c}" for c in rep["caveats"]]
            elif rep.get("message"):
                partes += ["", f"*{rep['message']}*"]
        except Exception as e:  # noqa: BLE001 — el documento nunca debe romperse por esto
            logger.warning("Backtest no disponible para el documento de criterios: %s", e)

    nombres = ", ".join(sorted({c["nombre"] for c in FAILED_COHORT}))
    partes += [
        "",
        "### 2. Backtest contra quiebras reales",
        "",
        "El motor de **Alerta Temprana** —que comparte los indicadores de crédito, capital y "
        "liquidez del puntaje— se corre mes a mes sobre el histórico de las entidades que "
        f"efectivamente salieron del sistema: {nombres}. Se mide con cuántos meses de "
        "anticipación se habría encendido un conglomerado de señales de severidad alta antes "
        "de la salida.",
        "",
        "Límite declarado de esta prueba: el histórico contable **no contiene morosidad antes "
        "de diciembre de 1993** ni capital regulatorio Basilea (anterior a su adopción), de "
        "modo que las entidades del episodio de inicios de los noventa **no son evaluables** "
        "por las reglas de crédito. El resultado se reporta sobre la cohorte efectivamente "
        "evaluable, no sobre el total del roster.",
    ]
    return "\n".join(partes)


def _limitaciones() -> str:
    return (
        "- **No es un rating de crédito.** Mide fortaleza financiera standalone sobre dato "
        "público; no estima probabilidad de incumplimiento ni pérdida esperada.\n"
        "- **No incorpora soporte externo en el puntaje.** El soporte accionario o estatal y "
        "el techo soberano se presentan, cuando aplican, como capa de contexto separada que "
        "no altera el puntaje standalone.\n"
        "- **Depende de la calidad del dato publicado.** Un error o un cambio de criterio "
        "contable en la fuente se propaga al puntaje. El motor rechaza valores imposibles "
        "(por ejemplo, un ratio de capital negativo) y cae a un cálculo estructural, pero no "
        "puede detectar contabilidad deliberadamente falseada: es el punto ciego declarado "
        "ante el fraude, y la razón por la que el backtest histórico muestra que las señales "
        "de ratio llegan tarde en ese escenario.\n"
        "- **Sin vintages de publicación.** La línea de tiempo usa el cierre del período, no "
        "la fecha en que el dato se publicó originalmente.\n"
        "- **La calificación no es una recomendación** de compra, venta o mantenimiento de "
        "valores, ni sustituye la debida diligencia del usuario."
    )


def build_criteria_document(db=None) -> Dict[str, str]:
    """Documento de criterios completo como ``{section_key: markdown}``.

    ``db`` es opcional: con sesión se incorpora el resultado VIVO del backtest; sin ella se
    describe el método sin cifras. Nunca se fabrica un número.
    """
    return {
        "crit_marco": _marco(),
        "crit_componentes": _componentes(),
        "crit_indicadores": _indicadores(),
        "crit_escala": _escala(),
        "crit_fuentes": _fuentes(),
        "crit_validacion": _validacion(db),
        "crit_limitaciones": _limitaciones(),
    }
