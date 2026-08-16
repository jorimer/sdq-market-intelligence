"""Consulta del gasto del modelo: la tabla que la auditoría tuvo que reconstruir a mano.

La pregunta que esto responde en una llamada es «¿en qué se fue el dinero?», y la
respuesta útil se agrupa por **disparador**, no por módulo: el módulo dice qué producto
consumió, el disparador dice si lo pidió alguien o si una tarea agendada lo generó sola.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from shared.observability.models import LLMCall

#: Ventana por defecto. Treinta días cubre el ciclo de facturación y las cadencias
#: mensuales de las operaciones sin traer historia que nadie mira.
DEFAULT_DAYS = 30


def _desde(days: int) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)


def _fila(r) -> Dict[str, Any]:
    llamadas = int(r.llamadas or 0)
    hits = int(r.hits or 0)
    return {
        "clave": r.clave or "desconocido",
        "costo_usd": round(float(r.costo or 0.0), 4),
        "llamadas": llamadas,
        "hits_de_cache": hits,
        # Sin esto, un disparador con 900 llamadas y 890 HIT se lee igual que uno con 900
        # generaciones reales, y son el caso barato y el caso caro.
        "generaciones_reales": llamadas - hits,
    }


def _agrupado(db: Session, columna, days: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(
            columna.label("clave"),
            func.sum(LLMCall.cost_usd).label("costo"),
            func.count(LLMCall.id).label("llamadas"),
            func.sum(func.cast(LLMCall.cache_hit, Integer)).label("hits"),
        )
        .filter(LLMCall.created_at >= _desde(days))
        .group_by(columna)
        .all()
    )
    return sorted((_fila(r) for r in rows), key=lambda d: -d["costo_usd"])


def spend_summary(db: Session, days: int = DEFAULT_DAYS,
                  top: int = 15) -> Dict[str, Any]:
    """Gasto de los últimos ``days`` días, repartido por disparador, módulo y motivo.

    Devuelve también el total y el conteo, para que el panel no tenga que sumar la lista
    —una lista truncada a ``top`` sumaría mal y el total es justo la cifra que se mira
    primero—.
    """
    desde = _desde(days)
    total = (db.query(func.sum(LLMCall.cost_usd), func.count(LLMCall.id))
             .filter(LLMCall.created_at >= desde).one())
    return {
        "desde": desde.isoformat(),
        "dias": days,
        "costo_total_usd": round(float(total[0] or 0.0), 4),
        "llamadas_totales": int(total[1] or 0),
        "por_disparador": _agrupado(db, LLMCall.trigger_detail, days)[:top],
        "por_modulo": _agrupado(db, LLMCall.module, days)[:top],
        # Separa PRODUCIR de VERIFICAR. El juez numérico corre sobre toda sección de toda
        # generación: sumado al mismo total que la narrativa, su peso era invisible.
        "por_motivo": _agrupado(db, LLMCall.purpose, days),
    }


def spend_detail(db: Session, days: int = DEFAULT_DAYS,
                 trigger: Optional[str] = None,
                 limit: int = 200) -> List[Dict[str, Any]]:
    """Las llamadas de un disparador, de la más cara a la más barata."""
    q = db.query(LLMCall).filter(LLMCall.created_at >= _desde(days))
    if trigger:
        q = q.filter(LLMCall.trigger_detail == trigger)
    filas = q.order_by(LLMCall.cost_usd.desc()).limit(limit).all()
    return [
        {
            "cuando": c.created_at.isoformat() if c.created_at else None,
            "disparador": c.trigger_detail,
            "tipo": c.trigger_kind,
            "modulo": c.module,
            "plantilla": c.template,
            "motivo": c.purpose,
            "modelo": c.model,
            "costo_usd": round(float(c.cost_usd or 0.0), 4),
            "hit_de_cache": bool(c.cache_hit),
            "detalle": c.detail,
        }
        for c in filas
    ]
