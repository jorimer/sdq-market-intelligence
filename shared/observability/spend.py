"""Consulta del gasto del modelo: la tabla que la auditoría tuvo que reconstruir a mano.

La pregunta que esto responde en una llamada es «¿en qué se fue el dinero?», y la
respuesta útil se agrupa por **disparador**, no por módulo: el módulo dice qué producto
consumió, el disparador dice si lo pidió alguien o si una tarea agendada lo generó sola.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from shared.observability import etiquetas
from shared.observability.models import LLMCall

#: Rango por defecto cuando no se pide uno: los últimos treinta días.
DEFAULT_DAYS = 30


def _rango(desde: Optional[date], hasta: Optional[date]) -> Tuple[datetime, datetime]:
    """Convierte un rango de FECHAS en el intervalo de instantes que se consulta.

    ``hasta`` es **inclusivo del día completo**: quien pide «hasta el 16» quiere lo del 16,
    no lo anterior a su medianoche. Tomar la fecha tal cual dejaría fuera todo el último día
    —el que más se mira— y el error sería invisible porque el total seguiría siendo un
    número plausible.
    """
    fin_dia = hasta or datetime.now(timezone.utc).date()
    ini_dia = desde or (fin_dia - timedelta(days=DEFAULT_DAYS))
    return (datetime.combine(ini_dia, time.min),
            datetime.combine(fin_dia, time.max))


def _fila(r, etiquetar) -> Dict[str, Any]:
    llamadas = int(r.llamadas or 0)
    hits = int(r.hits or 0)
    clave = r.clave or "desconocido"
    return {
        "clave": clave,
        # El nombre que ve quien lee. La clave técnica se conserva al lado porque, cuando
        # algo hay que depurar, la ruta es lo que se necesita: una etiqueta que la
        # reemplace convierte una investigación de dos minutos en una de veinte.
        "etiqueta": etiquetar(clave),
        "costo_usd": round(float(r.costo or 0.0), 4),
        "llamadas": llamadas,
        "hits_de_cache": hits,
        # Sin esto, un disparador con 900 llamadas y 890 HIT se lee igual que uno con 900
        # generaciones reales, y son el caso barato y el caso caro.
        "generaciones_reales": llamadas - hits,
    }


def _agrupado(db: Session, columna, ini: datetime, fin: datetime,
              etiquetar) -> List[Dict[str, Any]]:
    rows = (
        db.query(
            columna.label("clave"),
            func.sum(LLMCall.cost_usd).label("costo"),
            func.count(LLMCall.id).label("llamadas"),
            func.sum(func.cast(LLMCall.cache_hit, Integer)).label("hits"),
        )
        .filter(LLMCall.created_at >= ini, LLMCall.created_at <= fin)
        .group_by(columna)
        .all()
    )
    return sorted((_fila(r, etiquetar) for r in rows), key=lambda d: -d["costo_usd"])


def spend_summary(db: Session, desde: Optional[date] = None,
                  hasta: Optional[date] = None, top: int = 15) -> Dict[str, Any]:
    """Gasto de un rango de FECHAS, repartido por disparador, módulo y motivo.

    El rango es explícito y no una ventana de N días porque la pregunta que motiva esta
    consulta es «¿cuadra con lo que me facturaron?», y la facturación va por ciclo
    calendario. Una ventana móvil obliga a hacer la cuenta de cabeza cada vez.

    Devuelve también el total y el conteo, para que el panel no tenga que sumar la lista
    —una lista truncada a ``top`` sumaría mal y el total es justo la cifra que se mira
    primero—.
    """
    ini, fin = _rango(desde, hasta)
    total = (db.query(func.sum(LLMCall.cost_usd), func.count(LLMCall.id))
             .filter(LLMCall.created_at >= ini, LLMCall.created_at <= fin).one())
    return {
        "desde": ini.date().isoformat(),
        "hasta": fin.date().isoformat(),
        "costo_total_usd": round(float(total[0] or 0.0), 4),
        "llamadas_totales": int(total[1] or 0),
        "por_disparador": _agrupado(db, LLMCall.trigger_detail, ini, fin,
                                    etiquetas.etiqueta_disparador)[:top],
        "por_modulo": _agrupado(db, LLMCall.module, ini, fin,
                                etiquetas.etiqueta_modulo)[:top],
        # Separa PRODUCIR de VERIFICAR. El juez numérico corre sobre toda sección de toda
        # generación: sumado al mismo total que la narrativa, su peso era invisible.
        "por_motivo": _agrupado(db, LLMCall.purpose, ini, fin,
                                etiquetas.etiqueta_motivo),
    }


def spend_detail(db: Session, desde: Optional[date] = None,
                 hasta: Optional[date] = None,
                 trigger: Optional[str] = None,
                 limit: int = 200) -> List[Dict[str, Any]]:
    """Las llamadas de un disparador en el rango, de la más cara a la más barata."""
    ini, fin = _rango(desde, hasta)
    q = db.query(LLMCall).filter(LLMCall.created_at >= ini, LLMCall.created_at <= fin)
    if trigger:
        q = q.filter(LLMCall.trigger_detail == trigger)
    filas = q.order_by(LLMCall.cost_usd.desc()).limit(limit).all()
    return [
        {
            "cuando": c.created_at.isoformat() if c.created_at else None,
            "disparador": c.trigger_detail,
            "etiqueta": etiquetas.etiqueta_disparador(str(c.trigger_detail)),
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
