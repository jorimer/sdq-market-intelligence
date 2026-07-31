import { useState } from "react";
import { AlertTriangle, Check, FileSearch, Loader2 } from "lucide-react";

import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import {
  adoptStructure,
  discoverStructure,
  type BrandCandidate,
  type StructureProposal,
  type WaveCandidate,
} from "../api";

interface Props {
  slug: string;
  focalBrand: string;
  onClose: () => void;
  onAdopted: () => void;
}

interface WaveRow extends WaveCandidate {
  keep: boolean;
  period: string;
}

interface BrandRow extends BrandCandidate {
  keep: boolean;
  inSet: boolean;
}

function foldName(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

/**
 * Adopting the deck's structure: the step that lets an engagement exist without the
 * provider's workbook.
 *
 * The reading pass proposes; nothing is created until the reviewer confirms. That
 * ordering is the whole point — the strict ingest refuses labels it cannot map, so the
 * competitive set adopted here decides what the deck's figures are allowed to become.
 */
export function StructureDrawer({ slug, focalBrand, onClose, onAdopted }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [proposal, setProposal] = useState<StructureProposal | null>(null);
  const [waves, setWaves] = useState<WaveRow[]>([]);
  const [brands, setBrands] = useState<BrandRow[]>([]);
  const [focal, setFocal] = useState<string>("");
  const [phase, setPhase] = useState<"idle" | "reading" | "review" | "saving">("idle");
  const [error, setError] = useState<string | null>(null);

  const read = async (f: File) => {
    setPhase("reading");
    setError(null);
    try {
      const p = await discoverStructure(slug, f);
      setProposal(p);
      setWaves(p.waves.map((w) => ({ ...w, keep: true, period: w.period_date })));
      const rows = p.brands.map((b) => ({ ...b, keep: true, inSet: true }));
      setBrands(rows);
      // The engagement already named its focal brand; match it so the reviewer does not
      // have to re-pick what they already told us.
      const target = foldName(focalBrand);
      const hit = rows.find((b) => foldName(b.name) === target)
        ?? rows.find((b) => foldName(b.name).includes(target) && target.length > 3);
      setFocal(hit?.name ?? "");
      setPhase("review");
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "No se pudo leer la presentación.");
      setPhase("idle");
    }
  };

  const save = async () => {
    setPhase("saving");
    setError(null);
    try {
      await adoptStructure(slug, {
        waves: waves
          .filter((w) => w.keep)
          .map((w) => ({ code: w.code, label: w.label, period_date: w.period || null })),
        brands: brands
          .filter((b) => b.keep)
          .map((b) => ({
            name: b.name,
            is_focal: b.name === focal,
            in_category_set: b.inSet,
          })),
      });
      onAdopted();
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "No se pudo guardar la estructura.");
      setPhase("review");
    }
  };

  const keptWaves = waves.filter((w) => w.keep).length;
  const keptBrands = brands.filter((b) => b.keep).length;
  const noDate = waves.some((w) => w.keep && !w.period);

  return (
    <InsightDrawerShell
      eyebrow="Contexto de Marca"
      title="Estructura del tracker"
      onClose={onClose}
    >
      <p className="text-sm text-muted">
        Las olas y las marcas del estudio se leen de la propia presentación. El sistema
        propone lo que encuentra; nada se crea hasta que lo confirmas. Después, la carga
        de láminas solo acepta cifras que encajen en esta estructura.
      </p>

      {phase === "idle" && (
        <div className="space-y-4">
          <label className="block">
            <span className="text-xs font-semibold text-body">Presentación del proveedor</span>
            <input
              type="file"
              accept=".pdf"
              className="field mt-1"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <span className="text-xs text-muted">
              Las olas salen del texto del PDF sin costo. Las marcas se leen de una
              muestra de láminas, no del mazo completo.
            </span>
          </label>
          {error && (
            <div className="text-xs text-danger flex items-start gap-2">
              <AlertTriangle size={14} className="shrink-0 mt-px" />
              <span>{error}</span>
            </div>
          )}
          <button
            className="btn btn-primary w-full"
            disabled={!file}
            onClick={() => file && void read(file)}
          >
            <FileSearch size={15} /> Leer la presentación
          </button>
        </div>
      )}

      {phase === "reading" && (
        <div className="flex items-center gap-2 text-sm text-muted py-8 justify-center">
          <Loader2 size={16} className="animate-spin shrink-0" />
          <span>Leyendo la presentación…</span>
        </div>
      )}

      {(phase === "review" || phase === "saving") && proposal && (
        <div className="space-y-6">
          <div className="text-xs text-muted">{proposal.note}</div>

          <section className="space-y-2">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-semibold text-body truncate min-w-0 flex-1">
                Olas encontradas
              </h3>
              <span className="text-xs text-muted mono shrink-0 tabular-nums">
                {keptWaves}/{waves.length}
              </span>
            </div>
            {waves.length === 0 && (
              <p className="text-xs text-muted">
                No se encontró ninguna fecha de ola en el texto del PDF.
              </p>
            )}
            {waves.map((w, i) => (
              <div key={w.code} className="flex items-center gap-3 py-1">
                <input
                  type="checkbox"
                  checked={w.keep}
                  onChange={(e) =>
                    setWaves((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, keep: e.target.checked } : x)),
                    )
                  }
                  aria-label={`Adoptar ${w.label}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-body truncate">{w.label}</div>
                  <div className="text-xs text-muted mono truncate">
                    {w.code} · {w.occurrences} menciones
                    {w.spellings.length > 1 ? ` · ${w.spellings.join(" / ")}` : ""}
                  </div>
                </div>
                <input
                  type="date"
                  className="field w-auto text-xs shrink-0"
                  value={w.period}
                  onChange={(e) =>
                    setWaves((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, period: e.target.value } : x)),
                    )
                  }
                  aria-label={`Fecha de referencia de ${w.label}`}
                />
              </div>
            ))}
            {proposal.discarded_waves.length > 0 && (
              <p className="text-xs text-muted">
                Descartadas por aparecer pocas veces:{" "}
                {proposal.discarded_waves.map((d) => d.label).join(", ")}.
              </p>
            )}
          </section>

          <section className="space-y-2">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-semibold text-body truncate min-w-0 flex-1">
                Marcas encontradas
              </h3>
              <span className="text-xs text-muted mono shrink-0 tabular-nums">
                {keptBrands}/{brands.length}
              </span>
            </div>
            {brands.length === 0 && (
              <p className="text-xs text-muted">
                No se leyó ninguna marca.{" "}
                {proposal.brand_pass_error || "Puedes cargarlas con la plantilla Excel."}
              </p>
            )}
            {brands.map((b, i) => (
              <div key={b.name} className="flex items-center gap-3 py-1">
                <input
                  type="checkbox"
                  checked={b.keep}
                  onChange={(e) =>
                    setBrands((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, keep: e.target.checked } : x)),
                    )
                  }
                  aria-label={`Adoptar ${b.name}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-body truncate">{b.name}</div>
                  <div className="text-xs text-muted mono truncate">
                    {b.occurrences} menciones
                    {b.spellings.length > 1 ? ` · ${b.spellings.join(" / ")}` : ""}
                  </div>
                </div>
                <label className="text-xs text-muted flex items-center gap-1 shrink-0">
                  <input
                    type="radio"
                    name="focal-brand"
                    checked={focal === b.name}
                    disabled={!b.keep}
                    onChange={() => setFocal(b.name)}
                  />
                  focal
                </label>
              </div>
            ))}
          </section>

          {noDate && (
            <div className="text-xs text-muted flex items-start gap-2">
              <AlertTriangle size={14} className="shrink-0 mt-px" />
              <span>
                Una ola sin fecha de referencia no podrá deflactarse: el ticket en pesos
                constantes quedará fuera del informe.
              </span>
            </div>
          )}
          {!focal && keptBrands > 0 && (
            <div className="text-xs text-muted flex items-start gap-2">
              <AlertTriangle size={14} className="shrink-0 mt-px" />
              <span>
                Marca cuál es la marca focal: sin ella no se calculan las secciones que
                comparan al cliente contra la categoría.
              </span>
            </div>
          )}
          {error && (
            <div className="text-xs text-danger flex items-start gap-2">
              <AlertTriangle size={14} className="shrink-0 mt-px" />
              <span>{error}</span>
            </div>
          )}

          <button
            className="btn btn-primary w-full"
            disabled={phase === "saving" || (!keptWaves && !keptBrands)}
            onClick={() => void save()}
          >
            {phase === "saving" ? (
              <>
                <Loader2 size={15} className="animate-spin" /> Guardando…
              </>
            ) : (
              <>
                <Check size={15} /> Adoptar {keptWaves} ola{keptWaves === 1 ? "" : "s"} y{" "}
                {keptBrands} marca{keptBrands === 1 ? "" : "s"}
              </>
            )}
          </button>
        </div>
      )}
    </InsightDrawerShell>
  );
}
