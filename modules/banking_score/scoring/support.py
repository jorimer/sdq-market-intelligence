"""Capa de soporte/sistémico + techo soberano (Fase 6), estilo Fitch VR/GSR/IDR.

El score SDQ standalone (overall_score, los dos ejes, vector 21-dim) es el análogo del
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


def systemic_label(rank: Optional[int]) -> str:
    """La etiqueta de importancia sistémica que corresponde a un *rank* por activos.

    Vive fuera de :func:`support_overlay` porque la muestra curada del producto declara su
    propio rank y necesita la MISMA etiqueta: escribirla a mano es la forma de que la
    vidriera diga «Sistémica» al lado de un rank que la regla no llamaría así."""
    if rank and rank <= _SIFI_RANK:
        return f"Sistémica — top {rank} por activos (dentro del CR5)"
    if rank:
        return f"Relevante — top {rank} por activos"
    return "No sistémica (fuera del top-10 por activos)"


def sovereign_anchor(db: Optional[Session] = None) -> Dict[str, Any]:
    """Ancla soberana de RD desde el store refrescable multi-agencia (Wikipedia →
    ``AppSetting``, con el ``regulatory.yaml`` como piso). Bajo la política "S&P manda"
    (decisión dueño 2026-07-01), el rating/score/fecha que anclan son los de S&P; Fitch y
    Moody's viajan como CONTEXTO en ``agencies`` (no mueven el índice). Sin *db* cae al
    piso declarado. Transparente con su ``as_of`` (última acción)."""
    from shared.contracts.sovereign_ratings import combined_anchor

    return combined_anchor(COUNTRY, db=db)


def _after(fecha: Any, corte: date) -> bool:
    """¿La fecha ISO *fecha* es POSTERIOR al corte del informe? No parseable → False."""
    try:
        return date.fromisoformat(str(fecha)[:10]) > corte
    except (ValueError, TypeError):
        return False


def _sovereign_as_of(sov: Dict[str, Any], corte: date) -> Dict[str, Any]:
    """Ancla soberana vista DESDE el corte del informe.

    El rating soberano vigente al corte es dato legítimo, pero dos fechas del sobre pueden
    ser posteriores y no deben mostrarse en un informe fechado antes: la ``affirm_date`` (la
    anotación humana de "verifiqué que sigue vigente", que es metadato de verificación, no
    un hecho del período) y cualquier agencia cuya ÚLTIMA ACCIÓN ocurrió después del corte
    —esa acción todavía no existía—. El corte debe ser cónsono con TODA la información
    mostrada. No se altera el rating ni el score: solo se recorta lo que aún no había pasado.
    """
    out = dict(sov or {})
    if _after(out.get("affirm_date"), corte):
        out["affirm_date"] = None
    if _after(out.get("as_of"), corte):
        # La acción del ancla es posterior al corte: no hay ancla verificable a esa fecha.
        out["as_of"] = None
    ags = [a for a in (out.get("agencies") or [])
           if not _after((a or {}).get("action_date"), corte)]
    out["agencies"] = ags
    return out


def _entity_share(db: Session, bank: Bank, period_end: date, metric: str) -> Optional[Dict[str, Any]]:
    """Cuota (%) y rank de *bank* en *metric* (activos/depósitos) del universo EIF, o None
    si no está entre los mayores (top-10) o no hay dato."""
    conc = compute_market_concentration(db, period_end, metric)
    if not conc.get("available"):
        return None
    top = conc.get("top10") or []
    for i, t in enumerate(top):
        if t.get("name") == bank.name:
            # sujeto-ok: es la cuota de ESTA entidad —se llega acá por `t["name"] ==
            # bank.name`— y viaja con `rank` y `n_entities`, que declaran contra qué.
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

    # La propiedad estatal es un dato de configuración DECLARADO por SDQ (set de casa,
    # por nombre del catálogo SIB), no un flag publicado por el supervisor — se rotula.
    _decl = " (propiedad estatal: dato de configuración declarado por SDQ, no un indicador publicado por el SIB)"

    # Pata 1 — propensión (voluntad).
    if state_owned and is_systemic:
        prop = ("Propensión de soporte ALTA: propiedad estatal e importancia sistémica." + _decl)
    elif is_systemic:
        prop = ("Propensión de soporte por importancia sistémica (too-big-to-fail) sin "
                "propiedad estatal; dependería de la política de resolución, no de un mandato "
                "de propiedad.")
    else:  # state_owned, no sistémico
        prop = ("Propensión de soporte por propiedad estatal, con importancia sistémica no "
                "material a nivel de activos." + _decl)

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


def sovereign_at(period_end: date, db: Optional[Session] = None) -> Dict[str, Any]:
    """El ancla soberana de RD vista DESDE *period_end*: el rating vigente al corte, sin
    las fechas que todavía no habían ocurrido. Público porque la muestra curada del
    producto necesita el MISMO techo con la MISMA poda que un informe real."""
    return _sovereign_as_of(sovereign_anchor(db), period_end)


def support_overlay(db: Session, bank: Bank, standalone_score: float,
                    standalone_tier: str, period_end: date) -> Dict[str, Any]:
    """Overlay de soporte/sistémico/techo soberano para *bank*. NO muta el standalone;
    devuelve un bloque de contexto para narrativa + tabla del Deep Dive."""
    activos = _entity_share(db, bank, period_end, "activos")
    depositos = _entity_share(db, bank, period_end, "depositos")
    return compose_support_overlay(
        state_owned=bank.name in STATE_OWNED,
        activos_share=(activos or {}).get("share"),
        depositos_share=(depositos or {}).get("share"),
        rank_activos=(activos or {}).get("rank"),
        sovereign=sovereign_at(period_end, db),
        standalone_score=standalone_score,
        standalone_tier=standalone_tier,
    )


def compose_support_overlay(*, state_owned: bool, activos_share: Optional[float],
                            depositos_share: Optional[float], rank_activos: Optional[int],
                            sovereign: Dict[str, Any], standalone_score: float,
                            standalone_tier: str) -> Dict[str, Any]:
    """El overlay ARMADO desde sus primitivas, sin DB.

    Existe separado de :func:`support_overlay` porque la muestra curada del producto
    declara sus propias cuotas y su propio rank y debe pasar por ESTA misma composición:
    la etiqueta sistémica y la lectura del soporte son relaciones —se computan— y una
    muestra que las escriba a mano es una muestra que puede decir «Sistémica» al lado de
    un rank que la regla no llamaría así."""
    rank = rank_activos
    is_systemic = bool(rank and rank <= _SIFI_RANK)
    sys_label = systemic_label(rank)
    sov = sovereign
    return {
        "state_owned": state_owned,
        # Procedencia del flag: set de configuración declarado (regla de casa), no un
        # indicador publicado por el SIB. Rotula la rúbrica factual (brecha H2).
        "state_owned_provenance": {
            "source": "declarado",
            "note": ("Dato de configuración declarado por SDQ (set de casa, por nombre del "
                     "catálogo SIB); no es un flag publicado por el supervisor."),
        },
        "systemic": {
            # sujeto-ok: las dos nombran su población en la propia clave (activos del
            # sistema, depósitos del sistema) y son de la entidad del informe.
            "activos_share": activos_share,
            "depositos_share": depositos_share,  # sujeto-ok: ver arriba
            "rank_activos": rank,
            "is_systemic": is_systemic,
            "label": sys_label,
        },
        "sovereign": sov,
        "support_assessment": _support_assessment(state_owned, is_systemic, sov),
        "standalone": {"score": round(float(standalone_score), 2), "tier": standalone_tier},
    }
