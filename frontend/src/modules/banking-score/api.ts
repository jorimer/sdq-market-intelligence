import client from "@/shared/api/client";

export interface BankRef {
  id: string;
  name: string;
  bank_type: string | null;
}

export interface SubComponents {
  solidez: number;
  calidad: number;
  eficiencia: number;
  liquidez: number;
  diversificacion: number;
}

export const SUB_KEYS: (keyof SubComponents)[] = [
  "solidez",
  "calidad",
  "eficiencia",
  "liquidez",
  "diversificacion",
];

export const SUB_LABELS: Record<keyof SubComponents, string> = {
  solidez: "Solidez",
  calidad: "Calidad de activos",
  eficiencia: "Eficiencia",
  liquidez: "Liquidez",
  diversificacion: "Diversificación",
};

export interface ScoringResult {
  bank_id?: string;
  bank_name?: string;
  period_end?: string;
  overall_score: number;
  rating_tier: string;
  tier_color?: string;
  sub_components: SubComponents;
  indicators?: Record<string, { raw: number; score: number }>;
  entity_type?: string | null;
}

export async function listBanks(entityType?: string): Promise<BankRef[]> {
  const { data } = await client.get<{ banks: BankRef[] }>("/banking-score/banks", {
    params: entityType ? { entity_type: entityType } : {},
  });
  return data.banks ?? [];
}

export async function listPeriods(): Promise<string[]> {
  const { data } = await client.get<{ periods: string[] }>("/banking-score/periods");
  return data.periods ?? [];
}

export async function runScoring(bankId: string, periodEnd: string): Promise<ScoringResult> {
  const { data } = await client.post<ScoringResult>(
    `/banking-score/${bankId}/run`,
    null,
    { params: { period_end: periodEnd } },
  );
  return data;
}

export async function simulate(
  subComponents: SubComponents,
  entityType?: string,
): Promise<ScoringResult> {
  const { data } = await client.post<ScoringResult>("/banking-score/simulate-scenario", {
    sub_components: subComponents,
    ...(entityType ? { entity_type: entityType } : {}),
  });
  return data;
}

export async function getLatest(bankId: string): Promise<ScoringResult & { has_rating: boolean }> {
  const { data } = await client.get(`/banking-score/${bankId}/latest`);
  return data;
}
