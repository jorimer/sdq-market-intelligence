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

/** Desglose fiscal de un cobro (suscripción/compra + impuesto = total). */
export interface TaxBreakdown {
  currency: string;
  subtotal: string;
  rate_pct: string;
  tax: string;
  total: string;
  label: string;          // p.ej. "ITBIS"
  exempt: boolean;
  exempt_reason: string | null;
  country: string;
}

/** Cotiza un SKU con impuestos para el país dado (o el del perfil). Alimenta la
 * confirmación de checkout ("suscripción + impuestos" con desglose). */
export async function checkoutQuote(
  sku: string, interval = "once", country?: string,
): Promise<TaxBreakdown & { sku: string; interval: string }> {
  const { data } = await client.post("/billing/checkout/quote", { sku, interval, country });
  return data;
}

/** Compra puntual de un Deep Dive (once). Cobra el TOTAL (subtotal + impuesto). */
export async function checkoutOrder(sku: string, country?: string): Promise<{ approval_url: string; breakdown?: TaxBreakdown }> {
  const { data } = await client.post("/billing/checkout/order", { sku, country, ...returnUrls() });
  return data;
}

/** Suscripción a un producto (insight:{sector} | all_access | enterprise) mensual/anual. */
export async function checkoutSubscription(sku: string, interval: string, country?: string): Promise<{ approval_url: string; breakdown?: TaxBreakdown }> {
  const { data } = await client.post("/billing/checkout/subscription", { sku, interval, country, ...returnUrls() });
  return data;
}

/** Captura una orden aprobada (al volver de PayPal). */
export async function captureOrder(orderRef: string): Promise<{ status: string }> {
  const { data } = await client.post("/billing/checkout/order/capture", { order_ref: orderRef });
  return data;
}

/** Cancela una suscripción propia (llama a PayPal y refleja el estado). */
export async function cancelSubscription(subscriptionId: string): Promise<{ status: string }> {
  const { data } = await client.post(`/billing/subscription/${subscriptionId}/cancel`, {});
  return data;
}

/* ── Facturas (desglose subtotal/impuesto/total) ─────────────────── */
export interface Invoice {
  id: string;
  sku: string;
  kind: string;               // order | subscription
  currency: string;
  subtotal: string;
  tax_rate: string;
  tax_amount: string;
  total: string;
  tax_label: string | null;
  tax_exempt: boolean;
  invoice_number: string | null;
  status: string;
  created_at: string | null;
}

export async function listInvoices(): Promise<Invoice[]> {
  const { data } = await client.get<{ invoices: Invoice[] }>("/billing/invoices");
  return Array.isArray(data?.invoices) ? data.invoices : [];
}

/** Descarga el PDF de una factura del propio usuario. */
export async function downloadInvoice(transactionId: string, fallbackName: string): Promise<void> {
  const r = await client.get(`/billing/invoices/${transactionId}/pdf`, { responseType: "blob" });
  const cd = (r.headers["content-disposition"] as string) || "";
  const filename = /filename="?([^"]+)"?/.exec(cd)?.[1] ?? fallbackName;
  const blobUrl = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(blobUrl);
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

/* ── Impuestos (ITBIS) + emisor de la factura (admin) ────────────── */
export interface TaxConfig {
  enabled: boolean;
  rate: string;              // porcentaje, p.ej. "18"
  label: string;             // "ITBIS"
  home_country: string;      // ISO-2, p.ej. "DO"
  exempt_foreign: boolean;   // exento a clientes del exterior
}

export async function getTaxConfig(): Promise<TaxConfig> {
  const { data } = await client.get("/billing/tax");
  return data as TaxConfig;
}

export async function setTaxConfig(input: Partial<TaxConfig>): Promise<TaxConfig> {
  const { data } = await client.put("/billing/tax", input);
  return data as TaxConfig;
}

export interface InvoiceIssuer {
  name: string;
  rnc: string;
  address: string;
  email: string;
}

export async function getInvoiceIssuer(): Promise<InvoiceIssuer> {
  const { data } = await client.get("/billing/issuer");
  return data as InvoiceIssuer;
}

export async function setInvoiceIssuer(input: Partial<InvoiceIssuer>): Promise<InvoiceIssuer> {
  const { data } = await client.put("/billing/issuer", input);
  return data as InvoiceIssuer;
}
