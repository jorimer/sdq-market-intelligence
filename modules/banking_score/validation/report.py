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
from shared.validation.metrics import monotonicity_violations

# Below this many deterioration events the Gini is too thin to lean on.
_THIN_EVENTS = 30

# La prosa vive en constantes; la BANDA y su N se computan del propio resultado. El caveat
# anterior era una frase fija —«ruido muestral en tiers intermedios»— y describía mal el
# defecto: la anomalía está en la banda SUPERIOR y con el N más grande del panel. Es la
# doctrina de que las relaciones se computan y el texto las copia, no al revés.
_CAVEAT_NO_ORDENA = (
    "La curva de deterioro por banda NO ordena el riesgo, así que la tabla por banda no se "
    "publica como ordenamiento"
)
_CAVEAT_NO_ES_RUIDO = (
    "no es ruido de un tier intermedio ni de una muestra chica: es una inversión con N "
    "grande. El score continuo sí discrimina débilmente (ver Gini y su IC); la clasificación "
    "en bandas, no"
)


def _pct(v: float) -> str:
    """Porcentaje con coma decimal: el reporte se lee en español y viaja a un PDF."""
    return f"{v * 100:.1f}".replace(".", ",") + " %"


def _caveat_de_monotonia(violaciones) -> str:
    """Nombra la inversión concreta —qué bandas, con qué tasas y qué N— o describe el hueco."""
    if not violaciones:
        return f"{_CAVEAT_NO_ORDENA}."
    v = violaciones[0]
    return (
        f"{_CAVEAT_NO_ORDENA}: «{v['mejor']}» (n={v['mejor_n']}) registra "
        f"{_pct(v['mejor_rate'])} de deterioro, por encima de «{v['peor']}» "
        f"(n={v['peor_n']}, {_pct(v['peor_rate'])}) — {_CAVEAT_NO_ES_RUIDO}."
    )


def build_backtest_report(db: Session, horizon_q: int = HORIZON_Q,
                          n_boot: int = 1000) -> Dict:
    obs = derive_observations(db, horizon_q=horizon_q)
    # Orden de mejor a peor. `BANDAS_RESILIENCIA` YA cierra con el corte 0.0 → "Frágil";
    # agregarlo otra vez duplicaba la fila de Frágil en `by_tier` (fila repetida en el
    # informe de validación publicado, y una comparación tautológica rate<=rate en la
    # monotonía). Mismo off-by-one que sacaba la fila "Frágil | 0 – 0" en Criterios §4.
    tier_order = [n for _c, n in BANDAS_RESILIENCIA]

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
        "Se excluye a propósito el 'downgrade ≥2 bandas' como desenlace: está sesgado por "
        "el piso/techo de la escala (una entidad ya en la banda más baja no puede caer dos "
        "bandas) y produce un Gini negativo artificial; no mide deterioro real.",
        "Sin vintages de datos: la línea de tiempo usa period_end (fin de trimestre), "
        "no la fecha de publicación original. Se asume el rezago de publicación del SIB.",
    ]
    if n_events < _THIN_EVENTS:
        caveats.insert(0, f"Pocos eventos ({n_events}): el Gini es indicativo, no concluyente.")
    violaciones = monotonicity_violations(by_tier)
    if not monotonic:
        caveats.insert(0, _caveat_de_monotonia(violaciones))

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
        # Que la curva ORDENE el riesgo es una afirmación aparte de que exista: sin esto, la
        # superficie que la dibuja tiene que deducirlo, y la deducción se pierde en el camino
        # a un PDF o a una lámina.
        "by_tier_ordena_riesgo": monotonic,
        "monotonic_violations": violaciones,
        "caveats": caveats,
    }
