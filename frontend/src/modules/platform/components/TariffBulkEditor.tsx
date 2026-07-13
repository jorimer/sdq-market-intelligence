import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CircleDollarSign, Rocket, X } from "lucide-react";
import { Card, CardHead, Chip } from "@/shared/ui/primitives";
import { publishTariff, type CatalogSku } from "../billingApi";
import {
  CellChange,
  TariffDraft,
  computeChanges,
  initialDraft,
  normalizeAmount,
} from "../lib/tariffBulk";

const INTERVAL_LABEL: Record<string, string> = {
  once: "Puntual", monthly: "Mensual", annual: "Anual",
};

/** Nombre corto de fila: sin el prefijo de familia ("Insight · X" → "X"). */
function shortLabel(s: CatalogSku): string {
  return s.label.replace(/^(Insight|Deep Dive)\s*·\s*/, "");
}

interface Props {
  skus: CatalogSku[];
  /** Recargar el catálogo tras publicar (los vigentes cambian). */
  onPublished: () => void;
}

/** Editor MASIVO del tarifario: matriz por familia con los precios vigentes
 * precargados; se edita en línea, "aplicar a toda la columna" para las familias
 * por-sector, y una sola publicación en lote de las celdas MODIFICADAS, con
 * resumen (actual → nuevo) antes de confirmar. */
export function TariffBulkEditor({ skus, onPublished }: Props) {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;

  const [draft, setDraft] = useState<TariffDraft>(() => initialDraft(skus));
  const [label, setLabel] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [report, setReport] = useState<{ ok: number; fail: string[] } | null>(null);

  const insight = useMemo(() => skus.filter((s) => s.kind === "insight"), [skus]);
  const deepDive = useMemo(() => skus.filter((s) => s.kind === "deep_dive"), [skus]);
  const bundles = useMemo(
    () => skus.filter((s) => s.kind !== "insight" && s.kind !== "deep_dive"),
    [skus],
  );
  const changes = useMemo(() => computeChanges(skus, draft), [skus, draft]);

  const setCell = (sku: string, interval: string, value: string) =>
    setDraft((d) => ({ ...d, [sku]: { ...d[sku], [interval]: value } }));

  const applyColumn = (rows: CatalogSku[], interval: string, value: string) => {
    if (normalizeAmount(value) == null) return;
    setDraft((d) => {
      const next = { ...d };
      for (const s of rows) {
        if (s.intervals.includes(interval)) next[s.sku] = { ...next[s.sku], [interval]: value };
      }
      return next;
    });
  };

  async function publishAll() {
    setPublishing(true);
    setReport(null);
    const fails: string[] = [];
    let ok = 0;
    for (const c of changes) {
      try {
        await publishTariff({
          sku: c.sku, interval: c.interval, amount: c.next, currency: "USD",
          effective_from: effectiveFrom ? new Date(effectiveFrom).toISOString() : null,
          label: label.trim() || null,
        });
        ok += 1;
      } catch {
        fails.push(`${c.sku} · ${c.interval}`);
      }
    }
    setPublishing(false);
    setConfirming(false);
    setReport({ ok, fail: fails });
    if (ok > 0) onPublished();
  }

  return (
    <div className="space-y-5">
      <MatrixCard
        title={tr("tariff.bulk.insightTitle", "Insight por sector — suscripción")}
        subtitle={tr("tariff.bulk.insightSub", "Mensual y anual por sector. El anual suele ser el mensual con descuento.")}
        rows={insight}
        intervals={["monthly", "annual"]}
        draft={draft}
        setCell={setCell}
        onApplyColumn={(iv, v) => applyColumn(insight, iv, v)}
        tr={tr}
      />
      <MatrixCard
        title={tr("tariff.bulk.deepDiveTitle", "Deep Dive por sector — compra puntual")}
        subtitle={tr("tariff.bulk.deepDiveSub", "Precio por informe a demanda.")}
        rows={deepDive}
        intervals={["once"]}
        draft={draft}
        setCell={setCell}
        onApplyColumn={(iv, v) => applyColumn(deepDive, iv, v)}
        tr={tr}
      />
      <MatrixCard
        title={tr("tariff.bulk.bundlesTitle", "Bundles")}
        subtitle={tr("tariff.bulk.bundlesSub", "All-Access (todos los Insight) y Enterprise (todo el catálogo).")}
        rows={bundles}
        intervals={["monthly", "annual"]}
        draft={draft}
        setCell={setCell}
        tr={tr}
      />

      {/* Barra de publicación */}
      <div className="sticky bottom-3 z-10">
        <Card className="shadow-pop">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted flex-1 min-w-[160px]">
              {tr("tariff.bulk.label", "Etiqueta del lote (opcional)")}
              <input className="field" value={label} onChange={(e) => setLabel(e.target.value)}
                placeholder={tr("tariff.bulk.labelPh", "p.ej. Tarifario v0.3")} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              {tr("tariff.bulk.from", "Vigente desde (opcional)")}
              <input className="field" type="datetime-local" value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)} />
            </label>
            <button
              type="button"
              className="btn btn-primary"
              disabled={changes.length === 0 || publishing}
              onClick={() => setConfirming(true)}
            >
              <Rocket size={14} />
              {tr("tariff.bulk.publish", "Publicar")} {changes.length > 0 ? `(${changes.length})` : ""}
            </button>
          </div>
          {report && (
            <p className="text-xs mt-2" role="status">
              <span className="text-ok font-medium">
                {tr("tariff.bulk.okCount", "{{n}} precios publicados").replace("{{n}}", String(report.ok))}
              </span>
              {report.fail.length > 0 && (
                <span className="text-alert ml-2">
                  {tr("tariff.bulk.failCount", "Fallaron: {{list}}").replace("{{list}}", report.fail.join(", "))}
                </span>
              )}
            </p>
          )}
          <p className="text-xs text-faint mt-2">
            {tr("tariff.bulk.hint",
              "Solo se publican las celdas modificadas. Publicar no borra precios anteriores: quedan en el histórico. Una celda vacía no borra el precio (retirar es acción del histórico).")}
          </p>
        </Card>
      </div>

      {confirming && (
        <ConfirmModal
          changes={changes}
          label={label}
          publishing={publishing}
          onConfirm={() => void publishAll()}
          onClose={() => setConfirming(false)}
          tr={tr}
        />
      )}
    </div>
  );
}

function MatrixCard({
  title, subtitle, rows, intervals, draft, setCell, onApplyColumn, tr,
}: {
  title: string;
  subtitle: string;
  rows: CatalogSku[];
  intervals: string[];
  draft: TariffDraft;
  setCell: (sku: string, interval: string, value: string) => void;
  onApplyColumn?: (interval: string, value: string) => void;
  tr: (k: string, d: string) => string;
}) {
  const [colValue, setColValue] = useState<Record<string, string>>({});
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHead icon={CircleDollarSign} title={title} subtitle={subtitle} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[520px]">
          <thead>
            <tr className="text-left text-xs text-faint border-b border-line">
              <th scope="col" className="py-2 pr-3 font-semibold">
                {tr("tariff.bulk.colProduct", "Producto")}
              </th>
              {intervals.map((iv) => (
                <th scope="col" key={iv} className="py-2 pr-3 font-semibold w-44">
                  {INTERVAL_LABEL[iv] ?? iv} <span className="font-normal">(USD)</span>
                </th>
              ))}
            </tr>
            {onApplyColumn && rows.length > 1 && (
              <tr className="border-b border-line bg-surface2/60">
                <td className="py-2 pr-3 text-xs text-muted">
                  {tr("tariff.bulk.applyAll", "Aplicar a todos los sectores")}
                </td>
                {intervals.map((iv) => (
                  <td key={iv} className="py-2 pr-3">
                    <div className="flex gap-1.5">
                      <input
                        className="field mono w-24"
                        type="number" min="0" step="0.01" placeholder="0.00"
                        aria-label={`${tr("tariff.bulk.applyAll", "Aplicar a todos los sectores")} · ${INTERVAL_LABEL[iv] ?? iv}`}
                        value={colValue[iv] ?? ""}
                        onChange={(e) => setColValue((v) => ({ ...v, [iv]: e.target.value }))}
                      />
                      <button
                        type="button"
                        className="btn btn-soft"
                        disabled={normalizeAmount(colValue[iv] ?? "") == null}
                        onClick={() => onApplyColumn(iv, colValue[iv] ?? "")}
                      >
                        {tr("tariff.bulk.apply", "Aplicar")}
                      </button>
                    </div>
                  </td>
                ))}
              </tr>
            )}
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.sku} className="border-b border-line/60">
                <td className="py-2 pr-3">
                  <div className="text-ink">{shortLabel(s)}</div>
                  <code className="mono text-[11px] text-faint">{s.sku}</code>
                </td>
                {intervals.map((iv) => {
                  const editable = s.intervals.includes(iv);
                  if (!editable) return <td key={iv} className="py-2 pr-3 text-faint">—</td>;
                  const current = s.prices[iv]?.amount ?? null;
                  const value = draft[s.sku]?.[iv] ?? "";
                  const dirty =
                    normalizeAmount(value) != null &&
                    (current == null || Number(current) !== Number(value));
                  return (
                    <td key={iv} className="py-2 pr-3">
                      <div className="flex items-center gap-2">
                        <input
                          className={`field mono w-24 ${dirty ? "ring-1 ring-accent" : ""}`}
                          type="number" min="0" step="0.01" placeholder={tr("tariff.noprice", "sin precio")}
                          aria-label={`${shortLabel(s)} · ${INTERVAL_LABEL[iv] ?? iv}`}
                          value={value}
                          onChange={(e) => setCell(s.sku, iv, e.target.value)}
                        />
                        {dirty && current != null && (
                          <span className="mono text-[11px] text-faint line-through">{current}</span>
                        )}
                        {dirty && current == null && (
                          <Chip tone="accent">{tr("tariff.bulk.new", "nuevo")}</Chip>
                        )}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ConfirmModal({
  changes, label, publishing, onConfirm, onClose, tr,
}: {
  changes: CellChange[];
  label: string;
  publishing: boolean;
  onConfirm: () => void;
  onClose: () => void;
  tr: (k: string, d: string) => string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button aria-label={tr("common.cancel", "Cancelar")} onClick={onClose}
        className="absolute inset-0 bg-ink/40 backdrop-blur-sm" />
      <div role="dialog" aria-modal="true"
        className="relative w-full max-w-lg max-h-[80vh] overflow-y-auto bg-surface border border-line rounded-2xl shadow-pop p-5">
        <div className="flex items-start gap-3 mb-3">
          <div className="min-w-0 flex-1">
            <h3 className="font-display text-[15px] font-bold text-ink truncate">
              {tr("tariff.bulk.confirmTitle", "Confirmar publicación")}
            </h3>
            <p className="text-xs text-muted mt-0.5">
              {tr("tariff.bulk.confirmSub", "{{n}} precios nuevos rigen al publicar")
                .replace("{{n}}", String(changes.length))}
              {label.trim() ? ` · ${label.trim()}` : ""}
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn btn-ghost shrink-0 -mr-2"
            aria-label={tr("common.cancel", "Cancelar")}>
            <X size={14} />
          </button>
        </div>
        <table className="w-full text-sm mb-4">
          <thead>
            <tr className="text-left text-xs text-faint border-b border-line">
              <th scope="col" className="py-1.5 pr-3 font-semibold">{tr("tariff.bulk.colProduct", "Producto")}</th>
              <th scope="col" className="py-1.5 pr-3 font-semibold">{tr("tariff.col.interval", "Periodicidad")}</th>
              <th scope="col" className="py-1.5 pr-0 font-semibold text-right">{tr("tariff.bulk.colChange", "Cambio")}</th>
            </tr>
          </thead>
          <tbody>
            {changes.map((c) => (
              <tr key={`${c.sku}:${c.interval}`} className="border-b border-line/60">
                <td className="py-1.5 pr-3 text-ink">{c.label}</td>
                <td className="py-1.5 pr-3 text-muted">{INTERVAL_LABEL[c.interval] ?? c.interval}</td>
                <td className="py-1.5 pr-0 text-right mono tabular-nums">
                  {c.current != null
                    ? <><span className="text-faint line-through">{c.current}</span> → <span className="text-ink font-semibold">{c.next}</span></>
                    : <span className="text-ink font-semibold">{c.next}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            {tr("common.cancel", "Cancelar")}
          </button>
          <button type="button" className="btn btn-primary" disabled={publishing} onClick={onConfirm}>
            {publishing
              ? tr("common.saving", "Guardando…")
              : tr("tariff.bulk.confirm", "Publicar ahora")}
          </button>
        </div>
      </div>
    </div>
  );
}
