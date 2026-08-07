"""Perfil SDQ en pensiones — Ejecución y Resiliencia sobre el ISA (Fase 3, spec §6).

Reagrupa las dimensiones del ISA en dos ejes, sin recalibrar nada:

    Resiliencia   solvencia 70% · riesgo (volatilidad del NAV) 30%
    Ejecución     rentabilidad 71% · costo 29%
    (Escala queda FUERA de ambos ejes)

**Escala sale de Resiliencia y no se reemplaza** (§6.4). En seguros hizo falta poner
Reaseguro en su lugar porque no había otra señal del fenómeno que Escala proxeaba; acá no:
el ISA ya tiene una dimensión de riesgo REAL —la volatilidad del NAV mensual, ~30
observaciones encadenadas de los Boletines SIPEN— así que el proxy no aporta nada que la
señal directa no diga mejor.

Que Escala entre a Ejecución es un argumento distinto —más AUM podría reflejar éxito
comercial, no eficiencia de portafolio— y es una decisión de producto, no una inferencia
técnica. Queda fuera hasta que se decida.

**Los dos ejes son ABSOLUTOS, a diferencia de banca.** En banca, Ejecución tiene que ser
relativa al panel porque no existe un breakeven de eficiencia bancaria. Acá sí hay anclas:
rentabilidad y costo ya se puntúan contra bandas absolutas dentro del ISA (el costo incluso
contra un rango explícito de comisión sobre AUM). Con 7 AFP, además, unos cuartiles serían
puro ruido: cada corte se apoyaría en menos de dos observaciones.
"""
from typing import Any, Dict, List, Optional

# Pesos DENTRO de cada eje, renormalizados desde los del ISA (§6.5). No se tocan las
# proporciones relativas: solvencia:riesgo era 35:15 y rentabilidad:costo era 25:10.
#
# Se calculan como fracción exacta, no con el redondeo que muestra el spec (71%/29%):
# 0.71/0.29 da una razón de 2.448 en vez de 2.5, y ese medio punto es exactamente el tipo de
# desvío silencioso que después nadie sabe de dónde salió.
PESOS_RESILIENCIA = {"solvencia": 0.35 / 0.50, "riesgo": 0.15 / 0.50}
PESOS_EJECUCION = {"rentabilidad": 0.25 / 0.35, "costo": 0.10 / 0.35}

# Dimensión que NO participa de ningún eje, y por qué — explícito para que no se cuele de
# vuelta por olvido.
FUERA_DE_LOS_EJES = {"escala": "proxy de diversificación que la volatilidad real ya cubre (§6.4)"}

BANDAS_RESILIENCIA = [(75.0, "Sólida"), (60.0, "Adecuada"), (45.0, "En vigilancia"),
                      (0.0, "Frágil")]
BANDAS_EJECUCION = [(75.0, "Sobresaliente"), (60.0, "Competitiva"), (45.0, "Rezagada"),
                    (0.0, "Deficiente")]

# Con menos de este universo la banda sola engaña y el reporte debe mostrar la posición
# relativa junto a ella (§4.2). Las 7 AFP están muy por debajo: siempre la muestra.
MIN_UNIVERSO_SIN_POSICION = 15


def _banda(score: Optional[float], bandas) -> Optional[str]:
    if score is None:
        return None
    return next((n for t, n in bandas if score >= t), bandas[-1][1])


def banda_resiliencia(score: Optional[float]) -> Optional[str]:
    return _banda(score, BANDAS_RESILIENCIA)


def banda_ejecucion(score: Optional[float]) -> Optional[str]:
    return _banda(score, BANDAS_EJECUCION)


def _eje(dim_scores: Dict[str, Optional[float]], pesos: Dict[str, float]):
    """Suma ponderada sobre las dimensiones PRESENTES, renormalizando el peso.

    Devuelve ``(score, cobertura)``. Una dimensión ausente no cuenta como cero: se excluye y
    la cobertura lo declara.
    """
    presentes = {k: v for k, v in dim_scores.items() if v is not None and k in pesos}
    peso = sum(pesos[k] for k in presentes)
    if peso <= 0:
        return None, 0.0
    score = sum(presentes[k] * pesos[k] for k in presentes) / peso
    return round(score, 1), round(peso, 2)


def calcular_ejes(dim_scores: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """Los dos ejes de una AFP a partir de los scores de dimensión que ya calculó el ISA."""
    resiliencia, cob_r = _eje(dim_scores, PESOS_RESILIENCIA)
    ejecucion, cob_e = _eje(dim_scores, PESOS_EJECUCION)
    return {
        "ejecucion": ejecucion,
        "banda_ejecucion": banda_ejecucion(ejecucion),
        "cobertura_ejecucion": cob_e,
        "resiliencia": resiliencia,
        "banda_resiliencia": banda_resiliencia(resiliencia),
        "cobertura_resiliencia": cob_r,
        "dimensiones": {k: dim_scores.get(k) for k in
                        list(PESOS_RESILIENCIA) + list(PESOS_EJECUCION)},
        "fuera_de_los_ejes": {k: dim_scores.get(k) for k in FUERA_DE_LOS_EJES},
    }


def perfil_panel(afps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perfil SDQ de las AFP, con la posición relativa que exige la regla de N chico.

    Cada elemento de *afps* necesita ``slug``, ``name`` y ``dimension_scores``.
    """
    filas = []
    for a in afps:
        fila = dict(a)
        fila.pop("dimension_scores", None)
        fila.update(calcular_ejes(a.get("dimension_scores") or {}))
        filas.append(fila)

    n = len(filas)
    for eje in ("ejecucion", "resiliencia"):
        orden = sorted((f for f in filas if f[eje] is not None),
                       key=lambda f: f[eje], reverse=True)
        posicion = {id(f): i + 1 for i, f in enumerate(orden)}
        for f in filas:
            f[f"posicion_{eje}"] = posicion.get(id(f))
    for f in filas:
        # Con 7 AFP, "Sobresaliente" dice bastante menos que entre 42: la banda sola engaña.
        f["universo"] = n
        f["requiere_posicion_visible"] = n < MIN_UNIVERSO_SIN_POSICION

    filas.sort(key=lambda f: (f["ejecucion"] is not None, f["ejecucion"] or 0), reverse=True)
    return {"perfil": filas, "count": n}
