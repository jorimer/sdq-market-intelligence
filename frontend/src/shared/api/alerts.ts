import client from "@/shared/api/client";

/**
 * Watchlist de alertas (fase A de docs/SPEC_ALERTA_ACCIONABLE.md).
 *
 * `subject: null` significa "todo el eje" — el backend lo guarda con una sentinela, pero
 * ese detalle no cruza la API. No confundir con `/billing` ni con el plan del usuario:
 * esto es CONTENIDO (qué le interesa), no cobro.
 */
export interface AlertSubscription {
  id: string;
  sector_key: string;
  sector_label: string;
  /** null = todo el eje (sin nombrar entidad). */
  subject: string | null;
  /** Nombre legible del sujeto. `null` si es todo el eje, o si el catálogo ya no lo
   *  resuelve — ahí la pantalla cae al identificador, que es feo y es cierto. */
  subject_label?: string | null;
  rule_codes: string[] | null;
  min_severity: string; // alta | media | baja
  channels: string[];
  digest: string; // inmediato | diario | semanal
  active: boolean;
  /** Por qué está suspendida ("acceso_revocado" | "usuario_inactivo"), o null. */
  suspended_reason: string | null;
  /** Nivel que hace falta para vigilar esto: lo determina el sujeto, no una constante. */
  tier_requerido: string;
  /** ¿El eje ya tiene un productor enchufado al barrido? Un eje del catálogo puede estar
   *  implementado como producto y todavía no aportar señales. La UI tiene que decirlo:
   *  una vigilancia muda presentada como activa se lee como que no pasó nada. */
  sector_produce_alertas: boolean;
  created_at: string | null;
}

export interface AlertRule {
  codigo: string;
  label: string;
  descripcion: string;
  /** Por qué existe la regla — la lección o doctrina que la ancla. */
  basis: string;
  requiere_sujeto: boolean;
  /** ¿Ya tiene motor detrás? En la fase A ninguno lo tiene, y la UI debe decirlo. */
  implementado: boolean;
}

export interface AlertRulesCatalog {
  rules: AlertRule[];
  severidades: string[];
  /** Canales que HOY entregan de verdad en este despliegue. */
  canales_disponibles: string[];
  /** Existen en el código pero esta instalación no los tiene configurados (p. ej. correo
   *  sin SMTP). NO es lo mismo que `canales_planificados`, y la UI debe decir cuál es cuál:
   *  esto lo resuelve el dueño con tres variables de entorno; aquello, una fase futura. */
  canales_no_configurados: string[];
  canales_planificados: string[];
  digests: string[];
}

export interface AlertSubscriptionList {
  subscriptions: AlertSubscription[];
  total: number;
  max: number;
}

export async function getAlertSubscriptions(): Promise<AlertSubscriptionList> {
  const { data } = await client.get("/alerts/subscriptions");
  return data;
}

export async function getAlertRules(): Promise<AlertRulesCatalog> {
  const { data } = await client.get("/alerts/rules");
  return data;
}

/** Idempotente: re-vigilar lo que ya se vigila reactiva y reconfigura esa vigilancia. */
export async function watchSubject(
  sectorKey: string,
  subject?: string | null,
  opts?: { rule_codes?: string[]; min_severity?: string; channels?: string[]; digest?: string },
): Promise<AlertSubscription> {
  const { data } = await client.post("/alerts/subscriptions", {
    sector_key: sectorKey,
    subject: subject ?? null,
    ...(opts || {}),
  });
  return data;
}

export async function unwatch(id: string): Promise<void> {
  await client.delete(`/alerts/subscriptions/${encodeURIComponent(id)}`);
}

export async function updateAlertSubscription(
  id: string,
  patch: Partial<Pick<AlertSubscription, "min_severity" | "digest" | "active">> & {
    rule_codes?: string[] | null;
    channels?: string[];
  },
): Promise<AlertSubscription> {
  const { data } = await client.patch(`/alerts/subscriptions/${encodeURIComponent(id)}`, patch);
  return data;
}
