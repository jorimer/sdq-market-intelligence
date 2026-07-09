import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BadgeCheck, CreditCard, Package, FileText, Download, XCircle } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { getMyPlan, type MyPlan } from "../api";
import {
  checkoutSubscription, cancelSubscription, listInvoices, downloadInvoice, type Invoice,
} from "../billingApi";
import { CheckoutConfirmModal } from "../components/CheckoutConfirmModal";

const TIER_LABEL: Record<string, string> = {
  free: "Free",
  pro: "Pro · Insight",
  enterprise: "Enterprise · Deep Dive",
};

function tierTone(tier: string): "ok" | "warn" | "muted" {
  if (tier === "enterprise") return "ok";
  if (tier === "pro") return "warn";
  return "muted";
}

export function MiPlanPage() {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;
  const [plan, setPlan] = useState<MyPlan | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [payMsg, setPayMsg] = useState<string | null>(null);
  const [interval, setIntervalSel] = useState<"monthly" | "annual">("monthly");
  const [confirmSku, setConfirmSku] = useState<string | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelMsg, setCancelMsg] = useState<string | null>(null);

  const reload = () => {
    getMyPlan().then((p) => { setPlan(p); setStatus("ready"); }).catch(() => setStatus("error"));
    listInvoices().then(setInvoices).catch(() => setInvoices([]));
  };

  // Ejecuta el checkout del bundle con el país elegido (desde el modal) y redirige a PayPal.
  async function confirmSubscribe(country: string) {
    if (!confirmSku) return;
    setPayMsg(null);
    window.location.href = (await checkoutSubscription(confirmSku, interval, country)).approval_url;
  }

  async function onCancel(subId: string) {
    if (!window.confirm(tr("plan.sub.cancelConfirm", "¿Cancelar tu suscripción? Perderás el acceso al final del período vigente."))) return;
    setCancelBusy(true); setCancelMsg(null);
    try {
      await cancelSubscription(subId);
      setCancelMsg(tr("plan.sub.cancelled", "Suscripción cancelada. El acceso se ajusta al vencimiento del período."));
      reload();
    } catch (e) {
      const code = (e as { response?: { status?: number } })?.response?.status;
      setCancelMsg(code === 503
        ? tr("plan.pay.unavailable", "Los pagos en línea todavía no están disponibles.")
        : tr("plan.sub.cancelError", "No se pudo cancelar. Escribinos a ventas@sdqconsulting.com.do."));
    } finally {
      setCancelBusy(false);
    }
  }

  useEffect(() => { reload(); }, []);

  const activeSub = plan?.subscriptions.find((s) => s.status === "active");
  const activeEnts = (plan?.entitlements ?? []).filter((e) => e.active);

  return (
    <div>
      <PageHead
        eyebrow={tr("plan.eyebrow", "Mi cuenta")}
        title={tr("plan.title", "Mi plan")}
        sub={tr("plan.sub", "Tu nivel de acceso, tu suscripción y los productos que tenés desbloqueados.")}
      />

      {status === "loading" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card><Skeleton className="h-24 w-full" /></Card>
          <Card><Skeleton className="h-24 w-full" /></Card>
        </div>
      )}

      {status === "error" && (
        <StateBlock kind="error" message={tr("plan.error", "No se pudo cargar tu plan.")} />
      )}

      {status === "ready" && plan && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHead icon={BadgeCheck} title={tr("plan.tier.title", "Nivel de acceso")} />
            <div className="flex items-center gap-3">
              <span className="mono text-2xl font-bold text-ink">{TIER_LABEL[plan.effective_tier] ?? plan.effective_tier}</span>
              <Chip tone={tierTone(plan.effective_tier)}>{plan.effective_tier}</Chip>
            </div>
            <p className="text-xs text-muted mt-2">
              {plan.subscription_tier && plan.subscription_tier !== plan.manual_tier
                ? tr("plan.tier.fromSub", "Tu nivel efectivo viene de tu suscripción activa.")
                : tr("plan.tier.help", "El nivel efectivo es el mayor entre tu plan asignado y tu suscripción activa.")}
            </p>
          </Card>

          <Card>
            <CardHead icon={CreditCard} title={tr("plan.sub.title", "Suscripción")} />
            {activeSub ? (
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-lg font-semibold text-ink uppercase">{activeSub.tier}</span>
                  <Chip tone="ok">{tr("plan.sub.active", "Activa")}</Chip>
                </div>
                <p className="text-xs text-muted mt-1.5">
                  {activeSub.current_period_end
                    ? tr("plan.sub.until", "Vigente hasta {{d}}").replace(
                        "{{d}}",
                        new Date(activeSub.current_period_end).toLocaleDateString("es-DO", {
                          year: "numeric", month: "long", day: "numeric",
                        }),
                      )
                    : tr("plan.sub.openEnded", "Sin fecha de vencimiento.")}
                </p>
                <div className="mt-3">
                  <button className="btn btn-ghost !py-1 text-xs text-alert disabled:opacity-40"
                    disabled={cancelBusy} onClick={() => onCancel(activeSub.id)}>
                    <XCircle className="w-3.5 h-3.5" /> {tr("plan.sub.cancel", "Cancelar suscripción")}
                  </button>
                  {cancelMsg && <p className="text-[11px] text-muted mt-1">{cancelMsg}</p>}
                </div>
              </div>
            ) : (
              <div>
                <p className="text-sm text-muted mb-2">{tr("plan.sub.none", "No tenés una suscripción activa.")}</p>
                <p className="text-xs text-faint mb-3">
                  {tr("plan.sub.perSector", "Para un solo sector, suscribite desde el Catálogo. Acá podés tomar los bundles:")}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <select className="field !py-1 w-28 text-sm" value={interval} onChange={(e) => setIntervalSel(e.target.value as "monthly" | "annual")}>
                    <option value="monthly">{tr("plan.interval.monthly", "Mensual")}</option>
                    <option value="annual">{tr("plan.interval.annual", "Anual")}</option>
                  </select>
                  <button className="btn btn-primary" onClick={() => setConfirmSku("all_access")}>
                    {tr("plan.sub.allAccess", "All-Access")}
                  </button>
                  <button className="btn btn-soft" onClick={() => setConfirmSku("enterprise")}>
                    {tr("plan.sub.enterprise", "Enterprise")}
                  </button>
                </div>
                <p className="text-[11px] text-faint mt-2">{tr("plan.sub.plusTax", "Suscripción + impuestos · el pago se procesa con PayPal.")}</p>
                {payMsg && <p className="text-xs text-alert mt-2">{payMsg}</p>}
              </div>
            )}
          </Card>

          <Card className="md:col-span-2">
            <CardHead
              icon={Package}
              title={tr("plan.ents.title", "Productos desbloqueados")}
              subtitle={tr("plan.ents.count", "{{n}} acceso(s) por producto").replace("{{n}}", String(activeEnts.length))}
            />
            {activeEnts.length === 0 ? (
              <p className="text-sm text-muted">
                {tr("plan.ents.empty", "Todavía no tenés compras puntuales de productos. Tu acceso viene de tu nivel/suscripción.")}
              </p>
            ) : (
              <ul className="grid gap-2 sm:grid-cols-2">
                {activeEnts.map((e) => (
                  <li key={e.id} className="flex items-center gap-2 rounded-lg border border-line p-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-ink truncate">{e.sector_key}</div>
                      <div className="text-[11px] text-faint uppercase">{e.tier}</div>
                    </div>
                    {e.expires_at ? (
                      <Chip tone="warn">{tr("plan.ents.until", "hasta")} {new Date(e.expires_at).toLocaleDateString("es-DO")}</Chip>
                    ) : (
                      <Chip tone="ok">{tr("plan.ents.perpetual", "perpetuo")}</Chip>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="md:col-span-2">
            <CardHead
              icon={FileText}
              title={tr("plan.invoices.title", "Facturas")}
              subtitle={tr("plan.invoices.sub", "Cada cobro con su desglose: subtotal + impuesto = total.")}
            />
            {invoices.length === 0 ? (
              <p className="text-sm text-muted">
                {tr("plan.invoices.empty", "Todavía no tenés facturas. Aparecerán acá tras tu primera compra o suscripción.")}
              </p>
            ) : (
              <ul className="grid gap-2">
                {invoices.map((inv) => (
                  <li key={inv.id} className="flex items-center gap-3 rounded-lg border border-line p-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-ink truncate">
                        {inv.invoice_number || inv.sku}
                        <span className="text-[11px] text-faint ml-2">{inv.created_at ? new Date(inv.created_at).toLocaleDateString("es-DO") : ""}</span>
                      </div>
                      <div className="text-[11px] text-muted mono tabular-nums">
                        {inv.currency} {Number(inv.subtotal).toFixed(2)} + {inv.tax_label || "Imp."} {Number(inv.tax_amount).toFixed(2)} = <span className="text-ink font-semibold">{inv.currency} {Number(inv.total).toFixed(2)}</span>
                        {inv.tax_exempt && <span className="ml-1 text-faint">(exento)</span>}
                      </div>
                    </div>
                    <button className="btn btn-ghost !py-1 !px-2 text-xs shrink-0"
                      onClick={() => downloadInvoice(inv.id, `${inv.invoice_number || "factura"}.pdf`)}>
                      <Download className="w-3.5 h-3.5" /> {tr("plan.invoices.pdf", "PDF")}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}

      {confirmSku && (
        <CheckoutConfirmModal
          sku={confirmSku}
          interval={interval}
          title={confirmSku === "all_access" ? tr("plan.sub.allAccess", "All-Access") : tr("plan.sub.enterprise", "Enterprise")}
          subtitle={interval === "monthly" ? tr("plan.interval.monthly", "Mensual") : tr("plan.interval.annual", "Anual")}
          onConfirm={confirmSubscribe}
          onClose={() => setConfirmSku(null)}
        />
      )}
    </div>
  );
}
