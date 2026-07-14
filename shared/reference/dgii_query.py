"""Lectura del padrón DGII persistido (solo consulta — sin escritura ni red).

La usa el motor de research (``shared/knowledge/ingest.dgii_passages``) para armar los
pasajes del corte más reciente, y cualquier consumidor que necesite el dato estructurado.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from shared.reference.models import DgiiContribuyenteSubclase


def latest_corte(db: Session) -> Optional[date]:
    """La fecha de corte más reciente cargada, o ``None`` si la tabla está vacía."""
    row = (db.query(DgiiContribuyenteSubclase.corte)
           .order_by(DgiiContribuyenteSubclase.corte.desc())
           .first())
    return row[0] if row else None


def latest_contribuyentes(
    db: Session,
) -> Tuple[Optional[date], Dict[str, DgiiContribuyenteSubclase]]:
    """(corte más reciente, ``{subclase: fila}``). ``({}, None)`` si no hay datos."""
    corte = latest_corte(db)
    if corte is None:
        return None, {}
    rows = (db.query(DgiiContribuyenteSubclase)
            .filter(DgiiContribuyenteSubclase.corte == corte).all())
    return corte, {str(r.subclase): r for r in rows}
