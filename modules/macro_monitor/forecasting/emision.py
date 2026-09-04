"""Emitir las proyecciones al ledger. Es el paso que le da corriente al cableado.

Sin esto, `variable_signals()` leería un ledger vacío para siempre y toda la procedencia de
proyección quedaría construida y **sin ejercitar**: no hay forma de verificar un cableado que
nunca llevó corriente, y un camino que nadie recorrió es un camino que no funciona todavía —
en este repo ya pasó cinco veces con guardrails que vivían en el motor y no en la ruta.

**Qué se emite y qué no.**

* El **nowcast** del trimestre en curso, en sus dos variantes publicables. `m = 3` no se
  emite: con los tres meses del IMAE publicados el índice del PIB queda determinado por
  identidad aritmética, y darle una fila de pronóstico sería fabricarle un track record a una
  suma. Va por `nowcast.cifra_determinada`, que no tiene campo de intervalos.
* Del **BVAR**, solo los `pronosticos()` — los horizontes con track record. Los
  `escenarios()` no entran al ledger: `a_ledger()` lanza si recibe uno, y esa excepción es
  la defensa, no un accidente que haya que atrapar.

**Idempotente por la clave del ledger, no por un `if` acá.** Un rerun del mismo corte choca
contra el `UniqueConstraint` de cinco campos y se cuenta como omitido. Filtrar antes con una
consulta propia sería una segunda definición de «ya está», y dos definiciones del mismo hecho
se contradicen: la que vale es la de la base.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

import numpy as np
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import bloque, bvar, ledger, nowcast

logger = logging.getLogger("sdq.macro.forecasting.emision")

#: Serie objetivo del bloque. Es el nombre con que el BVAR la conoce, y el que viaja al
#: ledger como `target_series`.
OBJETIVO = "pib_real"
#: Las variantes de nowcast que se publican. `3` está deliberadamente fuera — ver el
#: docstring del módulo.
VARIANTES_PUBLICABLES: Tuple[int, ...] = (1, 2)


@dataclass(frozen=True)
class Emision:
    """Qué se escribió, qué se omitió por duplicado y qué no se pudo emitir.

    Los tres van juntos a propósito: un contador de escrituras que no distingue «no había
    nada que emitir» de «falló» deja pasar un trimestre en blanco sin que nadie se entere.
    """

    escritos: int
    omitidos_por_duplicado: int
    escenarios_no_registrados: int
    motivos: Tuple[str, ...] = ()

    @property
    def hubo_algo(self) -> bool:
        return self.escritos > 0 or self.omitidos_por_duplicado > 0


def _escribir(db: Session, *, model_id: str, horizonte: str, as_of: str, punto: float,
              intervalos: List[List[float]], objetivo: str = OBJETIVO) -> Optional[bool]:
    """``True`` escrito · ``False`` duplicado · ``None`` no se pudo."""
    try:
        ledger.registrar(db, model_id=model_id, target_series=objetivo, horizon=horizonte,
                         as_of=as_of, point=punto, intervals=intervalos)
        return True
    except IntegrityError:
        db.rollback()
        return False
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("no se pudo registrar %s %s: %s", model_id, horizonte, e)
        return None


def emitir(db: Session, *, as_of: Optional[date] = None) -> Emision:
    """Corre los modelos al corte *as_of* y escribe sus pronósticos al ledger."""
    corte = as_of or date.today()
    iso = corte.isoformat()
    escritos = omitidos = escenarios = 0
    motivos: List[str] = []

    # ── Nowcast del trimestre en curso ──────────────────────────────────────────────
    for variante in VARIANTES_PUBLICABLES:
        try:
            est = nowcast.estimar(db, corte, variante=variante)
        except Exception as e:  # noqa: BLE001
            motivos.append(f"nowcast m{variante}: {e}")
            continue
        if est is None:
            motivos.append(f"nowcast m{variante}: sin estimación para el corte {iso}")
            continue
        r = _escribir(db, model_id=est.model_id, horizonte=est.horizon, as_of=iso,
                      punto=est.point, intervalos=[list(t) for t in est.intervals],
                      objetivo=est.target_series)
        escritos += 1 if r is True else 0
        omitidos += 1 if r is False else 0
        if r is None:
            motivos.append(f"nowcast m{variante}: la escritura falló")

    # ── Trayectoria del BVAR ────────────────────────────────────────────────────────
    try:
        armado = bloque.armar(db)
        proy = bvar.proyectar_bloque(
            np.array([list(f) for f in armado.Y], dtype=float), armado.nombres,
            armado.trimestres[-1] if armado.trimestres else "",
            objetivo=OBJETIVO) if armado.trimestres else None
    except Exception as e:  # noqa: BLE001
        motivos.append(f"bvar: {e}")
        proy = None

    if proy is None:
        motivos.append("bvar: el bloque no alcanzó para proyectar")
    else:
        for p in proy.pronosticos():
            r = _escribir(db, model_id=p.model_id, horizonte=p.horizonte, as_of=iso,
                          punto=p.punto, intervalos=[list(t) for t in p.intervalos],
                          objetivo=p.target_series)
            escritos += 1 if r is True else 0
            omitidos += 1 if r is False else 0
            if r is None:
                motivos.append(f"bvar {p.horizonte}: la escritura falló")
        # Los escenarios se CUENTAN y no se escriben. Contarlos es lo que impide que
        # «no se emitió nada más allá de 2 trimestres» se lea como un fallo.
        escenarios = len(proy.escenarios())

    return Emision(escritos=escritos, omitidos_por_duplicado=omitidos,
                   escenarios_no_registrados=escenarios, motivos=tuple(motivos))
