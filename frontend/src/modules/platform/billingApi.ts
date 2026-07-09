import client from "@/shared/api/client";

/* ── Tarifario gestionado (monetización) ──────────────────────────
 * Consume /api/v1/billing (admin). El SKU es el vocabulario común: `insight`
 * (suscripción plataforma-wide), `deep_dive:{sector}` (compra puntual por producto),
 * `special:{slug}` (a medida). */

export interface SkuPrice {
  amount: string;
  currency: string;
  effective_from: string | null;
  effective_to: string | null;
  label: string | null;
}

export interface CatalogSku {
  sku: string;
  kind: "insight" | "deep_dive" | "all_access" | "enterprise";
  ref: string | null;
  label: string;
  intervals: string[];                          // once | monthly | annual válidos del SKU
  prices: Record<string, SkuPrice | null>;      // precio vigente por intervalo
}

export interface Tariff {
  id: string;
  sku: string;
  interval: string;
  currency: string;
  amount: string | null;
  effective_from: string | null;
  effective_to: string | null;
  active: boolean;
  is_current: boolean;
  scheduled: boolean;
  label: string | null;
  note: string | null;
}

export interface PublishTariffInput {
  sku: string;
  amount: string;
  interval?: string;
  currency?: string;
  effective_from?: string | null;
  effective_to?: string | null;
  label?: string | null;
  note?: string | null;
}

/** SKUs vendibles del catálogo + su precio vigente (para poblar el tarifario). */
export async function listSkus(): Promise<CatalogSku[]> {
  const { data } = await client.get<{ skus: CatalogSku[] }>("/billing/skus");
  return data.skus;
}

/** Tarifas de un SKU (vigentes / programadas / históricas), más reciente primero. */
export async function listTariffs(sku: string): Promise<Tariff[]> {
  const { data } = await client.get<{ tariffs: Tariff[] }>("/billing/tariffs", {
    params: { sku, include_inactive: true },
  });
  return data.tariffs;
}

/** Publica un precio con vigencia. Cada publicación es una fila nueva (no edita el histórico). */
export async function publishTariff(input: PublishTariffInput): Promise<unknown> {
  const { data } = await client.post("/billing/tariffs", input);
  return data;
}

/** Retira una tarifa (active=false) sin borrar el histórico. */
export async function withdrawTariff(tariffId: string): Promise<void> {
  await client.post(`/billing/tariffs/${tariffId}/withdraw`, {});
}

/* ── Pago self-serve (checkout PayPal, v2) ───────────────────────── */
function returnUrls(): { return_url: string; cancel_url: string } {
  const base = `${window.location.origin}/checkout/return`;
  return { return_url: `${base}?status=ok`, cancel_url: `${base}?status=cancel` };
}

/** Compra puntual de un Deep Dive (once). Devuelve el link de aprobación de PayPal. */
export async function checkoutOrder(sku: string): Promise<{ approval_url: string }> {
  const { data } = await client.post("/billing/checkout/order", { sku, ...returnUrls() });
  return data;
}

/** Suscripción a un producto (insight:{sector} | all_access | enterprise) mensual/anual. */
export async function checkoutSubscription(sku: string, interval: string): Promise<{ approval_url: string }> {
  const { data } = await client.post("/billing/checkout/subscription", { sku, interval, ...returnUrls() });
  return data;
}

/** Captura una orden aprobada (al volver de PayPal). */
export async function captureOrder(orderRef: string): Promise<{ status: string }> {
  const { data } = await client.post("/billing/checkout/order/capture", { order_ref: orderRef });
  return data;
}

/* ── Configuración de PayPal (admin) ─────────────────────────────── */
export interface PaypalConfig {
  clientId: string;
  secret: string;
  webhookId: string;
  env: string;
  plans: Record<string, Record<string, string>>;  // {sku: {interval: planId}}
  enabled: boolean;
  configured: boolean;
}

export async function getPaypalConfig(): Promise<PaypalConfig> {
  const { data } = await client.get("/billing/paypal");
  return data as PaypalConfig;
}

export async function setPaypalConfig(input: Partial<{
  clientId: string; secret: string; webhookId: string; env: string;
  enabled: boolean; plans: Record<string, Record<string, string>>;
}>): Promise<PaypalConfig> {
  const { data } = await client.put("/billing/paypal", input);
  return data as PaypalConfig;
}
