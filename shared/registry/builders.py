"""Constructores reutilizables de ``VariableSignal`` para cada patrón de procedencia.

Un producto implementa ``variable_signals()`` llamando a uno de estos helpers con lo
que ya calcula —su mapa ``sources`` (paneles) o su ``breakdown`` de puntaje
(índices)—, sin duplicar la lógica de normalización. Los PESOS por-variable salen de
la doctrina versionada (`shared/doctrine`), que es ``shared`` y por tanto legible
desde aquí sin violar el aislamiento entre módulos.

El motor de índice (`shared/indices`) define: cada dimensión = media simple de sus
variables; el total = suma ponderada de dimensiones. Por tanto el peso efectivo de
una variable = ``peso_dimensión / n_variables_de_la_dimensión``. Eso es lo que se
declara aquí (honesto y coherente con el motor), no un peso inventado.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from shared.registry.signals import GAP, REAL, RUBRIC, VariableSignal, normalize_state


def axis_variable_weights(axis: str) -> Dict[str, Tuple[str, float]]:
    """``{variable: (dimensión, peso_efectivo)}`` derivado de la doctrina del *axis*.

    Peso efectivo = peso de la dimensión / nº de variables declaradas en ella. Si la
    doctrina no existe o no declara dimensiones, devuelve ``{}`` (el helper de señales
    usa peso 0.0 → cobertura por promedio simple)."""
    from shared.doctrine import load_doctrine_raw

    try:
        doc = load_doctrine_raw(axis)
    except (FileNotFoundError, ValueError):
        return {}
    dim_weights: Dict[str, float] = doc.get("dimension_weights", {}) or {}
    dim_vars: Dict[str, List[str]] = doc.get("dimension_variables", {}) or {}
    out: Dict[str, Tuple[str, float]] = {}
    for dim, vars_ in dim_vars.items():
        w = float(dim_weights.get(dim, 0.0))
        n = len([v for v in vars_]) or 1
        for v in vars_:
            out[v] = (dim, round(w / n, 4))
    return out


def pattern_a_signals(
    *,
    axis: str,
    dataset: Dict[str, Dict[str, float]],
    sources: Dict[str, Dict[str, str]],
    source_label: str,
    cadence: str,
    labels: Optional[Dict[str, str]] = None,
    variables: Optional[List[str]] = None,
) -> List[VariableSignal]:
    """Construye señales desde un mapa ``sources`` de PANEL ("live"/"rubric" por sujeto).

    Agrega la procedencia de cada variable a través de los sujetos del panel: una
    variable es REAL si tiene dato real en ≥1 sujeto (con ``real_fraction`` = fracción
    de sujetos cubiertos, que declara la parcialidad); RUBRIC si es rúbrica declarada
    en todos; GAP si no aparece. Los pesos vienen de la doctrina del *axis*.
    """
    labels = labels or {}
    weights = axis_variable_weights(axis)
    # Universo de variables: el declarado explícito, o la unión de doctrina + lo visto.
    if variables is None:
        seen = {v for smap in sources.values() for v in smap}
        variables = sorted(set(weights) | seen)

    slugs = list(sources.keys())
    n = len(slugs) or 1
    out: List[VariableSignal] = []
    for var in variables:
        n_real = n_rubric = n_absent = 0
        sample_value: Optional[float] = None
        for slug in slugs:
            st = normalize_state(sources.get(slug, {}).get(var))
            if st == REAL:
                n_real += 1
                if sample_value is None:
                    v = dataset.get(slug, {}).get(var)
                    sample_value = float(v) if isinstance(v, (int, float)) else None
            elif st == RUBRIC:
                n_rubric += 1
            else:
                n_absent += 1

        if n_real > 0:
            state = REAL
        elif n_rubric > 0:
            state = RUBRIC
        else:
            state = GAP
        real_fraction = round(n_real / n, 4)

        note = ""
        if state == REAL and real_fraction < 0.999:
            note = f"cobertura parcial: dato real en {n_real}/{n} sujetos"
        elif state == GAP:
            note = "brecha: sin dato ni rúbrica para esta variable en el panel"

        dim, weight = weights.get(var, ("", 0.0))
        out.append(VariableSignal(
            key=var, label=labels.get(var, var), state=state, dimension=dim,
            weight=weight, source=source_label if state == REAL else "",
            cadence=cadence, value=sample_value, real_fraction=real_fraction, note=note,
        ))
    return out


def pattern_b_signals(
    *,
    breakdown: Any,
    source_label: str,
    cadence: str,
    labels: Optional[Dict[str, str]] = None,
) -> List[VariableSignal]:
    """Construye señales desde un ``breakdown`` de ÍNDICE de sujeto único.

    Acepta el breakdown como lista de dicts o dict de dicts; cada entrada debe traer
    al menos ``provenance`` ("real"/"brecha") y opcionalmente ``weight``/``value``/
    ``label``/``dimension``/``present``. Sujeto único → ``real_fraction`` es 1.0 (real)
    o 0.0 (brecha).
    """
    labels = labels or {}
    items = _iter_breakdown(breakdown)
    out: List[VariableSignal] = []
    for key, d in items:
        prov = d.get("provenance")
        present = d.get("present")
        if prov is None and present is not None:
            prov = "real" if present else "brecha"
        state = normalize_state(prov)
        weight = float(d.get("weight", 0.0) or 0.0)
        val = d.get("value")
        note = "" if state == REAL else "brecha declarada en el índice"
        out.append(VariableSignal(
            key=key, label=labels.get(key, d.get("label", key)), state=state,
            dimension=str(d.get("dimension", "")), weight=weight,
            source=source_label if state == REAL else "", cadence=cadence,
            value=float(val) if isinstance(val, (int, float)) else None,
            real_fraction=1.0 if state == REAL else 0.0, note=note,
        ))
    return out


def nested_breakdown_signals(
    *,
    breakdown: Dict[str, Any],
    axis: str,
    source_label: str,
    cadence: str,
    labels: Optional[Dict[str, str]] = None,
) -> List[VariableSignal]:
    """Construye señales desde un breakdown ANIDADO ``{dim: {weight, variables:
    {var: {source, value, ...}}}}`` de sujeto único (p.ej. el ``iai_breakdown``
    persistido). Cada variable lleva su ``source`` ("live"/"rubric"); sujeto único →
    ``real_fraction`` 1.0 (real) o 0.0. Los pesos salen de la doctrina del *axis*
    (fallback al peso de dimensión repartido si la variable no está en doctrina).
    """
    labels = labels or {}
    weights = axis_variable_weights(axis)
    out: List[VariableSignal] = []
    for dim, d in (breakdown or {}).items():
        vars_ = ((d or {}).get("variables") or {})
        dim_weight = float((d or {}).get("weight", 0.0) or 0.0)
        n = len(vars_) or 1
        for var, v in vars_.items():
            v = v or {}
            state = normalize_state(v.get("source"))
            _, doc_w = weights.get(var, ("", 0.0))
            weight = doc_w if doc_w > 0 else round(dim_weight / n, 4)
            val = v.get("value")
            note = "" if state != GAP else "brecha declarada"
            out.append(VariableSignal(
                key=var, label=labels.get(var, var), state=state, dimension=str(dim),
                weight=weight, source=source_label if state == REAL else "",
                cadence=cadence,
                value=float(val) if isinstance(val, (int, float)) else None,
                real_fraction=1.0 if state == REAL else 0.0, note=note,
            ))
    return out


def _iter_breakdown(breakdown: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """Normaliza un breakdown (lista o dict) a ``[(key, dict), …]``."""
    if isinstance(breakdown, dict):
        return [(str(k), v) for k, v in breakdown.items() if isinstance(v, dict)]
    if isinstance(breakdown, (list, tuple)):
        out: List[Tuple[str, Dict[str, Any]]] = []
        for i, v in enumerate(breakdown):
            if isinstance(v, dict):
                key = str(v.get("key") or v.get("dimension") or v.get("name") or i)
                out.append((key, v))
        return out
    return []
