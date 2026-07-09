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

    @staticmethod
    def _approval_url(links: list) -> str:
        for ln in links or []:
            if ln.get("rel") in ("approve", "payer-action"):
                return ln.get("href", "")
        raise ProviderError("PayPal no devolvió link de aprobación.")

    # ── Checkout ──
    def create_order_checkout(self, *, sku: str, amount: str, currency: str, user_id: str,
                              return_url: str, cancel_url: str) -> Checkout:
        self._require()
        body = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "custom_id": encode_custom_id(user_id, "order", sku),
                "amount": {"currency_code": currency, "value": amount},
            }],
            "application_context": {"return_url": return_url, "cancel_url": cancel_url,
                                    "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"},
        }
        data = self._post("/v2/checkout/orders", body)
        return Checkout(approval_url=self._approval_url(data.get("links", [])),
                        provider_ref=data.get("id", ""))

    def create_subscription_checkout(self, *, tier: str, user_id: str,
                                     return_url: str, cancel_url: str) -> Checkout:
        self._require()
        plan_id = (self._cfg.get("plans") or {}).get(tier)
        if not plan_id:
            raise ProviderNotConfigured(f"Falta el billing plan de PayPal para el tier '{tier}'.")
        body = {
            "plan_id": plan_id,
            "custom_id": encode_custom_id(user_id, "sub", tier),
            "application_context": {"return_url": return_url, "cancel_url": cancel_url,
                                    "user_action": "SUBSCRIBE_NOW", "shipping_preference": "NO_SHIPPING"},
        }
        data = self._post("/v1/billing/subscriptions", body)
        return Checkout(approval_url=self._approval_url(data.get("links", [])),
                        provider_ref=data.get("id", ""))

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

        user_id, kind, ref = _custom()
        if etype in ("PAYMENT.CAPTURE.COMPLETED", "CHECKOUT.ORDER.APPROVED"):
            return NormalizedEvent(event_id=event_id, kind="order_paid",
                                   provider_ref=resource.get("id", ""), user_id=user_id, sku=ref)
        if etype == "BILLING.SUBSCRIPTION.ACTIVATED":
            nbt = ((resource.get("billing_info") or {}).get("next_billing_time"))
            return NormalizedEvent(event_id=event_id, kind="subscription_active",
                                   provider_ref=resource.get("id", ""), user_id=user_id,
                                   tier=ref, period_end=nbt)
        if etype == "BILLING.SUBSCRIPTION.CANCELLED":
            return NormalizedEvent(event_id=event_id, kind="subscription_cancelled",
                                   provider_ref=resource.get("id", ""), user_id=user_id, tier=ref)
        if etype in ("BILLING.SUBSCRIPTION.EXPIRED", "BILLING.SUBSCRIPTION.SUSPENDED"):
            return NormalizedEvent(event_id=event_id, kind="subscription_expired",
                                   provider_ref=resource.get("id", ""), user_id=user_id, tier=ref)
        return None  # evento que no nos interesa
