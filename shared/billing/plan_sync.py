"""Sincronización automática tarifario → billing plans de PayPal.

PayPal solo cobra suscripciones contra un *Billing Plan* pre-creado (con su monto y
periodicidad propios). Hasta ahora el dueño los creaba a mano en el dashboard y los
mapeaba en /admin/pagos — con el riesgo de que el catálogo muestre un precio y PayPal
cobre otro. Este módulo lo automatiza: para cada SKU de suscripción con precio vigente
en el tarifario, garantiza que exista un plan de PayPal ACTIVO con ESE monto y lo deja
mapeado en ``paypal_plans``.

Reglas:
- El plan mapeado coincide (monto+moneda, ACTIVE) → no se toca ("ok").
- No hay plan, o el monto/moneda difiere, o el plan no está ACTIVE → se crea un plan
  NUEVO (el Product de PayPal del SKU se crea una vez y se reutiliza), se remapea, y el
  plan viejo se DESACTIVA — sus suscriptos existentes siguen cobrando su precio; el
  precio nuevo rige para suscripciones nuevas (misma semántica que el tarifario, que
  nunca reescribe el histórico).
- SKU de suscripción SIN precio vigente → se salta ("sin_precio"): no se vende, no
  necesita plan.
- Best-effort por SKU: un fallo de PayPal en un plan no aborta el resto; queda en el
  reporte como "error".

Las compras puntuales (deep_dive:*) no usan planes: quedan fuera.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.billing.providers import get_provider
from shared.billing.providers.base import ProviderError
from shared.billing.skus import catalog_skus
from shared.billing.tariffs import price_for

logger = logging.getLogger("sdq.billing.plan_sync")

_SUB_INTERVALS = ("monthly", "annual")


def _fmt_amount(value: Any) -> str:
    return f"{float(value):.2f}"


def _plan_matches(plan: Dict[str, Any], amount: str, currency: str) -> bool:
    try:
        return (str(plan.get("status", "")).upper() == "ACTIVE"
                and plan.get("value") is not None
                and float(plan["value"]) == float(amount)
                and str(plan.get("currency_code") or "").upper() == currency.upper())
    except (TypeError, ValueError):
        return False


def sync_paypal_plans(db: Session, provider=None) -> Dict[str, Any]:
    """Reconcilia los planes de PayPal con el tarifario vigente. Devuelve el reporte
    ``{enabled, results: [{sku, interval, action, plan_id?, amount?, detail?}], plans}``.

    ``action`` ∈ ok | created | sin_precio | error. Idempotente: correrla dos veces
    seguidas deja "ok" en todo."""
    from shared.settings.service import (
        get_paypal_config, get_paypal_products, set_paypal_config, set_paypal_products,
    )

    provider = provider or get_provider(db)
    if not provider.is_configured():
        return {"enabled": False, "results": [], "plans": {}}

    cfg = get_paypal_config(db)
    plans: Dict[str, Dict[str, str]] = {k: dict(v) for k, v in (cfg.get("plans") or {}).items()}
    products: Dict[str, str] = dict(get_paypal_products(db))
    results: List[Dict[str, Any]] = []
    dirty_plans = dirty_products = False

    subs = [s for s in catalog_skus() if any(iv in _SUB_INTERVALS for iv in s["intervals"])]
    for s in subs:
        sku, label = s["sku"], s["label"]
        for interval in (iv for iv in s["intervals"] if iv in _SUB_INTERVALS):
            row = price_for(db, sku, interval)
            if row is None:
                results.append({"sku": sku, "interval": interval, "action": "sin_precio"})
                continue
            amount, currency = _fmt_amount(row.amount), row.currency
            current_id: Optional[str] = (plans.get(sku) or {}).get(interval)
            try:
                if current_id:
                    try:
                        plan = provider.get_plan(current_id)
                    except ProviderError:
                        plan = None  # id roto/ajeno → se rota
                    if plan and _plan_matches(plan, amount, currency):
                        results.append({"sku": sku, "interval": interval, "action": "ok",
                                        "plan_id": current_id, "amount": amount})
                        continue

                product_id = products.get(sku)
                if not product_id:
                    product_id = provider.create_product(name=label)
                    products[sku] = product_id
                    dirty_products = True

                new_id = provider.create_plan(
                    product_id=product_id,
                    name=f"{label} · {interval} · {currency} {amount}",
                    interval=interval, amount=amount, currency=currency)
                plans.setdefault(sku, {})[interval] = new_id
                dirty_plans = True
                if current_id and current_id != new_id:
                    try:
                        provider.deactivate_plan(current_id)
                    except ProviderError as e:
                        logger.warning("No se pudo desactivar el plan viejo %s (%s); "
                                       "queda activo en PayPal.", current_id, e)
                results.append({"sku": sku, "interval": interval, "action": "created",
                                "plan_id": new_id, "amount": amount,
                                "replaced": current_id})
            except ProviderError as e:
                logger.warning("Sync de plan falló para %s/%s: %s", sku, interval, e)
                results.append({"sku": sku, "interval": interval, "action": "error",
                                "detail": str(e)})

    if dirty_products:
        set_paypal_products(db, products)
    if dirty_plans:
        set_paypal_config(db, client_id=None, secret=None, webhook_id=None, env=None,
                          enabled=None, plans=plans)

    created = sum(1 for r in results if r["action"] == "created")
    logger.info("plan-sync: %d ok, %d creados, %d sin precio, %d errores",
                sum(1 for r in results if r["action"] == "ok"), created,
                sum(1 for r in results if r["action"] == "sin_precio"),
                sum(1 for r in results if r["action"] == "error"))
    return {"enabled": True, "results": results, "plans": plans}
