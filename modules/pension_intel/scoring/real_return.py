"""Retorno real (Fase 5): deflacta la rentabilidad nominal de las AFP por la inflación
interanual del BCRD → retorno real.

Presentación pura — NO entra al ISA. Deflactar por una inflación común a todas las AFP es
un desplazamiento aditivo común: el min-max entre pares es invariante, así que el score no
cambia. El retorno real es honestidad económica (lo que el afiliado gana sobre la vida) en
el titular, la narrativa y la trayectoria; el ISA sigue puntuando sobre nominal.

La serie de inflación llega vía el AppSetting compartido que persiste ``macro_monitor``
(``shared.contracts.load_inflation_series``), sin importar el módulo macro.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def fisher_real(nominal_pct: float, inflation_pct: float) -> float:
    """Retorno real por Fisher: (1+n)/(1+i)−1, en %. Más correcto que n−i para tasas
    anuales de magnitud no trivial (aquí ~9% nominal, ~5% inflación)."""
    return round(((1.0 + nominal_pct / 100.0) / (1.0 + inflation_pct / 100.0) - 1.0) * 100.0, 2)


def _pkey(period: str) -> Tuple[int, int]:
    """Clave ordenable (año, mes-fin) para períodos 'YYYY-MM' | 'YYYY-Qn' | 'YYYY'.
    Permite comparar y hacer carry-forward de la inflación al período más cercano previo."""
    p = str(period)
    try:
        year = int(p[:4])
    except (ValueError, IndexError):
        return (0, 0)
    rest = p[5:] if len(p) > 4 else ""
    if rest.startswith("Q") and rest[1:].isdigit():
        return (year, int(rest[1:]) * 3)  # Qn → mes fin del trimestre
    if rest.isdigit():
        return (year, int(rest))
    return (year, 12)  # anual → fin de año


def inflation_at(infl: Dict[str, float], period: str) -> Optional[float]:
    """Inflación interanual en *period*: match exacto; si no, el valor disponible más
    reciente ANTERIOR o igual (carry-forward). None si no hay ninguno aplicable."""
    if not infl:
        return None
    if period in infl:
        return infl[period]
    target = _pkey(period)
    prior = [(_pkey(p), v) for p, v in infl.items() if _pkey(p) <= target]
    if not prior:
        return None
    prior.sort()
    return prior[-1][1]


def deflate_trend(trend: List[tuple], infl: Dict[str, float]) -> List[Tuple[str, float, float]]:
    """``[(period, nominal, real)]`` para cada punto con inflación aplicable; omite los
    períodos sin inflación (no fabrica). Vacío si no hay serie de inflación."""
    out: List[Tuple[str, float, float]] = []
    if not infl:
        return out
    for p, nominal in trend:
        i = inflation_at(infl, p)
        if i is None or nominal is None:
            continue
        out.append((p, nominal, fisher_real(nominal, i)))
    return out
