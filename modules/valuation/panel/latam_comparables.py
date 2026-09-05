"""El panel de bancos cotizados de LATAM: su contrato, y el gate que lo mantiene cerrado.

**No es ingesta, es investigación.** No hay proveedor de datos de mercado conectado a esta
plataforma, y no es un descuido de cableado: P/B, volatilidad de resultados y capitalización
de bancos cotizados vienen de fuentes de mercado con licencia, no de un portal público. El
panel se ARMA, se versiona y se declara — igual que el de transacciones de T-VL-7.

**Por qué el gate y no un panel chico.** La regresión tiene cinco predictores. Con menos de
diez observaciones por predictor, el `R²` sube porque el modelo memoriza el panel, no porque
explique nada: un `R²` de 0,9 sobre veinte bancos y cinco variables es ruido con buena
apariencia. Y como el segundo motor existe para CONTRASTAR al Excess Return, uno mal estimado
no aporta una segunda opinión — aporta una coincidencia inventada.

Mientras el panel no llegue al mínimo, `pb_regression` no publica y el valor sale de un solo
motor, dicho así.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

#: Predictores del modelo, en el orden en que entran a la matriz.
PREDICTORES: Tuple[str, ...] = (
    "roe_pct",              # rentabilidad sobre patrimonio
    "crecimiento_pct",      # crecimiento del patrimonio
    "volatilidad_roe",      # desviación del ROE — castiga resultados erráticos
    "log_activos",          # tamaño, en logaritmo: la relación no es lineal en el nivel
    "calidad_cartera_pct",  # cartera al día sobre cartera bruta
)

#: Observaciones por predictor que hacen falta para que el `R²` signifique algo.
POR_PREDICTOR = 10
#: El mínimo del gate: cinco predictores × diez.
MINIMO_DE_BANCOS = len(PREDICTORES) * POR_PREDICTOR

PANEL_VACIO = (
    "El panel de comparables LATAM está vacío. No hay proveedor de datos de mercado "
    "conectado —P/B, volatilidad de resultados y capitalización de bancos cotizados vienen "
    "de fuentes con licencia, no de un portal público—, así que el panel se arma como "
    f"investigación y se versiona. Hacen falta {MINIMO_DE_BANCOS} bancos "
    f"({POR_PREDICTOR} por predictor) para que el R² diga algo."
)


@dataclass(frozen=True)
class Comparable:
    """Un banco cotizado del panel. Todos los campos son obligatorios: uno faltante lo saca
    de la regresión, y rellenarlo con la media del panel inventaría una observación."""

    ticker: str
    pais: str
    pb: float
    roe_pct: float
    crecimiento_pct: float
    volatilidad_roe: float
    log_activos: float
    calidad_cartera_pct: float
    #: De dónde salió y cuándo. Sin esto el panel es un montón de números sin linaje.
    fuente: str
    capturado_el: str


@dataclass(frozen=True)
class EstadoDelPanel:
    n: int
    suficiente: bool
    minimo: int
    motivo: str


#: El panel, hoy vacío. Se llena con investigación, no con un sync.
PANEL: Tuple[Comparable, ...] = ()


def estado(panel: Sequence[Comparable] = PANEL) -> EstadoDelPanel:
    """¿Alcanza para estimar? El gate se consulta ANTES de regresar, no después."""
    n = len(panel)
    if n >= MINIMO_DE_BANCOS:
        return EstadoDelPanel(n=n, suficiente=True, minimo=MINIMO_DE_BANCOS, motivo="")
    return EstadoDelPanel(
        n=n, suficiente=False, minimo=MINIMO_DE_BANCOS,
        motivo=(PANEL_VACIO if n == 0 else
                f"El panel tiene {n} banco(s) y hacen falta {MINIMO_DE_BANCOS} "
                f"({POR_PREDICTOR} por cada uno de los {len(PREDICTORES)} predictores): con "
                "menos, el R² sube porque el modelo memoriza el panel, no porque explique."))


def matriz(panel: Sequence[Comparable]) -> Tuple[List[List[float]], List[float]]:
    """`(X, y)` en el orden de `PREDICTORES`. `y` es el P/B observado."""
    X = [[getattr(c, p) for p in PREDICTORES] for c in panel]
    y = [c.pb for c in panel]
    return X, y
