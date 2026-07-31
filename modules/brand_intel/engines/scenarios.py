"""Scenario and sensitivity engine (S4) — what could break the forecast.

Scenarios here **do not move the forecast's numbers**. With a handful of waves there is no
panel to estimate how a point of inflation translates into a point of preference, so a
scenario-adjusted point estimate would be fabricated precision. What a scenario does is
state the assumptions under which the frozen forecast should be read, and whether its band
should be read symmetrically or with a bias.

That distinction is the whole design: the band comes from sampling arithmetic and is
defensible; the tilt comes from the macro axis and is declared as judgement.

The sensitivity pass answers the harder question — what would have to be true for the
forecast to be wrong:

* **Rule dispersion.** The three naive rules are run on the same history. When they agree,
  the series is well characterised and the forecast is robust to the choice. When they
  disagree widely, the forecast rests on the rule rather than on the data, and that is
  reported as fragility instead of being hidden behind the winner.
* **Base sensitivity.** The band is a function of the next wave's sample size. If fieldwork
  lands a smaller base than expected, the band widens and results that would have been
  news no longer are.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from modules.brand_intel.engines.attribution import (
    DEMANDING,
    FAVOURABLE,
    NEUTRAL,
    UNKNOWN,
    EnvironmentReading,
)
from modules.brand_intel.engines.forecast import RULES, backtest_rules
from modules.brand_intel.engines.significance import confidence_halfwidth

CONTINUITY = "continuidad"
DETERIORATION = "deterioro"
RELIEF = "alivio"

SYMMETRIC = "simetrica"
DOWNSIDE = "sesgo_a_la_baja"
UPSIDE = "sesgo_al_alza"


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    assumptions: List[str]
    band_reading: str
    probability_note: str
    text: str


def build_scenarios(env: EnvironmentReading) -> List[Scenario]:
    """Three scenarios anchored on the macro contract's current stance.

    No probabilities are assigned. Assigning them would imply a distribution nobody
    estimated; the report says which assumptions each scenario rests on and leaves the
    weighing to the reader, who knows their own business better than the model does.
    """
    if not env.known:
        return [
            Scenario(
                CONTINUITY, "Escenario único · sin contexto macro",
                ["No hay factores macro con lectura disponible para el período."],
                SYMMETRIC,
                "Sin base para ponderar escenarios alternativos.",
                "El pronóstico se lee en términos puramente muestrales: la banda es "
                "simétrica y no incorpora sesgo de entorno.",
            )
        ]

    drivers = [d["label"] for d in env.drivers[:3]]
    driver_text = ", ".join(drivers) if drivers else "los factores macro publicados"

    stance_text = {
        DEMANDING: "un entorno exigente",
        FAVOURABLE: "un entorno favorable",
        NEUTRAL: "un entorno sin sesgo claro",
    }[env.stance]

    continuity_band = {
        DEMANDING: DOWNSIDE, FAVOURABLE: UPSIDE, NEUTRAL: SYMMETRIC,
    }[env.stance]

    return [
        Scenario(
            CONTINUITY,
            "Continuidad",
            [f"{driver_text} mantienen su lectura actual.",
             f"El período se desarrolla en {stance_text}."],
            continuity_band,
            "Es el escenario que prolonga lo ya observado; no requiere supuestos nuevos.",
            f"El pronóstico congelado se lee tal cual, con la banda "
            f"{'inclinada a la baja' if continuity_band == DOWNSIDE else 'inclinada al alza' if continuity_band == UPSIDE else 'simétrica'}.",
        ),
        Scenario(
            DETERIORATION,
            "Deterioro",
            [f"Los factores adversos ({env.adverse} en el período) se intensifican.",
             "El poder adquisitivo del consumidor de la categoría se contrae."],
            DOWNSIDE,
            "Requiere que el deterioro macro se acelere respecto de lo ya publicado.",
            "Los indicadores de tráfico y ticket deben leerse hacia el borde inferior de "
            "su banda; los actitudinales responden con rezago y se moverían menos.",
        ),
        Scenario(
            RELIEF,
            "Alivio",
            [f"Los factores adversos ({env.adverse}) se moderan.",
             "El gasto discrecional recupera espacio."],
            UPSIDE,
            "Requiere una mejora macro que aún no aparece en las series publicadas.",
            "Los indicadores de tráfico responderían primero; la preferencia declarada "
            "tarda al menos una ola adicional en reflejarlo.",
        ),
    ]


@dataclass(frozen=True)
class RuleDispersion:
    """How much the forecast depends on which rule was chosen."""

    metric_code: str
    label: str
    by_rule: Dict[str, float]
    spread: float
    robust: bool
    note: str


def rule_dispersion(
    metric_code: str, label: str, series: Sequence[float], band_halfwidth: Optional[float]
) -> Optional[RuleDispersion]:
    """Run every rule on the same history and measure how far apart they land.

    The comparison is against the forecast's own band: a spread that fits inside the
    sampling band is immaterial — any rule would give the same reading. A spread wider than
    the band means the choice of rule, not the data, is driving the answer.
    """
    usable = [v for v in series if v is not None]
    if len(usable) < 2:
        return None

    by_rule = {name: fn(usable) for name, fn in RULES.items()}
    spread = max(by_rule.values()) - min(by_rule.values())
    robust = band_halfwidth is not None and spread <= band_halfwidth

    note = (
        f"Las tres reglas coinciden dentro de la banda muestral (dispersión "
        f"{spread:.1f} pp ≤ ±{band_halfwidth:.1f} pp): el pronóstico no depende de la "
        f"regla elegida."
        if robust and band_halfwidth is not None else
        f"Las reglas difieren en {spread:.1f} pp"
        + (f", por encima de la banda de ±{band_halfwidth:.1f} pp" if band_halfwidth else "")
        + ": el pronóstico descansa en la regla más que en la serie. Léase con reserva."
    )
    return RuleDispersion(metric_code, label, by_rule, spread, robust, note)


@dataclass(frozen=True)
class BaseSensitivity:
    """How the band widens or narrows with the next wave's achieved sample."""

    point: float
    expected_base: Optional[int]
    rows: List[Dict[str, Any]]
    note: str


def base_sensitivity(
    point: float, expected_base: Optional[int], candidates: Sequence[int] = (150, 200, 300, 400)
) -> BaseSensitivity:
    """Recompute the band across plausible sample sizes for the coming wave."""
    rows = []
    for n in candidates:
        hw = confidence_halfwidth(point, n)
        if hw is None:
            continue
        rows.append({"base_n": n, "halfwidth": hw,
                     "lo": max(0.0, point - hw), "hi": min(100.0, point + hw)})
    note = (
        "La banda es función del tamaño de muestra logrado en campo. Una base menor a la "
        "esperada la ensancha, y resultados que habrían sido noticia dejan de serlo."
        if rows else "Sin base esperada: no se puede calcular la sensibilidad."
    )
    return BaseSensitivity(point, expected_base, rows, note)


def forecast_risks(
    dispersions: Sequence[RuleDispersion],
    n_waves: int,
    env: EnvironmentReading,
) -> List[Dict[str, str]]:
    """The stated ways this forecast can be wrong. Ordered by how much they matter here."""
    risks: List[Dict[str, str]] = []

    fragile = [d for d in dispersions if not d.robust]
    if fragile:
        risks.append({
            "risk": "Dependencia de la regla",
            "detail": "En "
                      + ", ".join(f"«{d.label}»" for d in fragile[:3])
                      + " las reglas de pronóstico difieren más que la banda muestral: "
                        "el resultado depende de la regla elegida, no solo de la serie.",
        })

    if n_waves < 8:
        risks.append({
            "risk": "Historia corta",
            "detail": f"Con {n_waves} ola(s) el pronóstico es una línea base ingenua. "
                      "Un quiebre de nivel —un cambio de precios, una campaña, una apertura— "
                      "no puede anticiparse porque no hay panel donde aprenderlo.",
        })

    risks.append({
        "risk": "Cambio de instrumento",
        "detail": "Cualquier cambio en el cuestionario, el marco muestral o la definición "
                  "de un indicador rompe la comparabilidad de la serie y con ella el "
                  "pronóstico. Debe avisarse antes del campo, no después.",
    })

    if env.stance == DEMANDING:
        risks.append({
            "risk": "Entorno exigente",
            "detail": "El balance macro del período es adverso. La banda inferior es el "
                      "escenario a vigilar, no el punto central.",
        })
    elif env.stance == UNKNOWN:
        risks.append({
            "risk": "Sin contexto macro",
            "detail": "No hay factores macro publicados para el período: el pronóstico "
                      "no incorpora ninguna lectura del entorno.",
        })

    return risks
