import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CreditCard, CheckCircle2, AlertCircle, Plus, X, Percent, FileText, Hash } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import {
  getPaypalConfig, setPaypalConfig, listSkus, syncPaypalPlans, getPaypalDiagnostics,
  getTaxConfig, setTaxConfig, getInvoiceIssuer, setInvoiceIssuer,
  type PaypalConfig, type CatalogSku, type TaxConfig, type InvoiceIssuer, type PaypalDiagnostics,
  type PlanSyncResult,
} from "../billingApi";
import { mensajeDeError } from "../../../shared/api/errores";

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

  // Fila para agregar un plan (manual, casos borde).
  const [pSku, setPSku] = useState("");
  const [pInterval, setPInterval] = useState("monthly");
  const [pId, setPId] = useState("");

  // Sync automático tarifario → planes de PayPal.
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncReport, setSyncReport] = useState<PlanSyncResult[] | null>(null);
  const [syncErr, setSyncErr] = useState<string | null>(null);

  // Alistamiento para cobrar en vivo (qué falta y qué se rompe si falta).
  const [diag, setDiag] = useState<PaypalDiagnostics | null>(null);

  // Impuesto (ITBIS) + emisor de la factura.
  const [tax, setTax] = useState<TaxConfig | null>(null);
  const [issuer, setIssuer] = useState<InvoiceIssuer | null>(null);
  const [taxBusy, setTaxBusy] = useState(false);
  const [taxMsg, setTaxMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    Promise.all([getPaypalConfig(), listSkus(), getTaxConfig(), getInvoiceIssuer(),
                 getPaypalDiagnostics().catch(() => null)])
      .then(([c, skus, tc, iss, dg]) => {
        setDiag(dg);
        setCfg(c); setEnv(c.env || "sandbox"); setEnabled(c.enabled);
        setClientId(c.clientId || ""); setSecret(c.secret || ""); setWebhookId(c.webhookId || "");
        setPlans(c.plans || {});
        const subs = skus.filter((s) => s.kind === "insight" || s.kind === "all_access" || s.kind === "enterprise");
        setSubSkus(subs);
        if (subs.length) setPSku(subs[0].sku);
        setTax(tc); setIssuer(iss);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [isAdmin]);

  async function saveTaxAndIssuer() {
    if (!tax || !issuer) return;
    setTaxBusy(true); setTaxMsg(null);
    try {
      const [tc, iss] = await Promise.all([setTaxConfig(tax), setInvoiceIssuer(issuer)]);
      setTax(tc); setIssuer(iss);
      setTaxMsg({ ok: true, text: tr("pagos.saved", "Configuración guardada.") });
    } catch {
      setTaxMsg({ ok: false, text: tr("pagos.saveError", "No se pudo guardar la configuración.") });
    } finally {
      setTaxBusy(false);
    }
  }

  async function doSyncPlans() {
    setSyncBusy(true); setSyncErr(null); setSyncReport(null);
    try {
      const res = await syncPaypalPlans();
      setPlans(res.plans || {});
      setSyncReport(res.results);
    } catch (e) {
      setSyncErr(mensajeDeError(e, tr("pagos.plans.syncError", "No se pudieron sincronizar los planes.")));
    } finally {
      setSyncBusy(false);
    }
  }

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
          {diag && (
            <Card>
              <CardHead icon={diag.ready ? CheckCircle2 : AlertCircle}
                title={tr("pagos.ready.title", "Alistamiento para cobrar en vivo")}
                subtitle={tr("pagos.ready.help", "Qué falta y qué deja de funcionar mientras falte. Se verifica contra la configuración real, no contra una lista escrita a mano.")} />
              <ul className="space-y-2">
                {diag.checks.map((c) => (
                  <li key={c.key} className="flex items-start gap-2 text-xs">
                    {c.ok
                      ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-ok" />
                      : <AlertCircle size={14} className="mt-0.5 shrink-0 text-alert" />}
                    <span className="min-w-0">
                      <span className={c.ok ? "text-muted" : "text-ink"}>{c.label}</span>
                      {!c.ok && <span className="block text-faint">{c.impact}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
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
              subtitle={tr("pagos.plans.helpAuto",
                "PayPal cobra las suscripciones contra un plan pre-creado. Sincronizá con un clic: se crea/rota el plan de cada producto con precio en el tarifario y queda mapeado solo.")}
              right={
                <button type="button" className="btn btn-primary" disabled={syncBusy || !enabled}
                  onClick={() => void doSyncPlans()}>
                  {syncBusy
                    ? tr("pagos.plans.syncing", "Sincronizando…")
                    : tr("pagos.plans.sync", "Sincronizar con el tarifario")}
                </button>
              } />
            {!enabled && (
              <p className="text-xs text-warn mb-3">
                {tr("pagos.plans.needEnabled", "Habilitá los cobros con PayPal (arriba) y guardá antes de sincronizar.")}
              </p>
            )}
            {syncErr && <p className="text-xs text-alert mb-3" role="alert">{syncErr}</p>}
            {syncReport && (
              <div className="mb-3 rounded-lg bg-surface2 p-2.5 text-xs" role="status">
                <span className="text-ok font-medium">
                  {tr("pagos.plans.syncOk", "{{ok}} al día · {{created}} creados")
                    .replace("{{ok}}", String(syncReport.filter((r) => r.action === "ok").length))
                    .replace("{{created}}", String(syncReport.filter((r) => r.action === "created").length))}
                </span>
                <span className="text-muted ml-2">
                  {tr("pagos.plans.syncSkipped", "{{n}} sin precio en el tarifario")
                    .replace("{{n}}", String(syncReport.filter((r) => r.action === "sin_precio").length))}
                </span>
                {syncReport.some((r) => r.action === "error") && (
                  <div className="text-alert mt-1">
                    {syncReport.filter((r) => r.action === "error")
                      .map((r) => `${r.sku} (${r.interval}): ${r.detail ?? "error"}`).join(" · ")}
                  </div>
                )}
              </div>
            )}
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

          {tax && (
            <Card>
              <CardHead icon={Percent} title={tr("pagos.tax.title", "Impuesto (ITBIS)")}
                subtitle={tr("pagos.tax.help", "El precio del tarifario es el subtotal; el impuesto se suma encima. A PayPal se le cobra el total; la factura al cliente lo desglosa.")} />
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex flex-col gap-1 text-sm text-muted">{tr("pagos.tax.rate", "Tasa (%)")}
                  <input className="field mono" value={tax.rate}
                    onChange={(e) => setTax({ ...tax, rate: e.target.value })} placeholder="18" />
                </label>
                <label className="flex flex-col gap-1 text-sm text-muted">{tr("pagos.tax.label", "Etiqueta")}
                  <input className="field" value={tax.label}
                    onChange={(e) => setTax({ ...tax, label: e.target.value })} placeholder="ITBIS" />
                </label>
                <label className="flex flex-col gap-1 text-sm text-muted">{tr("pagos.tax.home", "País que tributa (ISO-2)")}
                  <input className="field mono uppercase" value={tax.home_country}
                    onChange={(e) => setTax({ ...tax, home_country: e.target.value.toUpperCase() })} placeholder="DO" maxLength={2} />
                </label>
                <div className="flex flex-col gap-2 justify-end text-sm text-ink">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={tax.enabled} onChange={(e) => setTax({ ...tax, enabled: e.target.checked })} />
                    {tr("pagos.tax.enabled", "Cobrar impuesto")}
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={tax.exempt_foreign} onChange={(e) => setTax({ ...tax, exempt_foreign: e.target.checked })} />
                    {tr("pagos.tax.exempt", "Exento al exterior (exportación de servicios)")}
                  </label>
                </div>
              </div>
            </Card>
          )}

          {issuer && (
            <Card>
              <CardHead icon={FileText} title={tr("pagos.issuer.title", "Emisor de la factura")}
                subtitle={tr("pagos.issuer.help", "Datos de SDQ que salen en la factura. Sin RNC + secuencia NCF de la DGII, la factura sale como comprobante interno (no válido como crédito fiscal).")} />
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex flex-col gap-1 text-sm text-muted sm:col-span-2">{tr("pagos.issuer.name", "Razón social")}
                  <input className="field" value={issuer.name} onChange={(e) => setIssuer({ ...issuer, name: e.target.value })} />
                </label>
                <label className="flex flex-col gap-1 text-sm text-muted">RNC
                  <input className="field mono" value={issuer.rnc} onChange={(e) => setIssuer({ ...issuer, rnc: e.target.value })}
                    placeholder={tr("pagos.issuer.rncPh", "pendiente de cargar")} />
                </label>
                <label className="flex flex-col gap-1 text-sm text-muted">{tr("pagos.issuer.email", "Correo de facturación")}
                  <input className="field" value={issuer.email} onChange={(e) => setIssuer({ ...issuer, email: e.target.value })} />
                </label>
                <label className="flex flex-col gap-1 text-sm text-muted sm:col-span-2">{tr("pagos.issuer.address", "Dirección")}
                  <input className="field" value={issuer.address} onChange={(e) => setIssuer({ ...issuer, address: e.target.value })} />
                </label>
              </div>
              <div className="flex items-center justify-end gap-3 mt-3">
                {taxMsg && <span className={`text-xs ${taxMsg.ok ? "text-ok" : "text-alert"}`}>{taxMsg.text}</span>}
                <button className="btn btn-soft" disabled={taxBusy} onClick={saveTaxAndIssuer}>
                  {taxBusy ? tr("common.saving", "Guardando…") : tr("pagos.tax.save", "Guardar impuesto y emisor")}
                </button>
              </div>
            </Card>
          )}

          <Card>
            <CardHead icon={Hash} title={tr("pagos.ncf.title", "Comprobantes fiscales (NCF · DGII)")}
              subtitle={tr("pagos.ncf.help", "Los rangos autorizados, los comprobantes emitidos y el Formato 607 se administran en su propia pantalla.")} />
            <Link to="/admin/comprobantes" className="btn btn-soft">
              <Hash size={14} /> {tr("pagos.ncf.go", "Administrar comprobantes fiscales")}
            </Link>
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
