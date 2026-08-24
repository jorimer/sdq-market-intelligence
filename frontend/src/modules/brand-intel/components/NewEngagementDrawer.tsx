import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import {
  createClient,
  createEngagement,
  listClients,
  type BrandClient,
  type EngagementInput,
} from "../api";
import { mensajeDeError } from "../../../shared/api/errores";

interface Props {
  onClose: () => void;
  onCreated: (slug: string) => void;
}

/**
 * Slug from the focal brand: stable key, lowercase, no accents, dash-separated.
 *
 * Apostrophes are dropped rather than split on — they sit inside a word, and a brand
 * called "McDonald's" should propose `mcdonalds`, not `mcdonald-s`.
 */
function slugify(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/['‘’ʼ`´]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

/** Código legible desde el nombre del cliente. Se propone; se puede editar. */
function clientCodeFrom(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
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
  const [clients, setClients] = useState<BrandClient[]>([]);
  const [newClient, setNewClient] = useState(false);
  const [clientName, setClientName] = useState("");
  const [clientCode, setClientCode] = useState("");
  const [codeTouched, setCodeTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listClients()
      .then((rows) => {
        setClients(rows);
        // Sin ningún cliente todavía, lo primero es crearlo: es el paso que ahora
        // encabeza el flujo, no un campo más del encargo.
        if (!rows.length) setNewClient(true);
      })
      .catch(() => setNewClient(true));
  }, []);

  const set = (key: keyof EngagementInput) => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const onBrandChange = (value: string) => {
    setForm((f) => ({
      ...f,
      focal_brand: value,
      slug: slugTouched ? f.slug : slugify(value),
    }));
  };

  const clientReady = newClient
    ? clientName.trim().length >= 2 && clientCode.trim().length >= 2
    : (form.client ?? "").length > 0;

  const valid =
    form.slug.trim().length >= 2 &&
    form.focal_brand.trim().length >= 1 &&
    clientReady;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      let code = form.client;
      let name = form.client_name;
      if (newClient) {
        const c = await createClient({ code: clientCode.trim(), name: clientName.trim() });
        code = c.code;
        name = c.name;
      } else {
        name = clients.find((c) => c.code === code)?.name ?? name;
      }
      const created = await createEngagement({
        ...form,
        client: code,
        client_name: name,
        category: form.category?.trim() || undefined,
        research_provider: form.research_provider?.trim() || undefined,
      });
      onCreated(created.slug);
    } catch (e: unknown) {
      setError(mensajeDeError(e, "No se pudo crear el encargo."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <InsightDrawerShell eyebrow="Contexto de Marca" title="Nuevo encargo" onClose={onClose}>
      <p className="text-sm text-muted">
        Primero el cliente, después el estudio. Un cliente puede tener varios estudios;
        cada estudio es la frontera de aislamiento y sus datos no son visibles desde otro.
      </p>

      <div className="space-y-4">
        {/* El cliente encabeza el formulario: es lo que se elige primero, y de él
            cuelgan todos los estudios que se le hagan. */}
        {newClient ? (
          <div className="rounded-lg bg-surface2 p-3 space-y-3">
            <label className="block">
              <span className="text-xs font-semibold text-body">Cliente nuevo</span>
              <input
                className="field mt-1"
                value={clientName}
                onChange={(e) => {
                  setClientName(e.target.value);
                  if (!codeTouched) setClientCode(clientCodeFrom(e.target.value));
                }}
                placeholder="Operador de franquicia"
              />
              <span className="text-xs text-muted">Quién contrata los estudios.</span>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-body">Código del cliente</span>
              <input
                className="field mt-1 mono"
                value={clientCode}
                onChange={(e) => {
                  setCodeTouched(true);
                  setClientCode(e.target.value.toUpperCase());
                }}
                placeholder="MCD-RD"
              />
              <span className="text-xs text-muted">
                Llave estable del cliente. Se propone desde el nombre; se puede ajustar.
              </span>
            </label>
            {clients.length > 0 && (
              <button
                className="btn btn-ghost text-xs"
                onClick={() => setNewClient(false)}
              >
                Elegir uno existente
              </button>
            )}
          </div>
        ) : (
          <label className="block">
            <span className="text-xs font-semibold text-body">Cliente</span>
            <select
              className="field mt-1"
              value={form.client ?? ""}
              onChange={(e) => set("client")(e.target.value)}
            >
              <option value="">Elige un cliente…</option>
              {clients.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name} ({c.code}) — {c.engagements} estudio(s)
                </option>
              ))}
            </select>
            <button
              className="btn btn-ghost text-xs mt-2"
              onClick={() => setNewClient(true)}
            >
              <Plus size={13} /> Cliente nuevo
            </button>
          </label>
        )}

        <label className="block">
          <span className="text-xs font-semibold text-body">Marca focal o tema</span>
          <input
            className="field mt-1"
            value={form.focal_brand}
            onChange={(e) => onBrandChange(e.target.value)}
            placeholder="McDonald's"
            autoFocus
          />
          <span className="text-xs text-muted">
            Sobre qué trata el estudio: la marca del tracker, o el asunto que mide.
          </span>
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
        <p className="text-sm rounded-lg bg-alert-soft text-alert p-3">{error}</p>
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
