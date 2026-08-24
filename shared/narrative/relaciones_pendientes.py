"""Relaciones invertidas que SOBREVIVEN a la reparación, desde el motor hasta quien publica.

**El problema que resuelve.** El motor de narrativa detecta una comparación invertida, le pide
al modelo que la corrija y —desde 2026-08-24— le entrega la lectura correcta ya redactada para
que la copie. Si aun así el texto la contradice, hasta ahora el hallazgo moría ahí: se
escribía una línea de log y el informe se entregaba igual. Así salió publicada la §7 de un
Deep Dive de banca, afirmando que la capitalización contable «supera» al promedio de su grupo
cuando estaba por debajo, y contradiciendo a la §2 y a la §10 del mismo documento.

**Por qué hace falta un canal.** La marca no puede viajar por el valor de retorno: los
productos devuelven ``Dict[str, str]`` (``SectorProduct.narratives``), así que para cuando el
ensamblador decide si publica, la información ya se perdió. Cambiar ese contrato arreglaría
dos módulos rompiendo diez.

**Por qué el motor no decide solo.** Es transversal: lo usan los diez ejes y también el Pulse,
que es el nivel ABIERTO y por doctrina solo registra. Vetar desde el motor rompería el Pulse.
La política —premium veta, abierto registra— vive en el ensamblador, que es quien conoce el
nivel. Acá el motor solo REPORTA.

Mecanismo: un ``ContextVar`` acotado por un ``contextmanager``, el mismo patrón que
``shared/narrative/lang_context.py`` (que existe justamente para no tocar ~13 firmas de
endpoint) y que ``shared/observability/llm_ledger.attributed_to``. Dos generaciones
concurrentes no se ven entre sí: cada request corre en su propio contexto, y anyio copia el
contexto incluso para endpoints sync vía threadpool.

**Fuera del `contextmanager`, `registrar()` no hace nada** — a propósito. Un job de fondo o un
test que llame al motor sin abrir el acumulador no acumula basura global.
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Dict, Iterator, List

logger = logging.getLogger("sdq.narrative.relaciones_pendientes")

#: `{plantilla: [hallazgos]}` de la generación en curso. `None` = nadie está acumulando.
_PENDIENTES: contextvars.ContextVar = contextvars.ContextVar(
    "sdq_relaciones_pendientes", default=None,
)


@contextmanager
def acumulando() -> Iterator[Dict[str, List[str]]]:
    """Abre el acumulador para una generación y lo devuelve ya drenable.

    El dict que entrega es el MISMO que se va llenando, así que el llamador lo lee después
    del bloque sin tener que drenar explícitamente. Se restaura el token al salir para no
    filtrar estado a la generación siguiente del mismo contexto.
    """
    caja: Dict[str, List[str]] = {}
    token = _PENDIENTES.set(caja)
    try:
        yield caja
    finally:
        _PENDIENTES.reset(token)


def registrar(plantilla: str, hallazgos: List[str]) -> None:
    """Deposita los hallazgos de relación de *plantilla*. No-op si nadie acumula.

    Best-effort por diseño: registrar un hallazgo jamás puede tumbar una generación que, por
    lo demás, salió bien.
    """
    try:
        caja = _PENDIENTES.get()
        if caja is None or not hallazgos:
            return
        caja.setdefault(str(plantilla), []).extend(str(h) for h in hallazgos)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo registrar la relación pendiente de %s", plantilla)
