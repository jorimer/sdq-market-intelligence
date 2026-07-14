"""Sync del padrón de contribuyentes DGII → tabla ``dgii_contribuyente_subclase``.

Cadencia **manual** (§B.3): DGII no declara periodicidad; no se promete frescura automática
hasta confirmarla con una segunda descarga. Cada corrida hace upsert por ``(corte, subclase)``:
re-correr el mismo corte no duplica; un corte nuevo suma historia.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from shared.data.dgii_rnc_client import DGIIRncClient, DGIIRncError, SubclaseContrib
from shared.data.lineage import Lineage
from shared.reference.models import DgiiContribuyenteSubclase

logger = logging.getLogger("sdq.reference.dgii_sync")


def _upsert(db: Session, corte, rows, lineage: Lineage) -> int:
    existing: Dict[str, DgiiContribuyenteSubclase] = {
        str(r.subclase): r for r in db.query(DgiiContribuyenteSubclase)
        .filter(DgiiContribuyenteSubclase.corte == corte).all()
    }
    touched = 0
    for row in rows:  # type: SubclaseContrib
        vals = {"descripcion": row.descripcion, "activos": row.activos,
                "activos_fisica": row.activos_fisica, "activos_juridica": row.activos_juridica,
                "source": lineage.source, "source_url": lineage.url, "license": lineage.license}
        obj = existing.get(row.subclase)
        if obj is None:
            db.add(DgiiContribuyenteSubclase(corte=corte, subclase=row.subclase, **vals))
        else:
            for k, v in vals.items():
                setattr(obj, k, v)
        touched += 1
    db.commit()
    return touched


def dgii_contribuyentes_sync(
    db: Session, client: Optional[DGIIRncClient] = None
) -> Dict[str, Any]:
    """Descarga el padrón, agrega por subclase y hace upsert. *client* permite inyectar
    un cliente fixture en tests; live por defecto."""
    client = client or DGIIRncClient(mode="live")
    corte, rows, lineage = client.fetch_aggregates()
    if corte is None:
        raise DGIIRncError("no se pudo determinar la fecha de corte del padrón DGII")
    touched = _upsert(db, corte, rows, lineage)
    logger.info("DGII contribuyentes sync: corte=%s, %d subclases", corte, touched)
    return {"corte": corte.isoformat(), "subclases": len(rows), "touched": touched}
