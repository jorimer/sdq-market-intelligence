"""Sync de la obra pública adjudicada (DGCP, OCDS) — Fase 7.

Alimenta DOS ejes por EVENTO, no por import cruzado: escribe en `sector_observations` bajo
`construction` (toda la obra adjudicada) y bajo `energy` (la de las unidades de compra del sector
eléctrico), y publica `construction.updated` y `energy.updated` con los nombres de evento que
esos módulos ya usan. Vive en `shared/` porque ningún módulo es dueño de la fuente: un módulo
que importara al otro para escribirle las filas es lo que la arquitectura prohíbe.
"""
import logging
from typing import Dict, List, Tuple

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

logger = logging.getLogger("sdq.operations.obra_publica")

#: Serie → eje donde se publica. Un eje no lee las filas del otro.
EJE_DE_LA_SERIE: Dict[str, str] = {
    "dgcp.obras.adjudicaciones": "construction",
    "dgcp.obras.monto_contratado_dop": "construction",
    "dgcp.obras.sector_electrico.adjudicaciones": "energy",
    "dgcp.obras.sector_electrico.monto_contratado_dop": "energy",
}
EVENTO_DEL_EJE = {"construction": "construction.updated", "energy": "energy.updated"}


def escribir_obra_publica(db, registros, *, recuperado, source: str, license: str) -> Dict[str, int]:
    """Escribe las series en su eje. No commitea. Idempotente: borra y reescribe cada serie."""
    from shared.data.series_nature import infer_nature
    from shared.observations import service as obs

    por_eje: Dict[str, int] = {}
    codigos: List[Tuple[str, str]] = sorted({(EJE_DE_LA_SERIE[r.series], r.series) for r in registros})
    for eje, codigo in codigos:
        obs.borrar_serie(db, sector_key=eje, series_code=codigo)
    for r in registros:
        eje = EJE_DE_LA_SERIE[r.series]
        obs.upsert(db, sector_key=eje, series_code=r.series, period=r.period, value=r.value,
                   unit=r.unit, frequency="monthly", nature=infer_nature(r.unit, code=r.series),
                   source=source, license=license, published_at=recuperado)
        por_eje[eje] = por_eje.get(eje, 0) + 1
    return por_eje


def _run_obra_publica(params, user_id, set_phase) -> Dict:
    from shared.data.dgcp_ocds_client import DGCPOCDSClient
    from shared.events.event_bus import event_bus

    set_phase("descargando el OCDS de la DGCP (año en curso y anterior, mirror de OCP)")
    client = DGCPOCDSClient(mode="live")
    registros, recuperacion = client.leer()
    db = SessionLocal()
    try:
        set_phase("escribiendo la obra pública adjudicada en construcción y energía")
        por_eje = escribir_obra_publica(db, registros, recuperado=recuperacion.recuperado_el,
                                        source=client.source, license=client.license)
        db.commit()
    finally:
        db.close()
    for eje in por_eje:
        try:
            event_bus.publish(EVENTO_DEL_EJE[eje], {"origen": "dgcp-obras-sync",
                                                    "periodo": recuperacion.ultimo_mes_completo})
        except Exception:  # noqa: BLE001 — un suscriptor roto no deshace la ingesta
            logger.exception("evento %s de la obra pública no publicado", EVENTO_DEL_EJE[eje])
    return {"ultimo_mes": recuperacion.ultimo_mes_completo,
            "recuperado_el": (recuperacion.recuperado_el.isoformat()
                              if recuperacion.recuperado_el else None),
            "puntos_por_eje": por_eje}


register_operation(Operation(
    "dgcp-obras-sync", "Sincronizar obra pública adjudicada (DGCP, OCDS)",
    "Descarga el OCDS de Contrataciones Públicas del mirror de Open Contracting Partnership "
    "(año en curso y anterior), cuenta las obras adjudicadas por mes y suma su monto "
    "contratado, y lo publica en construcción (toda la obra) y en energía (las unidades de "
    "compra del sector eléctrico). Dato público real, ODbL.",
    # Mensual: OCP recupera la fuente una vez al mes. ⚠️ En prod manda la agenda GUARDADA.
    _run_obra_publica, default_interval_hours=720,
))
