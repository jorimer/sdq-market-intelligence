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
export async function checkoutOrder(sku: string, country?: string, taxId?: string): Promise<{ approval_url: string; breakdown?: TaxBreakdown }> {
  const { data } = await client.post("/billing/checkout/order", { sku, country, tax_id: taxId, ...returnUrls() });
  return data;
}

/** Suscripción a un producto (insight:{sector} | all_access | enterprise) mensual/anual. */
export async function checkoutSubscription(sku: string, interval: string, country?: string, taxId?: string): Promise<{ approval_url: string; breakdown?: TaxBreakdown }> {
  const { data } = await client.post("/billing/checkout/subscription", { sku, interval, country, tax_id: taxId, ...returnUrls() });
  return data;
}

/** Captura una orden aprobada (al volver de PayPal). Concede el acceso en el momento. */
export async function captureOrder(orderRef: string): Promise<{ status: string; settled?: string | null }> {
  const { data } = await client.post("/billing/checkout/order/capture", { order_ref: orderRef });
  return data;
}

/** Activa una suscripción aprobada (al volver de PayPal). Concede el acceso sin webhook. */
export async function activateSubscription(subscriptionId: string): Promise<{ status: string; settled?: string | null }> {
  const { data } = await client.post("/billing/checkout/subscription/activate", { subscription_id: subscriptionId });
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

/** Resultado por (sku, intervalo) del sync tarifario → planes de PayPal. */
export interface PlanSyncResult {
  sku: string;
  interval: string;
  action: "ok" | "created" | "sin_precio" | "error";
  plan_id?: string;
  amount?: string;
  replaced?: string | null;
  detail?: string;
}

/** Reconcilia los billing plans de PayPal con el tarifario vigente (idempotente):
 * crea/rota el plan de cada SKU de suscripción con precio y lo deja mapeado. */
export async function syncPaypalPlans(): Promise<{
  enabled: boolean;
  results: PlanSyncResult[];
  plans: Record<string, Record<string, string>>;
}> {
  const { data } = await client.post("/billing/paypal/sync-plans", {});
  return data;
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

/* ── Comprobantes fiscales (DGII): rangos, emitidos y Formato 607 (admin) ──
   Dos regímenes: 'ncf' (impreso, serie B + 8 dígitos) y 'ecf' (electrónico, E + 10). */
export interface FiscalSequence {
  id: string;
  regime: string;              // ncf | ecf
  doc_type: string;            // ncf: 01|02|04|16 · ecf: 31|32|34|46
  doc_label: string;
  range_from: string;
  range_to: string;
  current: string;
  issued: number;
  total: number;
  remaining: number;
  expires_at: string | null;
  active: boolean;
  expired: boolean;
  exhausted: boolean;
  usable: boolean;
  low: boolean;
  expiring_soon: boolean;
  next_number: string | null;
  note: string | null;
}

export interface FiscalDocType { doc_type: string; label: string }
export interface FiscalRegimeInfo { regime: string; label: string; types: FiscalDocType[] }

export interface FiscalOverview {
  regime: string;
  regimes: FiscalRegimeInfo[];
  issuer: InvoiceIssuer;
  issuer_ready: boolean;
  sequences: FiscalSequence[];
  attention: FiscalSequence[];
  pending_documents: number;
}

export interface FiscalDocument {
  id: string;
  invoice_number: string | null;
  fiscal_regime: string | null;
  fiscal_number: string | null;
  fiscal_doc_type: string | null;
  fiscal_doc_label: string | null;
  fiscal_status: string | null;
  valid_until: string | null;
  created_at: string | null;
  sku: string;
  kind: string;
  currency: string;
  subtotal: string | null;
  tax_amount: string | null;
  total: string | null;
  tax_exempt: boolean;
  country: string | null;
  status: string;
  client_email: string | null;
  client_name: string | null;
  client_tax_id: string | null;
}

/* ── Alistamiento del cobro en vivo (admin) ── */
export interface ReadinessCheck {
  key: string;
  ok: boolean;
  label: string;
  impact: string;
}

export interface PaypalDiagnostics {
  ready: boolean;
  env: string;
  fiscal_regime: string;
  checks: ReadinessCheck[];
}

export async function getPaypalDiagnostics(): Promise<PaypalDiagnostics> {
  const { data } = await client.get<PaypalDiagnostics>("/billing/paypal/diagnostics");
  return data;
}

export async function getFiscalOverview(): Promise<FiscalOverview> {
  const { data } = await client.get<FiscalOverview>("/billing/fiscal/overview");
  return data;
}

export async function setFiscalRegime(regime: string): Promise<{ regime: string }> {
  const { data } = await client.put("/billing/fiscal/regime", { regime });
  return data as { regime: string };
}

export async function upsertFiscalSequence(input: {
  regime: string; doc_type: string; range_from: number; range_to: number;
  current?: number; expires_at?: string | null; active?: boolean; note?: string;
}): Promise<FiscalSequence> {
  const { data } = await client.put("/billing/fiscal/sequences", input);
  return data as FiscalSequence;
}

export async function listFiscalDocuments(params: {
  period?: string; regime?: string; doc_type?: string; pending_only?: boolean;
} = {}): Promise<{ documents: FiscalDocument[]; pending: number }> {
  const { data } = await client.get<{ documents: FiscalDocument[]; pending_documents: number }>(
    "/billing/fiscal/documents", { params });
  return {
    documents: Array.isArray(data?.documents) ? data.documents : [],
    pending: data?.pending_documents ?? 0,
  };
}

export async function assignPendingFiscalNumbers(): Promise<{
  assigned_count: number; still_pending: number; blocked: Record<string, string>;
}> {
  const { data } = await client.post("/billing/fiscal/documents/assign-pending");
  return data as { assigned_count: number; still_pending: number; blocked: Record<string, string> };
}

export async function download607(period: string): Promise<void> {
  const res = await client.get(`/billing/fiscal/607`, {
    params: { period }, responseType: "blob",
  });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `SDQ_607_${period.replace("-", "")}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
