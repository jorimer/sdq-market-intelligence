"""«Desempeño de nuestras proyecciones anteriores», computado del ledger.

**Va en el CUERPO del informe, no en anexo.** Es el `[Lock]` de §5 del spec, y la razón es
comercial antes que metodológica: el track record es el argumento de venta, no la letra
chica. Los primeros trimestres va a incomodar — ése es el costo de entrada del foso, y quien
no lo paga no lo tiene.

**Ninguna cifra se escribe a mano.** La doctrina del repo ya lo fija para las validaciones
—«un número copiado es un número que se desincroniza»— y acá vale igual: todo sale de
`ledger.track_record()`. Esta sección no es prosa que un modelo redacta, es una tabla que el
código computa; un modelo redactándola inventaría el número que la sección existe para
probar.

**Cuando no hay nada puntuado, la sección DICE que no hay nada.** No se omite. Omitirla el
trimestre en que el resultado es malo es la misma tentación que la puntuación manual, y una
sección que aparece y desaparece se lee como que el producto no tiene track record en vez de
que todavía no lo tiene.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import ledger as led
from modules.macro_monitor.forecasting.models import ForecastLog

TITULO = "Desempeño de nuestras proyecciones anteriores"

_SIN_HISTORIAL = (
    "Todavía no hay pronósticos puntuados: ninguna de las proyecciones emitidas alcanzó su "
    "período de cierre con el dato observado publicado. Esta sección se llena sola a medida "
    "que los trimestres cierran, y aparece con o sin resultados — un desempeño que solo se "
    "publica cuando conviene no es un track record."
)


@dataclass(frozen=True)
class FilaDeDesempeno:
    model_id: str
    target_series: str
    horizonte: str
    n_oos: int
    rmse: Optional[float]
    mae: Optional[float]
    #: ``((nivel, cobertura_observada, n), …)`` — la calibración empírica del intervalo.
    interval_coverage: Tuple[Tuple[float, float, int], ...]
    solapan: Optional[bool]


def filas(db: Session) -> List[FilaDeDesempeno]:
    """Un renglón por conjunto de backtest con al menos un pronóstico puntuado."""
    conjuntos: Dict[Tuple[str, str, str], None] = {}
    for f in db.query(ForecastLog).filter(ForecastLog.status == "scored").all():
        conjuntos[(str(f.model_id), str(f.target_series), str(f.horizon))] = None
    salida: List[FilaDeDesempeno] = []
    for model_id, serie, horizonte in sorted(conjuntos):
        tr = led.track_record(db, led.backtest_id(model_id, serie, horizonte))
        if not tr.get("n_oos"):
            continue
        salida.append(FilaDeDesempeno(
            model_id=model_id, target_series=serie, horizonte=horizonte,
            n_oos=int(tr["n_oos"]), rmse=tr.get("rmse"), mae=tr.get("mae"),
            interval_coverage=tuple(tr.get("interval_coverage") or ()),
            solapan=tr.get("overlapping"),
        ))
    return salida


def _calibracion(fila: FilaDeDesempeno) -> str:
    if not fila.interval_coverage:
        return "sin cobertura de intervalos puntuada"
    partes = []
    for nivel, observada, n in fila.interval_coverage:
        partes.append(f"el del {nivel:.0%} acertó el {observada:.0%} de las veces (n={n})")
    return "; ".join(partes)


def seccion(db: Session) -> str:
    """El texto de la sección, en Markdown, computado."""
    fs = filas(db)
    if not fs:
        return _SIN_HISTORIAL

    lineas = [
        "Cada proyección que publicamos queda registrada antes de conocerse el resultado, y "
        "se puntúa sola cuando el dato llega. Esto es lo que acumulamos hasta hoy:",
        "",
        "| modelo | serie | horizonte | n | RMSE | MAE | calibración del intervalo |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for f in fs:
        rmse = f"{f.rmse:.3f}" if f.rmse is not None else "—"
        mae = f"{f.mae:.3f}" if f.mae is not None else "—"
        lineas.append(f"| {f.model_id} | {f.target_series} | {f.horizonte} | {f.n_oos} | "
                      f"{rmse} | {mae} | {_calibracion(f)} |")

    lineas.append("")
    lineas.append(
        "El error medio y la calibración van juntos y no por separado: un modelo cuyo "
        "intervalo del 80 % acierta el 45 % de las veces está mal calibrado aunque su error "
        "medio sea bajo, y quien dimensione riesgo con ese intervalo se va a equivocar.")

    # El solapamiento se DECLARA. Doce pronósticos a ocho trimestres tomados trimestre a
    # trimestre comparten información y no son doce observaciones independientes; no se
    # corrige el conteo con una fórmula inventada, se dice.
    if any(f.solapan for f in fs):
        lineas.append(
            "En los conjuntos marcados, las ventanas de evaluación **se solapan**: los "
            "pronósticos comparten información entre sí, así que el `n` de la tabla es "
            "mayor que el número de observaciones independientes que lo sostienen.")
    return "\n".join(lineas)
