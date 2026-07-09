import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreditCard, CheckCircle2, AlertCircle, Plus, X } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import { getPaypalConfig, setPaypalConfig, listSkus, type PaypalConfig, type CatalogSku } from "../billingApi";

const MASK = "••••••••";
const INTERVAL_LABEL: Record<string, string> = { monthly: "Mensual", annual: "Anual" };

export function PagosPage() {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");

  const [cfg, setCfg] = useState<PaypalConfig | null>(null);
  const [subSkus, setSubSkus] = useState<CatalogSku[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const [env, setEnv] = useState("sandbox");
  const [enabled, setEnabled] = useState(false);
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [webhookId, setWebhookId] = useState("");
  const [plans, setPlans] = useState<Record<string, Record<string, string>>>({});

  // Fila para agregar un plan.
  const [pSku, setPSku] = useState("");
  const [pInterval, setPInterval] = useState("monthly");
  const [pId, setPId] = useState("");

  useEffect(() => {
    if (!isAdmin) return;
    Promise.all([getPaypalConfig(), listSkus()])
      .then(([c, skus]) => {
        setCfg(c); setEnv(c.env || "sandbox"); setEnabled(c.enabled);
        setClientId(c.clientId || ""); setSecret(c.secret || ""); setWebhookId(c.webhookId || "");
        setPlans(c.plans || {});
        const subs = skus.filter((s) => s.kind === "insight" || s.kind === "all_access" || s.kind === "enterprise");
        setSubSkus(subs);
        if (subs.length) setPSku(subs[0].sku);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [isAdmin]);

  function addPlan() {
    if (!pSku || !pId.trim()) return;
    setPlans((p) => ({ ...p, [pSku]: { ...(p[pSku] || {}), [pInterval]: pId.trim() } }));
    setPId("");
  }
  function removePlan(sku: string, interval: string) {
    setPlans((p) => {
      const ivs = { ...(p[sku] || {}) };
      delete ivs[interval];
      const next = { ...p, [sku]: ivs };
      if (Object.keys(ivs).length === 0) delete next[sku];
      return next;
    });
  }

  async function save() {
    setBusy(true); setMsg(null);
    try {
      const input: Record<string, unknown> = { env, enabled, webhookId, plans };
      if (clientId !== MASK) input.clientId = clientId;
      if (secret !== MASK) input.secret = secret;
      const updated = await setPaypalConfig(input);
      setCfg(updated); setClientId(updated.clientId || ""); setSecret(updated.secret || "");
      setPlans(updated.plans || {});
      setMsg({ ok: true, text: tr("pagos.saved", "Configuración guardada.") });
    } catch {
      setMsg({ ok: false, text: tr("pagos.saveError", "No se pudo guardar la configuración.") });
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin) return <StateBlock kind="forbidden" message={tr("pagos.forbidden", "Solo para administradores.")} />;

  return (
    <div>
      <PageHead
        eyebrow={tr("pagos.eyebrow", "Monetización")}
        title={tr("pagos.title", "Pagos · PayPal")}
        sub={tr("pagos.sub", "Credenciales de la pasarela + los billing plans de PayPal por producto y periodicidad. Los secretos se guardan encriptados y nunca se muestran en claro.")}
        right={cfg?.configured
          ? <Chip tone="ok"><CheckCircle2 size={14} /> {tr("pagos.on", "Configurado")}</Chip>
          : <Chip tone="warn"><AlertCircle size={14} /> {tr("pagos.off", "Sin configurar")}</Chip>}
      />

      {status === "loading" && <Card><Skeleton className="h-64 w-full" /></Card>}
      {status === "error" && <StateBlock kind="error" message={tr("pagos.loadError", "No se pudo cargar la configuración.")} />}

      {status === "ready" && (
        <div className="grid gap-4 max-w-2xl">
          <Card>
            <CardHead icon={CreditCard} title={tr("pagos.card.creds", "Credenciales")} />
            <div className="grid gap-3">
              <label className="flex flex-col gap-1 text-sm text-muted">{tr("pagos.env", "Entorno")}
                <select className="field" value={env} onChange={(e) => setEnv(e.target.value)}>
                  <option value="sandbox">Sandbox (pruebas)</option>
                  <option value="live">Live (producción)</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm text-muted">Client ID
                <input className="field mono" value={clientId} onChange={(e) => setClientId(e.target.value)}
                  placeholder={tr("pagos.clientId.ph", "el Client ID de tu app PayPal")} />
              </label>
              <label className="flex flex-col gap-1 text-sm text-muted">Secret
                <input className="field mono" type="password" value={secret} onChange={(e) => setSecret(e.target.value)}
                  placeholder={tr("pagos.secret.ph", "el Secret de tu app")} />
              </label>
              <label className="flex flex-col gap-1 text-sm text-muted">Webhook ID
                <input className="field mono" value={webhookId} onChange={(e) => setWebhookId(e.target.value)}
                  placeholder={tr("pagos.webhook.ph", "id del webhook (para verificar firmas)")} />
              </label>
            </div>
          </Card>

          <Card>
            <CardHead icon={CreditCard} title={tr("pagos.card.plans", "Billing plans (suscripciones)")}
              subtitle={tr("pagos.plans.help", "El id del billing plan de PayPal por producto y periodicidad. Solo hacen falta para los que vendas por suscripción.")} />
            {Object.keys(plans).length === 0 ? (
              <p className="text-xs text-faint mb-3">{tr("pagos.plans.empty", "Sin planes mapeados todavía.")}</p>
            ) : (
              <ul className="space-y-1.5 mb-3">
                {Object.entries(plans).flatMap(([sku, ivs]) =>
                  Object.entries(ivs).map(([iv, id]) => (
                    <li key={`${sku}:${iv}`} className="flex items-center gap-2 rounded-lg border border-line p-2 text-xs">
                      <span className="mono text-ink">{sku}</span>
                      <Chip tone="muted">{INTERVAL_LABEL[iv] ?? iv}</Chip>
                      <span className="mono text-muted flex-1 truncate">{id}</span>
                      <button className="btn btn-ghost !py-0.5 !px-1.5 text-alert" onClick={() => removePlan(sku, iv)}>
                        <X size={13} />
                      </button>
                    </li>
                  )))}
              </ul>
            )}
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-xs text-muted flex-1 min-w-[160px]">{tr("pagos.plans.product", "Producto")}
                <select className="field" value={pSku} onChange={(e) => setPSku(e.target.value)}>
                  {subSkus.map((s) => <option key={s.sku} value={s.sku}>{s.label}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">{tr("pagos.plans.interval", "Periodicidad")}
                <select className="field w-28" value={pInterval} onChange={(e) => setPInterval(e.target.value)}>
                  <option value="monthly">Mensual</option>
                  <option value="annual">Anual</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted flex-1 min-w-[160px]">Plan ID
                <input className="field mono" value={pId} onChange={(e) => setPId(e.target.value)} placeholder="P-XXXXXXXX" />
              </label>
              <button className="btn btn-soft" onClick={addPlan}><Plus size={14} /> {tr("pagos.plans.add", "Agregar")}</button>
            </div>
          </Card>

          <Card>
            <div className="flex items-center justify-between gap-4">
              <label className="flex items-center gap-2 text-sm text-ink">
                <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
                {tr("pagos.enable", "Habilitar cobros con PayPal")}
              </label>
              <div className="flex items-center gap-3">
                {msg && <span className={`text-xs ${msg.ok ? "text-ok" : "text-alert"}`}>{msg.text}</span>}
                <button className="btn btn-primary" disabled={busy} onClick={save}>
                  {busy ? tr("common.saving", "Guardando…") : tr("pagos.save", "Guardar")}
                </button>
              </div>
            </div>
            <p className="text-xs text-faint mt-3">
              {tr("pagos.note", "Habilitar solo tiene efecto con Client ID y Secret cargados. Mientras no esté configurado, los botones de compra muestran un aviso y no cobran.")}
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
