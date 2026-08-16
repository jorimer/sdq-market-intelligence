"""Operación de consola: vigilancia de la numeración fiscal.

La alerta por evento (``fiscal.sequence.low``) sólo se dispara **al emitir un comprobante**.
Si nadie compra durante semanas, un rango puede VENCER sin que nadie se entere — y el aviso
llegaría recién con la primera venta que ya no se puede numerar. Esta operación diaria mira
los rangos aunque no haya ventas, que es exactamente el caso que el evento no cubre.
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_fiscal_sequence_watch(params, user_id, set_phase) -> Dict:
    from shared.billing.events import FISCAL_SEQUENCE_LOW
    from shared.billing.fiscal.documents import pending_count
    from shared.billing.fiscal.sequences import list_sequences, sequences_needing_attention
    from shared.events.event_bus import event_bus

    db = SessionLocal()
    try:
        set_phase("revisando rangos de comprobante fiscal")
        todos = list_sequences(db)
        alertas = sequences_needing_attention(db)
        for s in alertas:
            event_bus.publish(FISCAL_SEQUENCE_LOW, {
                "regime": s["regime"], "doc_type": s["doc_type"],
                "remaining": s["remaining"],
                "exhausted": s["exhausted"] or s["expired"],
            })
        pendientes = pending_count(db)
        return {
            "rangos_cargados": len(todos),
            "rangos_usables": sum(1 for s in todos if s["usable"]),
            "alertas": [{"regime": s["regime"], "doc_type": s["doc_type"],
                         "remaining": s["remaining"], "expired": s["expired"],
                         "exhausted": s["exhausted"], "expiring_soon": s["expiring_soon"]}
                        for s in alertas],
            "cobros_sin_comprobante": pendientes,
        }
    finally:
        db.close()


register_operation(Operation(
    name="fiscal-sequence-watch",
    label="Vigilar la numeración fiscal (NCF/e-NCF)",
    description="Revisa a diario los rangos de comprobante autorizados por la DGII y avisa "
                "ANTES de que se agoten o venzan — incluso si no hubo ventas, que es cuando "
                "la alerta por venta no puede dispararse. Informa también cuántos cobros "
                "quedaron esperando número.",
    runner=_run_fiscal_sequence_watch,
    default_interval_hours=24,
))
