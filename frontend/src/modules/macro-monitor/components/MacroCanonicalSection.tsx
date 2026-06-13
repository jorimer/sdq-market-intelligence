import { Fragment, useCallback, useEffect, useState } from "react";
import { BookMarked, Loader2, ChevronRight, Link2 } from "lucide-react";
import { Card, CardHead, StatTile, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { getCanonical, ingestCanonical, CanonicalSeries } from "../api";

const SECTOR_LABEL: Record<string, string> = {
  precios: "Precios",
  sector_real: "Sector real",
  sector_externo: "Sector externo",
  sector_monetario_financiero: "Monetario y financiero",
  mercado_cambiario: "Mercado cambiario",
  mercado_de_trabajo: "Mercado de trabajo",
  sector_turismo: "Turismo",
};

const ROBUSTNESS: Record<string, { tone: "ok" | "warn" | "alert"; label: string }> = {
  green: { tone: "ok", label: "robusto" },
  yellow: { tone: "warn", label: "revisar" },
  red: { tone: "alert", label: "pendiente" },
};

/** The canonical registry — the base-homogeneous selection (~25 series) an analyst
 * cites in reports: source, base, frequency, homogenization, economist rationale,
 * robustness and the API series it ties to. This is the documentation surface. */
export function MacroCanonicalSection() {
  const [series, setSeries] = useState<CanonicalSeries[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const { series } = await getCanonical();
      setSeries(series);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const ingest = async (persist: boolean) => {
    setBusy(true);
    setNote("");
    try {
      const r = await ingestCanonical(persist);
      setNote(r.message);
      // it runs in the background; refresh the extraction column shortly after
      setTimeout(load, 4000);
    } catch (e: unknown) {
      const s = (e as { response?: { status?: number } })?.response?.status;
      setNote(s === 403 ? "Requiere rol de administrador." : "No se pudo ingerir el set canónico.");
    } finally {
      setBusy(false);
    }
  };

  const counts = {
    green: series.filter((s) => s.robustness === "green").length,
    yellow: series.filter((s) => s.robustness === "yellow").length,
    red: series.filter((s) => s.robustness === "red").length,
  };

  return (
    <Card>
      <CardHead
        icon={BookMarked}
        title="Catálogo canónico de series"
        subtitle="Selección base-homogénea del BCRD (708 archivos → un set citable, atado al API)"
        right={
          <div className="flex gap-2">
            <button onClick={() => ingest(false)} disabled={busy} className="btn btn-soft">
              {busy ? <Loader2 size={14} className="animate-spin" /> : null} Analizar
            </button>
            <button onClick={() => ingest(true)} disabled={busy} className="btn btn-primary">
              Ingerir set
            </button>
          </div>
        }
      />

      {status === "error" && (
        <StateBlock
          kind="error"
          message="No se pudo cargar el catálogo canónico."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>}
        />
      )}

      {status === "loading" && (
        <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
      )}

      {status === "ready" && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <StatTile label="Series canónicas" value={series.length} />
            <StatTile label="Robustas" value={counts.green} />
            <StatTile label="A revisar" value={counts.yellow} />
            <StatTile label="Pendientes" value={counts.red} />
          </div>

          {note && <div className="text-xs text-muted bg-surface2 px-3 py-2 rounded-[10px] mb-3">{note}</div>}

          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-1 font-medium">Serie</th>
                  <th className="py-2 px-1 font-medium">Sector</th>
                  <th className="py-2 px-1 font-medium">Base</th>
                  <th className="py-2 px-1 font-medium">Frec.</th>
                  <th className="py-2 px-1 font-medium">API</th>
                  <th className="py-2 px-1 font-medium">Robustez</th>
                </tr>
              </thead>
              <tbody>
                {series.map((s) => {
                  const r = ROBUSTNESS[s.robustness];
                  const isOpen = open === s.key;
                  return (
                    <Fragment key={s.key}>
                      <tr
                        onClick={() => setOpen(isOpen ? null : s.key)}
                        className="border-b border-line/60 cursor-pointer hover:bg-surface2/60"
                      >
                        <td className="py-2 px-1">
                          <div className="flex items-center gap-1.5">
                            <ChevronRight
                              size={13}
                              className={`text-faint shrink-0 transition-transform ${isOpen ? "rotate-90" : ""}`}
                            />
                            <div className="min-w-0">
                              <div className="text-ink truncate">{s.concept}</div>
                              <div className="mono text-[11px] text-faint truncate">{s.source_file}</div>
                            </div>
                          </div>
                        </td>
                        <td className="py-2 px-1 text-xs text-body">{SECTOR_LABEL[s.sector] ?? s.sector}</td>
                        <td className="py-2 px-1 text-xs text-body">{s.base}</td>
                        <td className="py-2 px-1 text-xs text-body">{s.frequency}</td>
                        <td className="py-2 px-1">
                          {s.api_series ? (
                            <span className="inline-flex items-center gap-1 text-xs text-accent">
                              <Link2 size={12} /> {s.api_transform === "yoy" ? "YoY" : "sí"}
                            </span>
                          ) : (
                            <span className="text-xs text-faint">—</span>
                          )}
                        </td>
                        <td className="py-2 px-1">
                          <Chip tone={r.tone}>{r.label}</Chip>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="border-b border-line/60 bg-surface2/40">
                          <td colSpan={6} className="py-3 px-3">
                            <div className="space-y-2 text-xs">
                              <div>
                                <span className="font-semibold text-muted">Razón (economista): </span>
                                <span className="text-body">{s.rationale}</span>
                              </div>
                              <div>
                                <span className="font-semibold text-muted">Homogeneización: </span>
                                <span className="text-body">{s.homogenization}</span>
                              </div>
                              {s.api_series && (
                                <div>
                                  <span className="font-semibold text-muted">Serie API: </span>
                                  <span className="mono text-body">{s.api_series}</span>
                                  <span className="text-faint">
                                    {" "}
                                    · comparación {s.api_transform === "yoy" ? "por variación interanual" : "directa"}
                                  </span>
                                </div>
                              )}
                              {s.extraction ? (
                                <div>
                                  <span className="font-semibold text-muted">Extracción: </span>
                                  <span className="text-body">
                                    {s.extraction.status} · {s.extraction.n_series} series ·{" "}
                                    {s.extraction.orientation} · {s.extraction.method}
                                  </span>
                                </div>
                              ) : (
                                <div className="text-faint">Aún no extraída (corre "Analizar" o el barrido).</div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
