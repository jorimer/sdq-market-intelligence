import { useState } from "react";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { createEngagement, type EngagementInput } from "../api";

interface Props {
  onClose: () => void;
  onCreated: (slug: string) => void;
}

/** Slug from the focal brand: stable key, lowercase, no accents, dash-separated. */
function slugify(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

/** First step of the flow: without an engagement there is nothing to load data into. */
export function NewEngagementDrawer({ onClose, onCreated }: Props) {
  const [form, setForm] = useState<EngagementInput>({
    slug: "",
    client_name: "",
    focal_brand: "",
    market: "República Dominicana",
    category: "",
    research_provider: "",
  });
  const [slugTouched, setSlugTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (key: keyof EngagementInput) => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const onBrandChange = (value: string) => {
    setForm((f) => ({
      ...f,
      focal_brand: value,
      slug: slugTouched ? f.slug : slugify(value),
    }));
  };

  const valid =
    form.slug.trim().length >= 2 &&
    form.client_name.trim().length >= 2 &&
    form.focal_brand.trim().length >= 1;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await createEngagement({
        ...form,
        category: form.category?.trim() || undefined,
        research_provider: form.research_provider?.trim() || undefined,
      });
      onCreated(created.slug);
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "No se pudo crear el encargo.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <InsightDrawerShell eyebrow="Contexto de Marca" title="Nuevo encargo" onClose={onClose}>
      <p className="text-sm text-muted">
        Un encargo agrupa las olas, las marcas y las observaciones de un tracker. Es la
        frontera de aislamiento: los datos de un encargo no son visibles desde otro.
      </p>

      <div className="space-y-4">
        <label className="block">
          <span className="text-xs font-semibold text-body">Marca focal</span>
          <input
            className="field mt-1"
            value={form.focal_brand}
            onChange={(e) => onBrandChange(e.target.value)}
            placeholder="McDonald's"
            autoFocus
          />
          <span className="text-xs text-muted">La marca sobre la que trata el informe.</span>
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-body">Cliente</span>
          <input
            className="field mt-1"
            value={form.client_name}
            onChange={(e) => set("client_name")(e.target.value)}
            placeholder="Operador de franquicia"
          />
          <span className="text-xs text-muted">Quién contrata el estudio.</span>
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-body">Identificador</span>
          <input
            className="field mt-1 mono"
            value={form.slug}
            onChange={(e) => {
              setSlugTouched(true);
              set("slug")(slugify(e.target.value));
            }}
            placeholder="mcdonalds-rd"
          />
          <span className="text-xs text-muted">
            Llave estable del encargo. Se propone desde la marca; se puede ajustar.
          </span>
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs font-semibold text-body">Categoría</span>
            <input
              className="field mt-1"
              value={form.category ?? ""}
              onChange={(e) => set("category")(e.target.value)}
              placeholder="QSR"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-body">Mercado</span>
            <input
              className="field mt-1"
              value={form.market ?? ""}
              onChange={(e) => set("market")(e.target.value)}
            />
          </label>
        </div>

        <label className="block">
          <span className="text-xs font-semibold text-body">Proveedor de investigación</span>
          <input
            className="field mt-1"
            value={form.research_provider ?? ""}
            onChange={(e) => set("research_provider")(e.target.value)}
            placeholder="Agencia que levanta el tracker"
          />
        </label>
      </div>

      {error && (
        <p className="text-sm rounded-lg bg-danger-soft text-danger p-3">{error}</p>
      )}

      <div className="flex items-center gap-2">
        <button className="btn btn-primary" disabled={!valid || busy} onClick={submit}>
          {busy ? "Creando…" : "Crear encargo"}
        </button>
        <button className="btn btn-ghost" onClick={onClose} disabled={busy}>
          Cancelar
        </button>
      </div>

      <p className="text-xs text-muted">
        Al crearlo, el paso siguiente es descargar la plantilla, llenarla con los datos del
        tracker y cargarla.
      </p>
    </InsightDrawerShell>
  );
}
