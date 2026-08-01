/**
 * Lo que el estudio del proveedor AFIRMA, y la mesa de discrepancias.
 *
 * Dos vistas internas con una regla cada una. Las conclusiones se muestran con su
 * lámina — el recibo que permite comprobar que lo que el sistema atribuye al proveedor
 * está escrito en su mazo (en el informe del cliente esa referencia no viaja). Y la
 * mesa: el contraste abre discrepancias, pero solo una persona las cierra, con nota —
 * la conversación con el proveedor es suya, no del sistema.
 */
import { useCallback, useEffect, useState } from "react";
import { Quote, Scale } from "lucide-react";
import { Card, CardHead, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import {
  downloadMesa,
  getConclusions,
  getDiscrepancies,
  runContrast,
  updateDiscrepancy,
  type ConclusionsPayload,
  type DiscrepanciesPayload,
  type Discrepancy,
  type DiscrepancyStatus,
} from "../api";

const DIRECTION_LABEL: Record<string, string> = {
  sube: "sube", baja: "baja", estable: "estable",
};

const STATUS_TONE: Record<DiscrepancyStatus, "alert" | "warn" | "ok" | "muted"> = {
  abierta: "alert",
  discutida: "warn",
  acordada: "ok",
  retirada: "muted",
};

export function ConclusionsPanel({ slug }: { slug: string }) {
  const [conclusions, setConclusions] = useState<ConclusionsPayload | null>(null);
  const [mesa, setMesa] = useState<DiscrepanciesPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    try {
      const [c, d] = await Promise.all([getConclusions(slug), getDiscrepancies(slug)]);
      setConclusions(c);
      setMesa(d);
      setError(null);
    } catch {
      setError("No se pudieron cargar las conclusiones del estudio.");
    }
  }, [slug]);

  useEffect(() => {
    setConclusions(null);
    setMesa(null);
    setMsg(null);
    void load();
  }, [load]);

  const contrast = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const out = await runContrast(slug);
      setMsg(
        `${out.conclusiones} hallazgos contrastados: ${out.coinciden} coinciden, ` +
        `${out.discrepan} discrepan, ${out.no_evaluables} no evaluables.`,
      );
      await load();
    } catch {
      setError("El contraste no se pudo correr.");
    } finally {
      setBusy(false);
    }
  };

  const advance = async (d: Discrepancy, status: DiscrepancyStatus) => {
    let note: string | undefined;
    if (status === "acordada" || status === "retirada") {
      // La nota es obligatoria: sin ella, en tres meses nadie sabrá por qué esta
      // conclusión volvió a ser utilizable.
      const asked = window.prompt(
        status === "acordada"
          ? "¿Qué se acordó con el proveedor?"
          : "¿Por qué se retira la objeción?",
      );
      if (!asked || !asked.trim()) return;
      note = asked.trim();
    }
    setBusy(true);
    try {
      await updateDiscrepancy(slug, d.id, status, note);
      await load();
    } catch {
      setError("No se pudo actualizar la discrepancia.");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <Card>
        <CardHead icon={Quote} title="Lo que el estudio concluye" />
        <p className="text-sm text-alert">{error}</p>
      </Card>
    );
  }

  const hallazgos = (conclusions?.conclusions ?? []).filter(
    (c) => c.kind !== "contexto",
  );
  const visibles = showAll ? hallazgos : hallazgos.slice(0, 8);
  const bloqueantes = mesa?.bloqueantes ?? 0;

  return (
    <>
      <Card>
        <CardHead
          icon={Quote}
          title="Lo que el estudio concluye"
          subtitle="Leído del mazo del proveedor, literal y con su lámina — vista interna"
          right={
            <button
              type="button"
              className="btn-ghost text-sm shrink-0"
              onClick={() => void contrast()}
              disabled={busy || !conclusions?.total}
            >
              {busy ? "Contrastando…" : "Contrastar con las cifras"}
            </button>
          }
        />
        {msg && <p className="text-sm text-body mb-3">{msg}</p>}
        {conclusions == null ? (
          <p className="text-sm text-muted">Cargando…</p>
        ) : conclusions.total === 0 ? (
          <p className="text-sm text-muted">
            Este encargo aún no tiene conclusiones leídas. Se recogen solas al subir la
            presentación del proveedor: sube el PDF y vuelve aquí.
          </p>
        ) : (
          <div className="space-y-2">
            {visibles.map((c) => (
              <div key={c.id} className="border-t border-hair pt-2 first:border-t-0">
                <p className="text-sm text-body">«{c.claim}»</p>
                <p className="text-xs text-muted mt-1">
                  Lámina {c.page_number}
                  {c.subjects.length > 0 && <> · {c.subjects.join(", ")}</>}
                  {c.metric_code && <> · {c.metric_code}</>}
                  {c.direction && <> · {DIRECTION_LABEL[c.direction]}</>}
                  {c.kind === "recomendacion" && <> · recomendación</>}
                </p>
              </div>
            ))}
            {hallazgos.length > 8 && (
              <button
                type="button"
                className="btn-ghost text-xs"
                onClick={() => setShowAll((v) => !v)}
              >
                {showAll
                  ? "Mostrar menos"
                  : `Mostrar las ${fmtNum(hallazgos.length, 0)} conclusiones`}
              </button>
            )}
          </div>
        )}
      </Card>

      <Card>
        <CardHead
          icon={Scale}
          title="Mesa de discrepancias con el proveedor"
          subtitle="Desacuerdos defendibles con las cifras. Se discuten con el proveedor antes de que nada llegue al cliente"
          right={
            <div className="flex items-center gap-2 shrink-0">
              {bloqueantes > 0 && <Chip tone="alert">{bloqueantes} bloqueante(s)</Chip>}
              {(mesa?.total ?? 0) > 0 && (
                <button
                  type="button"
                  className="btn-ghost text-sm"
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    // La nota lleva láminas y umbrales: es material SDQ ↔ proveedor,
                    // nunca del cliente — el propio documento lo estampa en su pie.
                    downloadMesa(slug)
                      .catch(() => setError("No se pudo descargar la nota de mesa."))
                      .finally(() => setBusy(false));
                  }}
                >
                  Nota para la mesa (PDF)
                </button>
              )}
            </div>
          }
        />
        {mesa == null ? (
          <p className="text-sm text-muted">Cargando…</p>
        ) : mesa.total === 0 ? (
          <p className="text-sm text-muted">
            Sin discrepancias: las cifras confirmadas no contradicen de frente ninguna
            conclusión del estudio. Correr el contraste tras cada nueva entrega mantiene
            esta mesa al día.
          </p>
        ) : (
          <div className="space-y-3">
            {mesa.discrepancies.map((d) => (
              <div key={d.id} className="border-t border-hair pt-3 first:border-t-0">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-body">«{d.claim}»</p>
                    <p className="text-xs text-muted mt-1">
                      Lámina {d.page_number} · {d.metric_code} · el estudio dice{" "}
                      {d.provider_direction}
                    </p>
                    <p className="text-xs text-body mt-1">{d.data_note}</p>
                    {d.resolution_note && (
                      <p className="text-xs text-muted mt-1">
                        Resolución: {d.resolution_note}
                        {d.updated_by && <> — {d.updated_by}</>}
                      </p>
                    )}
                  </div>
                  <Chip tone={STATUS_TONE[d.status]}>{d.status}</Chip>
                </div>
                {(d.status === "abierta" || d.status === "discutida") && (
                  <div className="flex gap-2 mt-2">
                    {d.status === "abierta" && (
                      <button
                        type="button"
                        className="btn-ghost text-xs"
                        disabled={busy}
                        onClick={() => void advance(d, "discutida")}
                      >
                        Marcar discutida
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn-ghost text-xs"
                      disabled={busy}
                      onClick={() => void advance(d, "acordada")}
                    >
                      Acordada
                    </button>
                    <button
                      type="button"
                      className="btn-ghost text-xs"
                      disabled={busy}
                      onClick={() => void advance(d, "retirada")}
                    >
                      Retirar objeción
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
