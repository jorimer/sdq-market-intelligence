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
  needsSecondary: boolean;
  apiKeySet: boolean;
  apiKeySecondarySet: boolean;
  proxySecretSet: boolean;
  apiKeyMasked: string;
  lastTestStatus: string;
  lastTestDate: string;
  lastTestDetail: string;
}

/** Correo saliente. La contraseña NUNCA viaja de vuelta: sólo `passwordSet`. */
export interface SmtpSettings {
  host: string;
  port: number;
  user: string;
  fromAddress: string;
  starttls: boolean;
  passwordSet: boolean;
  /** Lo computa el emisor, no la pantalla: una sola autoridad sobre si el canal existe. */
  configurado: boolean;
  /** Qué falta, en palabras de esta pantalla (no nombres de variables de entorno). */
  falta: string[];
}

export interface AppSettings {
  claudeApiKeySet: boolean;
  defaultLanguage: string;
  /** Techo DIARIO de gasto del modelo en USD. 0 = sin techo. */
  llmDailyBudgetUsd: number;
  /** ¿El contador del día es compartido entre workers (Redis) o uno por worker? */
  llmBudgetCounterShared: boolean;
  cloudflareProxyUrl: string;
  cloudflareProxySecretSet: boolean;
  sectorApis: SectorApi[];
  smtp: SmtpSettings;
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

/** Omitir la contraseña (o mandar MASK) la conserva; "" la borra. */
export interface SmtpInput {
  host?: string;
  port?: number;
  user?: string;
  fromAddress?: string;
  starttls?: boolean;
  password?: string;
}

export interface SettingsInput {
  claudeApiKey?: string;
  defaultLanguage?: string;
  /** 0 apaga el corte a propósito; negativo lo rechaza el backend. */
  llmDailyBudgetUsd?: number;
  cloudflareProxyUrl?: string;
  cloudflareProxySecret?: string;
  sectorApis?: SectorApiInput[];
  smtp?: SmtpInput;
}

export interface TestResult {
  status: string;
  detail: string;
  httpStatus: number | null;
  viaProxy: boolean;
}

export interface SmtpTestResult {
  status: string;
  detail: string;
  destinatario: string;
}

export const settingsApi = {
  get: () => client.get<AppSettings>("/settings").then((r) => r.data),
  update: (payload: SettingsInput) =>
    client.put<AppSettings>("/settings", payload).then((r) => r.data),
  remove: (provider: string) =>
    client.delete(`/settings/sector-apis/${provider}`).then((r) => r.data),
  test: (payload: { provider: string } & Partial<SectorApiInput>) =>
    client.post<TestResult>("/settings/test", payload).then((r) => r.data),
  // Sin destinatario a propósito: el backend manda a la casilla de quien pide la prueba.
  // Un endpoint que acepta destinatario es un relay abierto con credenciales de la casa.
  testSmtp: () =>
    client.post<SmtpTestResult>("/settings/smtp/test").then((r) => r.data),
};
