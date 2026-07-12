"""Fase 6 — empaquetado comercial del tier de research custom.

docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §5 Fase 6 · §7. El tier nuevo (entre DD Express y DD
Full) NO inventa su propio mecanismo de precio: es un **informe especial cotizado a
medida**, así que reutiliza la familia ``special:{slug}`` del tarifario v2
(``shared/billing/skus``) y su precio vive en el modelo ``Tariff`` como cualquier otro
SKU — publicable/editable por el dueño en el tarifario, auditable e histórico.

"Activar" el tier = publicar una tarifa para su SKU (``create_tariff``). "Sin precio" =
no hay tarifa vigente → ``price_for`` devuelve ``None`` y el tier está inactivo. El precio
inicial es PROVISIONAL y se recalibra con los números del piloto (Fase 5), pero vive donde
viven todos los precios: el tarifario. Regla del dueño: el precio no se hardcodea en código
([[pricing-model-per-sector-intervals]]).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from shared.billing.skus import INTERVAL_ONCE, special_sku

# Identidad del SKU en el tarifario. Slug con guion (el regex de ``special:`` no admite
# guion bajo). Es un ``special:`` → sin grant automático de catálogo: la entrega la media
# el analista (acelerador del DD), no un acceso self-serve.
RESEARCH_CUSTOM_SLUG = "research-custom"
RESEARCH_CUSTOM_SKU = special_sku(RESEARCH_CUSTOM_SLUG)   # "special:research-custom"
RESEARCH_CUSTOM_NAME = "SDQ Research a Medida"
# Posicionamiento declarado por el spec (entre estos dos SKUs ya tarifados).
POSITION_BETWEEN = ("dd_express", "dd_full")


def packaging_status(db: Session) -> Dict[str, Any]:
    """Estado comercial del tier, LEÍDO del tarifario. ``enabled`` = hay tarifa vigente
    para el SKU; ``price_usd`` = su monto. Sin tarifa → inactivo (no se inventa precio)."""
    from shared.billing.tariffs import price_for

    row = price_for(db, RESEARCH_CUSTOM_SKU, INTERVAL_ONCE)
    price = float(row.amount) if row is not None else None
    return {
        "sku": RESEARCH_CUSTOM_SKU,
        "name": RESEARCH_CUSTOM_NAME,
        "enabled": row is not None,
        "price_usd": price,
        "currency": row.currency if row is not None else None,
        "interval": INTERVAL_ONCE,
        "positioned_between": list(POSITION_BETWEEN),
        "note": (row.note if row is not None else
                 "Sin tarifa vigente: el tier está inactivo hasta que el dueño publique un "
                 "precio en el tarifario (provisional, recalibrable con el piloto — §6)."),
    }


def set_provisional_price(db: Session, amount_usd: float, *,
                          created_by: Optional[str] = None) -> Dict[str, Any]:
    """Publica el precio PROVISIONAL del tier en el tarifario (una fila ``Tariff``).

    Es un envoltorio delgado sobre ``create_tariff`` que fija el SKU/label/nota correctos;
    la validación de precio > 0 y de SKU la hace el propio tarifario. El monto lo decide el
    dueño (aquí no hay default) y queda marcado como provisional para recalibrar en Fase 5.
    """
    from shared.billing.tariffs import create_tariff

    return create_tariff(
        db, sku=RESEARCH_CUSTOM_SKU, amount=amount_usd, currency="USD",
        interval=INTERVAL_ONCE, label=RESEARCH_CUSTOM_NAME,
        note="Provisional — recalibrar con los números del piloto (Fase 5).",
        created_by=created_by,
    )
