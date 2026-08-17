"""Captura las instantáneas de las fuentes sub-nacionales que producción no alcanza.

Se corre **donde la fuente responde** (hoy: una máquina de trabajo, no Railway) y deja
los ficheros listos para comitear. Producción los usa cuando el vivo falla, declarando
siempre que está leyendo una foto y de qué fecha (ver :mod:`shared.data.snapshots`).

    python scripts/refresh_social_snapshots.py            # las dos
    python scripts/refresh_social_snapshots.py siuben     # solo una

Cada fuente es independiente: que una falle no debe impedir capturar la otra, porque los
motivos son distintos y se destraban en momentos distintos —``siuben.gob.do`` es un
bloqueo de red y el tablero Power BI del MINERD es una limitación de tasa que cede sola—.
Salida distinta de cero si alguna no se pudo capturar, para que se note.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Callable, Dict, List, Tuple

# El script se corre desde cualquier directorio; la raíz del repo tiene que estar en la
# ruta de import para alcanzar ``shared``.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("refresh_snapshots")


def _siuben() -> Tuple[List, str, str]:
    from shared.data.siuben_client import SOURCE, fetch_siuben_provincial

    rows = fetch_siuben_provincial()
    return rows, SOURCE, ("Cinco tableros provinciales del SIUBEN "
                          "(32 provincias, trimestral). Producción no alcanza "
                          "siuben.gob.do: ConnectTimeout desde Railway.")


def _minerd() -> Tuple[List, str, str]:
    # Los DOS niveles educativos y las TRES resoluciones geográficas —incluido el total
    # país—, que es la forma que la sync consume desde 2026-08-17. Capturar la forma vieja
    # dejaría un fichero que producción no sabe leer: el respaldo existiría y no serviría,
    # que es peor que no tenerlo porque nadie lo notaría hasta necesitarlo.
    from shared.data.minerd_coverage import SOURCE, fetch_minerd_coverage_levels

    rows = fetch_minerd_coverage_levels()
    return rows, SOURCE, ("Cobertura neta básica y secundaria por región, provincia y "
                          "TOTAL PAÍS (tablero Power BI del SIIE). La API anónima de "
                          "Power BI limita por tasa y devuelve 400 sin aviso, también "
                          "desde producción: sin esta instantánea, la sync trae 0 filas "
                          "cada vez que el tablero está limitando.")


FUENTES: Dict[str, Callable[[], Tuple[List, str, str]]] = {
    "siuben": _siuben,
    "minerd": _minerd,
}
# El nombre tiene que ser el MISMO que pide `live_or_snapshot` en la sync. Se comprueba
# en `shared/data/tests/test_snapshots.py`: un nombre que no coincide produce un respaldo
# huérfano — escrito, comiteado y jamás leído.
SNAPSHOT_NAMES = {"siuben": "siuben_provincial", "minerd": "minerd_coverage_levels"}


def main(argv: List[str]) -> int:
    from shared.data.snapshots import write_snapshot

    pedidas = [a for a in argv[1:] if not a.startswith("-")] or list(FUENTES)
    desconocidas = [p for p in pedidas if p not in FUENTES]
    if desconocidas:
        logger.error("fuentes desconocidas: %s (opciones: %s)",
                     desconocidas, ", ".join(FUENTES))
        return 2

    fallos = []
    for clave in pedidas:
        logger.info("→ capturando %s …", clave)
        try:
            rows, source, note = FUENTES[clave]()
        except Exception as e:  # noqa: BLE001 — best-effort por fuente
            logger.error("   %s FALLÓ: %s: %s", clave, type(e).__name__, str(e)[:180])
            fallos.append(clave)
            continue
        path = write_snapshot(SNAPSHOT_NAMES[clave], rows, source=source, note=note)
        logger.info("   %s: %d filas → %s", clave, len(rows), path.name)

    if fallos:
        logger.error("no se pudieron capturar: %s — reintentar cuando la fuente responda",
                     ", ".join(fallos))
        return 1
    logger.info("listo: comitear shared/data/snapshots/ para que producción las use")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
