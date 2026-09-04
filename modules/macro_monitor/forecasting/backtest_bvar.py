"""Backtest del BVAR: ventana expansiva, un ajuste por corte, y el random walk al lado.

**λ₁ se re-elige en cada corte, con la ventana de entrenamiento de ESE corte.** Elegirlo una
vez sobre la muestra entera y reusarlo metería en cada pronóstico información de trimestres
que en ese momento no existían — que es la contaminación que el spec marca como el riesgo
principal de este bloque.

**Lo que este backtest NO es.** Usa el corte por TRIMESTRE, no por fecha de publicación: al
proyectar desde el trimestre T supone conocido el PIB de T, que en la realidad se publica ~60
días después de cerrarlo. Es el diseño estándar de ventana expansiva y su optimismo está
acotado, pero se declara: el nowcast, que sí corta por fecha de publicación, existe
justamente para cubrir esos 60 días.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from modules.macro_monitor.forecasting import bvar


@dataclass(frozen=True)
class PorHorizonte:
    h: int
    n: int
    rmse: float
    rmse_random_walk: float
    mejora_pct: float
    cobertura_80: Optional[float]
    cobertura_90: Optional[float]


def correr(Y: np.ndarray, nombres: Sequence[str], trimestres: Sequence[str], *,
           objetivo: str = "pib_real", pasos: int = 8, p: int = 2,
           min_train: int = 40) -> List[PorHorizonte]:
    """Un resultado por horizonte. Sin datos suficientes devuelve lista vacía."""
    if objetivo not in nombres or len(Y) <= min_train + 1:
        return []
    i = list(nombres).index(objetivo)
    err: Dict[int, List[float]] = {h: [] for h in range(1, pasos + 1)}
    err_rw: Dict[int, List[float]] = {h: [] for h in range(1, pasos + 1)}
    hits: Dict[int, List[Tuple[bool, bool]]] = {h: [] for h in range(1, pasos + 1)}

    for corte in range(min_train, len(Y) - 1):
        ventana = Y[:corte]
        pr = bvar.proyectar_bloque(ventana, nombres, trimestres[corte - 1], pasos=pasos, p=p)
        if pr is None:
            continue
        # El random walk que hay que ganar: el objetivo se queda en su último valor conocido.
        rw = float(ventana[-1, i])
        for h in range(1, pasos + 1):
            t = corte - 1 + h
            if t >= len(Y):
                break
            real = float(Y[t, i])
            err[h].append(real - pr.puntos[h - 1])
            err_rw[h].append(real - rw)
            ints = pr.intervalos[h - 1]
            i80 = next(x for x in ints if x[0] == 0.80)
            i90 = next(x for x in ints if x[0] == 0.90)
            hits[h].append((i80[1] <= real <= i80[2], i90[1] <= real <= i90[2]))

    salida: List[PorHorizonte] = []
    for h in range(1, pasos + 1):
        es, rws, hs = err[h], err_rw[h], hits[h]
        if not es:
            continue
        rmse = math.sqrt(sum(e * e for e in es) / len(es))
        rmse_rw = math.sqrt(sum(e * e for e in rws) / len(rws))
        salida.append(PorHorizonte(
            h=h, n=len(es), rmse=round(rmse, 4), rmse_random_walk=round(rmse_rw, 4),
            mejora_pct=round((rmse_rw - rmse) / rmse_rw * 100, 2) if rmse_rw else 0.0,
            cobertura_80=round(sum(1 for a, _b in hs if a) / len(hs), 4) if hs else None,
            cobertura_90=round(sum(1 for _a, b in hs if b) / len(hs), 4) if hs else None,
        ))
    return salida
