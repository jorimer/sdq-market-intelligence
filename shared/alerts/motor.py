"""El barrido: productores por eje → gate → entrega, con todo lo vetado registrado.

**Por qué los ejes REGISTRAN su productor en vez de que este módulo los recorra.** `shared/`
no puede importar de `modules/` (dirección de dependencia, `CLAUDE.md`), así que cada eje
registra su función al importarse — el mismo patrón que ya usa
`shared/operations/freshness.py::register_freshness_audit`. Un eje sin productor simplemente
no aporta eventos: brecha honesta, no error.

**Por qué un productor devuelve también lo que EVALUÓ y no disparó.** Sin eso el dedup no
puede cerrar el ciclo: sabría callar una condición rota pero no reabrirla cuando se arregla
y vuelve a romperse, que es justo la señal más valiosa. Es la misma lección que
`_clear_notified` en la auditoría de frescura, y por eso el contrato la exige en vez de
dejarla opcional — un campo opcional que decide si una alerta vuelve a sonar se olvida.

**El reloj es el respaldo, no el disparador.** La operación tiene cadencia diaria, pero lo
que hace correr el barrido a tiempo es la CASCADA: las operaciones que producen dato declaran
``alerts-sweep`` en sus ``triggers``. Una alerta que llega un día después de que el dato entró
no es una alerta.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Set

from sqlalchemy.orm import Session

from shared.alerts import entrega, service
from shared.alerts.gate import juzgar
from shared.alerts.models import AlertEventRow
from shared.alerts.reglas import AlertEvent

logger = logging.getLogger("sdq.alerts.motor")


@dataclass
class Produccion:
    """Lo que un eje aporta a un barrido.

    ``evaluadas`` son las claves de dedup de TODAS las condiciones que se miraron, hayan
    disparado o no. Las que se miraron y no dispararon están resueltas, y su marcador se
    limpia para que puedan volver a avisar si recaen.
    """

    eventos: List[AlertEvent] = field(default_factory=list)
    evaluadas: Set[str] = field(default_factory=set)


ProductorFn = Callable[[Session], Produccion]
_PRODUCTORES: Dict[str, ProductorFn] = {}


def register_producer(sector_key: str, fn: ProductorFn) -> None:
    """Registra el productor de un eje (idempotente por eje). Lo llama el módulo del eje al
    importarse — NUNCA este paquete a un módulo."""
    _PRODUCTORES[sector_key] = fn
    logger.debug("alerts: productor registrado para '%s'", sector_key)


def registered_sectors() -> List[str]:
    return sorted(_PRODUCTORES)


def _persistir(db: Session, e: AlertEvent, publicada: bool, motivo: str | None,
               detalle: str, entregas: int) -> AlertEventRow:
    row = AlertEventRow(
        codigo=e.codigo, sector_key=e.sector_key, subject=e.subject, periodo=e.periodo,
        severidad=e.severidad, titulo=e.titulo, cuerpo=e.cuerpo, basis=e.basis,
        relaciones=dict(e.relaciones), valores=dict(e.valores),
        procedencia=dict(e.procedencia), frescura=e.frescura,
        publicada=publicada, veto_motivo=motivo, veto_detalle=detalle,
        dedup_key=e.clave_dedup, entregas=entregas)
    db.add(row)
    db.commit()
    return row


def run_alerts_sweep(db: Session) -> Dict[str, object]:
    """Corre todos los productores registrados y entrega lo que el gate aprueba.

    Devuelve un resumen con ``vetadas`` DESGLOSADO por motivo. Un barrido que solo dijera
    «0 entregadas» sería indistinguible de uno donde el gate frenó veinte señales, y esas
    dos situaciones piden acciones opuestas.
    """
    total_eventos = 0
    entregadas = 0
    publicadas = 0
    vetadas: Dict[str, int] = {}
    por_eje: Dict[str, int] = {}
    cupo: Dict[str, int] = {}

    for sector_key, productor in sorted(_PRODUCTORES.items()):
        try:
            prod = productor(db)
        except Exception as e:  # noqa: BLE001 — un eje que falla no aborta a los demás
            logger.warning("alerts: el productor de '%s' falló: %s", sector_key, e)
            continue

        disparadas = {ev.clave_dedup for ev in prod.eventos}
        por_eje[sector_key] = len(prod.eventos)
        total_eventos += len(prod.eventos)

        for ev in prod.eventos:
            veredicto = juzgar(ev)
            if not veredicto.publica:
                motivo = veredicto.motivo or "desconocido"
                vetadas[motivo] = vetadas.get(motivo, 0) + 1
                _persistir(db, ev, False, motivo, veredicto.detalle, 0)
                continue
            publicadas += 1
            # La fila del evento se crea ANTES de entregar: la entrega por correo apunta a
            # ella (no copia el texto), así que sin id persistido no habría a qué apuntar.
            # El contador de entregas se actualiza después, cuando se sabe.
            fila = _persistir(db, ev, True, None, "", 0)
            subs = service.para_sujeto(db, ev.sector_key, ev.subject)
            detalle = entrega.entregar(db, ev, subs, entregados_por_usuario=cupo,
                                       evento_id=str(fila.id))
            n = len(detalle["entregadas"])
            entregadas += n
            fila.entregas = n
            db.commit()

        # Lo que se evaluó y NO disparó está resuelto: se limpia su marcador para que pueda
        # volver a avisar si recae. Solo a los suscriptos del eje — limpiar de más es
        # barato, pero recorrer todos los usuarios de la plataforma no lo sería.
        resueltas = prod.evaluadas - disparadas
        if resueltas:
            uids = {str(s.user_id) for s in _suscriptos_del_eje(db, sector_key)}
            if uids:
                entrega.resolver(db, resueltas, uids)

    return {"eventos": total_eventos, "publicadas": publicadas, "entregadas": entregadas,
            "vetadas": vetadas, "por_eje": por_eje,
            "productores": registered_sectors()}


def _suscriptos_del_eje(db: Session, sector_key: str) -> List:
    from shared.alerts.models import AlertSubscription
    return (db.query(AlertSubscription)
            .filter(AlertSubscription.sector_key == sector_key,
                    AlertSubscription.active.is_(True))
            .all())


# ── La operación ─────────────────────────────────────────────────────────────

SWEEP_OP_NAME = "alerts-sweep"


def _run(params, user_id, set_phase) -> Dict[str, object]:
    from shared.database.session import SessionLocal

    db = SessionLocal()
    try:
        set_phase("evaluando señales suscriptas")
        return run_alerts_sweep(db)
    finally:
        db.close()


def register_sweep_operation() -> None:
    """Registra el barrido en la consola de operaciones (idempotente).

    ``default_interval_hours=24`` es el RESPALDO, no el disparador: lo que hace correr el
    barrido a tiempo es que las operaciones que producen dato lo declaren en sus
    ``triggers``. Un reloj diario sobre dato trimestral avisaría 90 veces lo mismo o llegaría
    un día tarde, según cuándo cayera.
    """
    from shared.operations.service import register_operation
    from shared.operations.service import Operation

    register_operation(Operation(
        SWEEP_OP_NAME, "Barrido de alertas",
        "Evalúa las señales de los ejes con vigilancias activas, las pasa por el gate de "
        "publicación y entrega lo aprobado a la bandeja de cada suscripto. Lo vetado se "
        "registra con su motivo en vez de desaparecer.",
        _run, default_interval_hours=24,
    ))


register_sweep_operation()


# ── La cascada ───────────────────────────────────────────────────────────────

# Operaciones que NO despiertan el barrido, y por qué cada una. La lista es de EXCLUSIÓN a
# propósito: el default es cascadear.
#
# La asimetría decide el diseño. Un barrido de más cuesta unas consultas y no produce nada
# —todas las reglas son de transición, así que sin cambio no hay evento—. Un barrido de
# menos cuesta que la alerta llegue un día tarde, que es justo lo que el producto promete no
# hacer. Con una lista de INCLUSIÓN, cada sync nuevo nacería mudo hasta que alguien se
# acordara de agregarlo; con una de exclusión, nace conectado y hay que justificar sacarlo.
# Este repo ya pagó dos veces hoy el precio de una lista que se desactualiza en silencio.
SIN_CASCADA: Dict[str, str] = {
    SWEEP_OP_NAME: "se dispararía a sí misma",
    "alerts-digest": "consume alertas, no produce dato",
    "data-freshness-audit": "audita frescura, no produce dato",
    "prewarm-report-cache": "calienta la caché de informes",
    "market-brief": "genera un documento, no mueve el panel",
    "source-research-agent": "propone fuentes; el sistema propone y el dueño dispone",
    "catalog-discovery": "descubre publicaciones candidatas, no las ingiere",
    "fiscal-sequence-watch": "vigila secuencias de NCF, ajeno al panel",
}


def enganchar_cascada() -> List[str]:
    """Hace que toda operación que produce dato despierte el barrido al terminar bien.

    **El reloj del barrido es el respaldo; esto es el disparador.** Una alerta que llega un
    día después de que el dato entró no es una alerta.

    Idempotente y sin tocar el framework de operaciones: `shared/operations` no debe conocer
    a `shared/alerts` (dirección de dependencia), así que es este módulo el que se engancha,
    igual que `register_freshness_audit` en la auditoría de frescura.

    Se llama UNA vez al arrancar, después de que todos los módulos registraron sus
    operaciones. Devuelve las enganchadas para que no haya que adivinar leyendo código.
    """
    from shared.operations.service import OPERATIONS

    enganchadas: List[str] = []
    for nombre, op in OPERATIONS.items():
        if nombre in SIN_CASCADA:
            continue
        if SWEEP_OP_NAME not in op.triggers:
            op.triggers.append(SWEEP_OP_NAME)
        enganchadas.append(nombre)
    logger.info("alerts: cascada enganchada en %d operación(es); %d excluidas",
                len(enganchadas), len(SIN_CASCADA))
    return sorted(enganchadas)
