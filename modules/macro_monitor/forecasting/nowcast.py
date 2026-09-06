"""Nowcast del PIB trimestral con el IMAE mensual — bridge equation.

Estima el trimestre en curso ~45-60 días antes de que el BCRD publique la cifra. Dos pasos:

**Paso 1 — completar el trimestre.** Si el trimestre tiene `m ∈ {1,2,3}` meses de IMAE
publicados, los `3−m` que faltan se imputan con un AR(p) univariado sobre el índice mensual,
estimado con información disponible al corte. Con `m = 3` este paso no corre.

**Paso 2 — agregar y regresar.**

    Δlog(PIB_t) = α + β·Δlog(IMAE_trimestral_t) + γ·Δlog(PIB_{t−1}) + ε

**Un solo regresor agregado, no tres coeficientes mensuales.** Tres betas mensuales libres son
MIDAS sin restricción, un diseño distinto; con ~77 trimestres gastan grados de libertad sin
ganancia demostrada. Bridge en v1; MIDAS, si se hace, se mide CONTRA éste y no en su lugar.

**DOS variantes, no tres.** `m = 1` y `m = 2` son dos modelos distintos —difieren en cuánto
imputa el paso 1— y cada uno lleva su `model_id` y su propia fila de backtest. Un nowcast con
un mes de información no tiene el mismo error que con dos, y reportar un promedio entre ellos
es engañar.

**`m = 3` NO es un modelo.** Medido sobre los 77 trimestres del corpus, el promedio trimestral
del índice del IMAE **ES** el índice de volumen del PIB: diferencia máxima 0,0015 puntos, y
exactamente 0,0 en casi todos. El BCRD construye el IMAE así, como indicador mensual calibrado
sobre el PIB trimestral. Con los tres meses publicados la cifra no se estima: se calcula.

El backtest lo delataba con un RMSE de 0,0003 y «+100% de mejora sobre un random walk» — un
número real que, presentado como desempeño de un modelo, sería de lo más engañoso que esta
plataforma podría publicar. Va por `cifra_determinada`, sin banda de error, y su valor es de
OPORTUNIDAD: queda determinada ~15 días antes de que el BCRD publique el PIB (45 días de
rezago del IMAE contra 60 del PIB).

Sin dependencias nuevas: OLS por mínimos cuadrados de numpy, que es lo que ya está.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import panel as panel_mod
from shared.data import medida_de_pronostico as med

#: Cuántos trimestres de entrenamiento antes de que el bridge diga algo. Con menos, el
#: coeficiente lo fija el ruido.
MIN_TRAIN = 20

#: Rezagos del AR que completa los meses faltantes. Tres cubre la estacionalidad corta del
#: índice sin gastar la muestra.
AR_LAGS = 3

#: Cuantiles normales de los dos niveles que el ledger puntúa. El intervalo es paramétrico;
#: si acierta o no es exactamente lo que mide `interval_coverage`, y por eso se publica.
_Z = {0.80: 1.2815515655446004, 0.90: 1.6448536269514722}


def _ols(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
    """Coeficientes y error estándar residual. Devuelve ``(beta, sigma)``."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    gl = max(len(y) - X.shape[1], 1)
    return beta, float(math.sqrt(float(resid @ resid) / gl))


def imputar_meses(mensual: Sequence[float], faltan: int, lags: int = AR_LAGS) -> List[float]:
    """Los *faltan* meses que el trimestre todavía no tiene, por AR(p) sobre el índice.

    Se estima con lo que había al corte y se proyecta hacia adelante recursivamente. Si no
    hay muestra para el AR, se repite el último valor — que es el random walk, y se declara
    como tal en vez de fingir un modelo.
    """
    xs = [float(v) for v in mensual]
    if faltan <= 0:
        return []
    if len(xs) < lags + 5:
        return [xs[-1]] * faltan if xs else []
    d = [math.log(xs[i]) - math.log(xs[i - 1]) for i in range(1, len(xs)) if xs[i - 1] > 0]
    if len(d) < lags + 3:
        return [xs[-1]] * faltan
    X = np.array([[1.0, *d[i - lags:i]] for i in range(lags, len(d))])
    y = np.array(d[lags:])
    beta, _ = _ols(X, y)
    hist, nivel, out = list(d), xs[-1], []
    for _ in range(faltan):
        paso = float(beta[0] + np.dot(beta[1:], hist[-lags:]))
        hist.append(paso)
        nivel = nivel * math.exp(paso)
        out.append(nivel)
    return out


#: Cuánto puede separarse el promedio trimestral del IMAE del índice del PIB antes de que la
#: identidad deje de valer. Lo medido es 0,0015 puntos sobre un índice de ~100; el umbral es
#: holgado a propósito —no hace falta afinarlo para distinguir «coinciden» de «no»— pero
#: existe: la identidad es un hecho EMPÍRICO sobre la fuente, no un teorema.
TOLERANCIA_IDENTIDAD = 0.05


@dataclass(frozen=True)
class CifraDeterminada:
    """El PIB de un trimestre con sus tres meses de IMAE publicados. NO lleva intervalo.

    Ponerle banda de error la disfrazaría de pronóstico. No lo es: es el promedio de tres
    números que ya se publicaron.
    """

    target_series: str
    horizon: str
    as_of: str
    indice: float                # el índice de volumen del trimestre
    #: Su variación contra el trimestre anterior, en %. Es la de la serie ORIGINAL sin
    #: desestacionalizar: depende de en qué trimestre cae, y por eso NO es la cifra citable.
    dlog_pct: Optional[float]
    es_identidad: bool = True
    #: La variación contra el MISMO trimestre del año anterior, en %: la medida que la
    #: entrada canónica del PIB declara citable. `None` si ese trimestre no está publicado —
    #: nunca cero.
    interanual_pct: Optional[float] = None
    #: Qué tan bien se cumplió la identidad en la historia disponible, para que quien lea la
    #: cifra pueda juzgar la afirmación en vez de creerla.
    diferencia_maxima_historica: float = 0.0
    n_trimestres_verificados: int = 0


def verificar_identidad(db: Session) -> Dict[str, float]:
    """¿El promedio trimestral del IMAE sigue siendo el índice del PIB?

    Se comprueba contra el dato en cada corrida y no se supone: el día que el BCRD cambie
    cómo construye el IMAE, la «cifra determinada» pasaría a ser una mentira, y hay que
    enterarse por acá y no por un cliente.
    """
    pib = dict(panel_mod.observaciones(db, panel_mod.PIB_CODE))
    por_trim: Dict[str, List[float]] = {}
    for p, v in panel_mod.observaciones(db, panel_mod.IMAE_INDEX_CODE):
        por_trim.setdefault(panel_mod.trimestre_de(p), []).append(v)
    comunes = [t for t in pib if len(por_trim.get(t, [])) == 3]
    if not comunes:
        return {"n": 0, "diferencia_maxima": float("inf"), "se_cumple": False}
    peor = max(abs(sum(por_trim[t]) / 3 - pib[t]) for t in comunes)
    return {"n": len(comunes), "diferencia_maxima": peor,
            "se_cumple": peor <= TOLERANCIA_IDENTIDAD}


def cifra_determinada(db: Session, as_of: date) -> Optional[CifraDeterminada]:
    """El PIB del trimestre cuyos tres meses de IMAE ya se publicaron. ``None`` si no lo hay
    o si la identidad dejó de cumplirse — en cuyo caso no se publica nada, que es lo correcto:
    la afirmación depende de la identidad, no del promedio."""
    verificacion = verificar_identidad(db)
    if not verificacion["se_cumple"]:
        return None
    mensual = panel_mod.disponibles_al(
        panel_mod.observaciones(db, panel_mod.IMAE_INDEX_CODE), as_of, panel_mod._LAG_IMAE)
    pib = panel_mod.disponibles_al(
        panel_mod.observaciones(db, panel_mod.PIB_CODE), as_of,
        panel_mod.PIB_PUBLICATION_LAG_DAYS)
    por_trim: Dict[str, List[float]] = {}
    for p, v in mensual:
        por_trim.setdefault(panel_mod.trimestre_de(p), []).append(v)
    ya_publicados = {t for t, _v in pib}
    completos = [t for t, ms in sorted(por_trim.items())
                 if len(ms) == 3 and t not in ya_publicados]
    if not completos:
        return None
    t = completos[-1]
    indice = sum(por_trim[t]) / 3
    anterior = pib[-1][1] if pib else None
    dlog = (round((math.log(indice) - math.log(anterior)) * 100, 4)
            if anterior and anterior > 0 else None)
    # La interanual: contra el índice PUBLICADO del mismo trimestre del año anterior. Es la
    # medida citable; la trimestral de la serie original depende del calendario.
    mismo_del_anio_anterior = dict(pib).get(f"{int(t[:4]) - 1}{t[4:]}")
    interanual = (round((indice / mismo_del_anio_anterior - 1) * 100, 4)
                  if mismo_del_anio_anterior and mismo_del_anio_anterior > 0 else None)
    return CifraDeterminada(
        target_series=panel_mod.PIB_CODE, horizon=t, as_of=as_of.isoformat(),
        indice=round(indice, 6), dlog_pct=dlog, interanual_pct=interanual,
        diferencia_maxima_historica=round(float(verificacion["diferencia_maxima"]), 8),
        n_trimestres_verificados=int(verificacion["n"]),
    )


@dataclass(frozen=True)
class Nowcast:
    """La estimación de un trimestre, lista para entrar al ledger."""

    model_id: str
    #: El `series_code` observable contra el que se va a puntuar: el ÍNDICE de volumen del
    #: PIB. El punto no está en esa unidad — ver `measure`.
    target_series: str
    horizon: str
    as_of: str
    point: float                       # Δlog del PIB del trimestre, en %
    intervals: List[List[float]]
    n_train: int
    #: En qué medida está `point`. Es una TASA, y la serie contra la que se puntúa es un
    #: NIVEL (~133): sin declararlo, el ledger restaba una de la otra y el error salía del
    #: tamaño del índice.
    measure: str = med.DLOG_PCT


def _diseño(p: panel_mod.PanelTrimestral) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Matriz del bridge sobre los trimestres donde coinciden PIB e IMAE."""
    trimestres = sorted(set(p.dlog_pib) & set(p.dlog_imae))
    filas, ys, usados = [], [], []
    previos = sorted(p.dlog_pib)
    for t in trimestres:
        i = previos.index(t)
        if i == 0:
            continue
        filas.append([1.0, p.dlog_imae[t], p.dlog_pib[previos[i - 1]]])
        ys.append(p.dlog_pib[t])
        usados.append(t)
    return np.array(filas), np.array(ys), usados


def estimar(db: Session, as_of: date, *, variante: int, version: str = "v1"
            ) -> Optional[Nowcast]:
    """El nowcast del trimestre en curso con *variante* meses de IMAE. ``None`` si no hay
    con qué: no se estima a medias."""
    if variante == 3:
        raise ValueError(
            "m=3 no es una variante del modelo: con los tres meses de IMAE publicados el "
            "índice del PIB queda determinado por identidad (el promedio trimestral del IMAE "
            "ES el índice del PIB). Usar `cifra_determinada`, que no lleva banda de error.")
    base = panel_mod.construir(db, as_of)
    objetivo = base.trimestre_objetivo
    if objetivo is None or base.meses_del_trimestre_objetivo != variante:
        return None

    imputados: Dict[str, float] = {}
    faltan = 3 - variante
    if faltan:
        mensual = panel_mod.disponibles_al(
            panel_mod.observaciones(db, panel_mod.IMAE_INDEX_CODE), as_of,
            panel_mod._LAG_IMAE)
        valores = imputar_meses([v for _p, v in mensual], faltan)
        a, q = int(objetivo[:4]), int(objetivo[-1])
        meses_del_q = [(q - 1) * 3 + 1 + k for k in range(3)]
        ya = {int(p[5:7]) for p, _v in mensual if panel_mod.trimestre_de(p) == objetivo}
        pendientes = [m for m in meses_del_q if m not in ya]
        for mes, val in zip(pendientes, valores):
            imputados[f"{a}-{mes:02d}"] = val

    p = panel_mod.construir(db, as_of, imputados=imputados) if imputados else base
    X, y, _usados = _diseño(p)
    if len(y) < MIN_TRAIN or objetivo not in p.dlog_imae:
        return None
    beta, sigma = _ols(X, y)
    ultimo = sorted(p.dlog_pib)[-1] if p.dlog_pib else None
    if ultimo is None:
        return None
    x0 = np.array([1.0, p.dlog_imae[objetivo], p.dlog_pib[ultimo]])
    punto = float(x0 @ beta)
    intervals = [[niv, round((punto - z * sigma) * 100, 4), round((punto + z * sigma) * 100, 4)]
                 for niv, z in _Z.items()]
    return Nowcast(
        model_id=f"bridge_imae_pib.m{variante}.{version}",
        target_series=panel_mod.PIB_CODE, horizon=objetivo, as_of=as_of.isoformat(),
        point=round(punto * 100, 4), intervals=intervals, n_train=len(y),
    )
