"""El AÑO del sistema bancario dominicano, computado. Nada de esto lo narra el modelo.

Es el insumo del anuario: el primer documento de la firma cuyo sujeto es el sistema entero y
que además NOMBRA entidades. Por eso las reglas de este módulo no son estilo — cada una evita
un titular falso:

**Mediana, no media.** Medido en el corte 2025: la media del sistema SUBE (64,83 → 65,41) y la
mediana BAJA (68,34 → 67,93). Las dos son correctas y dicen lo contrario. A la media la
levantan unos pocos extremos —una cambiaria mejoró +60,60 puntos— así que un anuario que
titule «el sistema mejoró» apoyado en la media estaría técnicamente respaldado y sería falso
como lectura. Se sirven las dos, con la mediana como titular y la divergencia DECLARADA cuando
existe: esconder que discrepan sería peor que cualquiera de las dos cifras.

**El universo se declara y las parciales no se ordenan.** De 88 entidades vistas en 2025, 82
tienen los cuatro cortes y 6 no —las cuatro fiduciarias entraron con un solo corte—. Rankear
un año incompleto contra uno completo es comparar peras con naranjas; ocultarlo es peor,
porque desaparecen sin aviso. Van aparte y con el motivo.

**El cambio se mide contra el cierre ANTERIOR**, no contra el primer corte del año: «el año»
de una entidad es diciembre a diciembre. Y todos los agregados se computan sobre el MISMO
universo comparable, para que las cifras del documento sumen entre sí.
"""
from __future__ import annotations

import logging
import statistics as st
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.etiquetas import etiqueta_de_tipo
from modules.banking_score.models.models import Bank, ModelType, RatingResult

logger = logging.getLogger("sdq.banking.anuario")

#: Por debajo de este movimiento no se afirma que una entidad mejoró ni empeoró. Mismo criterio
#: que la materialidad de las comparaciones: forzar un lado sobre ruido no informa nada.
UMBRAL_MOVIMIENTO = 0.5

#: Cierres trimestrales de un año, más el cierre del año anterior como línea base.
def _cortes(anio: int) -> List[date]:
    return [date(anio - 1, 12, 31), date(anio, 3, 31), date(anio, 6, 30),
            date(anio, 9, 30), date(anio, 12, 31)]


def _anios_con_cierre(db: Session) -> List[int]:
    """Los años que tienen su corte de DICIEMBRE calificado, en orden.

    Es la definición operativa de «año completo» para el anuario: el producto compara cierre
    contra cierre, así que el año sin diciembre no se puede resumir.
    """
    cierres = (db.query(RatingResult.period_end)
               .filter(RatingResult.model_type == ModelType.deterministic)
               .distinct().all())
    return sorted({p.year for (p,) in cierres if p and (p.month, p.day) == (12, 31)})


def _panel(db: Session, cortes: List[date]) -> Dict[date, Dict[str, Dict[str, Any]]]:
    filas = (db.query(RatingResult, Bank)
             .join(Bank, Bank.id == RatingResult.bank_id)
             .filter(RatingResult.period_end.in_(cortes),
                     RatingResult.model_type == ModelType.deterministic)
             .all())
    out: Dict[date, Dict[str, Dict[str, Any]]] = {c: {} for c in cortes}
    for rr, b in filas:
        if rr.overall_score is None:
            continue
        out[rr.period_end][b.name] = {
            "score": float(rr.overall_score),
            "banda": rr.banda_resiliencia,
            "tipo": b.bank_type.value if b.bank_type else None,
        }
    return out


def _direccion(delta: float) -> str:
    if delta > UMBRAL_MOVIMIENTO:
        return "mejora"
    if delta < -UMBRAL_MOVIMIENTO:
        return "deterioro"
    return "estable"


def estado_del_anio(db: Session, anio: int) -> Dict[str, Any]:
    """Qué tiene el panel de *anio*, para decidir Y para explicar la negativa.

    El anuario mide UN AÑO, así que necesita que el año haya CERRADO: sin el corte de
    diciembre no hay «cambio del año», hay un tramo. La cuenta mínima de dos cortes que el
    motor exigía dejaba pasar exactamente eso — con el panel de producción al 2026-03-31, el
    período por defecto de la aplicación es 2026-Q1 y un anuario 2026 se armaba con la línea
    base de dic-2025 y un solo trimestre. El documento no traía ninguna cifra falsa: traía un
    TRIMESTRE con el encabezado de un año, que es la misma familia de defecto que la doctrina
    llama declarar la brecha en vez de rellenarla.

    Devuelve también el último año COMPLETO, porque una negativa que no dice qué sí se puede
    pedir obliga a adivinar.
    """
    cortes = _cortes(anio)
    panel = _panel(db, cortes)
    presentes = [c for c in cortes if panel.get(c)]
    completos = _anios_con_cierre(db)
    return {
        "anio": anio,
        "cortes_presentes": len(presentes),
        "cortes_esperados": len(cortes),
        "tiene_cierre": bool(panel.get(date(anio, 12, 31))),
        "ultimo_anio_completo": completos[-1] if completos else None,
    }


def anuario_del_sistema(db: Session, anio: int) -> Optional[Dict[str, Any]]:
    """Los hechos del año del sistema. ``None`` si el año no tiene panel suficiente."""
    cortes = _cortes(anio)
    panel = _panel(db, cortes)
    presentes = [c for c in cortes if panel.get(c)]
    if len(presentes) < 2:
        logger.info("Anuario %s: el panel no tiene cortes suficientes (%d).", anio, len(presentes))
        return None
    # EL AÑO TIENE QUE HABER CERRADO. Ver `estado_del_anio`: sin el corte de diciembre esto
    # no es el año, es un tramo, y salía titulado como un año.
    if not panel.get(date(anio, 12, 31)):
        logger.info("Anuario %s: el año no ha cerrado (falta el corte de diciembre).", anio)
        return None

    vistas = set().union(*(set(panel[c]) for c in presentes))
    comparables = sorted(set.intersection(*(set(panel[c]) for c in presentes)))
    parciales = sorted(vistas - set(comparables))
    if not comparables:
        return None

    ini, fin = presentes[0], presentes[-1]
    delta = {n: panel[fin][n]["score"] - panel[ini][n]["score"] for n in comparables}

    # ── El sistema, corte a corte ─────────────────────────────────────
    por_corte = []
    for c in presentes:
        v = [panel[c][n]["score"] for n in comparables]
        por_corte.append({"corte": str(c), "mediana": round(st.median(v), 2),
                          "media": round(st.mean(v), 2), "n": len(v)})
    d_med = round(por_corte[-1]["mediana"] - por_corte[0]["mediana"], 2)
    d_avg = round(por_corte[-1]["media"] - por_corte[0]["media"], 2)
    # La divergencia se DECLARA. Es el caso real de 2025 y el que produce el titular falso.
    divergen = (d_med > 0) != (d_avg > 0) and abs(d_med) > 0.01 and abs(d_avg) > 0.01
    sistema = {
        "por_corte": por_corte,
        "cambio_mediana": d_med,
        "cambio_media": d_avg,
        "estadistico_de_referencia": "mediana",
        "medias_y_medianas_divergen": divergen,
        "lectura": (
            f"la mediana del sistema {'subió' if d_med > 0 else 'cayó'} {abs(d_med):.2f} "
            f"puntos en {anio}"
            + (f", mientras la media {'subió' if d_avg > 0 else 'cayó'} {abs(d_avg):.2f}: "
               "la media la mueven unos pocos extremos, así que la lectura del sistema es la "
               "mediana" if divergen else "")),
    }

    # ── Cuántas suben y cuántas bajan ─────────────────────────────────
    conteo = {"mejora": 0, "deterioro": 0, "estable": 0}
    for d in delta.values():
        conteo[_direccion(d)] += 1

    # ── Por tipo de entidad ───────────────────────────────────────────
    por_tipo: Dict[str, List[float]] = {}
    for n in comparables:
        t = panel[fin][n]["tipo"] or "sin tipo"
        por_tipo.setdefault(t, []).append(delta[n])
    # La ETIQUETA viaja al lado de la clave. La clave cruda (`aap`, `banca_multiple`) llegaba
    # al contexto del modelo —incluido el nivel ABIERTO del producto anual, que es material de
    # mercado—, donde el modelo tiene que adivinar qué es «aap» o imprimirlo tal cual.
    tipos: List[Dict[str, Any]] = [
        {"tipo": t, "tipo_label": etiqueta_de_tipo(t), "n": len(v),
         "cambio_mediana": round(st.median(v), 2),
         "direccion": _direccion(st.median(v))} for t, v in por_tipo.items()]
    tipos.sort(key=lambda x: float(x["cambio_mediana"]))

    # ── Cambios de banda ──────────────────────────────────────────────
    bandas = [
        {"entidad": n, "tipo": panel[fin][n]["tipo"],
         "tipo_label": etiqueta_de_tipo(panel[fin][n]["tipo"]),
         "desde": panel[ini][n]["banda"], "hasta": panel[fin][n]["banda"],
         "cambio_score": round(delta[n], 2)}
        for n in comparables
        if panel[ini][n]["banda"] and panel[fin][n]["banda"]
        and panel[ini][n]["banda"] != panel[fin][n]["banda"]
    ]
    bandas.sort(key=lambda x: x["cambio_score"])

    # ── Extremos, con su advertencia ──────────────────────────────────
    orden = sorted(comparables, key=lambda n: delta[n])
    extremos = {
        "mayor_deterioro": {"entidad": orden[0], "cambio_score": round(delta[orden[0]], 2),
                            "tipo": panel[fin][orden[0]]["tipo"]},
        "mayor_mejora": {"entidad": orden[-1], "cambio_score": round(delta[orden[-1]], 2),
                         "tipo": panel[fin][orden[-1]]["tipo"]},
        "advertencia": ("son las COLAS de la distribución, no la tendencia: describilos como "
                        "casos, nunca como el comportamiento del sistema"),
    }

    return {
        "anio": anio,
        "cortes": [str(c) for c in presentes],
        "universo": {
            "comparables": len(comparables),
            "vistas_en_el_anio": len(vistas),
            "parciales": [
                {"entidad": n,
                 "cortes_presentes": sum(1 for c in presentes if n in panel[c]),
                 "de": len(presentes)}
                for n in parciales
            ],
            "regla": ("los agregados y el orden se computan SOLO sobre las entidades con "
                      "todos los cortes; las parciales se listan aparte y no se rankean —un "
                      "año incompleto no se ordena contra uno completo, y ocultarlas sería "
                      "peor porque desaparecerían sin aviso"),
        },
        "sistema": sistema,
        "conteo_direccion": conteo,
        "por_tipo": tipos,
        "cambios_de_banda": bandas,
        "extremos": extremos,
    }
