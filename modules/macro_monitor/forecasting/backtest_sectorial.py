"""Backtest de la desagregación sectorial, contra la línea base que hay que vencer.

**Qué se está midiendo, y qué no.** El backtest alimenta el método con el crecimiento
REALIZADO del PIB, no con el proyectado. Es deliberado: separa el error de la desagregación
del error del agregado. Si se le pasara el PIB proyectado por el BVAR, el resultado mezclaría
dos modelos y no diría cuál de los dos falla. Lo que se responde acá es una sola pregunta:
**dado el agregado, ¿repartimos bien?**

Corolario que hay que decir cuando se publique: el error sectorial de un pronóstico REAL es
mayor que el de esta tabla, porque encima carga el error del BVAR sobre el agregado.

**La línea base es la proporción pura** —cada sector crece como el PIB—, que es lo que hace
cualquiera sin modelo. Si el método no le gana, se publica la proporción pura y se dice.

**La muestra es corta y se declara.** El cuadro por actividad arranca en 2018-Q1, el
interanual se come cuatro trimestres y el entrenamiento otros dieciséis: quedan trece cortes.
Trece no es mucho, y por eso lo primero que reporta `ResultadoSectorial` es su `n`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Tuple

from modules.macro_monitor.forecasting.sectoral import (
    LAMBDA, PanelSectorial, _persistencia_encogida, reconciliar,
)

#: Trimestres de entrenamiento antes del primer corte.
ARRANQUE = 16
#: Grilla con la que `elegir_lambda` re-mide el encogimiento dentro de una ventana.
GRILLA_LAMBDA: Tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


@dataclass(frozen=True)
class ResultadoSectorial:
    metodo: str
    #: Cortes evaluados. Se lee ANTES que el RMSE: con n chico, un RMSE es una anécdota.
    n_cortes: int
    n_componentes: int
    rmse: float
    #: RMSE de la proporción pura sobre los mismos cortes.
    rmse_base: float
    #: clave → RMSE del componente.
    por_componente: Dict[str, float]

    @property
    def mejora_pct(self) -> float:
        if self.rmse_base <= 0:
            return 0.0
        return (self.rmse_base - self.rmse) / self.rmse_base * 100

    @property
    def publica(self) -> bool:
        """Le gana a la proporción pura, o no se publica el método."""
        return self.rmse < self.rmse_base


def _corte(panel: PanelSectorial, t: int, prediccion: Callable[[Sequence[float]], float],
           reconciliar_: bool) -> Dict[str, float]:
    claves = list(panel.crecimiento)
    crudo = {k: prediccion(panel.crecimiento[k][:t]) for k in claves}
    if not reconciliar_:
        return crudo
    pesos = {k: panel.pesos[k][t] for k in claves}
    ajustado, _ = reconciliar(crudo, pesos, panel.pib[t])
    return ajustado


def _rmse(panel: PanelSectorial, prediccion: Callable[[Sequence[float]], float],
          reconciliar_: bool, arranque: int = ARRANQUE
          ) -> Tuple[float, Dict[str, float], int]:
    errores: Dict[str, List[float]] = {k: [] for k in panel.crecimiento}
    cortes = 0
    for t in range(arranque, len(panel.trimestres)):
        g = _corte(panel, t, prediccion, reconciliar_)
        for k, v in g.items():
            errores[k].append(v - panel.crecimiento[k][t])
        cortes += 1
    todos = [e for lst in errores.values() for e in lst]
    if not todos:
        return float("nan"), {}, 0
    global_ = (sum(e * e for e in todos) / len(todos)) ** 0.5
    por = {k: (sum(e * e for e in lst) / len(lst)) ** 0.5
           for k, lst in errores.items() if lst}
    return global_, por, cortes


def elegir_lambda(panel: PanelSectorial, hasta: int,
                  grilla: Sequence[float] = GRILLA_LAMBDA) -> float:
    """El encogimiento que minimiza el error DENTRO de la ventana ``[:hasta]``.

    Nunca mira más allá de `hasta`. Es la misma disciplina que λ₁ del BVAR: elegir un
    hiperparámetro con el error fuera de muestra a la vista produce un backtest que no se ve
    roto, se ve mejor.
    """
    mejor, mejor_error = LAMBDA, float("inf")
    for lam in grilla:
        errores: List[float] = []

        def con_este_lambda(historia: Sequence[float], _l: float = lam) -> float:
            return _persistencia_encogida(historia, _l)

        for t in range(8, hasta):
            g = _corte(panel, t, con_este_lambda, True)
            errores.extend(g[k] - panel.crecimiento[k][t] for k in g)
        if not errores:
            continue
        e = sum(x * x for x in errores) / len(errores)
        if e < mejor_error:
            mejor_error, mejor = e, float(lam)
    return mejor


def correr(panel: PanelSectorial, *, arranque: int = ARRANQUE) -> ResultadoSectorial:
    """El método contra la proporción pura, sobre los mismos cortes."""
    # La proporción pura no depende de la historia del sector sino del agregado, así que
    # no pasa por `_rmse`: su predicción es la misma para todos los componentes.
    errores_base: List[float] = []
    for t in range(arranque, len(panel.trimestres)):
        for k in panel.crecimiento:
            errores_base.append(panel.pib[t] - panel.crecimiento[k][t])
    base = ((sum(e * e for e in errores_base) / len(errores_base)) ** 0.5
            if errores_base else float("nan"))

    rmse, por, cortes = _rmse(panel, _persistencia_encogida, True, arranque)
    return ResultadoSectorial(
        metodo=f"persistencia_encogida(lambda={LAMBDA})+reconciliacion",
        n_cortes=cortes, n_componentes=len(panel.crecimiento),
        rmse=rmse, rmse_base=base, por_componente=por,
    )
