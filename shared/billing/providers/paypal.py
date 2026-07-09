"""Adaptador PayPal del puerto ``BillingProvider`` (REST API v1/v2).

Compra puntual (Deep Dive) vía Orders API; suscripción (Insight/Enterprise) vía
Subscriptions API con un billing plan pre-creado por tier; webhook verificado contra PayPal.
Lee la config con ``get_paypal_config`` (credenciales encriptadas en AppSettings).

⚠️ Requiere credenciales del comercio para operar (sandbox o live). Sin ellas,
``is_configured`` es False y los endpoints de checkout responden 'no configurado'. La
verificación end-to-end depende de cargar una app de PayPal Developer.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional

import httpx

from shared.billing.providers.base import (
    Checkout,
    NormalizedEvent,
    ProviderError,
    ProviderNotConfigured,
)

logger = logging.getLogger("sdq.billing.paypal")

_BASE = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
_TIMEOUT = 25.0

# custom_id embebido en la orden/suscripción: "user_id|kind|ref" (ref = sku o tier).
_SEP = "|"


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def encode_custom_id(user_id: str, kind: str, ref: str) -> str:
    return _SEP.join([user_id, kind, ref])


def decode_custom_id(custom_id: str) -> Optional[tuple]:
    parts = (custom_id or "").split(_SEP)
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None


class PayPalProvider:
    name = "paypal"

    def __init__(self, config: dict):
        self._cfg = config or {}
        self._base = _BASE.get(str(self._cfg.get("env") or "sandbox"), _BASE["sandbox"])

    # ── Configuración ──
    def is_configured(self) -> bool:
        return bool(self._cfg.get("enabled"))

    def _require(self) -> None:
        if not self.is_configured():
            raise ProviderNotConfigured("PayPal no está configurado (faltan credenciales).")

    # ── HTTP ──
    def _token(self) -> str:
        """Access token OAuth2 (client_credentials)."""
        cid, secret = self._cfg.get("client_id", ""), self._cfg.get("secret", "")
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        try:
            r = httpx.post(f"{self._base}/v1/oauth2/token",
                           headers={"Authorization": f"Basic {auth}",
                                    "Content-Type": "application/x-www-form-urlencoded"},
                           data={"grant_type": "client_credentials"}, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()["access_token"]
        except httpx.HTTPError as e:  # pragma: no cover - red
            raise ProviderError(f"PayPal OAuth falló: {e}") from e

    def _post(self, path: str, body: dict, token: Optional[str] = None) -> dict:
        token = token or self._token()
        try:
            r = httpx.post(f"{self._base}{path}",
                           headers={"Authorization": f"Bearer {token}",
                                    "Content-Type": "application/json"},
                           json=body, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json() if r.content else {}
        except httpx.HTTPError as e:  # pragma: no cover - red
            raise ProviderError(f"PayPal {path} falló: {e}") from e

    def _interval_for_plan(self, sku: Optional[str], plan_id: Optional[str]) -> Optional[str]:
        """Resuelve el intervalo (monthly/annual) de una suscripción desde el ``plan_id``,
        buscándolo en el mapa de planes configurado para ese SKU. Sirve para facturar con el
        precio correcto del tarifario."""
        if not sku or not plan_id:
            return None
        for interval, pid in ((self._cfg.get("plans") or {}).get(sku) or {}).items():
            if pid == plan_id:
                return interval
        return None

    @staticmethod
    def _approval_url(links: list) -> str:
        for ln in links or []:
            if ln.get("rel") in ("approve", "payer-action"):
                return ln.get("href", "")
        raise ProviderError("PayPal no devolvió link de aprobación.")

    # ── Checkout ──
    def create_order_checkout(self, *, sku: str, amount: str, currency: str, user_id: str,
                              return_url: str, cancel_url: str,
                              subtotal: Optional[str] = None, tax: Optional[str] = None) -> Checkout:
        """Compra puntual. ``amount`` = TOTAL a cobrar (subtotal + impuesto). Si se dan
        ``subtotal`` y ``tax`` (>0), se envía el ``breakdown`` para que PayPal muestre y
        registre el desglose (item_total + tax_total) en su pantalla de aprobación y recibo."""
        self._require()
        amt: dict = {"currency_code": currency, "value": amount}
        # Desglose sólo si cuadra (item_total + tax_total == value); si no, se manda el total
        # plano (PayPal rechaza un breakdown que no suma exacto).
        if subtotal is not None:
            tax_val = tax or "0"
            amt["breakdown"] = {
                "item_total": {"currency_code": currency, "value": subtotal},
                "tax_total": {"currency_code": currency, "value": tax_val},
            }
        body = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "custom_id": encode_custom_id(user_id, "order", sku),
                "amount": amt,
            }],
            "application_context": {"return_url": return_url, "cancel_url": cancel_url,
                                    "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"},
        }
        data = self._post("/v2/checkout/orders", body)
        return Checkout(approval_url=self._approval_url(data.get("links", [])),
                        provider_ref=data.get("id", ""))

    def create_subscription_checkout(self, *, sku: str, interval: str, user_id: str,
                                     return_url: str, cancel_url: str,
                                     tax_percentage: Optional[str] = None) -> Checkout:
        """Suscripción. El monto base lo fija el ``plan_id`` (= subtotal del tarifario); el
        impuesto se pasa como ``plan.taxes.percentage`` (override por-suscripción) para que
        PayPal cobre subtotal + impuesto y lo exhiba desglosado en su UI y recibos. Un
        ``tax_percentage`` de "0"/None deja el cobro sin impuesto (p.ej. cliente exento)."""
        self._require()
        plan_id = ((self._cfg.get("plans") or {}).get(sku) or {}).get(interval)
        if not plan_id:
            raise ProviderNotConfigured(
                f"Falta el billing plan de PayPal para '{sku}' ({interval}). "
                "Créalo en PayPal y mapéalo en Pagos · PayPal.")
        body: dict = {
            "plan_id": plan_id,
            "custom_id": encode_custom_id(user_id, "sub", sku),
            "application_context": {"return_url": return_url, "cancel_url": cancel_url,
                                    "user_action": "SUBSCRIBE_NOW", "shipping_preference": "NO_SHIPPING"},
        }
        if tax_percentage is not None and _to_float(tax_percentage) > 0:
            # Override del impuesto a nivel de la suscripción (no muta el plan compartido).
            body["plan"] = {"taxes": {"percentage": str(tax_percentage), "inclusive": False}}
        data = self._post("/v1/billing/subscriptions", body)
        return Checkout(approval_url=self._approval_url(data.get("links", [])),
                        provider_ref=data.get("id", ""))

    def cancel_subscription(self, subscription_id: str, *, reason: str = "") -> None:
        """Cancela una suscripción activa en PayPal (lado comercio, a pedido del cliente).
        PayPal emite luego ``BILLING.SUBSCRIPTION.CANCELLED`` que corta el acceso vía webhook.
        204 No Content en éxito; un id ya cancelado devuelve 4xx → se traduce a ProviderError."""
        self._require()
        self._post(f"/v1/billing/subscriptions/{subscription_id}/cancel",
                   {"reason": reason or "Cancelada por el cliente desde la plataforma."})

    def capture_order(self, order_id: str) -> dict:
        """Captura (cobra) una orden aprobada al volver el usuario de PayPal. Devuelve
        ``{status, order_id}``. El acceso lo concede el webhook PAYMENT.CAPTURE.COMPLETED
        (idempotente); acá solo se toma el pago."""
        self._require()
        data = self._post(f"/v2/checkout/orders/{order_id}/capture", {})
        return {"status": data.get("status", ""), "order_id": data.get("id", order_id)}

    # ── Webhook ──
    def verify_webhook(self, *, headers: dict, body: bytes) -> bool:
        self._require()
        h = {k.lower(): v for k, v in (headers or {}).items()}
        needed = ["paypal-transmission-id", "paypal-transmission-time", "paypal-cert-url",
                  "paypal-auth-algo", "paypal-transmission-sig"]
        if not all(h.get(k) for k in needed):
            return False
        try:
            event = json.loads(body.decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            return False
        payload = {
            "transmission_id": h["paypal-transmission-id"],
            "transmission_time": h["paypal-transmission-time"],
            "cert_url": h["paypal-cert-url"],
            "auth_algo": h["paypal-auth-algo"],
            "transmission_sig": h["paypal-transmission-sig"],
            "webhook_id": self._cfg.get("webhook_id", ""),
            "webhook_event": event,
        }
        try:
            res = self._post("/v1/notifications/verify-webhook-signature", payload)
        except ProviderError:
            return False
        return res.get("verification_status") == "SUCCESS"

    def parse_event(self, payload: dict) -> Optional[NormalizedEvent]:
        etype = payload.get("event_type", "")
        event_id = payload.get("id", "")
        resource = payload.get("resource", {}) or {}

        def _custom() -> tuple:
            cid = resource.get("custom_id")
            if not cid:  # las órdenes lo llevan en purchase_units[].custom_id
                pus = resource.get("purchase_units") or []
                cid = pus[0].get("custom_id") if pus else None
            return decode_custom_id(cid) if cid else (None, None, None)

        def _order_gross() -> tuple:
            """(value, currency) realmente cobrado, para reconciliar contra el desglose."""
            amt = resource.get("amount") or {}
            if not amt:  # CHECKOUT.ORDER.APPROVED lo trae en purchase_units[0].amount
                pus = resource.get("purchase_units") or []
                amt = (pus[0].get("amount") if pus else {}) or {}
            return amt.get("value"), amt.get("currency_code")

        user_id, kind, ref = _custom()
        if etype in ("PAYMENT.CAPTURE.COMPLETED", "CHECKOUT.ORDER.APPROVED"):
            gross, ccy = _order_gross()
            return NormalizedEvent(event_id=event_id, kind="order_paid",
                                   provider_ref=resource.get("id", ""), user_id=user_id, sku=ref,
                                   interval="once", amount_gross=gross, amount_currency=ccy)
        # En v2 el custom_id de una suscripción embebe el SKU (insight:{sector}/all_access/
        # enterprise), no el tier: define el alcance del acceso.
        if etype == "BILLING.SUBSCRIPTION.ACTIVATED":
            binfo = resource.get("billing_info") or {}
            nbt = binfo.get("next_billing_time")
            last = (binfo.get("last_payment") or {}).get("amount") or {}
            plan_id = resource.get("plan_id")
            return NormalizedEvent(event_id=event_id, kind="subscription_active",
                                   provider_ref=resource.get("id", ""), user_id=user_id,
                                   sku=ref, period_end=nbt, plan_id=plan_id,
                                   interval=self._interval_for_plan(ref, plan_id),
                                   amount_gross=last.get("value"), amount_currency=last.get("currency_code"))
        if etype == "BILLING.SUBSCRIPTION.CANCELLED":
            return NormalizedEvent(event_id=event_id, kind="subscription_cancelled",
                                   provider_ref=resource.get("id", ""), user_id=user_id, sku=ref)
        if etype in ("BILLING.SUBSCRIPTION.EXPIRED", "BILLING.SUBSCRIPTION.SUSPENDED"):
            return NormalizedEvent(event_id=event_id, kind="subscription_expired",
                                   provider_ref=resource.get("id", ""), user_id=user_id, sku=ref)
        return None  # evento que no nos interesa
