"""Ledger de activos — hace VISIBLE la auto-extensión para quien automatiza.

El manifiesto ya descubre solo los activos nuevos (F1). Pero un cliente que corre sin
supervisión necesita algo más: saber **qué cambió desde su última corrida**. Este módulo
registra, en el mismo recorrido que ya construye el manifiesto, cuándo se vio cada activo
por primera y última vez, y marca como retirado al que dejó de aparecer.

Dos decisiones de diseño:

- **La baja no borra.** Un activo que desaparece se marca ``retired_at``; para un cliente
  la baja es tan informativa como el alta (una serie que dejó de publicarse le rompe un
  modelo en silencio si no se entera).
- **El registro es un efecto de lectura, no una tarea agendada.** Se actualiza al servir
  ``/catalog``, así que no puede desincronizarse del inventario real por un cron caído.
  El costo es un upsert por activo por consulta de catálogo; si se volviera visible, la
  salida natural es mover esto a un job — nunca dejar de registrar en silencio.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from shared.data_api.manifest import ExposedAsset
from shared.data_api.models import ApiAssetLedger

logger = logging.getLogger("sdq.data_api")


def record_manifest(db: Session, assets: Iterable[ExposedAsset]) -> Dict[str, int]:
    """Registra el inventario visto. Devuelve ``{new, updated, retired}``.

    Defensivo: cualquier fallo se traga (con log). Llevar la bitácora nunca puede tumbar
    la respuesta del catálogo — el dato del cliente vale más que la contabilidad.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stats = {"new": 0, "updated": 0, "retired": 0}
    try:
        seen = {a.key: a for a in assets}
        existing = {
            r.asset_key: r
            for r in db.query(ApiAssetLedger).all()
        }

        for key, asset in seen.items():
            quarantine = ", ".join(asset.quarantine) or None
            row = existing.get(key)
            if row is None:
                db.add(ApiAssetLedger(
                    asset_key=key, kind=asset.kind, sector_key=asset.sector_key,
                    code=asset.code, label=asset.label, first_seen_at=now,
                    last_seen_at=now, retired_at=None, last_exposed=asset.exposed,
                    last_quarantine=quarantine,
                ))
                stats["new"] += 1
            else:
                row.last_seen_at = now
                row.label = asset.label
                row.last_exposed = asset.exposed
                row.last_quarantine = quarantine
                if row.retired_at is not None:
                    # Reapareció: se des-retira, conservando su first_seen original.
                    row.retired_at = None
                stats["updated"] += 1

        for key, row in existing.items():
            if key not in seen and row.retired_at is None:
                row.retired_at = now
                stats["retired"] += 1

        db.commit()
    except Exception as exc:  # noqa: BLE001 — la contabilidad nunca rompe la entrega
        logger.warning("data_api: no se pudo actualizar el ledger de activos: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
    return stats


def _parse_since(since: str) -> Optional[datetime]:
    """Acepta fecha (``2026-07-01``) o instante ISO. ``None`` si no se puede leer."""
    text = (since or "").strip().replace("Z", "+00:00")
    for parser in (datetime.fromisoformat,):
        try:
            dt = parser(text)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except (ValueError, TypeError):
            continue
    return None


def changes_since(db: Session, since: str, *,
                  visible_keys: Optional[set] = None) -> Dict[str, Any]:
    """Altas y bajas desde ``since``. ``visible_keys`` acota a lo que la llave puede ver.

    Lanza ``ValueError`` si ``since`` no es una fecha legible — devolver "sin cambios"
    ante una fecha mal escrita sería la peor respuesta posible para un cliente que
    automatiza: silencio indistinguible de "no pasó nada".
    """
    cutoff = _parse_since(since)
    if cutoff is None:
        raise ValueError(
            f"Fecha 'since' inválida: '{since}'. Use ISO (2026-07-01 o "
            f"2026-07-01T12:00:00Z)."
        )

    rows = db.query(ApiAssetLedger).all()
    if visible_keys is not None:
        rows = [r for r in rows if r.asset_key in visible_keys]

    added: List[Dict[str, Any]] = []
    retired: List[Dict[str, Any]] = []
    for r in rows:
        if r.first_seen_at and r.first_seen_at >= cutoff:
            added.append({
                "asset_key": r.asset_key, "kind": r.kind, "sector_key": r.sector_key,
                "code": r.code, "label": r.label,
                "first_seen_at": r.first_seen_at.isoformat(),
                "exposed": bool(r.last_exposed),
                "quarantine": r.last_quarantine,
            })
        if r.retired_at and r.retired_at >= cutoff:
            retired.append({
                "asset_key": r.asset_key, "kind": r.kind, "sector_key": r.sector_key,
                "code": r.code, "label": r.label,
                "retired_at": r.retired_at.isoformat(),
                "last_quarantine": r.last_quarantine,
            })

    added.sort(key=lambda d: d["first_seen_at"], reverse=True)
    retired.sort(key=lambda d: d["retired_at"], reverse=True)
    return {"since": cutoff.isoformat(), "added": added, "retired": retired}
