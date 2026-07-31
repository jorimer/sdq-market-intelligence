import { useState } from "react";
import { AlertTriangle, Loader2, Trash2 } from "lucide-react";

import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { deleteEngagement } from "../api";

interface Props {
  slug: string;
  focalBrand: string;
  client: string;
  waves: number;
  brands: number;
  extractions: number;
  onClose: () => void;
  onDeleted: () => void;
}

/**
 * Deleting an engagement: the one action in this module that cannot be undone.
 *
 * Everything else here is recoverable — a bad ingest can be re-run, a wrong structure
 * re-adopted, a confirmed extraction superseded. This erases a client's dataset along
 * with the provenance trail that lets the report say where each figure came from, so the
 * drawer states what is about to be destroyed and asks for the identifier by hand. A
 * confirmation the user can dismiss by reflex is not a confirmation.
 */
export function DeleteEngagementDrawer({
  slug, focalBrand, client, waves, brands, extractions, onClose, onDeleted,
}: Props) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const armed = typed.trim() === slug;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteEngagement(slug);
      onDeleted();
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const status = (e as { response?: { status?: number } })?.response?.status;
      setError(
        status === 403
          ? "Hace falta rol de administrador para eliminar un encargo."
          : detail ?? "No se pudo eliminar el encargo.",
      );
      setBusy(false);
    }
  };

  return (
    <InsightDrawerShell
      eyebrow="Contexto de Marca"
      title="Eliminar el encargo"
      onClose={onClose}
    >
      <p className="text-sm text-muted">
        Se borra el encargo <span className="text-body font-semibold">{focalBrand}</span>{" "}
        de {client} y todo lo que cuelga de él. No hay deshacer, y no queda copia: el
        informe deja de poder reconstruirse porque desaparece también la procedencia de
        cada cifra.
      </p>

      <div className="rounded-lg bg-surface2 p-3">
        <div className="text-xs uppercase tracking-wide text-muted mb-2">
          Lo que se destruye
        </div>
        <ul className="space-y-1 text-sm text-body">
          <li className="flex items-baseline justify-between gap-3">
            <span className="truncate">Olas</span>
            <span className="mono tabular-nums shrink-0">{waves}</span>
          </li>
          <li className="flex items-baseline justify-between gap-3">
            <span className="truncate">Marcas</span>
            <span className="mono tabular-nums shrink-0">{brands}</span>
          </li>
          <li className="flex items-baseline justify-between gap-3">
            <span className="truncate">Presentaciones leídas</span>
            <span className="mono tabular-nums shrink-0">{extractions}</span>
          </li>
          <li className="flex items-baseline justify-between gap-3 text-muted">
            <span className="truncate">
              Observaciones, decisiones y pronósticos del encargo
            </span>
            <span className="mono shrink-0">todos</span>
          </li>
        </ul>
      </div>

      <label className="block">
        <span className="text-xs font-semibold text-body">
          Escribe <span className="mono">{slug}</span> para confirmar
        </span>
        <input
          type="text"
          className="field mt-1 mono"
          value={typed}
          autoComplete="off"
          spellCheck={false}
          placeholder={slug}
          onChange={(e) => setTyped(e.target.value)}
          aria-label={`Escribe ${slug} para confirmar la eliminación`}
        />
      </label>

      {error && (
        <div className="text-sm rounded-lg bg-alert-soft text-alert p-3 flex items-start gap-2">
          <AlertTriangle size={15} className="shrink-0 mt-px" />
          <span>{error}</span>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          className="btn btn-alert"
          disabled={!armed || busy}
          onClick={() => void submit()}
        >
          {busy ? (
            <>
              <Loader2 size={15} className="animate-spin" /> Eliminando…
            </>
          ) : (
            <>
              <Trash2 size={15} /> Eliminar definitivamente
            </>
          )}
        </button>
        <button className="btn btn-ghost" onClick={onClose} disabled={busy}>
          Cancelar
        </button>
      </div>
    </InsightDrawerShell>
  );
}
