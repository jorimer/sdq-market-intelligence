"""Operación de consola: el agente de descubrimiento de fuentes (Capa 3 Increment 3).

Agendable (recomendada semanal): lee las brechas vivas del readiness y puebla el tablero
de Inteligencia de Fuentes con propuestas evaluadas, sin disparo humano. El dueño decide.
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_research_agent(params, user_id, set_phase) -> Dict:
    from shared.source_intel.agent import run_research_agent
    db = SessionLocal()
    try:
        return run_research_agent(db, set_phase=set_phase)
    finally:
        db.close()


def _run_catalog_discovery(params, user_id, set_phase) -> Dict:
    from shared.source_intel.discoverer import run_catalog_discovery
    db = SessionLocal()
    try:
        return run_catalog_discovery(db, set_phase=set_phase)
    finally:
        db.close()


register_operation(Operation(
    name="source-research-agent",
    label="Agente de descubrimiento de fuentes",
    description="Lee las brechas vivas del readiness y propone (con IA) fuentes/información "
                "candidatas para cerrarlas, creándolas evaluadas en el tablero de "
                "Inteligencia de Fuentes. Idempotente por brecha (no re-propone lo abierto). "
                "Agendable (recomendada semanal); el dueño decide e integra.",
    runner=_run_research_agent,
    default_interval_hours=168,  # semanal
))

register_operation(Operation(
    name="catalog-discovery",
    label="Descubridor de catálogos (datos.gob.do)",
    description="Consulta la API del catálogo nacional CKAN (datos.gob.do) por cada brecha "
                "viva del readiness y crea sugerencias de datasets REALES verificados "
                "(título, organismo, URL, formato), evaluadas. A diferencia del agente IA "
                "(que propone desde conocimiento), aquí las fuentes existen y se citan. "
                "Idempotente por brecha; agendable (semanal). El dueño decide e integra.",
    runner=_run_catalog_discovery,
    default_interval_hours=168,
))
