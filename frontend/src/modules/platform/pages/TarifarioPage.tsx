import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CircleDollarSign, ChevronDown, Plus, X } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton, Tabs } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import { TariffBulkEditor } from "../components/TariffBulkEditor";
import {
  listSkus,
  listTariffs,
  publishTariff,
  withdrawTariff,
  type CatalogSku,
  type Tariff,
} from "../billingApi";
import { mensajeDeError } from "../../../shared/api/errores";

const INTERVAL_LABEL: Record<string, string> = {
  once: "Único", monthly: "Mensual", annual: "Anual",
};
const KIND_LABEL: Record<string, string> = {
  insight: "Suscripción · por sector", deep_dive: "Compra puntual · por reporte",
  all_access: "Suscripción · bundle (todos los Insight)", enterprise: "Suscripción · todo el catálogo",
};

function fmtMoney(amount: string | null | undefined, currency: string): string {
  if (amount == null) return "—";
  const n = Number(amount);
  if (Number.isNaN(n)) return `${amount} ${currency}`;
  return `${currency} ${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("es-DO", { year: "numeric", month: "short", day: "numeric" });
}

function tariffChip(t: Tariff, tr: (k: string, d: string) => string) {
  if (!t.active) return <Chip tone="muted">{tr("tariff.state.withdrawn", "Retirada")}</Chip>;
  if (t.is_current) return <Chip tone="ok">{tr("tariff.state.current", "Vigente")}</Chip>;
  if (t.scheduled) return <Chip tone="warn">{tr("tariff.state.scheduled", "Programada")}</Chip>;
  return <Chip tone="muted">{tr("tariff.state.past", "Histórica")}</Chip>;
}

interface FormState {
  interval: string;
  amount: string;
  currency: string;
  effective_from: string;
  label: string;
}
const mkForm = (interval: string): FormState => ({
  interval, amount: "", currency: "USD", effective_from: "", label: "",
});

export function TarifarioPage() {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");

  const [skus, setSkus] = useState<CatalogSku[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [tab, setTab] = useState("edicion");
  const [openSku, setOpenSku] = useState<string | null>(null);
  const [history, setHistory] = useState<Record<string, Tariff[]>>({});
  const [formSku, setFormSku] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(mkForm("once"));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setSkus(await listSkus());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  async function toggleHistory(sku: string) {
    if (openSku === sku) { setOpenSku(null); return; }
    setOpenSku(sku);
    if (!history[sku]) {
      try {
        const rows = await listTariffs(sku);
        setHistory((h) => ({ ...h, [sku]: rows }));
      } catch {
        setHistory((h) => ({ ...h, [sku]: [] }));
      }
    }
  }

  function openForm(s: CatalogSku) {
    setFormSku(s.sku);
    setForm(mkForm(s.intervals[0]));
    setErr(null);
  }

  async function submit(sku: string) {
    const amount = form.amount.trim();
    if (!amount || Number(amount) <= 0) {
      setErr(tr("tariff.err.amount", "Ingresá un monto válido (mayor a 0)."));
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await publishTariff({
        sku, amount, interval: form.interval, currency: form.currency.trim() || "USD",
        effective_from: form.effective_from ? new Date(form.effective_from).toISOString() : null,
        label: form.label.trim() || null,
      });
      setFormSku(null);
      setHistory((h) => { const { [sku]: _d, ...rest } = h; return rest; });
      if (openSku === sku) setOpenSku(null);
      await load();
    } catch (e) {
      setErr(mensajeDeError(e, tr("tariff.err.publish", "No se pudo publicar el precio.")));
    } finally {
      setBusy(false);
    }
  }

  async function doWithdraw(sku: string, id: string) {
    setBusy(true);
    try {
      await withdrawTariff(id);
      setHistory((h) => { const { [sku]: _d, ...rest } = h; return rest; });
      setOpenSku(null);
      await load();
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin) {
    return <StateBlock kind="forbidden" message={tr("tariff.forbidden", "El tarifario es solo para administradores.")} />;
  }

  const priced = skus.filter((s) => Object.values(s.prices).some(Boolean)).length;

  return (
    <div>
      <PageHead
        eyebrow={tr("tariff.eyebrow", "Monetización")}
        title={tr("tariff.title", "Tarifario")}
        sub={tr("tariff.sub",
          "Fijá el precio de cada producto: la suscripción Insight de cada sector (mensual y anual), su Deep Dive puntual, y los bundles All-Access y Enterprise. El precio anual suele ser el mensual con descuento.")}
      />

      {status === "loading" && <Card><Skeleton className="h-6 w-48 mb-4" /><Skeleton className="h-40 w-full" /></Card>}

      {status === "error" && (
        <StateBlock kind="error" message={tr("tariff.err.load", "No se pudo cargar el tarifario.")}
          action={<button className="btn btn-soft" onClick={() => void load()}>{tr("common.retry", "Reintentar")}</button>} />
      )}

      {status === "ready" && (
        <div className="mb-5">
          <Tabs
            tabs={[
              { id: "edicion", label: tr("tariff.tab.bulk", "Edición rápida") },
              { id: "catalogo", label: tr("tariff.tab.catalog", "Catálogo e histórico") },
            ]}
            active={tab}
            onChange={setTab}
          />
        </div>
      )}

      {status === "ready" && tab === "edicion" && (
        // key: al recargar los SKUs (post-publicación) el borrador se re-precarga
        // con los vigentes nuevos.
        <TariffBulkEditor key={JSON.stringify(skus.map((s) => s.prices))} skus={skus} onPublished={() => void load()} />
      )}

      {status === "ready" && tab === "catalogo" && (
        <Card>
          <CardHead icon={CircleDollarSign} title={tr("tariff.card.title", "Productos vendibles")}
            subtitle={tr("tariff.card.count", "{{priced}} de {{total}} con precio vigente")
              .replace("{{priced}}", String(priced)).replace("{{total}}", String(skus.length))} />
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[720px]">
              <thead>
                <tr className="text-left text-xs text-faint border-b border-line">
                  <th className="py-2 pr-3 font-semibold">{tr("tariff.col.product", "Producto")}</th>
                  <th className="py-2 pr-3 font-semibold">{tr("tariff.col.price", "Precios vigentes")}</th>
                  <th className="py-2 pr-3 font-semibold text-right">{tr("tariff.col.actions", "Acciones")}</th>
                </tr>
              </thead>
              <tbody>
                {skus.map((s) => (
                  <SkuRow key={s.sku} sku={s} tr={tr} open={openSku === s.sku} formOpen={formSku === s.sku}
                    form={form} setForm={setForm} busy={busy} err={formSku === s.sku ? err : null}
                    history={history[s.sku]} onToggleHistory={() => void toggleHistory(s.sku)}
                    onOpenForm={() => openForm(s)} onCloseForm={() => setFormSku(null)}
                    onSubmit={() => void submit(s.sku)} onWithdraw={(id) => void doWithdraw(s.sku, id)} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function SkuRow(props: {
  sku: CatalogSku;
  tr: (k: string, d: string) => string;
  open: boolean; formOpen: boolean;
  form: FormState; setForm: (f: FormState) => void;
  busy: boolean; err: string | null; history?: Tariff[];
  onToggleHistory: () => void; onOpenForm: () => void; onCloseForm: () => void;
  onSubmit: () => void; onWithdraw: (id: string) => void;
}) {
  const { sku: s, tr, open, formOpen, form, setForm, busy, err, history } = props;
  return (
    <>
      <tr className="border-b border-line align-top">
        <td className="py-3 pr-3">
          <div className="font-medium text-ink">{s.label}</div>
          <div className="text-xs text-faint mt-0.5">{KIND_LABEL[s.kind] ?? s.kind}</div>
          <code className="mono text-[11px] text-muted">{s.sku}</code>
        </td>
        <td className="py-3 pr-3">
          <div className="flex flex-wrap gap-2">
            {s.intervals.map((iv) => {
              const p = s.prices[iv];
              return (
                <span key={iv} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2 py-1">
                  <span className="text-[10px] uppercase tracking-wide text-faint">{INTERVAL_LABEL[iv] ?? iv}</span>
                  {p ? (
                    <span className="mono tabular-nums text-ink font-semibold">{fmtMoney(p.amount, p.currency)}</span>
                  ) : (
                    <span className="text-xs text-faint">{tr("tariff.noprice", "sin precio")}</span>
                  )}
                </span>
              );
            })}
          </div>
        </td>
        <td className="py-3 pr-0 text-right whitespace-nowrap">
          <button className="btn btn-soft mr-2" onClick={props.onOpenForm}>
            <Plus size={14} /> {tr("tariff.setprice", "Fijar precio")}
          </button>
          <button className="btn btn-ghost" onClick={props.onToggleHistory}>
            {tr("tariff.history", "Historial")}
            <ChevronDown size={14} className={open ? "rotate-180 transition-transform" : "transition-transform"} />
          </button>
        </td>
      </tr>

      {formOpen && (
        <tr className="border-b border-line bg-surface2">
          <td colSpan={3} className="p-4">
            <div className="flex flex-wrap items-end gap-3">
              {s.intervals.length > 1 && (
                <label className="flex flex-col gap-1 text-xs text-muted">
                  {tr("tariff.form.interval", "Periodicidad")}
                  <select className="field w-32" value={form.interval}
                    onChange={(e) => setForm({ ...form, interval: e.target.value })}>
                    {s.intervals.map((iv) => <option key={iv} value={iv}>{INTERVAL_LABEL[iv] ?? iv}</option>)}
                  </select>
                </label>
              )}
              <label className="flex flex-col gap-1 text-xs text-muted">
                {tr("tariff.form.amount", "Monto")}
                <input className="field mono w-32" type="number" min="0" step="0.01" value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })} placeholder="0.00" />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">
                {tr("tariff.form.currency", "Moneda")}
                <input className="field w-24" value={form.currency} maxLength={3}
                  onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">
                {tr("tariff.form.from", "Vigente desde (opcional)")}
                <input className="field" type="datetime-local" value={form.effective_from}
                  onChange={(e) => setForm({ ...form, effective_from: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted flex-1 min-w-[140px]">
                {tr("tariff.form.label", "Etiqueta (opcional)")}
                <input className="field" value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                  placeholder={tr("tariff.form.label.ph", "p.ej. Lanzamiento 2026")} />
              </label>
              <div className="flex gap-2">
                <button className="btn btn-primary" disabled={busy} onClick={props.onSubmit}>
                  {busy ? tr("common.saving", "Guardando…") : tr("tariff.form.publish", "Publicar")}
                </button>
                <button className="btn btn-ghost" onClick={props.onCloseForm} aria-label={tr("common.cancel", "Cancelar")}>
                  <X size={14} />
                </button>
              </div>
            </div>
            {err && <p className="text-xs text-alert mt-2">{err}</p>}
            <p className="text-xs text-faint mt-2">
              {tr("tariff.form.hint",
                "Sin fecha, el precio rige desde ahora. Una fecha futura programa el cambio. Publicar no borra el precio anterior: queda en el histórico.")}
            </p>
          </td>
        </tr>
      )}

      {open && (
        <tr className="border-b border-line bg-surface2">
          <td colSpan={3} className="p-4">
            {history === undefined ? (
              <Skeleton className="h-16 w-full" />
            ) : history.length === 0 ? (
              <p className="text-sm text-muted">{tr("tariff.history.empty", "Sin precios publicados para este producto.")}</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-faint">
                    <th className="py-1.5 pr-3 font-semibold">{tr("tariff.col.state", "Estado")}</th>
                    <th className="py-1.5 pr-3 font-semibold">{tr("tariff.col.interval", "Periodicidad")}</th>
                    <th className="py-1.5 pr-3 font-semibold">{tr("tariff.col.amount", "Monto")}</th>
                    <th className="py-1.5 pr-3 font-semibold">{tr("tariff.col.validity", "Vigencia")}</th>
                    <th className="py-1.5 pr-0 font-semibold text-right"></th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((row) => (
                    <tr key={row.id} className="border-t border-line">
                      <td className="py-2 pr-3">{tariffChip(row, tr)}</td>
                      <td className="py-2 pr-3 text-muted">{INTERVAL_LABEL[row.interval] ?? row.interval}</td>
                      <td className="py-2 pr-3 mono tabular-nums text-ink">{fmtMoney(row.amount, row.currency)}</td>
                      <td className="py-2 pr-3 text-muted">
                        {fmtDate(row.effective_from)} → {row.effective_to ? fmtDate(row.effective_to) : tr("tariff.open", "abierto")}
                      </td>
                      <td className="py-2 pr-0 text-right">
                        {row.active && (
                          <button className="btn btn-ghost" disabled={props.busy} onClick={() => props.onWithdraw(row.id)}>
                            {tr("tariff.withdraw", "Retirar")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
