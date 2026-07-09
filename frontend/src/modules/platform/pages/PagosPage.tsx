import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreditCard, CheckCircle2, AlertCircle } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import { getPaypalConfig, setPaypalConfig, type PaypalConfig } from "../billingApi";

const MASK = "••••••••";

export function PagosPage() {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");

  const [cfg, setCfg] = useState<PaypalConfig | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Campos editables. Los secretos arrancan con MASK si ya hay valor; solo se envían si el
  // usuario los cambia (para no pisar el secreto guardado con la máscara).
  const [env, setEnv] = useState("sandbox");
  const [enabled, setEnabled] = useState(false);
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [webhookId, setWebhookId] = useState("");
  const [planPro, setPlanPro] = useState("");
  const [planEnterprise, setPlanEnterprise] = useState("");

  useEffect(() => {
    if (!isAdmin) return;
    getPaypalConfig()
      .then((c) => {
        setCfg(c);
        setEnv(c.env || "sandbox");
        setEnabled(c.enabled);
        setClientId(c.clientId || "");
        setSecret(c.secret || "");
        setWebhookId(c.webhookId || "");
        setPlanPro(c.planPro || "");
        setPlanEnterprise(c.planEnterprise || "");
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [isAdmin]);

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const input: Record<string, unknown> = { env, enabled, webhookId, planPro, planEnterprise };
      // Secretos: enviar solo si cambiaron respecto a la máscara.
      if (clientId !== MASK) input.clientId = clientId;
      if (secret !== MASK) input.secret = secret;
      const updated = await setPaypalConfig(input);
      setCfg(updated);
      setClientId(updated.clientId || "");
      setSecret(updated.secret || "");
      setMsg({ ok: true, text: tr("pagos.saved", "Configuración guardada.") });
    } catch {
      setMsg({ ok: false, text: tr("pagos.saveError", "No se pudo guardar la configuración.") });
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin) {
    return <StateBlock kind="forbidden" message={tr("pagos.forbidden", "Solo para administradores.")} />;
  }

  return (
    <div>
      <PageHead
        eyebrow={tr("pagos.eyebrow", "Monetización")}
        title={tr("pagos.title", "Pagos · PayPal")}
        sub={tr(
          "pagos.sub",
          "Credenciales de la pasarela. Cargá una app de PayPal Developer (arrancá en sandbox). Los secretos se guardan encriptados y nunca se muestran en claro.",
        )}
        right={
          cfg?.configured ? (
            <Chip tone="ok"><CheckCircle2 size={14} /> {tr("pagos.on", "Configurado")}</Chip>
          ) : (
            <Chip tone="warn"><AlertCircle size={14} /> {tr("pagos.off", "Sin configurar")}</Chip>
          )
        }
      />

      {status === "loading" && <Card><Skeleton className="h-64 w-full" /></Card>}
      {status === "error" && <StateBlock kind="error" message={tr("pagos.loadError", "No se pudo cargar la configuración.")} />}

      {status === "ready" && (
        <div className="grid gap-4 max-w-2xl">
          <Card>
            <CardHead icon={CreditCard} title={tr("pagos.card.creds", "Credenciales")} />
            <div className="grid gap-3">
              <label className="flex flex-col gap-1 text-sm text-muted">
                {tr("pagos.env", "Entorno")}
                <select className="field" value={env} onChange={(e) => setEnv(e.target.value)}>
                  <option value="sandbox">Sandbox (pruebas)</option>
                  <option value="live">Live (producción)</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm text-muted">
                Client ID
                <input className="field mono" value={clientId} onChange={(e) => setClientId(e.target.value)}
                  placeholder={tr("pagos.clientId.ph", "el Client ID de tu app PayPal")} />
              </label>
              <label className="flex flex-col gap-1 text-sm text-muted">
                Secret
                <input className="field mono" type="password" value={secret} onChange={(e) => setSecret(e.target.value)}
                  placeholder={tr("pagos.secret.ph", "el Secret de tu app")} />
              </label>
              <label className="flex flex-col gap-1 text-sm text-muted">
                Webhook ID
                <input className="field mono" value={webhookId} onChange={(e) => setWebhookId(e.target.value)}
                  placeholder={tr("pagos.webhook.ph", "id del webhook (para verificar firmas)")} />
              </label>
            </div>
          </Card>

          <Card>
            <CardHead icon={CreditCard} title={tr("pagos.card.plans", "Planes de suscripción (billing plans)")}
              subtitle={tr("pagos.plans.help", "El id del billing plan de PayPal para cada nivel. Necesarios para la suscripción self-serve.")} />
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-sm text-muted">
                {tr("pagos.planPro", "Plan Pro (Insight)")}
                <input className="field mono" value={planPro} onChange={(e) => setPlanPro(e.target.value)} placeholder="P-XXXXXXXX" />
              </label>
              <label className="flex flex-col gap-1 text-sm text-muted">
                {tr("pagos.planEnt", "Plan Enterprise (Deep Dive)")}
                <input className="field mono" value={planEnterprise} onChange={(e) => setPlanEnterprise(e.target.value)} placeholder="P-XXXXXXXX" />
              </label>
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
