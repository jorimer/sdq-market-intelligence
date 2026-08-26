"""Canal por el que los hallazgos del guard viajan del MOTOR a quien decide si publica.

**El problema que resuelve.** El motor de narrativa detecta, repara y —si el hallazgo
sobrevive— lo deja en ``NarrativeResult.guard_unsupported``. Pero los productos devuelven
``Dict[str, str]``: para cuando el ensamblador decide si entrega, esa información ya se perdió.
Cambiar ese contrato arreglaría dos módulos rompiendo diez.

Sin canal, cada superficie de entrega hacía lo único que podía: **volver a juzgar el texto por
su cuenta**. Y ahí estaba el defecto que costó tres informes vetados y dos arreglos que no
arreglaron nada — la superficie no tiene el contexto con el que se generó el texto, tiene el
snapshot. Medido sobre un Deep Dive real de Asociación Bonao:

    contexto de la sección (el que produjo el texto) ... 133 números, CON `razones`
    snapshot.payload (con el que se vetaba) ...........  55 números, SIN `razones`

La misma frase —«equivale al 132 % del promedio del sistema», que era la razón 1,32 servida—
PASA contra el primero y se MARCA contra el segundo. El motor no marcaba nada; el veto lo
levantaba el ensamblador mirando un contexto que nunca vio el número. Por eso servir la cifra
en el contexto (#947) y enseñarle al guard la familia de formas (#949) no movieron la aguja:
los dos arreglaron el lado que ya funcionaba.

**La regla que sale de eso: a un texto lo juzga quien tiene el contexto con el que se
escribió.** El motor ya corre los dos chequeos deterministas Y el juez semántico contra ese
contexto —es un superconjunto estricto de lo que hacía la superficie—, así que la superficie no
necesita re-juzgar: necesita ENTERARSE. Este módulo es el enterarse.

**Por qué el motor no decide solo.** Es transversal: lo usan los diez ejes y también el Pulse,
que es el nivel ABIERTO y por doctrina solo registra. La política —premium veta, abierto
registra— vive en quien conoce el nivel. Acá el motor solo REPORTA.

Mecanismo: un ``ContextVar`` acotado por un ``contextmanager``, el mismo patrón que
``shared/narrative/lang_context.py`` y que ``shared/observability/llm_ledger.attributed_to``.
Dos generaciones concurrentes no se ven entre sí: cada request corre en su propio contexto, y
anyio lo copia incluso para endpoints sync vía threadpool.

**Fuera del ``contextmanager``, ``registrar()`` no hace nada** — a propósito. Un job de fondo o
un test que llame al motor sin abrir el acumulador no acumula basura global.

Hay DOS canales y comparten esta mecánica en vez de duplicarla: una relación invertida y una
cifra sin respaldo son hallazgos distintos con políticas distintas, pero el modo de falla de
tener dos copias del mismo acumulador es conocido —«un guard existe en un motor y falta en el
otro», cinco instancias en este repo—. Ver ``relaciones_pendientes`` y ``cifras_pendientes``.
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Dict, Iterator, List

logger = logging.getLogger("sdq.narrative.hallazgos_pendientes")


class CanalDeHallazgos:
    """Un canal nombrado: su propio ``ContextVar``, su propio ``acumulando()``.

    No es una clase por gusto de abstraer: cada canal necesita un ``ContextVar`` DISTINTO
    —si compartieran uno, abrir el de cifras cerraría el de relaciones— y el resto de la
    mecánica es idéntica palabra por palabra.
    """

    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self._var: contextvars.ContextVar = contextvars.ContextVar(
            f"sdq_{nombre}_pendientes", default=None)

    @contextmanager
    def acumulando(self) -> Iterator[Dict[str, List[str]]]:
        """Abre el acumulador para una generación y lo devuelve ya drenable.

        El dict que entrega es el MISMO que se va llenando, así que el llamador lo lee
        después del bloque sin drenar explícitamente. Se restaura el token al salir para no
        filtrar estado a la generación siguiente del mismo contexto.
        """
        caja: Dict[str, List[str]] = {}
        token = self._var.set(caja)
        try:
            yield caja
        finally:
            self._var.reset(token)

    @contextmanager
    def asegurando(self) -> Iterator[Dict[str, List[str]]]:
        """Como ``acumulando()``, pero NO anida: si ya hay uno abierto, entrega ÉSE.

        Lo pide el guard de escritura de la caché de productos, que corre dentro de
        ``_narratives_cached``. Ese punto necesita ver los hallazgos aunque nadie de arriba
        haya abierto el canal —si no, un llamador que se saltee la ruta de entrega persiste
        en Postgres, y SIN TTL, texto que el motor marcó—. Pero abrir uno anidado sería peor
        que no abrir ninguno: la caja interna se descarta al salir y los hallazgos NUNCA
        llegarían a quien decide si se entrega. Reusar la de afuera es lo que preserva las
        dos garantías.
        """
        caja = self._var.get()
        if caja is not None:
            yield caja
            return
        with self.acumulando() as nueva:
            yield nueva

    def pendientes(self) -> Dict[str, List[str]]:
        """Lo acumulado HASTA ACÁ, sin cerrar el bloque ni vaciarlo.

        Lo necesita quien decide en medio de la generación —el guard de ESCRITURA de la caché
        de productos corre antes de que el bloque termine— y por eso no drena: el mismo
        hallazgo lo vuelve a leer, ya fuera del bloque, quien decide si se entrega.
        """
        caja = self._var.get()
        return dict(caja) if caja else {}

    def registrar(self, plantilla: str, hallazgos: List[str]) -> None:
        """Deposita los hallazgos de *plantilla*. No-op si nadie acumula.

        Best-effort por diseño: registrar un hallazgo jamás puede tumbar una generación que,
        por lo demás, salió bien.
        """
        try:
            caja = self._var.get()
            if caja is None or not hallazgos:
                return
            caja.setdefault(str(plantilla), []).extend(str(h) for h in hallazgos)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo registrar el hallazgo de %s en %s",
                             plantilla, self.nombre)
