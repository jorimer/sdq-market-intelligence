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
  kind: "insight" | "deep_dive";
  ref: string | null;
  label: string;
  price: SkuPrice | null;
}

export interface Tariff {
  id: string;
  sku: string;
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
