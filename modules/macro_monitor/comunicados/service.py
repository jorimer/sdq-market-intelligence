"""Orquestación + queries de los Comunicados de Política Monetaria del BCRD.

Pipeline por comunicado: listar (descubrir ids, newest-first) → detalle (cuerpo) →
decisión DETERMINISTA (:func:`source.parse_decision`) + digest IA del racional →
upsert :class:`ComunicadoTPM`. Idempotente por ``article_id``.

El digest reusa el motor de publicaciones (``shared.publications.digest.build_digest``):
la IA interpreta el racional; el número de la TPM y el sentido de la decisión salen del
parser, nunca del modelo.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.macro_monitor.comunicados import source as src
from modules.macro_monitor.comunicados.models import ComunicadoTPM
from shared.publications import digest as digest_mod

logger = logging.getLogger("sdq.comunicados.service")

_REPORT_NAME = "Comunicado de Política Monetaria — BCRD"
_SECTORS = ("macro", "banca")

# Seams inyectables para que los tests no toquen red ni Anthropic.
ListFn = Callable[..., List[src.ComunicadoRef]]
DetailFn = Callable[[int], src.ComunicadoDetail]
DigestFn = Callable[[str, str, str, tuple], Dict[str, Any]]


def _default_digest(text: str, name: str, period: str, sectors: tuple) -> Dict[str, Any]:  # pragma: no cover - AI
    return digest_mod.build_digest(text, name, period, sectors)


def ingest_comunicados(
    db: Session,
    *,
    limit: int = 12,
    force: bool = False,
    list_fn: ListFn = src.list_comunicados,
    detail_fn: DetailFn = src.fetch_detail,
    make_digest: Optional[DigestFn] = None,
    set_phase: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Descubre los *limit* comunicados más recientes e ingiere los que falten.

    Idempotente por ``article_id``: omite los ya ``ok`` salvo *force*. Cada fallo se
    registra en su fila (``status='error'``) sin abortar el resto del lote.
    """
    make_digest = make_digest or _default_digest
    refs = list_fn(limit=limit)
    results: List[Dict[str, Any]] = []
    ingested = 0

    for i, ref in enumerate(refs, 1):
        if set_phase:
            set_phase(f"comunicado {i}/{len(refs)} ({ref.date_iso or ref.article_id})")
        existing = db.query(ComunicadoTPM).filter_by(article_id=ref.article_id).first()
        if existing and existing.status == "ok" and not force:
            results.append({"article_id": ref.article_id, "status": "skip", "date": ref.date_iso})
            continue

        row = existing or ComunicadoTPM(article_id=ref.article_id)
        row.string_id = ref.string_id
        row.title = ref.title
        row.decision_date = ref.date_iso
        row.source_url = ref.url
        row.status = "pending"
        row.error = None
        if existing is None:
            db.add(row)

        try:
            detail = detail_fn(ref.article_id)
            body = detail.body_text or ref.preview
            decision = src.parse_decision(ref.title, body)
            row.action = decision["action"]
            row.tpm_level = decision["tpm_level"]
            row.bps_change = decision["bps_change"]
            row.body_text = body[:20_000]
            row.digest = make_digest(body, _REPORT_NAME, ref.date_iso or ref.string_id, _SECTORS)
            row.status = "ok"
            ingested += 1
        except Exception as e:  # noqa: BLE001 — registra el fallo, no tumba el lote
            logger.warning("[comunicados] fallo al ingerir %s: %s", ref.article_id, e)
            row.status = "error"
            row.error = str(e)[:500]

        db.commit()
        db.refresh(row)
        results.append({"article_id": ref.article_id, "status": row.status,
                        "date": row.decision_date, "action": row.action,
                        "tpm_level": row.tpm_level})

    return {"discovered": len(refs), "ingested_ok": ingested, "results": results}


# ── Queries ───────────────────────────────────────────────────────
def list_comunicados(db: Session, limit: int = 24) -> List[ComunicadoTPM]:
    """Comunicados ingeridos, del más reciente al más antiguo."""
    return (
        db.query(ComunicadoTPM)
        .order_by(ComunicadoTPM.decision_date.desc().nullslast(),
                  ComunicadoTPM.article_id.desc())
        .limit(limit)
        .all()
    )


def latest_comunicado(db: Session) -> Optional[ComunicadoTPM]:
    """El comunicado más reciente ingerido con éxito, o None."""
    return (
        db.query(ComunicadoTPM)
        .filter(ComunicadoTPM.status == "ok")
        .order_by(ComunicadoTPM.decision_date.desc().nullslast(),
                  ComunicadoTPM.article_id.desc())
        .first()
    )


def comunicado_prompt_context(db: Session, max_findings: int = 3) -> Optional[Dict[str, Any]]:
    """Bloque compacto de la ÚLTIMA decisión de TPM para inyectar en el cerebro macro.

    Trae la decisión estructurada (sentido + nivel) más el digest recortado. None si no
    hay ninguna decisión ingerida con éxito o sin digest útil.
    """
    row = latest_comunicado(db)
    if row is None:
        return None
    dg = row.digest or {}
    _label = {"hold": "mantuvo", "cut": "redujo", "hike": "incrementó"}
    return {
        "fecha": row.decision_date,
        "decision": _label.get(row.action or "", row.action),
        "tpm_nivel": row.tpm_level,
        "titular": row.title,
        "resumen": dg.get("resumen", ""),
        "hallazgos": (dg.get("hallazgos") or [])[:max_findings],
        "riesgos": (dg.get("riesgos") or [])[:max_findings],
        "fuente": row.source_url,
    }
