"""Prosa de PROCEDENCIA generada desde el registro — no escrita a mano.

Por qué existe (lección del Hallazgo 7, 2026-07-22): un texto curado que **afirma** de qué
está hecho el índice ("es dato real", "corre sobre rúbrica") envejece solo, sin que nadie
lo toque, porque cada conector nuevo lo vuelve un poco más falso. Pasó en los dos sentidos
a la vez: el ``rationale`` del IAI declaraba como rúbrica cuatro variables que ya eran
reales, mientras el prompt de doctrina del IRC afirmaba "100% dato real" de un índice cuya
dimensión de transición cae a rúbrica cada vez que el sync de Ember falla.

La conclusión que ordena este módulo: **la procedencia no es un hecho que se pueda
escribir, es un estado que cambia en cada corrida.** Por lo tanto:

- La prosa curada (``rationale`` de la doctrina) declara solo lo DURABLE: qué mide la
  dimensión y por qué pesa lo que pesa. Eso no caduca.
- La frase de procedencia se GENERA acá, desde el mismo registro que gobierna el gate de
  honestidad. No puede divergir de la verdad porque no es una segunda fuente de verdad.
- Un gate de CI (``shared/knowledge/corpus/tests``) impide que el vocabulario de
  procedencia vuelva a colarse en la prosa curada.

Registro neutro (docs REPORT_STANDARD + ``REGISTER_NEUTRO``): español latinoamericano sin
anglicismos, tono advisory, sin adjetivos de venta.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from shared.data.medida_de_pronostico import COMO_SE_LEE
from shared.registry.signals import (
    COVERAGE_INDEX,
    COVERAGE_INSTRUMENT,
    COVERAGE_PROJECTION,
    GAP,
    NATIONAL,
    PROJECTED,
    REAL,
    RUBRIC,
    AxisRegistry,
    VariableSignal,
)


def _pct(x: float) -> str:
    return f"{round(float(x) * 100):.0f}%"


def _join(items: Sequence[str]) -> str:
    """Enumera en español: "a", "a y b", "a, b y c"."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} y {items[-1]}"


def _labels(signals: Iterable[VariableSignal]) -> List[str]:
    return [(s.label or s.key) for s in signals]


#: Titular de procedencia POR SEMÁNTICA de cobertura. La frase de índice afirmaba «del peso
#: de este índice» para todos los ejes, y en el de evaluación de leyes eso es sencillamente
#: falso: ese eje no arma un índice, mide cuántas de las metas de una ley tienen dato. La
#: frase salía en la Metodología del informe y en el payload de calidad de la API paga.
#: Vive en constantes y no incrustada en la función porque un literal partido por ancho de
#: línea deja de existir en el fuente aunque el valor sea correcto.
FRASE_COBERTURA_INDICE = (
    "{pct} del peso de este índice se sostiene en dato real con fuente citable; el resto se "
    "declara como supuesto de casa o como brecha, y nunca se completa con un valor fabricado."
)
FRASE_COBERTURA_INSTRUMENTO = (
    "{pct} de los indicadores que el propio instrumento se fijó tienen hoy una fuente "
    "verificada que los mide; el resto se declara como brecha con su motivo, y ninguno se "
    "completa con una serie parecida. Esta cobertura no es comparable con la de un índice "
    "de la plataforma: mide metas del instrumento, no peso anclado a dato real."
)
FRASE_COBERTURA_PROYECCION = (
    "{pct} de lo que este eje publica está sostenido por un pronóstico que pasa el gate de "
    "admisibilidad o por una cifra determinada por identidad; el resto se sirve rotulado "
    "como escenario o como brecha, con su motivo. Esta cobertura no es comparable con la de "
    "un índice de la plataforma: acá el índice ES la proyección, así que mide admisibilidad "
    "del pronóstico, no peso anclado a dato medido."
)

#: `coverage_kind` → su frase de PROCEDENCIA. Es un mapa y no una cadena de `if` para que
#: agregar una semántica sin su frase FALLE en vez de heredar la de índice en silencio. Lo
#: vigila `shared/products/tests/test_la_frase_de_cobertura_dice_lo_que_el_eje_mide.py`, que
#: cruza este mapa contra el de metodología y contra el vocabulario entero.
FRASES_COBERTURA_PROCEDENCIA = {
    COVERAGE_INDEX: FRASE_COBERTURA_INDICE,
    COVERAGE_INSTRUMENT: FRASE_COBERTURA_INSTRUMENTO,
    COVERAGE_PROJECTION: FRASE_COBERTURA_PROYECCION,
}


def coverage_sentence(axis: AxisRegistry) -> str:
    """Una frase con la cobertura del eje, en los términos de LO QUE ESE EJE MIDE.

    Es el titular de procedencia, y por eso no puede ser genérico: decirle a un cliente que
    «el 5,6% del peso de este índice se sostiene en dato real» cuando el producto evalúa el
    cumplimiento de una ley describe mal el producto que está comprando.
    """
    plantilla = FRASES_COBERTURA_PROCEDENCIA.get(axis.coverage_kind, FRASE_COBERTURA_INDICE)
    # Cuál cobertura, no solo cuál frase. En un eje de proyección `coverage_real` es 0 por
    # construcción —una proyección nunca es REAL— así que la frase saldría diciendo 0% junto
    # a una metodología que dice otra cosa. Es el defecto original en chico: dos números bajo
    # la misma palabra, en la misma página.
    cobertura = (axis.coverage_anclada if axis.coverage_kind == COVERAGE_PROJECTION
                 else axis.coverage_real)
    return plantilla.format(pct=_pct(cobertura))


def scope_sentence(axis: AxisRegistry) -> str:
    """Distingue lo que DIFERENCIA entre sujetos de lo que solo sostiene el nivel.

    Es el matiz que "dato real" oculta: una variable nacional es dato real y sin embargo
    aporta la misma lectura a todos los sujetos del panel, así que no explica por qué uno
    puntúa distinto de otro. Sin esta frase, el cliente atribuye a su sector una diferencia
    que en realidad no existe.
    """
    real = [s for s in axis.signals if s.state == REAL]
    national = [s for s in real if s.scope == NATIONAL]
    if not national:
        return ""
    per_subject = [s for s in real if s.scope != NATIONAL]
    txt = (f"De las variables con dato real, {_join(_labels(national))} "
           f"{'se miden' if len(national) > 1 else 'se mide'} a nivel país: "
           f"{'aportan' if len(national) > 1 else 'aporta'} la misma lectura a todos los "
           f"casos comparados, de modo que "
           f"{'sostienen' if len(national) > 1 else 'sostiene'} el nivel del índice pero no "
           f"{'explican' if len(national) > 1 else 'explica'} las diferencias entre ellos.")
    if per_subject:
        txt += (f" Lo que sí diferencia un caso de otro es {_join(_labels(per_subject))}.")
    return txt


def limits_sentence(axis: AxisRegistry) -> str:
    """Declara explícitamente lo que HOY no es dato real, con su razón cuando la hay."""
    rubric = [s for s in axis.signals if s.state == RUBRIC]
    gap = [s for s in axis.signals if s.state == GAP]
    parts: List[str] = []
    if rubric:
        notes = {s.note for s in rubric if s.note}
        why = f" ({_join(sorted(notes))})" if notes else ""
        parts.append(
            f"{_join(_labels(rubric))} {'siguen' if len(rubric) > 1 else 'sigue'} siendo un "
            f"supuesto neutral de casa{why}: se declara como tal y no discrimina entre casos.")
    if gap:
        parts.append(
            f"{_join(_labels(gap))} no {'tienen' if len(gap) > 1 else 'tiene'} dato en este "
            f"período y se {'reportan' if len(gap) > 1 else 'reporta'} como brecha, no como cero.")
    return " ".join(parts)


def partial_coverage_sentence(axis: AxisRegistry) -> str:
    """Declara la parcialidad de una variable real que solo cubre a algunos sujetos."""
    partial = [s for s in axis.signals
               if s.state == REAL and 0.0 < float(s.real_fraction) < 1.0]
    if not partial:
        return ""
    detail = _join([f"{s.label or s.key} ({_pct(s.real_fraction)} de los casos)"
                    for s in partial])
    return (f"Con cobertura parcial: {detail}. Donde la fuente no llega, la variable queda "
            f"ausente en vez de rellenarse.")


def projection_sentence(axis: Optional[AxisRegistry]) -> str:
    """Lo que hay que decir de una proyección para que el lector pueda juzgarla.

    Cuatro elementos, y ninguno es opcional:

    * la **unidad** del punto y de su banda. Sin ella la cifra se lee en la que el lector
      suponga, y para el PIB la natural —el nivel del índice— es la equivocada.
    * el **error** del backtest, EN LA MISMA FRASE que la proyección. Enterrarlo en una
      sección de limitaciones al final es la práctica que esta plataforma existe para no
      repetir: quien lee la cifra y sigue leyendo ya se formó la idea.
    * la **calibración empírica** del intervalo. Un intervalo del 80% que acierta el 45% de
      las veces engaña a quien dimensiona riesgo con él, por bajo que sea el RMSE.
    * el **solapamiento**, cuando existe. Un `n` grande sugiere una precisión que ventanas
      correlacionadas no sostienen. Cuando no se solapan, la cláusula se OMITE — escribir
      «no se solapan» es ruido.
    * el **corte de información**, que es lo que separa un pronóstico de un ajuste hecho con
      datos que entonces no se tenían.

    Solo se narra lo que ANCLA: una proyección que el gate rechaza no se cuenta a medias.
    """
    from shared.registry.projection import projection_is_admissible

    if axis is None or not axis.signals:
        return ""
    frases: List[str] = []
    for s in axis.signals:
        if s.state != PROJECTED or s.projection is None:
            continue
        m = s.projection
        ok, _motivo = projection_is_admissible(m)
        if not ok:
            continue
        nivel, lo, hi = sorted(m.intervals, key=lambda i: i[0])[0]
        # La UNIDAD va pegada a las cifras. «entre 3.1 y 4.7» sin ella se lee en la unidad
        # que el lector suponga, y para el PIB la suposición natural —el nivel del índice—
        # es la equivocada: lo que se proyecta es su variación. Y el PUNTO se publica: era
        # la única cifra que la frase omitía, y es justamente la que después se cita.
        como = COMO_SE_LEE.get(str(m.measure or ""), "")
        unidad = f" {como}" if como else ""
        partes = [
            f"La proyección de {s.label or s.key} para {m.horizon} sale del modelo "
            f"{m.model_id}: {m.point}{unidad}, con intervalo de {_pct(nivel)} entre "
            f"{lo} y {hi}."
        ]
        cobertura = {lv: (cob, n) for lv, cob, n in m.interval_coverage}
        if nivel in cobertura:
            cob, _n = cobertura[nivel]
            partes.append(
                f"Ese modelo erró en promedio {m.oos_error} "
                f"({m.error_metric.upper()}) en {m.n_oos} períodos fuera de muestra, y su "
                f"intervalo de {_pct(nivel)} contuvo al dato observado en {_pct(cob)} de "
                f"esos casos."
            )
        else:
            partes.append(f"Ese modelo erró en promedio {m.oos_error} "
                          f"({m.error_metric.upper()}) en {m.n_oos} períodos fuera de "
                          f"muestra.")
        if m.n_oos_overlapping:
            partes.append(
                f"Las ventanas de evaluación se solapan, así que esos {m.n_oos} períodos "
                f"no son {m.n_oos} observaciones independientes."
            )
        partes.append(f"La estimación usa información disponible al {m.as_of} y no "
                      f"incorpora nada posterior.")
        frases.append(" ".join(partes))
    return " ".join(frases)


def provenance_paragraph(axis: Optional[AxisRegistry]) -> str:
    """El párrafo completo de procedencia del eje, listo para la sección de Metodología.

    Devuelve cadena vacía si el eje no expone señal por-variable — silencio honesto antes
    que una afirmación que no podemos sostener.
    """
    if axis is None or not axis.signals:
        return ""
    if axis.degraded:
        # El eje no descompone por variable: solo se puede hablar a nivel agregado.
        return coverage_sentence(axis)
    parts = [
        coverage_sentence(axis),
        partial_coverage_sentence(axis),
        scope_sentence(axis),
        # La proyección va ANTES de los límites: su error viaja en su propia frase, no en la
        # sección donde se guardan las salvedades.
        projection_sentence(axis),
        limits_sentence(axis),
    ]
    return " ".join(p for p in parts if p)


def provenance_for_sector(db, sector_key: str) -> str:
    """Párrafo de procedencia de un sector, resuelto contra el registro en vivo.

    Defensivo por construcción: cualquier fallo devuelve cadena vacía. Es una sección
    informativa del reporte — nunca debe tumbar la entrega.
    """
    try:
        from shared.registry.service import build_data_registry

        registry = build_data_registry(db)
        for axis in registry.axes:
            if axis.sector_key == sector_key:
                return provenance_paragraph(axis)
    except Exception:  # noqa: BLE001 — la metodología nunca rompe el reporte
        return ""
    return ""
