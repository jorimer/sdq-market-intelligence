import { useEffect, useState } from "react";
import { X, ExternalLink, Loader2, ShieldCheck } from "lucide-react";
import { Skeleton } from "@/shared/ui/primitives";
import { checkoutQuote, type TaxBreakdown } from "../billingApi";

/** Confirmación previa al redirect a PayPal. Cumple los requisitos del dueño:
 *  - Indica que el pago es con PayPal y que llevará a la pantalla de aprobación de PayPal.
 *  - Muestra "suscripción/compra + impuestos" con el desglose Subtotal + ITBIS = Total.
 *  - Deja elegir el país de facturación (RD tributa · Exterior = exportación de servicios,
 *    exento), y re-cotiza en vivo. Al confirmar, el padre dispara el checkout con ese país. */
export function CheckoutConfirmModal({
  sku, interval, title, subtitle, onConfirm, onClose,
}: {
  sku: string;
  interval: "once" | "monthly" | "annual";
  title: string;
  subtitle?: string;
  /** Ejecuta el checkout con el país + RNC/cédula elegidos y redirige a PayPal. Debe devolver
   *  una promesa (el modal muestra el spinner hasta que resuelva/redirija). */
  onConfirm: (country: string, taxId?: string) => Promise<void>;
  onClose: () => void;
}) {
  const [country, setCountry] = useState("DO");
  const [taxId, setTaxId] = useState("");
  const [quote, setQuote] = useState<TaxBreakdown | null>(null);
  const [loading, setLoading] = useState(true);
  const [going, setGoing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let live = true;
    setLoading(true); setErr(null);
    checkoutQuote(sku, interval, country)
      .then((q) => { if (live) { setQuote(q); setLoading(false); } })
      .catch(() => {
        if (live) {
          // Sin precio configurado aún: no bloquea el flujo, se avisa.
          setQuote(null); setLoading(false);
          setErr("Este producto aún no tiene precio configurado. Escribinos a ventas@sdqconsulting.com.do.");
        }
      });
    return () => { live = false; };
  }, [sku, interval, country]);

  const money = (v: string | undefined, ccy: string) =>
    v == null ? "—" : `${ccy} ${Number(v).toLocaleString("es-DO", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const go = async () => {
    setGoing(true); setErr(null);
    try {
      await onConfirm(country, country === "DO" ? taxId.trim() || undefined : undefined);
    } catch {
      setGoing(false);
      setErr("No se pudo iniciar el pago. Intentá de nuevo.");
    }
  };

  const intervalLabel = interval === "monthly" ? "mensual" : interval === "annual" ? "anual" : "";
  const ccy = quote?.currency || "USD";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button aria-label="Cerrar" onClick={onClose} className="absolute inset-0 bg-ink/40 backdrop-blur-sm" />
      <div className="relative w-full max-w-md bg-surface border border-line rounded-[14px] shadow-pop overflow-hidden">
        <div className="px-5 py-4 border-b border-line flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-muted truncate">Confirmar {interval === "once" ? "compra" : "suscripción"}</div>
            <h2 className="text-base font-semibold text-ink font-display truncate">{title}</h2>
            {subtitle && <div className="text-[11px] text-faint truncate">{subtitle}</div>}
          </div>
          <button onClick={onClose} className="btn btn-ghost shrink-0 -mr-2" aria-label="Cerrar">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* País de facturación → define el trato fiscal. */}
          <div>
            <label className="text-xs text-muted block mb-1">País de facturación</label>
            <select className="field w-full" value={country} onChange={(e) => setCountry(e.target.value)}>
              <option value="DO">República Dominicana (ITBIS 18%)</option>
              <option value="XX">Exterior — exportación de servicios (exento)</option>
            </select>
          </div>

          {/* RNC/cédula (solo RD): si lo dan, la factura es de crédito fiscal (e-CF 31). */}
          {country === "DO" && (
            <div>
              <label className="text-xs text-muted block mb-1">
                RNC / Cédula <span className="text-faint">(opcional — para factura con crédito fiscal)</span>
              </label>
              <input className="field w-full mono" value={taxId} onChange={(e) => setTaxId(e.target.value)}
                placeholder="RNC o cédula del receptor de la factura" />
            </div>
          )}

          {/* Desglose suscripción/compra + impuestos. */}
          <div className="rounded-[10px] border border-line bg-surface2 p-3">
            {loading ? (
              <Skeleton className="h-20" />
            ) : quote ? (
              <div className="space-y-1.5 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted">
                    {interval === "once" ? "Compra" : `Suscripción ${intervalLabel}`}
                  </span>
                  <span className="mono tabular-nums text-ink">{money(quote.subtotal, ccy)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">
                    {quote.label} {quote.exempt ? "(exento)" : `(${Number(quote.rate_pct)}%)`}
                  </span>
                  <span className="mono tabular-nums text-ink">{money(quote.tax, ccy)}</span>
                </div>
                <div className="flex items-center justify-between border-t border-line pt-1.5 mt-1.5">
                  <span className="font-semibold text-ink">Total {intervalLabel && `/ ${intervalLabel}`}</span>
                  <span className="mono tabular-nums text-base font-bold text-ink">{money(quote.total, ccy)}</span>
                </div>
                {quote.exempt && quote.exempt_reason && (
                  <p className="text-[11px] text-faint pt-1">{quote.exempt_reason}</p>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted">Precio no disponible por ahora.</p>
            )}
          </div>

          {/* Aviso PayPal: medio de pago + redirección a la pantalla de aprobación. */}
          <div className="flex items-start gap-2 rounded-[10px] bg-surface2 border border-line p-3">
            <ShieldCheck className="w-4 h-4 text-accent shrink-0 mt-0.5" />
            <p className="text-[12px] leading-snug text-muted">
              El pago se procesa con <span className="font-semibold text-ink">PayPal</span>. Al continuar,
              te llevaremos a la <span className="font-semibold text-ink">pantalla de aprobación de PayPal</span> para
              que confirmes el pago{quote ? ` de ${money(quote.total, ccy)}` : ""}. Podés usar tu cuenta PayPal o tarjeta.
            </p>
          </div>

          {err && <p className="text-xs text-alert">{err}</p>}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button onClick={onClose} className="btn btn-ghost" disabled={going}>Cancelar</button>
            <button onClick={go} disabled={going || loading} className="btn btn-primary disabled:opacity-40">
              {going ? <Loader2 className="w-4 h-4 animate-spin" /> : <ExternalLink className="w-4 h-4" />}
              {going ? "Redirigiendo a PayPal…" : "Continuar a PayPal"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
