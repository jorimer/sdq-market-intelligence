"""Agente de descubrimiento de fuentes (Increment 3 de la Capa 3).

Lee las brechas vivas del readiness (`build_audit`) y PROPONE solo fuentes/tipos de
información candidatos para cerrarlas, las crea en el tablero (`origin="agent"`) y las
evalúa (Increment 2). Cierra el lazo: el sistema sugiere y se evalúa sin disparo humano;
el dueño decide e integra.

Honestidad: las propuestas son CANDIDATAS a investigar (conocimiento del modelo, sin
verificación web). Sin ``ANTHROPIC_API_KEY`` el agente no propone (generar requiere el
modelo) y lo reporta — no inventa fuentes con heurística.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from shared.config.settings import settings
from shared.source_intel.models import (
    KINDS,
    KIND_SOURCE,
    ORIGIN_AGENT,
    STATUS_APPROVED,
    STATUS_EVALUATED,
    STATUS_EVALUATING,
    STATUS_INTEGRATING,
    STATUS_PROPOSED,
    SourceSuggestion,
)
from shared.source_intel.service import create_suggestion, evaluate

logger = logging.getLogger("sdq.source_intel.agent")

# Estados "abiertos": si ya hay una propuesta del agente en uno de estos para una
# brecha (axis, gate), no se vuelve a proponer (anti-flood). rejected/integrated/deferred
# = cerrados → el agente puede volver a proponer si la brecha sigue.
_OPEN = (STATUS_PROPOSED, STATUS_EVALUATING, STATUS_EVALUATED, STATUS_APPROVED, STATUS_INTEGRATING)

_SYSTEM = (
    "Eres un investigador de fuentes de datos para una plataforma de inteligencia de "
    "mercado de República Dominicana. Dada una brecha concreta de un eje, propones fuentes "
    "de datos o tipos de información REALES y CONCRETAS de RD (portales oficiales, boletines, "
    "encuestas, registros) que podrían cerrarla. Son candidatas a investigar, no verificadas: "
    "si no estás seguro de que existan, igual proponé la más plausible y sé específico. "
    "Respondes SOLO con un arreglo JSON, sin texto alrededor."
)


def _open_agent_keys(db: Session) -> Set[Tuple[Optional[str], Optional[str]]]:
    rows = (db.query(SourceSuggestion)
            .filter(SourceSuggestion.origin == ORIGIN_AGENT,
                    SourceSuggestion.status.in_(_OPEN)).all())
    return {(r.target_axis, r.target_gate) for r in rows}


def _propose_sources(axis: str, display: str, gap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Llama a Claude para proponer ≤2 fuentes candidatas para una brecha. JSON-only."""
    import anthropic

    user = (
        f"Eje: {display} ({axis}). Brecha: {gap.get('label')} al {gap.get('value', 0):.0%}. "
        f"Qué falta: {gap.get('falta')}. Pista de acción: {gap.get('accion')}.\n\n"
        "Propón hasta 2 fuentes/tipos de información candidatas de RD para cerrarla. "
        "Devuelve SOLO este arreglo JSON: "
        "[{\"kind\": \"source|info_type\", \"title\": \"nombre concreto de la fuente\", "
        "\"description\": \"qué aporta y por qué cierra la brecha\"}]."
    )
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=settings.ANTHROPIC_MODEL, max_tokens=900,
        system=_SYSTEM, messages=[{"role": "user", "content": user}])
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("["):]
    text = text[text.find("["): text.rfind("]") + 1]
    data = json.loads(text)
    return data if isinstance(data, list) else []


def run_research_agent(db: Session, set_phase=None, max_create: int = 12) -> Dict[str, Any]:
    """Recorre las brechas vivas y puebla el tablero con propuestas evaluadas.

    Idempotente por brecha: no re-propone para una (axis, gate) que ya tiene propuestas
    del agente en estado abierto. Acota el total creado por corrida (costo IA)."""
    set_phase = set_phase or (lambda _m: None)

    # Mantenimiento primero (no necesita IA): auto-difiere las sugerencias abiertas cuya
    # brecha ya se cerró por otra vía (p.ej. boletines INDOTEL tras ITU, o energy tras la
    # transición). El tablero se auto-limpia sin que el dueño rechace a mano las que envejecen.
    from shared.source_intel.service import reflag_covered_suggestions
    set_phase("revisando sugerencias ya cubiertas (auto-diferir)")
    reflagged = reflag_covered_suggestions(db)

    if not getattr(settings, "ANTHROPIC_API_KEY", None):
        return {"created": 0, "evaluated": 0, "reflagged_covered": len(reflagged),
                "reason": "sin IA (ANTHROPIC_API_KEY)"}

    from shared.products.audit import build_audit
    audit = build_audit(db)
    open_keys = _open_agent_keys(db)
    created: List[str] = []
    skipped_gaps = 0
    skipped_covered = 0
    hit_cap = False

    from shared.source_intel.coverage import coverage_status

    for sector in audit.get("sectors", []):
        if hit_cap:
            break
        if not sector.get("implemented"):
            continue
        # No proponer fuentes nuevas para un sector cuyo gate de datos (g1) ya está en
        # pleno: más datos no cierran su brecha (típicamente g5/backtest). Evita generar
        # redundantes de raíz — la misma clase de propuesta que el reflag difiere.
        if coverage_status(db, sector["sector_key"])["covered"]:
            skipped_covered += 1
            continue
        for gap in sector.get("gaps", []):
            if len(created) >= max_create:
                hit_cap = True
                break
            axis, gate = sector["sector_key"], gap.get("gate")
            if (axis, gate) in open_keys:
                skipped_gaps += 1
                continue
            set_phase(f"proponiendo fuentes para {axis} · {gap.get('label')}")
            try:
                proposals = _propose_sources(axis, sector.get("display_name", axis), gap)
            except Exception as e:  # noqa: BLE001 — una brecha que falla no aborta el resto
                logger.warning("propuesta para %s/%s falló: %s", axis, gate, e)
                continue
            open_keys.add((axis, gate))  # marcar aunque haya 0, para no reintentar este run
            for p in proposals[:2]:
                if len(created) >= max_create:
                    hit_cap = True
                    break
                kind = p.get("kind") if p.get("kind") in KINDS else KIND_SOURCE
                title = (p.get("title") or "").strip()
                if not title:
                    continue
                # El gate se ANCLA a la brecha que generó la propuesta — NO al que el modelo
                # elija (que deriva: macro/g1 → el modelo proponía g2/g3). Anclarlo mantiene
                # la idempotencia entre corridas (la sugerencia persiste con el gate real).
                s = create_suggestion(
                    db, kind=kind, title=title[:200],
                    description=(p.get("description") or "")[:1000], origin=ORIGIN_AGENT,
                    target_axis=axis, target_gate=gate)
                try:
                    evaluate(db, s["id"])  # que llegue evaluada
                except Exception as e:  # noqa: BLE001 — la eval no debe perder la sugerencia
                    logger.warning("auto-eval de %s falló: %s", s["id"], e)
                created.append(s["id"])

    if created:
        _notify_agent_proposals(db, len(created))
    # ``capped``: hubo más brechas que el tope por corrida → no se truncó en silencio
    # (correr de nuevo cubre el resto; el dedup salta lo ya propuesto).
    return {"created": len(created), "evaluated": len(created),
            "skipped_gaps": skipped_gaps, "skipped_covered": skipped_covered,
            "capped": hit_cap, "reflagged_covered": len(reflagged)}


def _notify_agent_proposals(db: Session, n: int) -> None:
    """Avisa a los admins que el agente propuso fuentes nuevas para revisar."""
    from shared.auth.models import User, UserRole
    from shared.notifications.service import notification_service

    admin_ids = [u.id for u in db.query(User).filter(
        User.is_active.is_(True),
        User.role.in_([UserRole.admin, UserRole.super_admin])).all()]
    title = "Inteligencia de Fuentes: nuevas propuestas"
    body = (f"El agente propuso {n} fuente(s) candidata(s) para cerrar brechas del readiness. "
            f"Revisar y decidir en el tablero (el sistema ya las evaluó).")
    for uid in admin_ids:
        notification_service.create(db, user_id=uid, type="info", title=title, body=body)
