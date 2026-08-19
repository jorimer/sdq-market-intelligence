"""¿La recalibración del 7-ago DEGRADÓ la discriminación del rating, o el 0,44 medía otra cosa?

**El hecho.** El reporte persistido el 27-jul declaraba Gini 0,4436 [0,383 · 0,502]. El de
hoy, sobre el MISMO panel (1.693 observaciones, 301 eventos), declara 0,1615 [0,083 · 0,242].
Entre ambos hay un solo commit que toca el número: `02fcdd2` (2026-08-07), la recalibración de
los cinco indicadores de SOLIDEZ —el 40% del score— de rectas saturadas a curvas de dos tramos.

**Por qué hace falta medirlo y no razonarlo.** El argumento intuitivo apunta al revés: si el
score viejo saturaba (96% del sistema marcaba 100/100 en tres indicadores), debería haber
discriminado PEOR, no mejor. Que el Gini haya caído a un tercio con más varianza en el
sub-componente de mayor peso es contraintuitivo, y una credencial comercial no se defiende con
una intuición.

**El método.** Se rehace el backtest cambiando UNA sola cosa: el score. Mismo panel, mismos
desenlaces —los produce `derive_observations`, que no se toca—, mismas bandas. El score previo
se reconstruye aplicando las curvas de `02fcdd2^` a los MISMOS valores crudos (la
recalibración cambió cómo se puntúa un crudo, no cómo se computa), y reagregando con los
sub-componentes persistidos de las otras cuatro dimensiones.

Además se mide el Gini de cada dimensión por separado. Si la discriminación vive en una sola,
el promedio ponderado del score la diluye — y eso se arregla en el score, no en el reporte.

**Lo que esta reconstrucción NO reproduce**, declarado: la recalibración también cambió el
tratamiento del dato ausente (denominador en cero pasó de puntuar 0 a declarar el indicador no
disponible). El score previo lo replica —cuenta los cinco indicadores siempre, con 0 donde no
hay crudo—, que es el comportamiento viejo, pero solo en SOLIDEZ: en `morosidad`, que también
ganó la regla, la dimensión de calidad se toma persistida y por lo tanto ya recalibrada. El
efecto de esa parte queda fuera de la comparación y no se le atribuye a la curva.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple, cast

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, BankingData, ModelType, RatingResult
from modules.banking_score.scoring.engine import (
    calc_cobertura_provisiones, calc_leverage, calc_patrimonio_activos,
    calc_solvencia, calc_tier1_ratio, calculate_deterministic_score,
)
from modules.banking_score.scoring.perfil_sdq import BANDAS_RESILIENCIA
from modules.banking_score.scoring.weights import get_sub_component_weights
from modules.banking_score.validation.metrics import (
    deterioration_rate_by_tier, gini_bootstrap_ci,
)
from modules.banking_score.validation.outcomes_derivation import HORIZON_Q, derive_observations

_DIMENSIONES = ("solidez", "calidad", "eficiencia", "liquidez", "diversificacion")


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


# Las curvas ANTERIORES a `02fcdd2`, copiadas del commit padre. Viven acá y no se importan
# porque el motor ya no las tiene: son el término de comparación, no una alternativa viva.
def _solvencia_previa(raw: float) -> float:
    return _clamp(min(100.0, (raw / 15) * 100))


def _tier1_previa(raw: float) -> float:
    return _clamp(min(100.0, ((raw - 4.5) / 4) * 100)) if raw >= 4.5 else 0.0


def _leverage_previa(raw: float) -> float:
    return _clamp(min(100.0, (raw / 6) * 100))


def _cobertura_previa(raw: float) -> float:
    return _clamp(min(100.0, raw))


def _patrimonio_previa(raw: float) -> float:
    return _clamp(min(100.0, (raw / 12) * 100))


_CURVAS_PREVIAS = {
    "solvencia": (calc_solvencia, _solvencia_previa),
    "tier1_ratio": (calc_tier1_ratio, _tier1_previa),
    "leverage": (calc_leverage, _leverage_previa),
    "cobertura_provisiones": (calc_cobertura_provisiones, _cobertura_previa),
    "patrimonio_activos": (calc_patrimonio_activos, _patrimonio_previa),
}


def solidez_previa(d: BankingData) -> Optional[float]:
    """Sub-componente de solidez con las curvas viejas: promedio simple de los CINCO.

    Siempre los cinco, incluso cuando el crudo no se puede computar: el motor viejo no
    declaraba indicadores no disponibles, `_safe_div` devolvía 0.0 y la ausencia puntuaba
    como el peor valor posible. Reproducirlo es el punto — es el score que produjo el 0,44.
    """
    puntajes: List[float] = []
    for _nombre, (calc, curva) in _CURVAS_PREVIAS.items():
        try:
            crudo = calc(d).get("raw")
        except Exception:  # noqa: BLE001 — un indicador roto no invalida la comparación
            crudo = None
        puntajes.append(0.0 if crudo is None else round(curva(float(crudo)), 2))
    return round(sum(puntajes) / len(puntajes), 2) if puntajes else None


def _gini(scores: List[float], labels: List[int], n_boot: int) -> Dict:
    g, lo, hi = gini_bootstrap_ci(scores, labels, n_boot=n_boot)
    if g is None:
        return {"gini": None, "gini_ci": None}
    ci = None if lo is None or hi is None else [round(lo, 4), round(hi, 4)]
    return {"gini": round(g, 4), "gini_ci": ci}


def _curva_por_banda(tiers: List[str], labels: List[int]) -> Tuple[List[Dict], bool]:
    return deterioration_rate_by_tier(tiers, labels, [n for _c, n in BANDAS_RESILIENCIA])


def comparar_recalibracion(db: Session, horizon_q: int = HORIZON_Q,
                           n_boot: int = 1000) -> Dict:
    """Mismo panel y mismos desenlaces, dos scores: el vigente y el previo a `02fcdd2`."""
    obs = derive_observations(db, horizon_q=horizon_q)
    if not obs:
        return {"ok": False, "motivo": "sin panel: no hay observaciones con horizonte"}

    ratings = {(str(r.bank_id), cast(date, r.period_end)): r for r in
               db.query(RatingResult).filter(
                   RatingResult.model_type == ModelType.deterministic).all()}
    financieros = {(str(d.bank_id), cast(date, d.period_end)): d
                   for d in db.query(BankingData).all()}
    # El perfil de pesos depende del TIPO de entidad: una cambiaria y un banco múltiple no
    # agregan sus dimensiones igual, y usar el perfil base para todos movería el score por
    # una razón ajena a la recalibración.
    tipo_por_banco: Dict[str, Optional[str]] = {
        str(b.id): (b.bank_type.value if hasattr(b.bank_type, "value") else str(b.bank_type))
        for b in db.query(Bank).all()
    }

    etiquetas: List[int] = []
    bandas: List[str] = []
    score_actual: List[float] = []
    score_previo: List[float] = []
    por_dimension: Dict[str, Tuple[List[float], List[int]]] = {d: ([], []) for d in _DIMENSIONES}
    sin_reconstruir = 0

    for o in obs:
        rr = ratings.get((str(o.bank_id), o.period_end))
        bd = financieros.get((str(o.bank_id), o.period_end))
        etiqueta = 1 if o.deteriorated else 0
        # Las dimensiones se miden sobre TODAS las observaciones que las tengan, aunque la
        # reconstrucción del score previo falle: son preguntas distintas y mezclar los
        # universos volvería incomparables las cifras.
        if rr is not None:
            for dim in _DIMENSIONES:
                v = getattr(rr, f"{dim}_score", None)
                if v is not None:
                    por_dimension[dim][0].append(float(v))
                    por_dimension[dim][1].append(etiqueta)
        if rr is None or bd is None:
            sin_reconstruir += 1
            continue
        sol_previa = solidez_previa(bd)
        if sol_previa is None:
            sin_reconstruir += 1
            continue
        subs = {dim: (None if getattr(rr, f"{dim}_score", None) is None
                      else float(getattr(rr, f"{dim}_score")))
                for dim in _DIMENSIONES}
        subs["solidez"] = sol_previa
        pesos = get_sub_component_weights(tipo_por_banco.get(o.bank_id))
        etiquetas.append(etiqueta)
        bandas.append(o.tier)
        score_actual.append(o.score)
        score_previo.append(calculate_deterministic_score(subs, pesos))

    actual_curva, actual_monotona = _curva_por_banda(bandas, etiquetas)
    dimensiones = {}
    for dim, (xs, ys) in por_dimension.items():
        dimensiones[dim] = {**_gini(xs, ys, n_boot), "n": len(xs), "eventos": sum(ys)}

    return {
        "ok": True,
        "panel": {
            "n_observaciones_backtest": len(obs),
            "n_eventos_backtest": sum(1 for o in obs if o.deteriorated),
            "n_comparables": len(etiquetas),
            "n_sin_reconstruir": sin_reconstruir,
            "n_eventos_comparables": sum(etiquetas),
        },
        "actual": {**_gini(score_actual, etiquetas, n_boot),
                   "by_tier": actual_curva, "monotonic": actual_monotona},
        # Sin curva por banda para el score previo, a propósito: la banda sale del eje de
        # Resiliencia del Perfil SDQ, no del `overall_score`, así que no hay forma de
        # re-bandear el score reconstruido sin inventar un corte. La comparación que este
        # diagnóstico sostiene es la del PODER DISCRIMINANTE, que no necesita bandas.
        "previo": _gini(score_previo, etiquetas, n_boot),
        "por_dimension": dimensiones,
        "limite_declarado": (
            "La reconstrucción cambia SOLO las curvas de los cinco indicadores de solidez. "
            "El cambio de trato del dato ausente en `morosidad` (calidad) queda dentro del "
            "score persistido de esa dimensión y no se le atribuye a la curva."
        ),
    }
