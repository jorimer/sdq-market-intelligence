"""IRC backtest (Gate E) — does climate resilience track realized harm?

Cross-sectional validation over the Caribbean/LatAm panel: a less climate-
resilient country (lower IRC) should suffer higher climate-disaster mortality
(OWID/EM-DAT). We report the Spearman rank correlation (with a bootstrap CI) and
the mean mortality by IRC band, checking monotonicity. Honest caveat: cross-
sectional and preliminary — hurricane exposure is partly an IRC input (endogenous)
and the panel is small; this is a directional check, not a causal claim.
"""
import random
from typing import Any, Dict, List, Optional, Tuple

from shared.validation.control_tamano import (
    VEREDICTO_CONTROL_NO_EVALUABLE, VEREDICTO_EMPATE, VEREDICTO_SCORE_SUPERA,
    VEREDICTO_TAMANO_ALCANZA,
)

_BANDS = (("Alta", 60.0), ("Moderada", 40.0), ("Baja", 0.0))


def _spearman(pairs: List[Tuple[float, float]]) -> Optional[float]:
    n = len(pairs)
    if n < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rx = _ranks(xs)
    ry = _ranks(ys)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return round(1 - 6 * d2 / (n * (n * n - 1)), 3)


def _ranks(vals: List[float]) -> List[float]:
    """Average ranks (ties shared), 0-based."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _bootstrap_ci(pairs: List[Tuple[float, float]], iters: int = 1000,
                  seed: int = 12345) -> Tuple[Optional[float], Optional[float]]:
    if len(pairs) < 3:
        return None, None
    rng = random.Random(seed)
    n = len(pairs)
    rs: List[float] = []
    for _ in range(iters):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        r = _spearman(sample)
        if r is not None:
            rs.append(r)
    if not rs:
        return None, None
    rs.sort()
    lo = rs[int(0.025 * len(rs))]
    hi = rs[min(len(rs) - 1, int(0.975 * len(rs)))]
    return round(lo, 3), round(hi, 3)


def _band(score: float) -> str:
    for name, lower in _BANDS:
        if score >= lower:
            return name
    return "Baja"


def _control_por_tamano(common: List[str], mortality: Dict[str, float],
                        poblacion: Optional[Dict[str, float]],
                        rho_del_score: Optional[float],
                        ic_del_score: Optional[List] = None) -> Dict[str, Any]:
    """La misma mortalidad, ordenada solo por el tamaño del país.

    El desenlace ya viene por 100.000 habitantes, así que la población es su DEFLACTOR — la
    misma situación que dio vuelta el veredicto del IAI, donde el signo lo producía dividir
    por el tamaño y no el índice. Se mide con Spearman porque el motor es de correlación, no
    de clasificación: comparar un ρ con un Gini sería comparar dos escalas distintas.
    """
    base: Dict[str, Any] = {
        "variable": "SP.POP.TOTL",
        "nota": ("la misma mortalidad climática ordenada solo por la población del país. El "
                 "desenlace está expresado POR 100.000 habitantes, así que la población es su "
                 "deflactor: si ordena tan bien como el IRC, la correlación es del deflactor"),
        "metrica": "spearman",
    }
    if not poblacion:
        return {**base, "spearman": None, "spearman_ci": None, "n": 0,
                "motivo": "no se pudo obtener la población del panel (WDI `SP.POP.TOTL`): el "
                          "control no se computó en esta corrida",
                "veredicto": VEREDICTO_CONTROL_NO_EVALUABLE}
    pares = [(poblacion[i], mortality[i]) for i in common if poblacion.get(i)]
    if len(pares) < 3:
        return {**base, "spearman": None, "spearman_ci": None, "n": len(pares),
                "motivo": "menos de tres países con población: sin pares no hay correlación",
                "veredicto": VEREDICTO_CONTROL_NO_EVALUABLE}
    rho = _spearman(pares)
    lo, hi = _bootstrap_ci(pares)
    alcanza = (rho is not None and rho_del_score is not None
               and abs(rho) >= abs(rho_del_score))
    # El EMPATE: si el ρ del control cae dentro del intervalo del score, la diferencia no se
    # distingue del ruido y decir «el score supera» inventa una ventaja que el dato no da.
    empata = bool(rho is not None and ic_del_score
                  and ic_del_score[0] is not None and ic_del_score[1] is not None
                  and ic_del_score[0] <= rho <= ic_del_score[1])
    if rho is None or rho_del_score is None:
        veredicto = VEREDICTO_CONTROL_NO_EVALUABLE
    elif empata:
        veredicto = VEREDICTO_EMPATE
    elif alcanza:
        veredicto = VEREDICTO_TAMANO_ALCANZA
    else:
        veredicto = VEREDICTO_SCORE_SUPERA
    return {
        **base, "spearman": rho, "spearman_ci": [lo, hi], "n": len(pares),
        "n_del_score": len(common),
        "spearman_del_score": rho_del_score,
        "el_tamano_alcanza_al_score": bool(alcanza),
        "empata_con_el_score": bool(empata),
        "veredicto": veredicto,
    }


def build_esg_backtest(irc: Dict[str, float], mortality: Dict[str, float],
                       window_from: int = 2000,
                       poblacion: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Report: Spearman(IRC, climate mortality) + bootstrap CI + mortality by IRC
    band + monotonicity. *irc* and *mortality* are ``{iso3: value}``."""
    common = sorted(set(irc) & set(mortality))
    pairs = [(irc[i], mortality[i]) for i in common]
    if len(pairs) < 3:
        return {"computed": False, "message": "Datos insuficientes para el backtest.",
                "n_countries": len(pairs),
                # Aun sin backtest la clave viaja: un control que desaparece cuando falta su
                # insumo se lee como que el control se hizo.
                "control_solo_tamano": _control_por_tamano(common, mortality, poblacion, None)}

    rho = _spearman(pairs)
    lo, hi = _bootstrap_ci(pairs)

    by_band: List[Dict[str, Any]] = []
    means: List[float] = []
    import statistics
    for name, _lower in _BANDS:
        vals = [mortality[i] for i in common if _band(irc[i]) == name]
        mean = round(statistics.mean(vals), 4) if vals else None
        by_band.append({"band": name, "n": len(vals), "mean_climate_deaths_per_100k": mean})
        if mean is not None:
            means.append(mean)
    # Monotonic if mortality falls as resilience rises (Baja ≥ Moderada ≥ Alta).
    ordered = [b["mean_climate_deaths_per_100k"] for b in reversed(by_band)
               if b["mean_climate_deaths_per_100k"] is not None]
    monotonic = all(ordered[k] >= ordered[k + 1] for k in range(len(ordered) - 1))

    return {
        "computed": True,
        "n_countries": len(pairs),
        "window_from": window_from,
        "outcome": "muertes por desastre climático / 100k hab/año (OWID/EM-DAT)",
        "spearman": rho,
        "spearman_ci": [lo, hi],
        # El control viaja pegado a la cifra que acota, nunca en otro documento.
        "control_solo_tamano": _control_por_tamano(common, mortality, poblacion, rho,
                                                   [lo, hi]),
        "by_band": by_band,
        "monotonic": monotonic,
        "note": "Validación direccional preliminar (transversal, panel pequeño); la "
                "exposición a huracanes es en parte insumo del IRC. No es afirmación causal.",
    }
