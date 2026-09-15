"""Escritura y lectura de las observaciones sub-anuales. Sin reglas de negocio."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.observations.models import SectorObservation

logger = logging.getLogger("sdq.observations.service")


def upsert(db: Session, *, sector_key: str, series_code: str, period: str,
           value: Optional[float], unit: Optional[str] = None,
           frequency: Optional[str] = None, nature: Optional[str] = None,
           provincia: str = "", tipologia: str = "",
           source: Optional[str] = None, published_at: Optional[date] = None,
           license: Optional[str] = None, municipio: str = "",
           barrio: str = "") -> SectorObservation:
    """Escribe (o reemplaza) UN punto. No commitea — el llamador decide.

    ``value=None`` se persiste como NULL: un dato ausente es NULL, jamás 0.0. Escribir un
    cero haría que un mes sin publicar se lea como un mes sin actividad, que son cosas
    distintas y la segunda es una afirmación.
    """
    row = (db.query(SectorObservation)
           .filter(SectorObservation.sector_key == sector_key,
                   SectorObservation.series_code == series_code,
                   SectorObservation.period == period,
                   SectorObservation.provincia == provincia,
                   SectorObservation.tipologia == tipologia,
                   SectorObservation.municipio == municipio,
                   SectorObservation.barrio == barrio)
           .first())
    if row is None:
        row = SectorObservation(sector_key=sector_key, series_code=series_code,
                                period=period, provincia=provincia, tipologia=tipologia,
                                municipio=municipio, barrio=barrio)
        db.add(row)
    row.value = value
    row.unit = unit
    row.frequency = frequency
    row.nature = nature
    row.source = source
    row.published_at = published_at
    row.license = license
    return row


def serie(db: Session, *, sector_key: str, series_code: str,
          provincia: str = "", tipologia: str = "",
          hasta: Optional[str] = None, municipio: str = "",
          barrio: str = "") -> List[SectorObservation]:
    """La serie completa de un punto de medición, ascendente por período.

    Los períodos son ``AAAA-MM`` / ``AAAA-QN`` / ``AAAA``: cadenas de ancho fijo que ordenan
    lexicográficamente igual que cronológicamente. Ordenar en la base y no en Python evita
    traer la serie entera para recortarla, y ``hasta`` permite la vista AS-OF —leer como se
    veía en un corte— sin la que un backtest se miente solo.
    """
    q = (db.query(SectorObservation)
         .filter(SectorObservation.sector_key == sector_key,
                 SectorObservation.series_code == series_code,
                 SectorObservation.provincia == provincia,
                 SectorObservation.tipologia == tipologia,
                 SectorObservation.municipio == municipio,
                 SectorObservation.barrio == barrio))
    if hasta:
        q = q.filter(SectorObservation.period <= hasta)
    return q.order_by(SectorObservation.period.asc()).all()


def codigos(db: Session, *, sector_key: str) -> List[str]:
    """Los códigos de serie que el eje tiene observados (agregado, sin dimensión)."""
    rows = (db.query(SectorObservation.series_code)
            .filter(SectorObservation.sector_key == sector_key,
                    SectorObservation.provincia == "",
                    SectorObservation.tipologia == "",
                    SectorObservation.municipio == "",
                    SectorObservation.barrio == "")
            .distinct().all())
    return sorted(r[0] for r in rows)


def ultimo_periodo(db: Session, *, sector_key: str,
                   series: Optional[List[str]] = None,
                   con_valor: bool = False) -> Optional[str]:
    """El período más reciente observado del eje, o ``None`` si no hay ninguno.

    ``series`` acota a un FEED: un eje con dos emisores en la tabla (las licencias del MIVHED y
    las de la ONE, que publica con más rezago) tiene dos «últimos períodos», y el de uno no
    describe al otro.

    ``con_valor`` descarta los períodos cuyas filas son todas NULL. Un NULL declara que falta
    el dato —un total del sistema de ARS con una entidad sin reportar se persiste así—, y un
    período sin ningún valor no es una edición publicada. Sin esto, el sensor daba «al día» a
    las ARS midiendo un julio vacío y la sección del delta narraba su ausencia en prod.
    """
    q = db.query(SectorObservation.period).filter(SectorObservation.sector_key == sector_key)
    if series:
        q = q.filter(SectorObservation.series_code.in_(list(series)))
    if con_valor:
        q = q.filter(SectorObservation.value.isnot(None))
    row = q.order_by(SectorObservation.period.desc()).first()
    return row[0] if row else None


def ultima_publicacion(db: Session, *, sector_key: str,
                       series: Optional[List[str]] = None) -> Optional[date]:
    """La fecha más reciente en que el EMISOR publicó algo de este eje, o ``None``.

    Es otra medida que ``ultimo_periodo``: el período dice a qué mes pertenece el dato, la
    publicación dice cuándo lo sacó el emisor. Una fuente al día con rezago normal tiene las
    dos cerca; una que dejó de publicar tiene la publicación quieta mientras el calendario
    avanza, y eso es lo que se declara.
    """
    from sqlalchemy import func

    q = (db.query(func.max(SectorObservation.published_at))
         .filter(SectorObservation.sector_key == sector_key))
    if series:
        q = q.filter(SectorObservation.series_code.in_(list(series)))
    row = q.first()
    return row[0] if row and row[0] else None


def ultima_escritura(db: Session, *, sector_key: str,
                     series: Optional[List[str]] = None) -> Optional[date]:
    """La fecha en que se ESCRIBIÓ por última vez el feed, o ``None``.

    Es la fecha de NUESTRA última descarga que se leyó y persistió, no la del emisor: la
    ingesta borra y reescribe la serie, así que el ``created_at`` más nuevo es esa corrida. Un
    eje sin sonda propia cita esto como «nuestra última descarga».
    """
    from datetime import datetime

    from sqlalchemy import func

    q = (db.query(func.max(SectorObservation.created_at))
         .filter(SectorObservation.sector_key == sector_key))
    if series:
        q = q.filter(SectorObservation.series_code.in_(list(series)))
    row = q.first()
    valor = row[0] if row else None
    if valor is None:
        return None
    return valor.date() if isinstance(valor, datetime) else valor


#: Qué columnas identifican cada dimensión y cuáles tienen que venir VACÍAS. Una fila de
#: barrio lleva su municipio y su provincia; sin exigir vacío lo más fino, el total de una
#: provincia sumaría también sus municipios y sus barrios — la misma plaza tres veces.
_DIMENSIONES: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "provincia": (("provincia",), ("tipologia", "municipio", "barrio")),
    "tipologia": (("tipologia",), ("provincia", "municipio", "barrio")),
    "municipio": (("provincia", "municipio"), ("tipologia", "barrio")),
    "barrio": (("provincia", "municipio", "barrio"), ("tipologia",)),
}


def por_dimension(db: Session, *, sector_key: str, series_code: str, period: str,
                  campo: str) -> List[Dict[str, Any]]:
    """Las filas de *period* desagregadas por una dimensión, de mayor a menor.

    Es el microdato que el agregado anual tiraba, y la diferencia entre «el sector creció»
    y «tal plaza concentra tal cosa». Un municipio sale con su provincia y un barrio con su
    municipio y su provincia: el nombre suelto no dice de qué plaza es.
    """
    if campo not in _DIMENSIONES:
        raise ValueError("La dimensión debe ser 'provincia', 'tipologia', 'municipio' o "
                         "'barrio'.")
    llenas, vacias = _DIMENSIONES[campo]
    q = (db.query(SectorObservation)
         .filter(SectorObservation.sector_key == sector_key,
                 SectorObservation.series_code == series_code,
                 SectorObservation.period == period,
                 getattr(SectorObservation, campo) != ""))
    for c in vacias:
        q = q.filter(getattr(SectorObservation, c) == "")
    salida = [{**{c: getattr(r, c) for c in llenas}, "valor": r.value, "unidad": r.unit}
              for r in q.all() if r.value is not None]
    return sorted(salida, key=lambda d: -(d["valor"] or 0.0))


def borrar_serie(db: Session, *, sector_key: str, series_code: str) -> int:
    """Borra una serie entera del eje (re-ingesta idempotente). Devuelve las filas borradas."""
    n = (db.query(SectorObservation)
         .filter(SectorObservation.sector_key == sector_key,
                 SectorObservation.series_code == series_code)
         .delete(synchronize_session=False))
    return int(n or 0)


def contar(db: Session, *, sector_key: str) -> int:
    return int(db.query(SectorObservation)
               .filter(SectorObservation.sector_key == sector_key).count())


def _iter_valores(rows: Iterable[SectorObservation]) -> Dict[str, Optional[float]]:
    return {r.period: r.value for r in rows}
