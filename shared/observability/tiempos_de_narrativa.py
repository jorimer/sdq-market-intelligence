"""Cuánto tarda CADA sección de un informe, y cuánto tarda armarlo entero.

**El hueco que cierra.** El registro guardaba costo, tokens y caché — pero no cuánto tardó
NADA. Así, cuando un Deep Dive se pasaba del techo de tiempo, no había forma de saber si lo
consumió una sección lenta o la suma de todas: solo quedaban el promedio y la conjetura. Se
intentó diagnosticar así el 2026-08-26 y no se pudo; hubo que descartar el tope de gasto a
mano y aun así quedarse sin causa.

**Por qué la sección es la unidad.** Las secciones se generan en PARALELO (`asyncio.gather`
acotado por `NARRATIVE_MAX_CONCURRENCY`), así que el total NO es la suma: es aproximadamente
la más lenta. Y dentro de una sección el trabajo sí es serial —generar, juez, regenerar, juez,
regenerar, juez—, de modo que una sola sección con reparaciones puede consumir el presupuesto
entero ella sola. Sin el desglose por sección, ese caso se lee igual que «todo está lento».

**Lo que responde en una consulta:**

- qué plantilla tiene la mediana y el p90 más altos — la candidata a mirar;
- cuánto tardó ARMAR cada informe (`purpose="ensamblado"`), y cuáles se cortaron;
- si un informe se cortó, cuán lejos del techo estaba.

**Lo que NO responde**, y conviene saberlo: los HIT de caché se registran con 0 s y se
excluyen de los percentiles. Mezclarlos haría parecer que una generación real es mucho más
rápida de lo que es — que es justo el autoengaño que este módulo viene a evitar.
"""
from __future__ import annotations

import statistics as st
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.observability.models import LLMCall

#: Rango por defecto: los últimos siete días. Más corto que el de gasto a propósito — acá la
#: pregunta es «¿está lento AHORA?», no «¿en qué se fue el mes?».
DEFAULT_DAYS = 7

#: Tope de filas leídas. Es una consulta de consola, no un export.
MAX_FILAS = 4000


def _rango(desde: Optional[date], hasta: Optional[date]) -> Tuple[datetime, datetime]:
    fin_dia = hasta or datetime.now(timezone.utc).date()
    ini_dia = desde or (fin_dia - timedelta(days=DEFAULT_DAYS))
    return (datetime.combine(ini_dia, time.min),
            datetime.combine(fin_dia, time.max))


def _pct(valores: List[float], p: float) -> Optional[float]:
    if not valores:
        return None
    orden = sorted(valores)
    i = min(len(orden) - 1, int(p * len(orden)))
    return round(orden[i], 2)


def tiempos_de_narrativa(db: Session, desde: Optional[date] = None,
                        hasta: Optional[date] = None,
                        modulo: Optional[str] = None) -> Dict[str, Any]:
    """Tiempos por SECCIÓN y por INFORME, en el rango pedido."""
    ini, fin = _rango(desde, hasta)
    q = (db.query(LLMCall)
         .filter(LLMCall.created_at >= ini, LLMCall.created_at <= fin))
    if modulo:
        q = q.filter(LLMCall.module == modulo)
    filas = q.order_by(LLMCall.created_at.desc()).limit(MAX_FILAS).all()

    por_plantilla: Dict[str, List[float]] = {}
    ensamblados: List[Dict[str, Any]] = []
    sin_medicion = 0

    for f in filas:
        det: Dict[str, Any] = f.detail if isinstance(f.detail, dict) else {}
        seg = det.get("segundos")
        if f.purpose == "ensamblado":
            ensamblados.append({
                "producto": f.module, "nivel": f.template,
                "segundos": seg, "corto_por_tiempo": bool(det.get("corto_por_tiempo")),
                "periodo": det.get("periodo"), "scope": det.get("scope"),
                "cuando": f.created_at.isoformat() if f.created_at else None,
            })
            continue
        if seg is None:
            # Fila anterior a esta medición: se CUENTA y se declara. Un total bajo que en
            # realidad es «no lo estábamos midiendo» es el mismo engaño que `stale=null`.
            sin_medicion += 1
            continue
        if f.cache_hit or float(seg) <= 0:
            continue           # un HIT no tarda; incluirlo falsearía los percentiles
        por_plantilla.setdefault(str(f.template or "(sin plantilla)"), []).append(float(seg))

    secciones = sorted(
        ({"plantilla": t, "n": len(v), "mediana": round(st.median(v), 2),
          "p90": _pct(v, 0.9), "max": round(max(v), 2)}
         for t, v in por_plantilla.items()),
        key=lambda x: -float(x["p90"] or 0))

    cortados = [e for e in ensamblados if e["corto_por_tiempo"]]
    return {
        "desde": ini.date().isoformat(), "hasta": fin.date().isoformat(),
        "modulo": modulo,
        "por_seccion": secciones,
        "informes": {
            "n": len(ensamblados),
            "cortados_por_tiempo": len(cortados),
            "ultimos_cortados": cortados[:10],
            "mediana_segundos": (round(st.median([e["segundos"] for e in ensamblados
                                                  if e["segundos"] is not None]), 2)
                                 if any(e["segundos"] is not None for e in ensamblados)
                                 else None),
        },
        "llamadas_sin_medicion": sin_medicion,
        "truncado": len(filas) >= MAX_FILAS,
        "como_leerlo": (
            "Las secciones se generan en PARALELO, así que el tiempo de un informe es "
            "aproximadamente el de su sección más lenta, no la suma. Dentro de una sección el "
            "trabajo es serial (generar · juez · regenerar…), de modo que una sola con "
            "reparaciones puede consumir el presupuesto entero. Mirá el p90 por plantilla: la "
            "de arriba es la candidata. Los HIT de caché quedan fuera de los percentiles."),
    }
