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
from shared.doctrine.loader import load_doctrine_raw

COUNTRY = "DO"

# Entidades de propiedad estatal (set de config; extensible por PR). Hoy solo el Banco
# de Reservas. Por nombre exacto del catálogo SIB — no hay flag en el modelo Bank y
# hay exactamente una banca estatal, así que un set declarado es honesto y mínimo.
STATE_OWNED = frozenset({"Banco de Reservas de la República Dominicana"})

# Umbral de importancia sistémica: dentro del CR5 por activos = sistémica (too-big-to-fail).
_SIFI_RANK = 5


def sovereign_anchor() -> Dict[str, Any]:
    """Ancla soberana de RD desde la doctrina declarada (regulatory.yaml): rating S&P
    de largo plazo en moneda extranjera + su fecha + score 0-100. Dato declarado (no hay
    API gratuita de ratings), transparente con su ``as_of``."""
    doc = load_doctrine_raw("regulatory")
    info = (doc.get("sovereign_ratings") or {}).get(COUNTRY) or {}
    scale = doc.get("rating_scale") or {}
    rating = info.get("rating")
    return {
        "rating": rating,
        "agency": info.get("agency"),
        "as_of": info.get("as_of"),
        "score": scale.get(rating),
    }


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


def _support_assessment(state_owned: bool, is_systemic: bool) -> str:
    """Lectura cualitativa del soporte extraordinario probable (estilo GSR de Fitch)."""
    if state_owned and is_systemic:
        return ("Soporte extraordinario probable ALTO: entidad de propiedad estatal e "
                "importancia sistémica. En clave crediticia comparable, su solvencia "
                "efectiva podría exceder su perfil financiero standalone.")
    if is_systemic:
        return ("Soporte sistémico POSIBLE: importancia sistémica (too-big-to-fail) sin "
                "propiedad estatal; el soporte dependería de la política de resolución.")
    if state_owned:
        return ("Soporte estatal POSIBLE por propiedad, con importancia sistémica no "
                "material a nivel de activos.")
    return ("Sin soporte extraordinario esperado: la lectura relevante para esta entidad "
            "es su perfil financiero standalone.")


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

    return {
        "state_owned": state_owned,
        "systemic": {
            "activos_share": (activos or {}).get("share"),
            "depositos_share": (depositos or {}).get("share"),
            "rank_activos": rank,
            "is_systemic": is_systemic,
            "label": sys_label,
        },
        "sovereign": sovereign_anchor(),
        "support_assessment": _support_assessment(state_owned, is_systemic),
        "standalone": {"score": round(float(standalone_score), 2), "tier": standalone_tier},
    }
