"""Esquema normalizado de la señal por-variable + helpers de construcción.

El vocabulario del sistema tiene HOY dos dialectos (ver docstring del paquete):
mapas ``sources`` con "live"/"rubric" (paneles) y ``breakdown.provenance`` con
"real"/"brecha" (índices). Aquí se unifican en tres estados canónicos —los mismos
tres que el REPORT_STANDARD y el §4 del spec del motor exigen declarar:

    REAL   — dato real con lineage (fuente + fecha).           ("live" | "real")
    RUBRIC — rúbrica declarada (juicio de casa, no dato).      ("rubric")
    GAP    — brecha declarada (sin dato ni rúbrica hoy).       ("brecha" | ausente)

``real_fraction`` guarda la verdad cuantitativa cuando una variable de PANEL es real
para unos sujetos y no para otros (p.ej. rentabilidad ENAE cubre ~9/17 sectores): el
estado sigue siendo REAL —está anclado a dato— pero la fracción lo declara sin
maquillar. El gate de honestidad de la Fase 4 pondera con esa fracción, no solo con
la categoría.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# ─── Estados canónicos ────────────────────────────────────────────────
REAL = "real"       # dato real con lineage
RUBRIC = "rubric"   # rúbrica declarada
GAP = "gap"         # brecha declarada

# ─── Alcance de la medición (ver ``VariableSignal.scope``) ────────────
PER_SUBJECT = "per_subject"   # se mide por sujeto → diferencia entre ellos
NATIONAL = "national"         # dato real de alcance país → igual para todos los sujetos

# ─── Qué MIDE la cobertura de un eje (ver ``AxisRegistry.coverage_kind``) ────────────
#
# Hasta que entró el eje de evaluación de leyes, todos los ejes respondían la misma
# pregunta: «¿qué fracción del PESO de mi índice está anclada a dato real?». El eje de
# leyes responde otra: «¿cuántos de los indicadores que la LEY se fijó estamos midiendo?».
# Las dos son fracciones entre 0 y 1 y ninguna es más honesta que la otra — pero
# promediarlas produce un número que no significa nada, y ese número alimentaba el
# resumen del registro.
#
# Es la doctrina de «solo se ordena lo comparable» aplicada a los ejes en vez de a un
# panel de pares: el promedio se computa sobre los comparables, y los de otra semántica
# NO se ocultan (eso los haría desaparecer sin aviso) — van aparte y marcados.
COVERAGE_INDEX = "fraccion_real_del_indice"
COVERAGE_INSTRUMENT = "indicadores_medidos_del_instrumento"
COVERAGE_KINDS = (COVERAGE_INDEX, COVERAGE_INSTRUMENT)

_STATE_ALIASES = {
    "live": REAL, "real": REAL,
    "rubric": RUBRIC, "rúbrica": RUBRIC,
    "brecha": GAP, "gap": GAP, "": GAP, "absent": GAP, "missing": GAP,
}


def normalize_state(raw: Optional[str]) -> str:
    """Mapea cualquiera de los dialectos ("live"/"rubric"/"brecha"/…) al canónico.

    Desconocido o ``None`` → ``GAP`` (conservador: si no sabemos que hay dato, se
    declara brecha; nunca se asume real por omisión — esa es la regla dura del §4)."""
    if raw is None:
        return GAP
    return _STATE_ALIASES.get(str(raw).strip().lower(), GAP)


@dataclass(frozen=True)
class VariableSignal:
    """La señal atómica del registro: una variable de un eje y su procedencia real.

    ``weight`` es el peso de la variable dentro del índice del eje [0,1] (de la
    doctrina versionada); ``0.0`` si el eje no expone pesos por-variable. ``value``
    es indicativo (para un panel multi-sujeto suele ser ``None`` — el valor es
    per-sujeto, no del eje). Lo que importa para el motor de research es
    ``state`` + ``source`` + ``cadence`` + ``real_fraction``.
    """

    key: str                         # clave de la variable, p.ej. "regulatory_quality"
    label: str                       # etiqueta legible
    state: str                       # REAL | RUBRIC | GAP
    dimension: str = ""              # dimensión/grupo del índice al que pertenece
    weight: float = 0.0              # peso en el índice [0,1] (doctrina)
    source: str = ""                 # lineage: fuente que respalda el dato real
    cadence: str = "unknown"         # monthly | quarterly | annual | unknown
    value: Optional[float] = None    # valor indicativo (None en paneles multi-sujeto)
    real_fraction: float = field(default=1.0)  # fracción de sujetos con dato real [0,1]
    note: str = ""                   # nota de trazabilidad (parcialidad, caveat)
    # ALCANCE de la medición — distingue dos cosas que "dato real" confunde:
    #   PER_SUBJECT — se mide por sujeto (sector, país, entidad): DIFERENCIA entre ellos
    #                 y por tanto mueve el ranking.
    #   NATIONAL    — dato real, pero de alcance país: idéntico para todos los sujetos del
    #                 panel. Sostiene el nivel del índice; NO mueve el ranking.
    # Sin este eje, un cliente lee "dato real" y entiende "esto distingue a mi sector de
    # los demás", que puede ser falso. Default PER_SUBJECT (el caso común); un producto
    # con variables nacionales lo declara explícitamente.
    scope: str = "per_subject"


@dataclass(frozen=True)
class AxisRegistry:
    """Todo lo que un eje/producto mide, normalizado. Unidad de agregación del registro."""

    sector_key: str
    display_name: str
    source: str                      # fuente autoritativa del eje (catálogo)
    implemented: bool
    degraded: bool = False           # cayó al fallback a-nivel-producto (sin variable_signals)
    period: Optional[str] = None
    signals: Tuple[VariableSignal, ...] = ()
    note: str = ""
    #: Qué responde ``coverage_real`` en ESTE eje. Por defecto la pregunta de siempre, así
    #: que ningún eje existente cambia de significado al agregarse el campo.
    coverage_kind: str = COVERAGE_INDEX

    # ── Métricas derivadas (no se guardan crudas: se calculan de las señales) ──
    @property
    def coverage_real(self) -> float:
        """Fracción del PESO del índice anclada a dato real (ponderada por
        ``real_fraction``). Si el eje no expone pesos, cae a promedio simple por
        variable. Es la métrica que alimenta el gate de honestidad (§3.4/§4)."""
        if not self.signals:
            return 0.0
        wsum = sum(s.weight for s in self.signals)
        if wsum > 0:
            got = sum(s.weight * _real_credit(s) for s in self.signals)
            return round(got / wsum, 4)
        # sin pesos: promedio simple del crédito real por variable
        return round(sum(_real_credit(s) for s in self.signals) / len(self.signals), 4)

    @property
    def state_counts(self) -> Dict[str, int]:
        counts = {REAL: 0, RUBRIC: 0, GAP: 0}
        for s in self.signals:
            counts[s.state] = counts.get(s.state, 0) + 1
        return counts


def _real_credit(s: VariableSignal) -> float:
    """Crédito de "realidad" de una señal para la cobertura ponderada: una variable
    REAL aporta su ``real_fraction`` (parcial cuenta parcial); RUBRIC/GAP aportan 0
    —una rúbrica no es dato, aunque sea un juicio declarado y honesto."""
    return s.real_fraction if s.state == REAL else 0.0


@dataclass(frozen=True)
class DataRegistry:
    """El registro completo: todos los ejes + un resumen de portafolio."""

    generated_at: str
    axes: Tuple[AxisRegistry, ...] = ()

    @property
    def summary(self) -> Dict:
        implemented = [a for a in self.axes if a.implemented]
        total_signals = sum(len(a.signals) for a in self.axes)
        by_state = {REAL: 0, RUBRIC: 0, GAP: 0}
        for a in self.axes:
            for k, v in a.state_counts.items():
                by_state[k] = by_state.get(k, 0) + v
        # El promedio se computa SOLO sobre los ejes cuya cobertura mide lo mismo. Mezclar
        # «fracción real del índice» con «indicadores medidos de una ley» daba un número sin
        # significado: al entrar el eje de leyes con 5 de 90, el promedio de la plataforma
        # caía sin que ningún índice hubiera perdido un solo dato real.
        con_senales = [a for a in implemented if a.signals]
        comparables = [a for a in con_senales if a.coverage_kind == COVERAGE_INDEX]
        cov = [a.coverage_real for a in comparables]
        # Los de otra semántica van APARTE y marcados, nunca omitidos: omitirlos los haría
        # desaparecer del resumen sin aviso, que es peor que promediarlos mal.
        otros = [
            {"sector_key": a.sector_key, "coverage_kind": a.coverage_kind,
             "coverage": a.coverage_real}
            for a in con_senales if a.coverage_kind != COVERAGE_INDEX
        ]
        return {
            "axes_total": len(self.axes),
            "axes_implemented": len(implemented),
            "axes_degraded": len([a for a in self.axes if a.degraded]),
            "variables_total": total_signals,
            "by_state": by_state,
            "coverage_real_mean": round(sum(cov) / len(cov), 4) if cov else 0.0,
            # Sin este denominador, «cobertura media 62%» no dice sobre cuántos ejes.
            "coverage_real_mean_sobre_ejes": len(cov),
            "coverage_no_comparable": otros,
        }
