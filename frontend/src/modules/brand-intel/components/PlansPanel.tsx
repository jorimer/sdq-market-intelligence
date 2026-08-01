/**
 * Los planes del cliente: subir el documento, revisar lo que el lector propuso, adoptar.
 *
 * El flujo entero vive aquí para que registrar el plan de una agencia no requiera
 * teclear decisión por decisión: se sube el PDF/HTML, el lector extrae las metas con su
 * página como recibo, y cada una se adopta (con ajustes) o se descarta (con motivo).
 * El portón humano es la adopción — nada de lo que el lector propone llega al informe
 * del cliente sin pasar por él.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Upload } from "lucide-react";
import { Card, CardHead, Chip } from "@/shared/ui/primitives";
import {
  dismissPlanGoal,
  getPlanDetail,
  listPlans,
  uploadPlan,
  type PlanDetail,
  type PlanDocument,
  type PlanGoal,
  type SignalRow,
  type WaveRef,
} from "../api";
import { PlanReviewDrawer } from "./PlanReviewDrawer";

const GOAL_TONE: Record<PlanGoal["status"], "warn" | "ok" | "muted"> = {
  propuesta: "warn",
  adoptada: "ok",
  descartada: "muted",
};

interface Props {
  slug: string;
  dataWaves: WaveRef[];
  allWaves: WaveRef[];
  metrics: SignalRow[];
  focalBrand: string | null;
  /** El ledger cambió (una meta se adoptó): la página recarga decisiones e informe. */
  onLedgerChange: () => void;
}

export function PlansPanel({
  slug, dataWaves, allWaves, metrics, focalBrand, onLedgerChange,
}: Props) {
  const [plans, setPlans] = useState<PlanDocument[]>([]);
  const [open, setOpen] = useState<PlanDetail | null>(null);
  const [adopting, setAdopting] = useState<PlanGoal | null>(null);
  const [dismissing, setDismissing] = useState<PlanGoal | null>(null);
  const [dismissNote, setDismissNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const ps = await listPlans(slug);
      setPlans(ps);
      setError(null);
    } catch {
      setError("No se pudieron cargar los planes.");
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshOpen = useCallback(async (planId: string) => {
    const d = await getPlanDetail(slug, planId);
    setOpen(d);
  }, [slug]);

  const onUpload = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const created = await uploadPlan(slug, file);
      await load();
      await refreshOpen(created.id);
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "No se pudo leer el plan.");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const onDismiss = async () => {
    if (!open || !dismissing || dismissNote.trim().length < 5) return;
    setBusy(true);
    try {
      await dismissPlanGoal(slug, open.id, dismissing.id, dismissNote.trim());
      setDismissing(null);
      setDismissNote("");
      await refreshOpen(open.id);
      await load();
    } catch {
      setError("No se pudo descartar la meta.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHead
        icon={FileText}
        title="Planes del cliente"
        subtitle="El lector propone las metas del documento; solo una persona las adopta al ledger"
      />

      <div className="flex items-center gap-3">
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.html,.htm"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onUpload(f);
          }}
        />
        <button
          className="btn btn-primary"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="h-4 w-4" />
          {busy ? "Leyendo el plan…" : "Subir plan (.pdf / .html)"}
        </button>
        {busy && (
          <span className="text-xs text-muted">
            El lector trabaja sobre la capa de texto; suele tomar menos de un minuto.
          </span>
        )}
      </div>

      {error && <p className="mt-3 text-sm rounded-lg bg-alert-soft text-alert p-3">{error}</p>}

      {plans.length === 0 && !busy && (
        <p className="mt-3 text-sm text-muted">
          Aún no hay planes cargados. Sube el documento que el cliente compartió (la
          estrategia de su agencia, su plan de medios) para proponer sus metas.
        </p>
      )}

      <div className="mt-3 space-y-2">
        {plans.map((p) => (
          <div key={p.id} className="rounded-lg border border-line p-3">
            <button
              className="flex w-full items-center justify-between gap-2 text-left"
              onClick={() =>
                open?.id === p.id ? setOpen(null) : void refreshOpen(p.id)
              }
            >
              <div>
                <div className="text-sm font-semibold text-body">
                  {p.title ?? p.filename}
                </div>
                <div className="text-xs text-muted">
                  {p.source_org ? `${p.source_org} · ` : ""}
                  {p.goals.total} meta(s): {p.goals.adoptadas} adoptada(s) ·{" "}
                  {p.goals.propuestas} por revisar · {p.goals.descartadas} descartada(s)
                </div>
              </div>
              <Chip tone={p.status === "revisado" ? "ok" : "warn"}>
                {p.status === "revisado" ? "Revisado" : "Por revisar"}
              </Chip>
            </button>

            {open?.id === p.id && (
              <div className="mt-3 space-y-2 border-t border-line pt-3">
                {open.metas.length === 0 && (
                  <p className="text-sm text-muted">
                    {open.note ?? "El lector no encontró metas en este documento."}
                  </p>
                )}
                {open.metas.map((g) => (
                  <div key={g.id} className="rounded-lg bg-panel p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="text-sm text-body">
                        «{g.claim}»
                        <div className="mt-1 text-xs text-muted">
                          {g.page_number ? `Página ${g.page_number} · ` : ""}
                          {g.kind === "accion" ? "Acción · " : ""}
                          {g.metric_code
                            ? `Tracker: ${g.metric_code}`
                            : `Fuente: ${g.measure_source ?? "sin declarar"}`}
                          {g.segment !== "total" ? ` · ${g.segment}` : ""}
                          {!g.confident ? " · lectura con duda" : ""}
                        </div>
                        {g.status === "descartada" && g.dismiss_note && (
                          <div className="mt-1 text-xs text-muted">
                            Descartada: {g.dismiss_note}
                          </div>
                        )}
                      </div>
                      <Chip tone={GOAL_TONE[g.status]}>{g.status}</Chip>
                    </div>
                    {g.status === "propuesta" && (
                      <div className="mt-2 flex gap-2">
                        <button
                          className="btn btn-primary"
                          onClick={() => setAdopting(g)}
                          disabled={busy}
                        >
                          Adoptar…
                        </button>
                        <button
                          className="btn btn-ghost"
                          onClick={() => {
                            setDismissing(g);
                            setDismissNote("");
                          }}
                          disabled={busy}
                        >
                          Descartar…
                        </button>
                      </div>
                    )}
                    {dismissing?.id === g.id && (
                      <div className="mt-2 flex items-center gap-2">
                        <input
                          className="field"
                          value={dismissNote}
                          onChange={(e) => setDismissNote(e.target.value)}
                          placeholder="Por qué no se adopta (obligatorio)"
                          autoFocus
                        />
                        <button
                          className="btn btn-primary"
                          disabled={dismissNote.trim().length < 5 || busy}
                          onClick={() => void onDismiss()}
                        >
                          Confirmar
                        </button>
                        <button
                          className="btn btn-ghost"
                          onClick={() => setDismissing(null)}
                        >
                          Cancelar
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {adopting && open && (
        <PlanReviewDrawer
          slug={slug}
          planId={open.id}
          goal={adopting}
          dataWaves={dataWaves}
          allWaves={allWaves}
          metrics={metrics}
          focalBrand={focalBrand}
          onClose={() => setAdopting(null)}
          onAdopted={() => {
            setAdopting(null);
            void refreshOpen(open.id);
            void load();
            onLedgerChange();
          }}
        />
      )}
    </Card>
  );
}
