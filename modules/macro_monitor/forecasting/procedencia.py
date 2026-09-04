"""Del ledger a `ProjectionMeta`. En esa dirección y en ninguna otra.

El `[Lock]` de §3.6.2 del spec dice: **el ledger es la fuente de verdad y la meta se
construye leyendo de él, nunca al revés**. La razón es concreta. Una meta armada por el
modelo y guardada al lado del ledger sería una segunda copia del pronóstico, y dos copias del
mismo hecho se desincronizan: bastaría con que una corrección entrara al ledger y no a la
meta para que el informe cite un pronóstico que ya no es el vigente, con el track record del
que sí lo es. Acá la meta no se guarda en ningún lado — se DERIVA en cada lectura.

**Un solo lugar computa el track record.** `n_oos`, el error, la cobertura empírica de los
intervalos y el solapamiento salen de `ledger.track_record()`, que ya los devuelve juntos.
Recalcularlos acá sería la copia a mano de un serializador, que en este repo ya borró la tasa
de 38 entidades por tener el productor dos bocas.

**Una proyección sin filas puntuadas NO se filtra acá.** Sale con `n_oos = 0` y el gate de
admisión la rechaza con su motivo, que es el que termina en la nota de la brecha. Silenciarla
en este módulo la haría desaparecer sin que nadie sepa por qué: «no hay proyección» y «hay
una y no tiene backtest» son cosas distintas, y la segunda es la interesante.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import ledger as led
from modules.macro_monitor.forecasting.models import ForecastLog
from shared.data.periodos import fin_del_periodo
from shared.registry.signals import ProjectionMeta

#: El error que se declara. Nombrado, nunca inferido: `ProjectionMeta.error_metric` existe
#: porque un RMSE y un MAE no se comparan entre sí y confundirlos cambia el veredicto.
METRICA = "rmse"


def _intervalos(crudo) -> Tuple[Tuple[float, float, float], ...]:
    """El JSON del ledger a la tupla de la meta. El JSON es el que vale, no los
    denormalizados `lo_80/hi_80`: si difieren, los denormalizados son la copia."""
    if not crudo:
        return ()
    salida = []
    for tramo in crudo:
        if tramo is None or len(tramo) < 3:
            continue
        salida.append((float(tramo[0]), float(tramo[1]), float(tramo[2])))
    return tuple(salida)


def meta_de(db: Session, fila: ForecastLog) -> ProjectionMeta:
    """El `ProjectionMeta` de una fila del ledger, con su track record leído del ledger."""
    bt = led.backtest_id(str(fila.model_id), str(fila.target_series), str(fila.horizon))
    tr = led.track_record(db, bt)
    rmse = tr.get("rmse")
    return ProjectionMeta(
        model_id=str(fila.model_id),
        target_series=str(fila.target_series),
        horizon=str(fila.horizon),
        as_of=str(fila.as_of),
        revision=int(fila.revision or 0),
        point=float(fila.point),
        intervals=_intervalos(fila.intervals),
        backtest_id=bt,
        # Sin filas puntuadas no hay error que declarar. Va NaN y no 0.0 a propósito: un 0,0
        # se lee como «no se equivoca nunca», que es la mentira más cara que este campo puede
        # decir. El gate rechaza antes por `n_oos`, así que el motivo que ve el lector es el
        # informativo.
        oos_error=float(rmse) if rmse is not None else float("nan"),
        error_metric=METRICA,
        n_oos=int(tr.get("n_oos") or 0),
        n_oos_overlapping=tr.get("overlapping"),
        interval_coverage=tuple(tr.get("interval_coverage") or ()),
    )


def _clave(f: ForecastLog) -> Tuple[str, str, str]:
    return (str(f.model_id), str(f.target_series), str(f.horizon))


def vigentes(db: Session, *, hoy: Optional[date] = None) -> List[ForecastLog]:
    """Las filas del ledger que representan el pronóstico VIGENTE de cada serie y horizonte.

    Vigente = el corte `as_of` más reciente y, dentro de él, la revisión más alta. Es la
    lectura que el `[Lock]` de la revisión hace posible: las correcciones conviven con el
    original en la tabla, y quién manda hoy se resuelve al leer en vez de pisando filas.

    **Se excluye lo ya vencido**: un «pronóstico» de un trimestre que ya cerró no es una
    proyección, es historia, y publicarlo como proyección confunde las dos cosas. El gate lo
    rechazaría igual por `as_of` posterior al cierre, pero dejarlo llegar hasta ahí
    convertiría cada trimestre viejo en una brecha declarada, que es ruido.
    """
    corte = hoy or date.today()
    mejor: Dict[Tuple[str, str, str], ForecastLog] = {}
    for f in db.query(ForecastLog).all():
        cierre = fin_del_periodo(str(f.horizon))
        if cierre is not None and cierre < corte:
            continue
        k = _clave(f)
        previo = mejor.get(k)
        if previo is None or (str(f.as_of), int(f.revision or 0)) > (
                str(previo.as_of), int(previo.revision or 0)):
            mejor[k] = f
    return sorted(mejor.values(), key=lambda f: (str(f.target_series), str(f.horizon)))


def proyeccion_por_serie(db: Session, *, hoy: Optional[date] = None
                         ) -> Dict[str, ProjectionMeta]:
    """Una proyección por serie: la del horizonte MÁS CERCANO que sigue abierto.

    Una sola y no la lista entera porque una `VariableSignal` lleva un valor: si se emitiera
    la trayectoria completa, el consumidor tendría que elegir cuál es «la» proyección de la
    variable y cada uno elegiría distinto. La trayectoria se publica en la sección de
    reporte, que es donde tiene sentido verla completa.
    """
    salida: Dict[str, ProjectionMeta] = {}
    orden: Dict[str, Optional[date]] = {}
    for f in vigentes(db, hoy=hoy):
        serie = str(f.target_series)
        cierre = fin_del_periodo(str(f.horizon))
        actual = orden.get(serie)
        if serie in salida and not (
                cierre is not None and (actual is None or cierre < actual)):
            continue
        salida[serie] = meta_de(db, f)
        orden[serie] = cierre
    return salida


def es_publicable(meta: ProjectionMeta) -> Tuple[bool, str]:
    """Atajo de lectura sobre el gate compartido, para no repetir el desempaquetado.

    Existe por una razón sola: `projection_is_admissible` devuelve una TUPLA, y una tupla no
    vacía siempre es truthy. Quien la use como condición directa ancla toda proyección, con
    backtest o sin él.
    """
    from shared.registry.projection import projection_is_admissible

    ok, motivo = projection_is_admissible(meta)
    return ok, motivo
