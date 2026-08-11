"""Assemble the rating backtest report (metrics + honesty caveats).

Deterministic and cheap (in-memory over the rating history), so it can be
recomputed on demand or on a schedule from the Operation Console.
"""
from typing import Dict

from sqlalchemy.orm import Session

from modules.banking_score.scoring.perfil_sdq import BANDAS_RESILIENCIA
from modules.banking_score.validation.metrics import (
    deterioration_rate_by_tier, gini_bootstrap_ci,
)
from modules.banking_score.validation.outcomes_derivation import (
    HORIZON_Q, derive_observations,
)

# Below this many deterioration events the Gini is too thin to lean on.
_THIN_EVENTS = 30


def build_backtest_report(db: Session, horizon_q: int = HORIZON_Q,
                          n_boot: int = 1000) -> Dict:
    obs = derive_observations(db, horizon_q=horizon_q)
    # Orden de mejor a peor, igual que antes con los escalones.
    tier_order = [n for _c, n in BANDAS_RESILIENCIA] + ["Frágil"]

    if not obs:
        return {
            "ok": False,
            "horizon_quarters": horizon_q,
            "n_observations": 0,
            "n_events": 0,
            "message": "No hay suficiente histórico para backtestear (faltan períodos con horizonte).",
        }

    scores = [o.score for o in obs]
    labels = [1 if o.deteriorated else 0 for o in obs]
    tiers = [o.tier for o in obs]
    n_events = sum(labels)

    g, g_lo, g_hi = gini_bootstrap_ci(scores, labels, n_boot=n_boot)
    by_tier, monotonic = deterioration_rate_by_tier(tiers, labels, tier_order)

    caveats = [
        "Validación preliminar — NO es un rating grado-Basilea ni una PD calibrada.",
        "Desenlace = distress financiero (mora que se duplica / solvencia <10% / ROA<0 "
        "sostenido), NO quiebras: el sistema bancario dominicano no registra defaults en "
        "la ventana, así que la discriminación es direccional.",
        "Se excluye a propósito el 'downgrade ≥2 escalones' como desenlace: está sesgado "
        "por el piso/techo de la escala (un SDQ-D no puede caer 2 escalones) y produce un "
        "Gini negativo artificial; no mide deterioro real.",
        "Sin vintages de datos: la línea de tiempo usa period_end (fin de trimestre), "
        "no la fecha de publicación original. Se asume el rezago de publicación del SIB.",
    ]
    if n_events < _THIN_EVENTS:
        caveats.insert(0, f"Pocos eventos ({n_events}): el Gini es indicativo, no concluyente.")
    if g is not None and not monotonic:
        caveats.insert(0, "La curva de distress por tier es positiva pero NO estrictamente "
                          "monótona (ruido muestral en tiers intermedios): direccional, no validada.")

    return {
        "ok": True,
        "horizon_quarters": horizon_q,
        "n_observations": len(obs),
        "n_events": n_events,
        "event_rate": n_events / len(obs),
        "gini": g,
        "gini_ci": [g_lo, g_hi] if g is not None else None,
        "by_tier": by_tier,
        "monotonic": monotonic,
        "caveats": caveats,
    }
