import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Card } from "@/shared/ui/primitives";
import { captureOrder, activateSubscription } from "../billingApi";

type Phase = "working" | "ok" | "cancelled" | "error";

/** Retorno de PayPal tras aprobar (o cancelar) un pago.
 * Órdenes (compra puntual): PayPal agrega ``token`` = id de la orden → se captura acá.
 * Suscripciones: PayPal agrega ``subscription_id`` → el acceso lo activa el webhook. */
export function CheckoutReturnPage() {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;
  const [phase, setPhase] = useState<Phase>("working");
  const [detail, setDetail] = useState("");

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (q.get("status") === "cancel") { setPhase("cancelled"); return; }
    const orderToken = q.get("token");
    const subId = q.get("subscription_id");
    if (orderToken) {
      captureOrder(orderToken)
        .then((r) => {
          const done = (r.status || "").toUpperCase() === "COMPLETED";
          setPhase(done ? "ok" : "error");
          setDetail(done
            ? tr("checkout.orderOk", "Tu compra se procesó. El acceso al reporte quedará disponible en unos instantes.")
            : tr("checkout.orderPending", "El pago está en revisión. Si no ves el acceso pronto, escribinos."));
        })
        .catch(() => {
          setPhase("error");
          setDetail(tr("checkout.captureError", "No pudimos confirmar el pago. Si te cobraron, escribinos y lo resolvemos."));
        });
    } else if (subId) {
      activateSubscription(subId)
        .then((r) => {
          const active = (r.status || "").toUpperCase() === "ACTIVE" || !!r.settled;
          setPhase("ok");
          setDetail(active
            ? tr("checkout.subActive", "Tu suscripción quedó activa. Ya podés usar el producto — revisá 'Mi plan'.")
            : tr("checkout.subPending", "Tu suscripción está en proceso; el plan se activa en unos segundos. Revisá 'Mi plan'."));
        })
        .catch(() => {
          // Si la activación en el retorno falla, el webhook (en vivo) lo resuelve.
          setPhase("ok");
          setDetail(tr("checkout.subPending", "Tu suscripción está en proceso; el plan se activa en unos segundos. Revisá 'Mi plan'."));
        });
    } else {
      setPhase("ok");
      setDetail(tr("checkout.generic", "Gracias. Si completaste un pago, el acceso se reflejará en breve."));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const icon = phase === "working" ? <Loader2 className="w-8 h-8 text-accent animate-spin" />
    : phase === "ok" ? <CheckCircle2 className="w-8 h-8 text-ok" />
    : phase === "cancelled" ? <XCircle className="w-8 h-8 text-muted" />
    : <XCircle className="w-8 h-8 text-alert" />;
  const title = phase === "working" ? tr("checkout.working", "Confirmando tu pago…")
    : phase === "ok" ? tr("checkout.done", "¡Listo!")
    : phase === "cancelled" ? tr("checkout.cancelledTitle", "Pago cancelado")
    : tr("checkout.errorTitle", "No se pudo confirmar");

  return (
    <div className="max-w-lg mx-auto mt-10">
      <Card className="text-center">
        <div className="flex justify-center mb-3">{icon}</div>
        <h1 className="font-display text-lg font-bold text-ink">{title}</h1>
        <p className="text-sm text-muted mt-2">
          {phase === "cancelled"
            ? tr("checkout.cancelledMsg", "No se realizó ningún cobro. Podés volver al catálogo cuando quieras.")
            : detail}
        </p>
        {phase !== "cancelled" && (
          <p className="text-[11px] text-faint mt-2">
            {tr("checkout.viaPaypal", "El pago se procesó con PayPal, tu medio de pago. La factura con el desglose (subtotal + impuestos) queda en «Mi plan».")}
          </p>
        )}
        <div className="flex justify-center gap-2 mt-5">
          <Link to="/mi-plan" className="btn btn-soft">{tr("checkout.myPlan", "Ir a Mi plan")}</Link>
          <Link to="/catalog" className="btn btn-ghost">{tr("checkout.catalog", "Volver al catálogo")}</Link>
        </div>
      </Card>
    </div>
  );
}
