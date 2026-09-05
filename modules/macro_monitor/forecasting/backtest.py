"""El backtest del nowcast, y el único criterio que decide si se publica.

**Si no le gana a un random walk fuera de muestra, no se publica.** No es un umbral elegido:
es la definición de que el modelo aporta algo. Un nowcast que no mejora sobre «el próximo
trimestre crece lo mismo que el anterior» no tiene por qué existir, y publicarlo con un
intervalo bonito es peor que no publicarlo.

Ventana EXPANSIVA y corte point-in-time en cada paso: en la fecha `t` el modelo ve solo lo
que estaba publicado en `t`. Sin eso, el backtest se evalúa con información que en su momento
no existía y el track record es inventado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import nowcast as nowcast_mod
from modules.macro_monitor.forecasting import panel as panel_mod
from shared.data import medida_de_pronostico as med
from shared.data.periodos import fin_del_periodo


@dataclass(frozen=True)
class Resultado:
    model_id: str
    n_oos: int
    rmse: float
    mae: float
    rmse_random_walk: float
    #: Cuánto mejora sobre el random walk. ≤ 0 significa que NO aporta y no se publica.
    mejora_pct: float
    gana: bool


def _fechas_de_corte(db: Session, variante: int) -> List[date]:
    """Un corte por trimestre observado, en el día en que ese trimestre tenía exactamente
    *variante* meses de IMAE publicados."""
    imae = panel_mod.observaciones(db, panel_mod.IMAE_INDEX_CODE)
    por_trim: Dict[str, List[str]] = {}
    for p, _v in imae:
        por_trim.setdefault(panel_mod.trimestre_de(p), []).append(p)
    cortes = []
    for trimestre, meses in sorted(por_trim.items()):
        if len(meses) < variante:
            continue
        # el día siguiente a que se publique el mes número `variante` de ese trimestre
        publicado = fin_del_periodo(sorted(meses)[variante - 1])
        if publicado is not None:
            cortes.append(publicado + timedelta(days=panel_mod._LAG_IMAE + 1))
    return cortes


def correr(db: Session, *, variante: int, version: str = "v1") -> Optional[Resultado]:
    """Ventana expansiva sobre todos los cortes posibles. ``None`` si no hay nada que medir.

    Solo `m = 1` y `m = 2`: con los tres meses publicados el índice del PIB queda determinado
    por identidad y medirle «error» a una identidad da 0,0003 y «+100% sobre un random walk»,
    que presentado como desempeño de un modelo es de lo más engañoso que se puede publicar.
    Ver `nowcast.cifra_determinada`.
    """
    if variante == 3:
        raise ValueError("m=3 no se backtestea: es una identidad, no un modelo")
    # La MISMA realización con que el ledger puntúa. Antes esto recomputaba el Δlog a mano y
    # era la tercera copia de la transformación en el módulo; el ledger iba a ser la cuarta.
    # Si el backtest y el track record no realizan el observado igual, miden cosas distintas
    # y el informe publica las dos como si fueran comparables.
    #
    # Un cambio de conducta que vale la pena nombrar: `medida.realizar` exige el trimestre
    # ANTERIOR DE CALENDARIO, no «el anterior que haya». Con un hueco en la serie, esto
    # dejaba pasar una variación de dos trimestres rotulada de uno.
    observado_pib = dict(panel_mod.observaciones(db, panel_mod.PIB_CODE))
    dlog_obs: Dict[str, float] = med.serie_realizada(med.DLOG_PCT, observado_pib)

    errores, errores_rw = [], []
    for corte in _fechas_de_corte(db, variante):
        nc = nowcast_mod.estimar(db, corte, variante=variante, version=version)
        if nc is None or nc.horizon not in dlog_obs:
            continue
        real = dlog_obs[nc.horizon]
        errores.append(real - nc.point)
        # El random walk que hay que ganar: «el trimestre crece lo mismo que el anterior».
        p = panel_mod.construir(db, corte)
        previos = sorted(p.dlog_pib, key=lambda t: (fin_del_periodo(t) or date.min, t))
        if not previos:
            errores.pop()
            continue
        errores_rw.append(real - p.dlog_pib[previos[-1]] * 100)

    n = len(errores)
    if n == 0:
        return None
    rmse = math.sqrt(sum(e * e for e in errores) / n)
    rmse_rw = math.sqrt(sum(e * e for e in errores_rw) / n)
    mejora = (rmse_rw - rmse) / rmse_rw * 100 if rmse_rw > 0 else 0.0
    return Resultado(
        model_id=f"bridge_imae_pib.m{variante}.{version}", n_oos=n,
        rmse=round(rmse, 4), mae=round(sum(abs(e) for e in errores) / n, 4),
        rmse_random_walk=round(rmse_rw, 4), mejora_pct=round(mejora, 2),
        gana=rmse < rmse_rw,
    )
