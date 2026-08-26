/**
 * Administración de comprobantes fiscales (NCF / e-NCF · DGII).
 *
 * Pantalla propia y no una tarjeta dentro de Pagos: acá se administra la numeración con la
 * que SDQ factura — los rangos autorizados, cuánto queda de cada uno, qué se emitió, qué
 * cobros quedaron esperando número, y el Formato 607 que se le presenta a la DGII.
 *
 * Regla que la pantalla respeta en todas sus filas: **el número nunca aparece solo**, siempre
 * con su tipo. Un "B0200000001" sin decir que es Factura de Consumo se lee mal.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle, CheckCircle2, Download, FileText, Hash, Plus, Wand2 } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import {
  assignPendingFiscalNumbers, download607, getFiscalOverview, listFiscalDocuments,
  setFiscalRegime, upsertFiscalSequence,
  type FiscalDocument, type FiscalOverview, type FiscalSequence,
} from "../billingApi";
import { mensajeDeError } from "../../../shared/api/errores";

/** Mes actual en AAAA-MM, para el selector del 607. */
function currentPeriod(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** "1 cobro" / "3 cobros" — el singular importa en un mensaje que se lee de a uno. */
function cobros(n: number): string {
  return n === 1 ? "1 cobro" : `${n} cobros`;
}

function SequenceRow({ s }: { s: FiscalSequence }) {
  const pct = s.total > 0 ? Math.min(100, Math.round((s.issued / s.total) * 100)) : 0;
  const tone = s.exhausted || s.expired ? "warn" : s.low || s.expiring_soon ? "warn" : "ok";
  return (
    <li className="rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {/* El tipo viaja SIEMPRE con el número. */}
        <Chip tone="muted">{s.doc_type} · {s.doc_label}</Chip>
        <span className="mono text-muted">{s.range_from}–{s.range_to}</span>
        <span className="mono text-ink">próximo {s.next_number ?? "—"}</span>
        <span className="ml-auto text-faint">{s.remaining} de {s.total} disponibles</span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-line/60">
        <div className={`h-1.5 rounded-full ${tone === "ok" ? "bg-ok" : "bg-alert"}`}
          style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {s.expired && <Chip tone="warn">vencida</Chip>}
        {s.exhausted && <Chip tone="warn">agotada</Chip>}
        {!s.expired && !s.exhausted && s.low && <Chip tone="warn">quedan pocos</Chip>}
        {!s.expired && s.expiring_soon && <Chip tone="warn">vence pronto</Chip>}
        {s.usable && !s.low && !s.expiring_soon && <Chip tone="ok">al día</Chip>}
        {s.expires_at && (
          <span className="text-faint">vence {s.expires_at.slice(0, 10)}</span>
        )}
      </div>
    </li>
  );
}

export function ComprobantesPage() {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");

  const [ov, setOv] = useState<FiscalOverview | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({ doc_type: "02", range_from: "", range_to: "", expires_at: "" });
  const [docs, setDocs] = useState<FiscalDocument[]>([]);
  const [period, setPeriod] = useState(currentPeriod());
  const [pendingOnly, setPendingOnly] = useState(false);

  const regime = ov?.regime ?? "ncf";
  const types = useMemo(
    () => ov?.regimes.find((r) => r.regime === regime)?.types ?? [],
    [ov, regime],
  );

  const reload = useCallback(async () => {
    const [overview, listed] = await Promise.all([
      getFiscalOverview(),
      listFiscalDocuments({ period, pending_only: pendingOnly }),
    ]);
    setOv(overview);
    setDocs(listed.documents);
    setStatus("ready");
  }, [period, pendingOnly]);

  useEffect(() => {
    if (!isAdmin) return;
    reload().catch(() => setStatus("error"));
  }, [isAdmin, reload]);

  async function saveSequence() {
    setMsg(null);
    const from = parseInt(form.range_from, 10);
    const to = parseInt(form.range_to, 10);
    if (!Number.isFinite(from) || !Number.isFinite(to)) {
      setMsg({ ok: false, text: tr("ncf.err.range", "Indicá el rango: desde y hasta.") });
      return;
    }
    setBusy(true);
    try {
      await upsertFiscalSequence({
        regime, doc_type: form.doc_type, range_from: from, range_to: to,
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
      });
      setForm({ ...form, range_from: "", range_to: "", expires_at: "" });
      await reload();
      setMsg({ ok: true, text: tr("ncf.ok.saved", "Rango cargado.") });
    } catch (e: unknown) {
      setMsg({ ok: false, text: mensajeDeError(e, tr("ncf.err.saved", "No se pudo cargar el rango.")) });
    } finally {
      setBusy(false);
    }
  }

  async function assignPending() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await assignPendingFiscalNumbers();
      await reload();
      const blocked = Object.keys(r.blocked);
      setMsg({
        ok: r.still_pending === 0,
        text: r.still_pending === 0
          ? `Se numeraron ${cobros(r.assigned_count)}.`
          : `Se numeraron ${cobros(r.assigned_count)}; quedan ${cobros(r.still_pending)} sin comprobante` +
            (blocked.length ? ` (sin rango para el tipo ${blocked.join(", ")}).` : "."),
      });
    } catch {
      setMsg({ ok: false, text: tr("ncf.err.assign", "No se pudo numerar los pendientes.") });
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin) {
    return <StateBlock kind="empty" title={tr("common.noAccess", "Sin acceso")}
      message={tr("ncf.adminOnly", "Esta sección es solo para administradores.")} />;
  }

  return (
    <div className="space-y-5">
      <PageHead
        title={tr("ncf.title", "Comprobantes fiscales (NCF)")}
        sub={tr("ncf.subtitle", "Rangos autorizados por la DGII, comprobantes emitidos y Formato 607. Cada cobro consume un número de la secuencia activa.")} />

      {status === "loading" && <Skeleton className="h-64" />}
      {status === "error" && (
        <StateBlock kind="error" title={tr("common.error", "No se pudo cargar")}
          message={tr("ncf.err.load", "No se pudo leer el estado de la numeración fiscal.")} />
      )}

      {status === "ready" && ov && (
        <div className="space-y-5">
          {/* Estado general: régimen, emisor y brechas abiertas. */}
          <Card>
            <CardHead icon={FileText} title={tr("ncf.state.title", "Estado de la numeración")}
              subtitle={tr("ncf.state.help", "Con qué régimen se numeran los cobros nuevos y si el emisor está completo.")} />
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-muted">{tr("ncf.regime", "Régimen activo")}</span>
              <select className="field w-64" value={regime} disabled={busy}
                onChange={async (e) => {
                  setBusy(true);
                  try { await setFiscalRegime(e.target.value); await reload(); }
                  finally { setBusy(false); }
                }}>
                {ov.regimes.map((r) => (
                  <option key={r.regime} value={r.regime}>{r.label}</option>
                ))}
              </select>
              {ov.issuer_ready
                ? <Chip tone="ok">RNC {ov.issuer.rnc}</Chip>
                : <Chip tone="warn">{tr("ncf.noRnc", "falta el RNC del emisor")}</Chip>}
            </div>
            {!ov.issuer_ready && (
              <p className="mt-2 flex items-start gap-2 text-xs text-alert">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                {tr("ncf.noRncHelp", "Sin RNC del emisor toda factura sale rotulada como comprobante interno. Se carga en Pagos · PayPal, tarjeta «Emisor de la factura».")}
              </p>
            )}
            {ov.pending_documents > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-alert/40 bg-alert/5 p-3">
                <AlertCircle size={16} className="text-alert shrink-0" />
                <span className="text-xs text-ink">
                  {`${cobros(ov.pending_documents)} ${ov.pending_documents === 1 ? "quedó" : "quedaron"} sin comprobante fiscal `}
                  {tr("ncf.pendingWhy", "(se registraron cuando no había rango cargado). La venta ya está cobrada; falta numerarla.")}
                </span>
                <button className="btn btn-soft ml-auto" disabled={busy} onClick={assignPending}>
                  <Wand2 size={14} /> {tr("ncf.assign", "Numerar los pendientes")}
                </button>
              </div>
            )}
            {ov.attention.length > 0 && (
              <p className="mt-2 flex items-start gap-2 text-xs text-alert">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                {tr("ncf.attention", "Hay rangos por agotarse o vencer. Solicitá los próximos a la DGII antes de que se acaben.")}
              </p>
            )}
            {msg && (
              <p className={`mt-2 flex items-center gap-2 text-xs ${msg.ok ? "text-ok" : "text-alert"}`}>
                {msg.ok ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}{msg.text}
              </p>
            )}
          </Card>

          {/* Rangos autorizados. */}
          <Card>
            <CardHead icon={Hash} title={tr("ncf.ranges.title", "Rangos autorizados")}
              subtitle={tr("ncf.ranges.help", "Los rangos que autoriza la DGII, por tipo de comprobante. Se consumen en orden al facturar.")} />
            {ov.sequences.length > 0 ? (
              <ul className="space-y-2 mb-4">
                {ov.sequences.map((s) => <SequenceRow key={s.id} s={s} />)}
              </ul>
            ) : (
              <p className="mb-4 text-xs text-faint">
                {tr("ncf.ranges.empty", "Todavía no hay rangos cargados. Mientras no los haya, los cobros se registran sin comprobante y quedan pendientes de numerar.")}
              </p>
            )}
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-xs text-muted">{tr("ncf.form.type", "Tipo")}
                <select className="field w-64" value={form.doc_type}
                  onChange={(e) => setForm({ ...form, doc_type: e.target.value })}>
                  {types.map((tt) => (
                    <option key={tt.doc_type} value={tt.doc_type}>{tt.doc_type} · {tt.label}</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">{tr("ncf.form.from", "Desde")}
                <input className="field mono w-32" value={form.range_from} placeholder="1"
                  onChange={(e) => setForm({ ...form, range_from: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">{tr("ncf.form.to", "Hasta")}
                <input className="field mono w-32" value={form.range_to} placeholder="1000"
                  onChange={(e) => setForm({ ...form, range_to: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">{tr("ncf.form.expires", "Vence")}
                <input type="date" className="field" value={form.expires_at}
                  onChange={(e) => setForm({ ...form, expires_at: e.target.value })} />
              </label>
              <button className="btn btn-soft" disabled={busy} onClick={saveSequence}>
                <Plus size={14} /> {tr("ncf.form.add", "Cargar rango")}
              </button>
            </div>
          </Card>

          {/* Emitidos + 607. */}
          <Card>
            <CardHead icon={FileText} title={tr("ncf.docs.title", "Comprobantes emitidos")}
              subtitle={tr("ncf.docs.help", "Lo que se facturó en el período. El Formato 607 se genera de este registro, no se transcribe a mano.")} />
            <div className="mb-3 flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-xs text-muted">{tr("ncf.docs.period", "Período")}
                <input type="month" className="field" value={period}
                  onChange={(e) => setPeriod(e.target.value)} />
              </label>
              <label className="flex items-center gap-2 text-xs text-muted">
                <input type="checkbox" checked={pendingOnly}
                  onChange={(e) => setPendingOnly(e.target.checked)} />
                {tr("ncf.docs.pendingOnly", "Solo los que están sin numerar")}
              </label>
              <button className="btn btn-soft ml-auto" onClick={() => download607(period)}>
                <Download size={14} /> {tr("ncf.docs.export", "Descargar Formato 607")}
              </button>
            </div>
            {docs.length === 0 ? (
              <p className="text-xs text-faint">
                {tr("ncf.docs.empty", "No hay comprobantes en este período.")}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-muted">
                    <tr className="border-b border-line text-left">
                      <th className="py-2 pr-3">{tr("ncf.col.number", "Comprobante")}</th>
                      <th className="py-2 pr-3">{tr("ncf.col.type", "Tipo")}</th>
                      <th className="py-2 pr-3">{tr("ncf.col.date", "Fecha")}</th>
                      <th className="py-2 pr-3">{tr("ncf.col.client", "Cliente")}</th>
                      <th className="py-2 pr-3 text-right">{tr("ncf.col.subtotal", "Subtotal")}</th>
                      <th className="py-2 pr-3 text-right">{tr("ncf.col.tax", "ITBIS")}</th>
                      <th className="py-2 text-right">{tr("ncf.col.total", "Total")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs.map((d) => (
                      <tr key={d.id} className="border-b border-line/60">
                        <td className="py-2 pr-3 mono text-ink">
                          {d.fiscal_number ?? <Chip tone="warn">sin numerar</Chip>}
                        </td>
                        {/* El tipo NUNCA falta al lado del número. */}
                        <td className="py-2 pr-3 text-muted">{d.fiscal_doc_label ?? "—"}</td>
                        <td className="py-2 pr-3 text-muted">{(d.created_at ?? "").slice(0, 10)}</td>
                        <td className="py-2 pr-3 text-muted">
                          {d.client_email ?? "—"}
                          {d.client_tax_id && <span className="mono text-faint"> · {d.client_tax_id}</span>}
                        </td>
                        <td className="py-2 pr-3 text-right mono">{d.currency} {d.subtotal ?? "—"}</td>
                        <td className="py-2 pr-3 text-right mono">
                          {d.tax_exempt ? tr("ncf.exempt", "exento") : `${d.currency} ${d.tax_amount ?? "—"}`}
                        </td>
                        <td className="py-2 text-right mono text-ink">{d.currency} {d.total ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

export default ComprobantesPage;
