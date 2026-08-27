"""El AÑO de una entidad, computado. La Revisión Anual — nada de esto lo narra el modelo.

**Por qué existe.** Hasta ahora la única lectura «anual» de una entidad era el informe al
cierre de diciembre, y eso confunde dos cosas distintas: el informe AL CIERRE del ejercicio y
el informe DEL ejercicio. La ventana móvil de doce meses toca **una sola** magnitud —la
utilidad neta, o sea ROA y ROE—; los otros diecinueve indicadores son fotos al 31 de
diciembre, y el score es una lectura AL CORTE, no un agregado del año.

Peor: todo lo «anual» que sí traían los informes —trayectoria, anclas, atribución— corre sobre
una ventana de **ocho trimestres móviles**. Un informe a diciembre-2025 tiene ventana
dic-2023 → dic-2025, así que su «pico» y su «valle» son de DOS años. Ése era el hueco.

**Lo que este módulo computa, y de dónde sale cada cifra:**

1. El año en una línea (apertura/cierre de score y banda) — de la trayectoria acotada al año.
2. El CAMINO: amplitud, pico, valle, trimestres al alza y a la baja, y si el peor momento fue
   INTERMEDIO. Una entidad que cayó y se recuperó cierra igual que una que nunca se movió, y
   no son lo mismo.
3. Los cambios de banda DURANTE el año, no solo apertura contra cierre.
4. BALANCE de apertura contra cierre por indicador: lo que hoy no existe en ninguna parte,
   porque los indicadores de stock solo se veían en su foto final.
5. El movimiento de POSICIÓN relativa: percentil al abrir y al cerrar. Responde lo que el
   nivel no responde — ¿mejoró contra sí misma o contra el mercado?

**Lo que NO computa, a propósito:**

- **No hay «score anual».** El score del año es el DEL CIERRE, y el resto es el camino.
  Promediar los cuatro trimestres daría un número que no coincide con ninguno publicado y
  dejaría «¿cuál es el score de X en 2025?» con dos respuestas legítimas.
- **No se emite un año sin cerrar.** Sin el corte de diciembre esto es un tramo, no un año —
  la misma regla que el anuario del sistema, y por el mismo motivo.
- **Los cortes ausentes se DECLARAN.** Un año con un trimestre faltante sigue siendo
  resumible cierre a cierre, pero sus anclas de camino se marcan parciales: el pico de una
  serie con huecos es el pico de lo que se vio, no el del año.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank
from modules.banking_score.scoring.indicator_detail import INDICATOR_META
from modules.banking_score.scoring.sensitivity import nivel_de_referencia
from shared.narrative.derived import (MATERIALIDAD_PP, MATERIALIDAD_POR_UNIDAD,
                                      veredicto_de_movimiento)

logger = logging.getLogger("sdq.banking.revision_anual")

#: Los cinco cortes de un año: el cierre anterior como línea base, más los cuatro trimestres.
def _cortes_del_anio(anio: int) -> List[str]:
    return [f"{anio - 1}-12-31", f"{anio}-03-31", f"{anio}-06-30",
            f"{anio}-09-30", f"{anio}-12-31"]


#: Por debajo de esto no se afirma que un indicador mejoró ni empeoró: mismo criterio que la
#: materialidad de las comparaciones. Forzar un lado sobre ruido no informa nada.
UMBRAL_MOVIMIENTO_SCORE = 0.5


def _serie_del_anio(serie: List[Dict[str, Any]], cortes: List[str]) -> List[Dict[str, Any]]:
    """Los puntos de *serie* que caen en los cortes del año, en orden."""
    por_corte = {str(p.get("period_end")): p for p in (serie or []) if isinstance(p, dict)}
    return [por_corte[c] for c in cortes if c in por_corte]


def _camino(puntos: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """El CAMINO del score dentro del año, no solo sus extremos.

    El hecho que esto captura y un «abrió en X, cerró en Y» no: que el peor momento haya sido
    INTERMEDIO. Dos entidades con el mismo cierre —una estable, otra que cayó y se recuperó—
    no tienen el mismo año, y el informe al corte no las distingue.
    """
    vals = [(str(p["period_end"]), float(p["score"])) for p in puntos
            if p.get("score") is not None]
    if len(vals) < 3:
        return None
    scores = [v for _, v in vals]
    i_pico, i_valle = scores.index(max(scores)), scores.index(min(scores))
    subidas = sum(1 for a, b in zip(scores, scores[1:]) if b - a > UMBRAL_MOVIMIENTO_SCORE)
    bajadas = sum(1 for a, b in zip(scores, scores[1:]) if a - b > UMBRAL_MOVIMIENTO_SCORE)
    intermedio = 0 < i_valle < len(scores) - 1
    return {
        "amplitud": round(max(scores) - min(scores), 2),
        "pico": {"corte": vals[i_pico][0], "score": round(vals[i_pico][1], 2)},
        "valle": {"corte": vals[i_valle][0], "score": round(vals[i_valle][1], 2)},
        "trimestres_al_alza": subidas,
        "trimestres_a_la_baja": bajadas,
        "valle_intermedio": intermedio,
        "lectura": (
            f"el año se movió en un rango de {max(scores) - min(scores):.2f} puntos"
            + (f"; el peor momento fue {vals[i_valle][0][:7]} y NO el cierre, así que el año "
               "tuvo una recuperación que la foto de diciembre no muestra"
               if intermedio else "")),
    }


def _balance(indicadores: Dict[str, List[Dict[str, Any]]], cortes: List[str],
             claves: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Apertura contra cierre de cada indicador: el dato que la foto final no da.

    Solvencia, apalancamiento, liquidez y morosidad son STOCKS: su valor en diciembre no dice
    nada del año. Lo que dice algo es contra qué nivel arrancó.
    """
    apertura, cierre = cortes[0], cortes[-1]
    filas = []
    for clave, serie in sorted((indicadores or {}).items()):
        if claves and clave not in claves:
            continue
        por_corte = {str(p.get("period_end")): p for p in serie if isinstance(p, dict)}
        a, c = por_corte.get(apertura), por_corte.get(cierre)
        if not a or not c or a.get("raw") is None or c.get("raw") is None:
            continue
        v0, v1 = float(a["raw"]), float(c["raw"])
        # El SCORE ya viaja en la trayectoria y este balance lo tiraba. El contexto del
        # trimestral sí lo tiene, así que el modelo podía decir «score 34 de 100» al corte y
        # no en el año: la misma asimetría que dejó fuera el nivel de referencia. Un número
        # que existe y no se sirve es un número que el modelo va a poner de memoria.
        s0, s1 = a.get("score"), c.get("score")
        meta = INDICATOR_META.get(clave) or {}
        unidad = meta.get("unit") or ""
        direccion = meta.get("direction")
        # MATERIALIDAD por unidad: el mismo criterio que las comparaciones al corte. Sin él,
        # una décima de ruido se narra como mejora.
        piso = MATERIALIDAD_POR_UNIDAD.get(unidad, MATERIALIDAD_PP)
        material = abs(v1 - v0) >= piso
        veredicto, por_que = veredicto_de_movimiento(direccion, v1 > v0, material=material)
        # El NIVEL DE REFERENCIA del indicador. Sin él, «cobertura de 96,75 %» no se puede
        # leer: hace falta saber que 100 % es donde las provisiones cubren exactamente la
        # cartera vencida. El modelo lo sabe y lo escribe igual —«por encima del 100 %»,
        # «puede cruzar por debajo del 100 %»—, y como el contexto no lo servía, esa cifra
        # llegaba sin respaldo y el guard vetaba el informe entero. Dos Revisiones Anuales
        # murieron así el 2026-08-27. No era el detector: era el hueco.
        referencia = nivel_de_referencia(clave, v1)
        filas.append({
            "indicador": clave,
            "que_mide": meta.get("que", ""),
            "unidad": unidad,
            "nivel_de_referencia": referencia,
            "nivel_de_referencia_significa": (
                None if referencia is None else
                f"{referencia}{unidad} es el nivel en que este indicador puntúa 50 sobre 100; "
                "por encima el score mejora y por debajo empeora"),
            "contra_la_referencia": (
                None if referencia is None else
                ("por encima" if v1 > referencia else
                 "por debajo" if v1 < referencia else "en la referencia")),
            "apertura": round(v0, 4), "cierre": round(v1, 4),
            "cambio": round(v1 - v0, 4),
            "score_apertura": None if s0 is None else round(float(s0), 2),
            "score_cierre": None if s1 is None else round(float(s1), 2),
            "cambio_de_score": (None if s0 is None or s1 is None
                                else round(float(s1) - float(s0), 2)),
            "subio": v1 > v0,
            # El VEREDICTO se computa acá, no lo deduce el modelo: morosidad de 1,33 a 1,96 y
            # solvencia de 26,8 a 23,3 son las dos deterioros, y sin esto se narran como si
            # una fuera mejora. `no_aplica` en los de óptimo intermedio, con su motivo.
            "sentido_de_la_escala": direccion,
            "veredicto": veredicto,
            "veredicto_por_que": por_que,
        })
    return filas


def _bandas_del_anio(puntos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cada cambio de banda DURANTE el año, no solo apertura contra cierre.

    Una entidad que bajó de banda en junio y volvió en diciembre figura hoy como «sin
    cambio», que es exactamente el año que un comité querría conocer.
    """
    cambios = []
    previo = None
    for p in puntos:
        banda = p.get("banda_resiliencia")
        if banda and previo and banda != previo:
            cambios.append({"corte": str(p["period_end"]), "desde": previo, "hasta": banda})
        if banda:
            previo = banda
    return cambios


def revision_anual(db: Session, bank: Bank, anio: int) -> Optional[Dict[str, Any]]:
    """El año de *bank*. ``None`` si el año no cerró o no hay panel suficiente."""
    from modules.banking_score.scoring.amplitude import entity_trajectories, period_percentiles

    cortes = _cortes_del_anio(anio)
    cierre = date(anio, 12, 31)
    # Ventana amplia y luego RECORTE a los cortes del año: pedir n=5 devolvería los cinco
    # ÚLTIMOS cortes disponibles, que con un trimestre ausente serían de otro año.
    traj = entity_trajectories(db, bank, n=9, as_of=cierre)
    overall = _serie_del_anio(traj.get("overall") or [], cortes)
    if not overall or str(overall[-1]["period_end"]) != cortes[-1]:
        logger.info("Revisión anual %s de %s: el año no cerró (o falta diciembre).",
                    anio, bank.name)
        return None
    if len(overall) < 2:
        logger.info("Revisión anual %s de %s: un solo corte.", anio, bank.name)
        return None

    apertura, final = overall[0], overall[-1]
    delta = round(float(final["score"]) - float(apertura["score"]), 2)
    faltantes = [c for c in cortes if c not in {str(p["period_end"]) for p in overall}]

    pos = {}
    for etiqueta, corte in (("apertura", cortes[0]), ("cierre", cortes[-1])):
        if corte in {str(p["period_end"]) for p in overall}:
            try:
                p = period_percentiles(db, bank, date.fromisoformat(corte))
                pos[etiqueta] = (p or {}).get("overall")
            except Exception:  # noqa: BLE001 — la posición nunca tumba el informe
                logger.exception("No se pudo computar el percentil de %s en %s",
                                 bank.name, corte)

    return {
        "anio": anio,
        "entidad": bank.name,
        "cortes_del_anio": [str(p["period_end"]) for p in overall],
        # Se DECLARA lo que falta: el pico de una serie con huecos es el pico de lo que se
        # vio, no el del año, y ocultarlo haría pasar una lectura parcial por completa.
        "cortes_faltantes": faltantes,
        "serie": [{"corte": str(p["period_end"]), "score": round(float(p["score"]), 2),
                   "banda": p.get("banda_resiliencia")} for p in overall],
        "apertura": {"corte": str(apertura["period_end"]),
                     "score": round(float(apertura["score"]), 2),
                     "banda": apertura.get("banda_resiliencia")},
        "cierre": {"corte": str(final["period_end"]),
                   "score": round(float(final["score"]), 2),
                   "banda": final.get("banda_resiliencia")},
        "cambio_score": delta,
        # El score del año ES el del cierre. Se declara para que nadie —modelo ni lector—
        # deduzca que hay un promedio anual en alguna parte.
        "regla_del_score": ("el score del año es el DEL CIERRE; no se promedian los "
                            "trimestres, porque un promedio no coincidiría con ningún score "
                            "publicado y daría dos respuestas a «cuál es el score de esta "
                            "entidad en el año»"),
        "camino": _camino(overall),
        "cambios_de_banda": _bandas_del_anio(overall),
        "balance": _balance(traj.get("indicators") or {}, cortes),
        "posicion": pos or None,
    }
