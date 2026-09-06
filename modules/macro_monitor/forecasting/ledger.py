"""Registro y puntuación de pronósticos. La fuente de verdad del track record.

`ProjectionMeta` se construye LEYENDO de acá, nunca al revés: el ledger es lo que ocurrió, y
la meta es cómo se cuenta.

**Una fila declara contra QUÉ se la va a puntuar, y no se supone.** Son dos declaraciones y
hacen falta las dos: `target_series` es un `series_code` OBSERVABLE —el que existe en
`mm_series`— y `measure` dice en qué medida está `point`. Faltando cualquiera de las dos, la
puntuación adivina, y las dos veces que adivinó se equivocó:

* el BVAR registraba ``target_series="pib_real"``, que es el nombre de su variable dentro del
  bloque y no una serie: la fila quedaba `pending` **para siempre**, y la sección de
  desempeño lo publicaba como «ninguna alcanzó su período de cierre» — que se lee como que
  los trimestres no cerraron cuando la verdad es que no PUEDEN cerrar;
* el punto de los dos motores es un Δlog en % (~0,4) y se comparaba contra el índice de
  volumen del PIB (~133), o sea una tasa contra un nivel: `abs_error ≈ 132,75`, publicado
  como RMSE.

Lo vetado se LISTA (`no_puntuables`): un `pending` que no puede cerrar nunca y un `pending`
que espera el trimestre son cosas distintas, y confundirlos es mentir con el instrumento.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting.models import ForecastLog
from modules.macro_monitor.models.models import MacroSeries
from shared.data import medida_de_pronostico as med
from shared.registry.signals import backtest_id as _clave_de_conjunto

#: Los dos únicos valores de `status`. El linaje NO es un estado — ver el docstring de
#: `models.py`.
ESTADOS = ("pending", "scored")

_NIVELES = (0.80, 0.90)


def backtest_id(model_id: str, target_series: str, h: Optional[int],
                measure: str) -> str:
    """La clave del CONJUNTO de pronósticos comparables. Ver `signals.backtest_id`, que es
    la ÚNICA implementación: acá había una copia, y el motor del BVAR tenía otra."""
    return _clave_de_conjunto(model_id, target_series, measure, h)


def _lado(intervals: Sequence, nivel: float):
    for fila in intervals or ():
        if abs(float(fila[0]) - nivel) < 1e-9:
            return float(fila[1]), float(fila[2])
    return None, None


def registrar(db: Session, *, model_id: str, target_series: str, horizon: str, as_of: str,
              point: float, intervals: List[List[float]], measure: str, revision: int = 0,
              h: Optional[int] = None) -> ForecastLog:
    """Escribe un pronóstico. Falla si ya existe esa clave de cinco campos — que es lo que
    impide que un rerun duplique el historial.

    *measure* no tiene valor por defecto, y ésa es la mitad del arreglo: la puerta del ledger
    es donde la declaración se puede EXIGIR. Un default —cualquiera— reintroduce la
    suposición, porque el que se equivoca nunca es el que la escribe a mano.
    """
    med.validar(measure)
    if not str(target_series).strip():
        raise ValueError(
            "un pronóstico sin serie objetivo no se puede puntuar contra nada. "
            "`target_series` es el `series_code` OBSERVABLE, no el nombre que el modelo le "
            "da a su variable.")
    lo80, hi80 = _lado(intervals, 0.80)
    lo90, hi90 = _lado(intervals, 0.90)
    fila = ForecastLog(
        model_id=model_id, target_series=target_series, horizon=horizon, as_of=as_of,
        revision=revision, point=float(point), intervals=intervals, h=h,
        measure=str(measure),
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
        # Sin medida declarada NO se puntúa. Suponerle «nivel» es justo el defecto: el punto
        # de los dos motores es una tasa, y contra el índice da un error del tamaño del
        # índice. `no_puntuables` las lista para que la ausencia se vea.
        if str(f.measure or "") not in med.MEDIDAS:
            continue
        medida = str(f.measure)
        observado = _observado(db, str(f.target_series),
                               med.periodos_necesarios(medida, str(f.horizon)))
        # «El período existe con valor nulo» no es «llegó el dato»; y a una TASA le falta el
        # dato mientras no esté el período anterior, aunque el suyo ya haya llegado.
        realizacion = med.realizar(medida, str(f.horizon), observado)
        if realizacion.valor is None:
            continue
        obs = realizacion.valor
        punto = float(f.point)
        # Se escribe con `setattr` y se lee a variables locales a propósito: las columnas
        # declarativas están tipadas como `Column[...]`, así que asignarles el valor Python
        # que corresponde es lo que el ORM espera y lo que el verificador de tipos no puede
        # ver. Es el mismo patrón que el resto del repositorio.
        # `realized` va EN LA MEDIDA DEL PUNTO, que es lo que hace auditable el error: si
        # guardara el nivel mientras el punto es una tasa, la fila mentiría por sí sola.
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


def _observado(db: Session, series_code: str,
               periodos: Sequence[str]) -> Dict[str, Optional[float]]:
    """Los valores de esa serie en esos períodos, en UNA consulta.

    Una tasa necesita dos períodos y una vuelta por período los pediría de a uno; peor, el
    que falta se descubriría recién al calcular. `medida.periodos_necesarios` los declara
    antes y esto los trae juntos.
    """
    filas = (db.query(MacroSeries)
             .filter(MacroSeries.series_code == series_code,
                     MacroSeries.period.in_(list(periodos)))
             .all())
    return {str(r.period): (None if r.value is None else float(r.value)) for r in filas}


#: Motivos por los que un `pending` no puede cerrar NUNCA. No son «todavía no».
SIN_MEDIDA = "medida_no_declarada"
SERIE_DESCONOCIDA = "serie_desconocida"

_EXPLICACION = {
    SIN_MEDIDA: ("la fila no declara en qué medida está su punto, así que no hay contra qué "
                 "compararlo"),
    SERIE_DESCONOCIDA: ("la serie objetivo no tiene una sola observación en el registro: no "
                        "es un período que falta, es una serie que no existe"),
}


@dataclass(frozen=True)
class NoPuntuable:
    """Un pronóstico pendiente que no va a cerrar nunca, y por qué.

    Se LISTA en vez de saltearse en silencio. Un veto que no deja marca se lee como que el
    eje todavía no tiene track record, y es otra cosa: tiene filas rotas.
    """

    fila_id: str
    model_id: str
    target_series: str
    horizon: str
    motivo: str

    @property
    def explicacion(self) -> str:
        return _EXPLICACION.get(self.motivo, self.motivo)


def no_puntuables(db: Session) -> List[NoPuntuable]:
    """Los `pending` que `puntuar_pendientes` no va a poder cerrar por más que pase el
    tiempo. Vacío es la respuesta sana."""
    pendientes = db.query(ForecastLog).filter(ForecastLog.status == "pending").all()
    if not pendientes:
        return []
    conocidas: Dict[str, bool] = {}
    salida: List[NoPuntuable] = []
    for f in pendientes:
        serie = str(f.target_series)
        if str(f.measure or "") not in med.MEDIDAS:
            motivo = SIN_MEDIDA
        else:
            if serie not in conocidas:
                conocidas[serie] = bool(
                    db.query(MacroSeries.id).filter_by(series_code=serie).first())
            if conocidas[serie]:
                continue
            motivo = SERIE_DESCONOCIDA
        salida.append(NoPuntuable(fila_id=str(f.id), model_id=str(f.model_id),
                                  target_series=serie, horizon=str(f.horizon),
                                  motivo=motivo))
    return salida


def _del_conjunto(db: Session, bt_id: str) -> List[ForecastLog]:
    """Las filas que sostienen un `backtest_id`: **revisión 0 y `scored`**, sin mirar
    `superseded_by`. El track record mide el pronóstico como se PUBLICÓ, no como se corrigió
    después.

    El cuarto campo del id es el horizonte RELATIVO (`+1T`). Una fila sin `h` —anterior a la
    migración que lo introdujo— queda FUERA del conjunto: darle un horizonte inventado sería
    fabricarle track record, que es lo único que este ledger existe para impedir.

    El tercero es la MEDIDA, y no tiene comodín: un modelo que cambia de unidad parte su
    track record en dos poblaciones, y promediarlas publica un RMSE que no es el error de
    ninguno de los dos modelos.
    """
    model_id, target, medida, rel = bt_id.split("|", 3)
    q = (db.query(ForecastLog)
         .filter(ForecastLog.model_id == model_id,
                 ForecastLog.target_series == target,
                 ForecastLog.measure == medida,
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
    return _una_por_horizonte(q.all())


def _una_por_horizonte(filas: Sequence[ForecastLog]) -> List[ForecastLog]:
    """Un trimestre OBJETIVO cuenta una sola vez POR DISTANCIA, con su emisión más TEMPRANA.

    `n_oos` contaba emisiones, no trimestres — y la emisión se dispara en cascada tras cada
    ingesta canónica, así que un mismo trimestre se re-emite varias veces antes de cerrar:
    cada corrida en otra fecha escribe una fila, porque `as_of` está en la clave de cinco
    campos. Medido: cuatro trimestres de evidencia real daban `n_oos = 12`, y el gate —que
    exige doce— ADMITÍA. Es fabricar track record, que es lo único que este ledger existe
    para impedir.

    **Y no era solo el conteo.** Con tres filas del mismo trimestre, el error de ESE trimestre
    pesaba el triple en el RMSE: el promedio quedaba inclinado por cuántas veces corrió una
    operación.

    **Una re-emisión no es evidencia nueva.** Si viene del mismo bloque es el mismo pronóstico
    re-sellado: el conjunto de información no cambió. Y si el bloque avanzó, el horizonte
    RELATIVO cambia —2026-Q3 pasa de h=2 a h=1— y la fila se va sola a otro conjunto. O sea
    que varias `as_of` para el mismo horizonte dentro de un conjunto implican el mismo bloque.

    Se conserva la MÁS TEMPRANA: el pronóstico como se publicó por primera vez, que es la
    misma doctrina que ya rige para las revisiones.

    **La clave es (horizonte, distancia), no el horizonte solo.** En el conjunto comodín
    conviven varias distancias, y 2026-Q3 pronosticado a un trimestre vista y a dos son dos
    pronósticos DISTINTOS —el segundo se hizo con un bloque que terminaba un trimestre
    antes—: sí son evidencia separada. Lo que no lo es son dos cortes de la misma distancia.
    """
    mejor: Dict[Tuple[str, Optional[int]], ForecastLog] = {}
    for f in filas:
        clave = (str(f.horizon), None if f.h is None else int(f.h))
        previa = mejor.get(clave)
        if previa is None or str(f.as_of) < str(previa.as_of):
            mejor[clave] = f
    return list(mejor.values())


def track_record(db: Session, bt_id: str) -> Dict[str, Any]:
    """Error y cobertura empírica de intervalos de un conjunto de pronósticos puntuados.

    La cobertura de intervalos se devuelve junto al error y no aparte: un intervalo del 80%
    que acierta el 45% de las veces se ve ahí y en ningún otro lado.
    """
    todas = _del_conjunto(db, bt_id)
    # Una fila `scored` SIN error no vale cero: entraba al RMSE como un acierto perfecto y
    # sumaba al `n_oos` (`sq_error or 0.0`). Es rellenar la brecha. Se veta y se LISTA.
    sin_error = sorted(str(f.horizon) for f in todas
                       if f.sq_error is None or f.abs_error is None)
    filas = [f for f in todas if f.sq_error is not None and f.abs_error is not None]
    n = len(filas)
    if not n:
        return {"backtest_id": bt_id, "n_oos": 0, "rmse": None, "mae": None,
                "interval_coverage": (), "overlapping": None, "sin_error": sin_error}
    rmse = math.sqrt(sum(float(f.sq_error) for f in filas) / n)
    mae = sum(float(f.abs_error) for f in filas) / n
    cobertura = []
    for nivel, campo in ((0.80, "interval_hit_80"), (0.90, "interval_hit_90")):
        hits = [getattr(f, campo) for f in filas if getattr(f, campo) is not None]
        if hits:
            cobertura.append((nivel, sum(1 for h in hits if h) / len(hits), len(hits)))
    return {"backtest_id": bt_id, "n_oos": n, "rmse": round(rmse, 6),
            "mae": round(mae, 6), "interval_coverage": tuple(cobertura),
            "overlapping": _se_solapan(filas), "sin_error": sin_error}


def _trimestre_ordinal(period: str) -> Optional[int]:
    """``2026-Q3`` → un entero comparable en trimestres. ``None`` si no es un trimestre."""
    m = re.fullmatch(r"(\d{4})-Q([1-4])", str(period).strip().upper())
    return None if m is None else int(m.group(1)) * 4 + int(m.group(2))


def _se_solapan(filas: Sequence[ForecastLog]) -> Optional[bool]:
    """¿Las ventanas de evaluación se solapan? ``None`` cuando no se puede saber.

    La regla es la que el docstring anterior ya declaraba y **nunca se había escrito**: se
    solapan cuando *el paso entre cortes es menor que el salto entre horizontes*. Es el
    resultado estándar — pronósticos a `h` pasos emitidos cada `paso` períodos comparten
    información cuando ``paso < h``, y sus errores quedan autocorrelacionados, así que el `n`
    no son `n` observaciones independientes.

    Lo único implementado antes era «dos filas comparten horizonte», y eso lo resuelve ahora
    `_una_por_horizonte` deduplicando: dejar la comprobación vieja habría hecho que esta
    función devolviera ``False`` siempre y el informe dejara de declarar un caveat que sí
    declaraba. Apagar un aviso en silencio es peor que el defecto que la deduplicación cura.

    No se corrige el conteo con una fórmula inventada: se DECLARA, que es lo que la casa hace
    con toda limitación. Y ``None`` no es ``False``: un horizonte que no resuelve a un
    trimestre no se puede juzgar, y el gate ya rechaza el ``None`` con su motivo — decir que
    no se solapan afirmaría que se comprobó.
    """
    if len(filas) <= 1:
        return False                      # con una sola fila no hay con qué solaparse
    pasos = {int(f.h) for f in filas if f.h is not None}
    if not pasos:
        return None
    crudos = [_trimestre_ordinal(str(f.horizon)) for f in filas]
    if any(o is None for o in crudos):
        return None
    ordinales = sorted(o for o in crudos if o is not None)
    salto = min(b - a for a, b in zip(ordinales, ordinales[1:]))
    return salto < max(pasos)
