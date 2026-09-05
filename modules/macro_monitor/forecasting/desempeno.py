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

**Y «todavía no» no es lo mismo que «nunca».** El texto de sección vacía decía que ninguna
proyección había alcanzado su período de cierre — o sea, que los trimestres no habían
cerrado. Durante meses la verdad fue otra: las filas del BVAR apuntaban a `"pib_real"`, que
es el nombre de la variable en el bloque y no una serie, así que **no podían** cerrar. El
instrumento reportaba paciencia donde había una rotura. Lo que no puede puntuarse se LISTA
(`ledger.no_puntuables`): un veto silencioso se lee como que el eje no tiene track record.

**Hay DOS superficies que publican esta sección**, y arreglar una sola deja el documento
contradiciéndose: el eje macro la pide acá (`app/products_macro._track_record_md`) y el
producto de proyecciones la arma del snapshot (`products_forecast._md_desempeno`), que es
otro proceso y no ve la base. Por eso la prosa vive en CONSTANTES y los renglones los arma
`renglones_no_puntuables()` a partir de dicts: la segunda superficie no re-computa nada, se
ENTERA — el payload le lleva la lista ya resuelta.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import ledger as led
from modules.macro_monitor.forecasting.models import ForecastLog

TITULO = "Desempeño de nuestras proyecciones anteriores"

SIN_HISTORIAL = (
    "Todavía no hay pronósticos puntuados: ninguna de las proyecciones emitidas alcanzó su "
    "período de cierre con el dato observado publicado. Esta sección se llena sola a medida "
    "que los trimestres cierran, y aparece con o sin resultados — un desempeño que solo se "
    "publica cuando conviene no es un track record."
)

#: El encabezado de la lista de lo que NO va a cerrar. En constante y no incrustado: un
#: literal partido por ancho de línea deja de existir en el fuente aunque el valor sea
#: correcto, y un test que lo busque ahí falla sin motivo.
HAY_ROTAS = (
    "**Hay proyecciones emitidas que no van a cerrar solas.** No están esperando el "
    "trimestre: les falta algo que la puntuación necesita, y por eso se listan en vez de "
    "quedarse calladas. Mientras estén así no suman al track record, y el track record que "
    "esta sección muestra no las cuenta."
)

QUE_SI_SE_PUEDE_ESPERAR = (
    "El resto de las proyecciones sí se puntúa sola cuando el BCRD publica el trimestre; "
    "esta sección aparece igual, con o sin resultados."
)


@dataclass(frozen=True)
class FilaDeDesempeno:
    model_id: str
    target_series: str
    #: El horizonte RELATIVO del conjunto (`+1T`), no un trimestre calendario: es lo que
    #: hace comparables a las filas que se promedian.
    horizonte: str
    n_oos: int
    rmse: Optional[float]
    mae: Optional[float]
    #: ``((nivel, cobertura_observada, n), …)`` — la calibración empírica del intervalo.
    interval_coverage: Tuple[Tuple[float, float, int], ...]
    solapan: Optional[bool]


def filas(db: Session) -> List[FilaDeDesempeno]:
    """Un renglón por conjunto de backtest con al menos un pronóstico puntuado."""
    conjuntos: Dict[Tuple[str, str, int], None] = {}
    for f in (db.query(ForecastLog)
              .filter(ForecastLog.status == "scored", ForecastLog.h.isnot(None)).all()):
        conjuntos[(str(f.model_id), str(f.target_series), int(f.h))] = None
    salida: List[FilaDeDesempeno] = []
    for model_id, serie, paso in sorted(conjuntos):
        bt = led.backtest_id(model_id, serie, paso)
        horizonte = bt.rsplit("|", 1)[-1]
        tr = led.track_record(db, bt)
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


def como_dict(r: led.NoPuntuable) -> Dict[str, str]:
    """Lo que el snapshot transporta a la otra superficie. Incluye la EXPLICACIÓN ya
    resuelta: el que renderiza no tiene que saber traducir un código de motivo, y si tuviera
    que hacerlo aparecería una segunda tabla de motivos que se desincroniza con ésta."""
    return {"model_id": r.model_id, "target_series": r.target_series,
            "horizon": r.horizon, "motivo": r.motivo, "explicacion": r.explicacion}


def no_puntuables(db: Session) -> List[Dict[str, str]]:
    """Lo que no va a cerrar nunca, listo para viajar en el snapshot."""
    return [como_dict(r) for r in sorted(led.no_puntuables(db),
                                         key=lambda x: (x.model_id, x.target_series,
                                                        x.horizon))]


def renglones_no_puntuables(rotas: Sequence[Mapping[str, Any]]) -> List[str]:
    """El bloque en Markdown. Una sola implementación para las dos superficies."""
    if not rotas:
        return []
    return [HAY_ROTAS, ""] + [
        f"- `{r.get('model_id')}` → `{r.get('target_series')}` ({r.get('horizon')}): "
        f"{r.get('explicacion')}."
        for r in rotas
    ]


def seccion(db: Session) -> str:
    """El texto de la sección, en Markdown, computado."""
    return texto(filas(db), no_puntuables(db))


def texto(fs: Sequence[FilaDeDesempeno], rotas: Sequence[Mapping[str, Any]]) -> str:
    """El renderizador, sin base de datos: las dos superficies lo comparten.

    Que no tome `Session` es a propósito — el producto de proyecciones lo arma desde un
    snapshot ya congelado, y si esta función pidiera la base ese camino habría escrito su
    propia copia del texto. Ya lo hizo una vez: la frase «ninguna alcanzó su período de
    cierre» estaba duplicada literal en `products_forecast`, y el arreglo de acá no la
    tocaba.
    """
    if not fs:
        bloque = renglones_no_puntuables(rotas)
        if bloque:
            return "\n".join(bloque + ["", QUE_SI_SE_PUEDE_ESPERAR])
        return SIN_HISTORIAL

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

    # Lo roto va DEBAJO de la tabla y no en lugar de ella: con track record acumulándose,
    # una fila que no puede cerrar desaparecería del todo si solo se contara cuando la tabla
    # está vacía, y el `n` de arriba se leería como si fuera todo lo emitido.
    bloque = renglones_no_puntuables(rotas)
    if bloque:
        lineas.append("")
        lineas.extend(bloque)
    return "\n".join(lineas)
