import { useEffect, useMemo, useState } from "react";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import {
  confirmExtraction,
  getExtraction,
  type CellValidation,
  type ConfirmResult,
  type ExtractionCell,
  type ExtractionDetail,
} from "../api";

interface Props {
  slug: string;
  extractionId: string;
  onClose: () => void;
  onConfirmed: () => void;
}

const VALIDATION_TONE: Record<CellValidation, "ok" | "alert" | "warn" | "muted"> = {
  passed: "ok",
  failed: "alert",
  conflict: "warn",
  unchecked: "muted",
};

const VALIDATION_LABEL: Record<CellValidation, string> = {
  passed: "Confirmada",
  failed: "Inconsistente",
  conflict: "En conflicto",
  unchecked: "Sin verificar",
};

/** Review what the extractor read, before any of it becomes data.
 *
 *  Cells are ordered worst-first: an inconsistency the reviewer never scrolls to is the
 *  same as one that was never flagged. */
export function ExtractionReviewDrawer({ slug, extractionId, onClose, onConfirmed }: Props) {
  const [detail, setDetail] = useState<ExtractionDetail | null>(null);
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ConfirmResult | null>(null);

  useEffect(() => {
    getExtraction(slug, extractionId)
      .then((d) => {
        setDetail(d);
        setDropped(new Set(d.cells.filter((c) => !c.included).map((c) => c.id)));
      })
      .catch(() => setError("No se pudo cargar la extracción."));
  }, [slug, extractionId]);

  const order: Record<CellValidation, number> = {
    failed: 0, conflict: 1, unchecked: 2, passed: 3,
  };
  const cells = useMemo(
    () => [...(detail?.cells ?? [])].sort(
      (a, b) => order[a.validation] - order[b.validation] || (a.page ?? 0) - (b.page ?? 0),
    ),
    [detail],
  );

  const counts = detail?.summary;
  const promotable = cells.filter(
    (c) => c.validation !== "failed" && !dropped.has(c.id),
  ).length;

  const toggle = (id: string) =>
    setDropped((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await confirmExtraction(
        slug, extractionId,
        cells.map((c) => ({ cell_id: c.id, included: !dropped.has(c.id) })),
      );
      // Anything that did not land as stated stays on screen. Closing on it would
      // report a clean confirmation over a silent hole — whether the hole is a figure
      // the deck stated two ways, or one a later delivery already corrected.
      if (result.discrepancias.length > 0 || result.cifras_que_cambian.length > 0) {
        setOutcome(result);
        return;
      }
      onConfirmed();
    } catch (e: unknown) {
      const detailMsg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detailMsg ?? "No se pudo confirmar la extracción.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <InsightDrawerShell
      eyebrow={detail?.document ?? "Extracción"}
      title="Revisar antes de confirmar"
      onClose={onClose}
    >
      <p className="text-sm text-muted">
        Estas cifras aún no son datos: viven en una zona de espera hasta que las confirmes.
        Las marcadas como inconsistentes no se promueven aunque las dejes marcadas — una
        invariante ya demostró que no cuadran.
      </p>

      {outcome && (
        <div className="space-y-3">
          <p className="text-sm text-body rounded-lg bg-surface2 p-3">
            Se guardaron {outcome.creadas} observación(es) nueva(s) y se actualizaron{" "}
            {outcome.actualizadas}.{" "}
            <span className="text-muted">
              Esta entrega llega hasta {outcome.anada_de_la_entrega || "—"}; lo que dijo queda
              en el registro aunque otra entrega mande sobre la cifra vigente.
            </span>
          </p>

          {outcome.omitidas_por_discrepancia > 0 && (
            <div className="space-y-1">
              <p className="text-sm text-body">
                <span className="font-semibold">
                  {outcome.omitidas_por_discrepancia}
                </span>{" "}
                quedaron fuera porque la presentación da dos cifras distintas para el mismo
                dato: elegir una sería inventar cuál de las dos láminas se leyó mal.
              </p>
              <ul className="space-y-1">
                {outcome.discrepancias.slice(0, 8).map((d, i) => (
                  <li key={i} className="text-xs text-muted mono truncate">
                    {d.marca} · {d.metrica}
                    {d.segmento !== "total" ? ` · ${d.segmento}` : ""} ={" "}
                    {d.valores.join(" vs ")}
                    {d.laminas.length ? ` · láminas ${d.laminas.join(", ")}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Que el proveedor haya cambiado una cifra no es ruido de carga: es una
              lectura sobre el propio tracker, y el cliente paga por saberla. */}
          {outcome.cifras_que_cambian.length > 0 && (
            <div className="space-y-1">
              <p className="text-sm text-body">
                <span className="font-semibold">
                  {outcome.cifras_que_cambian.length} cifra(s) cambian respecto a lo que ya
                  estaba cargado
                </span>
                {outcome.no_reemplazan_por_entrega_mas_nueva > 0 && (
                  <>
                    {" "}
                    — de ellas {outcome.no_reemplazan_por_entrega_mas_nueva} no reemplazan
                    nada: una entrega posterior ya manda sobre esa ola. Quedan en el
                    registro.
                  </>
                )}
              </p>
              <ul className="space-y-1">
                {outcome.cifras_que_cambian.slice(0, 8).map((c, i) => (
                  <li key={i} className="text-xs text-muted mono truncate">
                    {c.marca} · {c.metrica} · {c.ola} ={" "}
                    {c.corregida != null
                      ? `${c.anterior} → ${c.corregida}`
                      : `${c.vigente} (vigente, de ${c.entrega_vigente}) · esta entrega decía ${c.esta_entrega}`}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <button className="btn btn-primary" onClick={onConfirmed}>
            Entendido
          </button>
        </div>
      )}

      {detail?.note && (
        <p className="text-sm text-body rounded-lg bg-surface2 p-3">{detail.note}</p>
      )}

      {counts && (
        <div className="flex flex-wrap gap-2">
          <Chip tone="ok">{counts.passed} confirmadas</Chip>
          {counts.unchecked > 0 && <Chip tone="muted">{counts.unchecked} sin verificar</Chip>}
          {counts.conflict > 0 && <Chip tone="warn">{counts.conflict} en conflicto</Chip>}
          {counts.failed > 0 && <Chip tone="alert">{counts.failed} inconsistentes</Chip>}
        </div>
      )}

      {(detail?.summary?.findings ?? []).length > 0 && (
        <ul className="space-y-1">
          {(detail?.summary?.findings ?? []).slice(0, 6).map((f, i) => (
            <li key={i} className="text-xs text-muted">
              <span className="font-semibold text-body">{f.kind}</span> · {f.detail}
            </li>
          ))}
        </ul>
      )}

      <div className={`space-y-2 ${outcome ? "hidden" : ""}`}>
        {cells.map((c: ExtractionCell) => {
          const isDropped = dropped.has(c.id);
          const blocked = c.validation === "failed";
          return (
            <div
              key={c.id}
              className={`rounded-lg border border-hair p-3 ${isDropped || blocked ? "opacity-55" : ""}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm text-ink">
                    <span className="font-semibold">{c.label}</span>
                    {c.brand ? ` · ${c.brand}` : " · categoría"}
                    {c.wave ? ` · ${c.wave}` : ""}
                    {c.attribute ? ` · «${c.attribute}»` : ""}
                    {c.segment !== "total" ? ` · ${c.segment}` : ""}
                  </div>
                  <div className="text-xs text-muted mt-0.5">
                    Lámina {c.page ?? "—"}
                    {c.chart ? ` · ${c.chart}` : ""}
                    {c.source_method === "both" ? " · dos fuentes coinciden" : ""}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="mono text-sm font-semibold text-ink">
                    {fmtNum(c.value)}
                    {c.base_n ? <span className="text-muted font-normal"> · n={c.base_n}</span> : null}
                  </span>
                  <Chip tone={VALIDATION_TONE[c.validation]}>
                    {VALIDATION_LABEL[c.validation]}
                  </Chip>
                </div>
              </div>
              {c.validation_note && (
                <p className="text-xs text-muted mt-1.5">{c.validation_note}</p>
              )}
              {!blocked && (
                <button
                  className="btn btn-ghost text-xs mt-2"
                  onClick={() => toggle(c.id)}
                >
                  {isDropped ? "Volver a incluir" : "Descartar"}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {error && <p className="text-sm rounded-lg bg-alert-soft text-alert p-3">{error}</p>}

      {!outcome && (
        <div className="flex items-center gap-2">
          <button
            className="btn btn-primary"
            disabled={busy || promotable === 0 || detail?.status === "confirmed"}
            onClick={submit}
          >
            {busy ? "Confirmando…" : `Confirmar ${promotable} celda(s)`}
          </button>
          <button className="btn btn-ghost" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
        </div>
      )}
    </InsightDrawerShell>
  );
}
