"""El año CONTRA los años: el cierre de la entidad frente a los cierres anteriores.

**Qué lo distingue del año por trimestres.** Lo fijó el dueño el 2026-08-27, cuando los dos
productos estaban sirviendo el mismo informe:

* en «SDQ Banking Intelligence», el año se lee POR DENTRO — la serie de sus trimestres y el
  movimiento de cada tramo;
* **acá**, en «SDQ Banking · Revisión Anual», el año TOTAL contra el año anterior y la
  TENDENCIA plurianual.

La diferencia es la **unidad de comparación**: allá se compara dentro del año, acá entre años.

**Por qué la tendencia es el aporte real.** «Cerró en 58,71» no dice si es un mal año o el
cuarto consecutivo bajando, y son decisiones de exposición distintas. La serie de cierres es
lo único que lo distingue, y hasta ahora ningún informe la traía: `entity_trajectories`
devuelve ocho trimestres —dos años— y ese es todo el horizonte que el eje tenía.

**El horizonte, declarado — y de quién es el límite.** Hoy son seis cierres (2020→2025) porque
ahí arranca NUESTRO backfill, no porque la fuente termine ahí: la Superintendencia publica
mucho más atrás. Confundir el límite propio con el de la fuente sería exactamente el error de
leer «no hay dato» donde dice «no lo trajimos».

Lo que sí tiene un piso real es el capital regulatorio —patrimonio técnico, APR, solvencia—,
que no existe en el balance crudo anterior a ~2004: hacia allá el score no se puede computar
con la misma metodología.

Se usa TODO lo disponible y se DICE cuánto es: recortar la ventana escondería un deterioro
largo, y no declararla haría pasar seis años por «siempre».
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import extract
from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, ModelType, RatingResult

logger = logging.getLogger("sdq.banking.anio_contra_anios")

#: Por debajo de esto un año contra otro no se llama movimiento.
UMBRAL_ANUAL = 0.5

#: Las cinco dimensiones, con la columna del rating que las guarda.
_DIMENSIONES = (("solidez", "solidez_score"), ("calidad", "calidad_score"),
                ("eficiencia", "eficiencia_score"), ("liquidez", "liquidez_score"),
                ("diversificacion", "diversificacion_score"))


def cierres_anuales(db: Session, bank: Bank, hasta: int) -> List[Dict[str, Any]]:
    """Los cierres de DICIEMBRE calificados de *bank*, del más antiguo al más reciente.

    Se consulta directo en vez de usar `entity_trajectories` porque aquélla devuelve los N
    últimos CORTES —ocho, o sea dos años— y acá el sujeto es la serie de AÑOS. Pedirle nueve
    trimestres y quedarse con los diciembres daría dos puntos y una «tendencia» de dos años,
    que no es una tendencia.
    """
    filas = (db.query(RatingResult)
             .filter(RatingResult.bank_id == bank.id,
                     RatingResult.model_type == ModelType.deterministic,
                     extract("month", RatingResult.period_end) == 12,
                     extract("day", RatingResult.period_end) == 31,
                     RatingResult.period_end <= date(hasta, 12, 31))
             .order_by(RatingResult.period_end.asc()).all())
    out = []
    for rr in filas:
        if rr.overall_score is None:
            continue
        out.append({
            "anio": rr.period_end.year,
            "corte": rr.period_end.isoformat(),
            "score": round(float(rr.overall_score), 2),
            # La banda es del eje de Resiliencia, no de `score`: viaja con su propio número.
            "resiliencia": (None if rr.resiliencia_score is None
                            else round(float(rr.resiliencia_score), 2)),
            "banda": rr.banda_resiliencia,
            "dimensiones": {nombre: (None if getattr(rr, col) is None
                                     else round(float(getattr(rr, col)), 2))
                            for nombre, col in _DIMENSIONES},
            "indicadores": rr.indicator_details or {},
        })
    return out


def _variaciones(serie: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Año contra año. El movimiento que la foto de un solo cierre no da."""
    out = []
    for antes, despues in zip(serie, serie[1:]):
        delta = round(despues["score"] - antes["score"], 2)
        out.append({
            "anio": despues["anio"], "contra": antes["anio"],
            "score": despues["score"], "score_anterior": antes["score"],
            "cambio": delta,
            "direccion": ("estable" if abs(delta) < UMBRAL_ANUAL
                          else "al alza" if delta > 0 else "a la baja"),
            "banda": despues["banda"],
            # `cambio` es del score GLOBAL y la banda es del eje de Resiliencia: un cambio de
            # banda explicado con el delta de otro número no se puede auditar. Viaja el suyo.
            "resiliencia": despues.get("resiliencia"),
            "resiliencia_anterior": antes.get("resiliencia"),
            "cambio_resiliencia": (
                None if antes.get("resiliencia") is None or despues.get("resiliencia") is None
                else round(despues["resiliencia"] - antes["resiliencia"], 2)),
            "cambio_de_banda": (None if despues["banda"] == antes["banda"]
                                else {"desde": antes["banda"], "hasta": despues["banda"]}),
        })
    return out


def _tendencia(variaciones: List[Dict[str, Any]], horizonte: int) -> Dict[str, Any]:
    """Cuántos años CONSECUTIVOS lleva moviéndose en la misma dirección.

    Es la pregunta que separa un mal año de un deterioro estructural, y es una RELACIÓN: se
    computa acá y el modelo la copia. Los años ESTABLES no cortan la racha ni la alargan —
    cortarla con un año plano diría que el deterioro se detuvo cuando solo hizo una pausa, y
    contarlo como parte de la racha afirmaría un movimiento que no hubo.
    """
    if not variaciones:
        return {"anios_comparados": 0,
                "lectura": "no hay dos cierres anuales: no se puede hablar de tendencia"}
    racha, direccion = 0, None
    for v in reversed(variaciones):
        if v["direccion"] == "estable":
            continue
        if direccion is None:
            direccion = v["direccion"]
        if v["direccion"] != direccion:
            break
        racha += 1
    neto = round(variaciones[-1]["score"] - variaciones[0]["score_anterior"], 2)
    return {
        "anios_comparados": len(variaciones),
        "horizonte_disponible": horizonte,
        "direccion_sostenida": direccion,
        "anios_consecutivos": racha,
        "cambio_neto_del_horizonte": neto,
        "desde": variaciones[0]["contra"], "hasta": variaciones[-1]["anio"],
        "lectura": (
            f"la serie cubre {horizonte} cierre(s) anual(es); en el horizonte el score se "
            f"movió {neto:+.2f} puntos"
            + (f" y lleva {racha} año(s) consecutivo(s) {direccion}" if racha and direccion
               else "")),
        "por_que_este_horizonte": (
            "El panel calificado arranca en el cierre de 2020 porque ahí arranca NUESTRO "
            "backfill, no porque la fuente termine ahí: la Superintendencia publica mucho "
            "más atrás. El horizonte es una decisión de ingesta y se puede extender. Lo que "
            "sí tiene un piso real es el capital regulatorio (patrimonio técnico, APR, "
            "solvencia), que no existe en el balance crudo anterior a ~2004."),
    }


def _balance_contra_el_anio_anterior(serie: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cada indicador al cierre, contra su valor al cierre ANTERIOR.

    Es la misma idea que el balance del año por trimestres, con otra base: allá la apertura es
    el arranque del año; acá es el cierre del año pasado. La distinción es el producto entero.
    """
    from modules.banking_score.reports.revision_anual import _balance

    if len(serie) < 2:
        return []
    previo, actual = serie[-2], serie[-1]
    indicadores: Dict[str, List[Dict[str, Any]]] = {}
    for etiqueta, punto in (("previo", previo), ("actual", actual)):
        for clave, blob in (punto.get("indicadores") or {}).items():
            if not isinstance(blob, dict) or blob.get("raw") is None:
                continue
            indicadores.setdefault(clave, []).append(
                {"period_end": punto["corte"], "raw": blob.get("raw"),
                 "score": blob.get("score")})
    return _balance(indicadores, [previo["corte"], actual["corte"]])


def anio_contra_anios(db: Session, bank: Bank, anio: int) -> Optional[Dict[str, Any]]:
    """El año de *bank* contra los anteriores. ``None`` si ese año no cerró."""
    serie = cierres_anuales(db, bank, anio)
    if not serie or serie[-1]["anio"] != anio:
        logger.info("Revisión Anual %s de %s: el año no cerró.", anio, bank.name)
        return None

    variaciones = _variaciones(serie)
    return {
        "anio": anio,
        "entidad": bank.name,
        "lectura_del_producto": (
            "Este informe lee el año TOTAL contra los años anteriores y su tendencia. El año "
            "por dentro —la serie de sus trimestres y el movimiento de cada tramo— es el otro "
            "producto, «SDQ Banking Intelligence»."),
        "serie_de_cierres": [{k: v for k, v in p.items() if k != "indicadores"}
                             for p in serie],
        "cierre": {k: v for k, v in serie[-1].items() if k != "indicadores"},
        "contra_el_anio_anterior": variaciones[-1] if variaciones else None,
        "variaciones": variaciones,
        "tendencia": _tendencia(variaciones, len(serie)),
        "balance": _balance_contra_el_anio_anterior(serie),
        "regla_del_score": ("el score del año es el DEL CIERRE; no se promedian los "
                            "trimestres, porque un promedio no coincidiría con ningún score "
                            "publicado"),
    }
