import client from "@/shared/api/client";

export interface SectorApi {
  id: string;
  provider: string;
  providerName: string;
  apiName: string;
  country: string;
  sector: string;
  baseUrl: string;
  proxyUrl: string;
  enabled: boolean;
  apiKeySet: boolean;
  apiKeySecondarySet: boolean;
  proxySecretSet: boolean;
  apiKeyMasked: string;
  lastTestStatus: string;
  lastTestDate: string;
  lastTestDetail: string;
}

export interface AppSettings {
  claudeApiKeySet: boolean;
  defaultLanguage: string;
  sectorApis: SectorApi[];
}

/** Secret fields: omit to keep unchanged, send "" to clear. */
export interface SectorApiInput {
  provider: string;
  providerName?: string;
  apiName?: string;
  country?: string;
  sector?: string;
  baseUrl?: string;
  proxyUrl?: string;
  enabled?: boolean;
  apiKey?: string;
  apiKeySecondary?: string;
  proxySecret?: string;
}

export interface SettingsInput {
  claudeApiKey?: string;
  defaultLanguage?: string;
  sectorApis?: SectorApiInput[];
}

export interface TestResult {
  status: string;
  detail: string;
  httpStatus: number | null;
  viaProxy: boolean;
}

export const settingsApi = {
  get: () => client.get<AppSettings>("/settings").then((r) => r.data),
  update: (payload: SettingsInput) =>
    client.put<AppSettings>("/settings", payload).then((r) => r.data),
  remove: (provider: string) =>
    client.delete(`/settings/sector-apis/${provider}`).then((r) => r.data),
  test: (payload: { provider: string } & Partial<SectorApiInput>) =>
    client.post<TestResult>("/settings/test", payload).then((r) => r.data),
};
