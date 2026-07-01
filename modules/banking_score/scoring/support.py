"""Capa de soporte/sistémico + techo soberano (Fase 6), estilo Fitch VR/GSR/IDR.

El score SDQ standalone (overall_score, rating_tier, vector 21-dim) es el análogo del
Viability Rating y se mantiene PURO — esta capa NO lo muta. Es un overlay de CONTEXTO,
calculado en read-time y adjuntado al scoring_result (patrón de la amplitud de Fase 4),
solo Deep Dive. Provee tres lecturas que el standalone deliberadamente no incorpora:

- Soporte estatal — propiedad estatal de la entidad (set de config; hoy Banreservas).
- Importancia sistémica — cuota de activos/depósitos + rank CR (too-big-to-fail).
- Techo soberano — la calificación soberana de RD (dato declarado, regulatory.yaml).

Doctrina (consistente con Fase 3): el SDQ es fortaleza financiera STANDALONE RELATIVA
dentro de RD, NO un rating de crédito. Por eso el techo soberano y el soporte se
presentan como CONTEXTO analítico rotulado, no como un ajuste que baje/suba el SDQ.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank
from modules.banking_score.scoring.market_concentration import compute_market_concentration

COUNTRY = "DO"

# Entidades de propiedad estatal (set de config; extensible por PR). Hoy solo el Banco
# de Reservas. Por nombre exacto del catálogo SIB — no hay flag en el modelo Bank y
# hay exactamente una banca estatal, así que un set declarado es honesto y mínimo.
STATE_OWNED = frozenset({"Banco de Reservas de la República Dominicana"})

# Umbral de importancia sistémica: dentro del CR5 por activos = sistémica (too-big-to-fail).
_SIFI_RANK = 5


def sovereign_anchor(db: Optional[Session] = None) -> Dict[str, Any]:
    """Ancla soberana de RD desde el store refrescable multi-agencia (Wikipedia →
    ``AppSetting``, con el ``regulatory.yaml`` como piso). Bajo la política "S&P manda"
    (decisión dueño 2026-07-01), el rating/score/fecha que anclan son los de S&P; Fitch y
    Moody's viajan como CONTEXTO en ``agencies`` (no mueven el índice). Sin *db* cae al
    piso declarado. Transparente con su ``as_of`` (última acción)."""
    from shared.contracts.sovereign_ratings import combined_anchor

    return combined_anchor(COUNTRY, db=db)


def _entity_share(db: Session, bank: Bank, period_end: date, metric: str) -> Optional[Dict[str, Any]]:
    """Cuota (%) y rank de *bank* en *metric* (activos/depósitos) del universo EIF, o None
    si no está entre los mayores (top-10) o no hay dato."""
    conc = compute_market_concentration(db, period_end, metric)
    if not conc.get("available"):
        return None
    top = conc.get("top10") or []
    for i, t in enumerate(top):
        if t.get("name") == bank.name:
            return {"share": t.get("share"), "rank": i + 1, "n_entities": conc.get("n_entities")}
    return None


# Grado de inversión arranca en BBB- (rating_scale = 55). Por debajo, el soberano es de
# grado ESPECULATIVO → capacidad fiscal limitada para proveer soporte extraordinario.
_INVESTMENT_GRADE_SCORE = 55.0


def _support_assessment(state_owned: bool, is_systemic: bool,
                        sovereign: Dict[str, Any]) -> str:
    """Lectura cualitativa del soporte extraordinario (estilo GSR de Fitch), en sus DOS
    patas: PROPENSIÓN (propiedad estatal / importancia sistémica → voluntad de soporte) y
    CAPACIDAD (fortaleza del soberano → habilidad de costearlo). Un soberano de grado
    especulativo acota la capacidad, así que el soporte no puede leerse como asegurado por
    fuerte que sea la propensión — un rescate lo paga el soberano, no la doctrina."""
    if not state_owned and not is_systemic:
        return ("Sin soporte extraordinario esperado: la lectura relevante para esta entidad "
                "es su perfil financiero standalone.")

    # Pata 1 — propensión (voluntad).
    if state_owned and is_systemic:
        prop = ("Propensión de soporte ALTA: propiedad estatal e importancia sistémica.")
    elif is_systemic:
        prop = ("Propensión de soporte por importancia sistémica (too-big-to-fail) sin "
                "propiedad estatal; dependería de la política de resolución, no de un mandato "
                "de propiedad.")
    else:  # state_owned, no sistémico
        prop = ("Propensión de soporte por propiedad estatal, con importancia sistémica no "
                "material a nivel de activos.")

    # Pata 2 — capacidad (habilidad del soberano). Un soberano especulativo la acota.
    score = sovereign.get("score")
    rating = sovereign.get("rating")
    if isinstance(score, (int, float)) and score < _INVESTMENT_GRADE_SCORE:
        cap = (f" No obstante, la CAPACIDAD efectiva de ese soporte está ACOTADA por el perfil "
               f"soberano de grado especulativo (RD {rating}): un soberano con margen fiscal "
               f"limitado tiene menor habilidad para proveer soporte extraordinario, por lo que "
               f"el soporte debe leerse como INCIERTO, no asumido.")
    else:
        cap = (" La capacidad de ese soporte se apoya en un soberano de grado de inversión "
               f"(RD {rating}), con mayor margen fiscal.")
    return prop + cap


def support_overlay(db: Session, bank: Bank, standalone_score: float,
                    standalone_tier: str, period_end: date) -> Dict[str, Any]:
    """Overlay de soporte/sistémico/techo soberano para *bank*. NO muta el standalone;
    devuelve un bloque de contexto para narrativa + tabla del Deep Dive."""
    state_owned = bank.name in STATE_OWNED
    activos = _entity_share(db, bank, period_end, "activos")
    depositos = _entity_share(db, bank, period_end, "depositos")
    rank = (activos or {}).get("rank")
    is_systemic = bool(rank and rank <= _SIFI_RANK)
    if rank and rank <= _SIFI_RANK:
        sys_label = f"Sistémica — top {rank} por activos (dentro del CR5)"
    elif rank:
        sys_label = f"Relevante — top {rank} por activos"
    else:
        sys_label = "No sistémica (fuera del top-10 por activos)"

    sov = sovereign_anchor(db)
    return {
        "state_owned": state_owned,
        "systemic": {
            "activos_share": (activos or {}).get("share"),
            "depositos_share": (depositos or {}).get("share"),
            "rank_activos": rank,
            "is_systemic": is_systemic,
            "label": sys_label,
        },
        "sovereign": sov,
        "support_assessment": _support_assessment(state_owned, is_systemic, sov),
        "standalone": {"score": round(float(standalone_score), 2), "tier": standalone_tier},
    }
