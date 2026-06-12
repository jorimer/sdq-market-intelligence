import client from "@/shared/api/client";

export interface DigestCifra {
  etiqueta: string;
  valor: string;
}

export interface Digest {
  resumen: string;
  hallazgos: string[];
  cifras: DigestCifra[];
  riesgos: string[];
  relevancia: Record<string, string>;
}

export interface PublicationSummary {
  id: string;
  report_key: string;
  report_name: string;
  period: string;
  title: string;
  source_url: string;
  landing_url: string;
  sectors: string[];
  status: string;
  published_at: string | null;
  resumen: string;
  has_digest: boolean;
}

export interface PublicationDetail extends PublicationSummary {
  digest: Digest;
  error: string | null;
}

export interface CatalogReport {
  key: string;
  name: string;
  cadence: string;
  sectors: string[];
  landing_url: string;
  latest_ingested_period: string | null;
}

export async function getPublications(): Promise<PublicationSummary[]> {
  const { data } = await client.get("/macro-monitor/publications");
  return data.publications ?? [];
}

export async function getCatalog(): Promise<CatalogReport[]> {
  const { data } = await client.get("/macro-monitor/publications/catalog");
  return data.reports ?? [];
}

export async function getPublication(id: string): Promise<PublicationDetail> {
  const { data } = await client.get(`/macro-monitor/publications/${id}`);
  return data;
}

export async function refreshPublications(reportKey?: string): Promise<{ ingested_ok: number }> {
  const qs = reportKey ? `?report_key=${encodeURIComponent(reportKey)}` : "";
  const { data } = await client.post(`/macro-monitor/publications/refresh${qs}`);
  return data;
}
