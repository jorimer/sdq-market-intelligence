"""Registro y puntuación de pronósticos. La fuente de verdad del track record.

`ProjectionMeta` se construye LEYENDO de acá, nunca al revés: el ledger es lo que ocurrió, y
la meta es cómo se cuenta.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting.models import ForecastLog
from modules.macro_monitor.models.models import MacroSeries

#: Los dos únicos valores de `status`. El linaje NO es un estado — ver el docstring de
#: `models.py`.
ESTADOS = ("pending", "scored")

_NIVELES = (0.80, 0.90)


def backtest_id(model_id: str, target_series: str, h: Optional[int]) -> str:
    """La clave del CONJUNTO de pronósticos comparables de un modelo.

    *h* es el horizonte **RELATIVO** en trimestres (1 = el próximo), no el trimestre
    calendario. La diferencia decide si el producto funciona: con el calendario como clave,
    cada conjunto tiene UNA sola observación —el trimestre 2025-Q4 se pronostica una vez a
    cada distancia— y `n_oos` nunca alcanza el mínimo del gate. Medido: doce trimestres
    emitidos a un trimestre vista y puntuados dan `n_oos = 1` con el calendario y **12** con
    el relativo.

    La pregunta que el track record responde es «¿qué tan bien pronosticamos a UN trimestre
    vista?». Ésa se acumula a lo largo de los trimestres; «¿qué tan bien pronosticamos
    2025-Q4?» es una muestra de uno.

    Con *h* en ``None`` abarca TODOS los horizontes de ese modelo y serie, que mezcla
    pronósticos de dificultad distinta: sirve para un total, no para juzgar calibración.

    `h is not None`, no `if h`: el nowcast apunta al trimestre EN CURSO y su horizonte
    relativo es CERO, que es falsy. Con `if h` habría caído al comodín y su track record se
    habría mezclado con el de los horizontes largos.
    """
    return f"{model_id}|{target_series}|{('+' + str(h) + 'T') if h is not None else '*'}"


def _lado(intervals: Sequence, nivel: float):
    for fila in intervals or ():
        if abs(float(fila[0]) - nivel) < 1e-9:
            return float(fila[1]), float(fila[2])
    return None, None


def registrar(db: Session, *, model_id: str, target_series: str, horizon: str, as_of: str,
              point: float, intervals: List[List[float]], revision: int = 0,
              h: Optional[int] = None) -> ForecastLog:
    """Escribe un pronóstico. Falla si ya existe esa clave de cinco campos — que es lo que
    impide que un rerun duplique el historial."""
    lo80, hi80 = _lado(intervals, 0.80)
    lo90, hi90 = _lado(intervals, 0.90)
    fila = ForecastLog(
        model_id=model_id, target_series=target_series, horizon=horizon, as_of=as_of,
        revision=revision, point=float(point), intervals=intervals, h=h,
        lo_80=lo80, hi_80=hi80, lo_90=lo90, hi_90=hi90, status="pending",
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return fila


def marcar_superseded(db: Session, original: ForecastLog, correccion: ForecastLog) -> None:
    """Anota el linaje SIN tocar `status`: la revisión 0 se puntúa igual y sigue contando."""
    setattr(original, "superseded_by", str(correccion.id))
    db.commit()


def puntuar_pendientes(db: Session) -> int:
    """Puntúa todo pronóstico `pending` cuyo período ya tenga observado. Devuelve cuántos.

    Automática por diseño: un proceso de puntuación que requiere que alguien se acuerde deja
    de correr justo el trimestre en que el resultado es malo.
    """
    pendientes = db.query(ForecastLog).filter(ForecastLog.status == "pending").all()
    if not pendientes:
        return 0
    puntuados = 0
    for f in pendientes:
        fila = (db.query(MacroSeries)
                .filter_by(series_code=f.target_series, period=f.horizon)
                .first())
        # «El período existe con valor nulo» no es «llegó el dato».
        if fila is None or fila.value is None:
            continue
        obs = float(fila.value)
        punto = float(f.point)
        # Se escribe con `setattr` y se lee a variables locales a propósito: las columnas
        # declarativas están tipadas como `Column[...]`, así que asignarles el valor Python
        # que corresponde es lo que el ORM espera y lo que el verificador de tipos no puede
        # ver. Es el mismo patrón que el resto del repositorio.
        setattr(f, "realized", obs)
        setattr(f, "realized_period_end", str(f.horizon))
        setattr(f, "abs_error", abs(obs - punto))
        setattr(f, "sq_error", (obs - punto) ** 2)
        intervalos = list(f.intervals or [])
        for nivel, campo in ((0.80, "interval_hit_80"), (0.90, "interval_hit_90")):
            lo, hi = _lado(intervalos, nivel)
            setattr(f, campo, None if lo is None else bool(lo <= obs <= hi))
        setattr(f, "status", "scored")
        setattr(f, "scored_at", datetime.now(timezone.utc))
        puntuados += 1
    db.commit()
    return puntuados


def _del_conjunto(db: Session, bt_id: str) -> List[ForecastLog]:
    """Las filas que sostienen un `backtest_id`: **revisión 0 y `scored`**, sin mirar
    `superseded_by`. El track record mide el pronóstico como se PUBLICÓ, no como se corrigió
    después.

    El tercer campo del id es el horizonte RELATIVO (`+1T`). Una fila sin `h` —anterior a la
    migración que lo introdujo— queda FUERA del conjunto: darle un horizonte inventado sería
    fabricarle track record, que es lo único que este ledger existe para impedir.
    """
    model_id, target, rel = bt_id.split("|", 2)
    q = (db.query(ForecastLog)
         .filter(ForecastLog.model_id == model_id,
                 ForecastLog.target_series == target,
                 ForecastLog.revision == 0,
                 ForecastLog.status == "scored"))
    if rel != "*":
        try:
            paso = int(rel.strip("+T"))
        except ValueError:
            return []
        q = q.filter(ForecastLog.h == paso)
    else:
        q = q.filter(ForecastLog.h.isnot(None))
    return q.all()


def track_record(db: Session, bt_id: str) -> Dict[str, Any]:
    """Error y cobertura empírica de intervalos de un conjunto de pronósticos puntuados.

    La cobertura de intervalos se devuelve junto al error y no aparte: un intervalo del 80%
    que acierta el 45% de las veces se ve ahí y en ningún otro lado.
    """
    filas = _del_conjunto(db, bt_id)
    n = len(filas)
    if not n:
        return {"backtest_id": bt_id, "n_oos": 0, "rmse": None, "mae": None,
                "interval_coverage": (), "overlapping": None}
    rmse = math.sqrt(sum(float(f.sq_error or 0.0) for f in filas) / n)
    mae = sum(float(f.abs_error or 0.0) for f in filas) / n
    cobertura = []
    for nivel, campo in ((0.80, "interval_hit_80"), (0.90, "interval_hit_90")):
        hits = [getattr(f, campo) for f in filas if getattr(f, campo) is not None]
        if hits:
            cobertura.append((nivel, sum(1 for h in hits if h) / len(hits), len(hits)))
    return {"backtest_id": bt_id, "n_oos": n, "rmse": round(rmse, 6),
            "mae": round(mae, 6), "interval_coverage": tuple(cobertura),
            "overlapping": _se_solapan(filas)}


def _se_solapan(filas: Sequence[ForecastLog]) -> bool:
    """¿Las ventanas de evaluación se solapan? Es ``True`` cuando dos pronósticos del
    conjunto comparten horizonte con cortes distintos, o cuando el paso entre cortes es menor
    que el salto entre horizontes. No se corrige el conteo con una fórmula inventada: se
    DECLARA, que es lo que la casa hace con toda limitación."""
    horizontes = [f.horizon for f in filas]
    return len(set(horizontes)) < len(horizontes)
