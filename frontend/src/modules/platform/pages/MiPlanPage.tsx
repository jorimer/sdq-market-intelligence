import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BadgeCheck, CreditCard, Package } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { getMyPlan, type MyPlan } from "../api";
import { checkoutSubscription } from "../billingApi";

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
  const [busy, setBusy] = useState(false);
  const [payMsg, setPayMsg] = useState<string | null>(null);

  async function upgrade(tier: string) {
    setBusy(true);
    setPayMsg(null);
    try {
      const { approval_url } = await checkoutSubscription(tier);
      window.location.href = approval_url;
    } catch (e) {
      const code = (e as { response?: { status?: number } })?.response?.status;
      setPayMsg(code === 503
        ? tr("plan.pay.unavailable", "Los pagos en línea todavía no están disponibles. Escribinos a ventas@sdqconsulting.com.do.")
        : tr("plan.pay.error", "No se pudo iniciar el pago. Intentá de nuevo."));
      setBusy(false);
    }
  }

  useEffect(() => {
    getMyPlan()
      .then((p) => {
        setPlan(p);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

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
              </div>
            ) : (
              <div>
                <p className="text-sm text-muted mb-3">{tr("plan.sub.none", "No tenés una suscripción activa.")}</p>
                <div className="flex flex-wrap gap-2">
                  <button className="btn btn-primary" disabled={busy} onClick={() => upgrade("pro")}>
                    {tr("plan.sub.getPro", "Suscribirme a Pro")}
                  </button>
                  <button className="btn btn-soft" disabled={busy} onClick={() => upgrade("enterprise")}>
                    {tr("plan.sub.getEnt", "Enterprise")}
                  </button>
                </div>
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
        </div>
      )}
    </div>
  );
}
