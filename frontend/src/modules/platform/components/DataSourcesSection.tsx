import { useEffect, useState } from "react";
import { KeyRound, ShieldCheck, Wifi, Plus, Trash2, Loader2 } from "lucide-react";
import { Card, CardHead, Chip, StateBlock } from "@/shared/ui/primitives";
import {
  settingsApi,
  AppSettings,
  SectorApi,
  SectorApiInput,
} from "../settingsApi";

const MASK = "••••••••";

/** Claude API key + sector benchmark APIs. Admin-only (gated by the page). */
export function DataSourcesSection() {
  const [data, setData] = useState<AppSettings | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  async function reload() {
    setLoading(true);
    setError(false);
    try {
      setData(await settingsApi.get());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
  }, []);

  if (loading) return <StateBlock kind="loading" />;
  if (error || !data)
    return (
      <StateBlock
        kind="error"
        message="No se pudo cargar la configuración."
        action={
          <button className="btn btn-soft" onClick={reload}>
            Reintentar
          </button>
        }
      />
    );

  return (
    <div className="space-y-5">
      <ClaudeKeyCard data={data} onSaved={reload} />
      <SectorApisCard data={data} onChanged={reload} />
    </div>
  );
}

/* ── Claude API key ──────────────────────────────────────────── */
function ClaudeKeyCard({ data, onSaved }: { data: AppSettings; onSaved: () => void }) {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      await settingsApi.update({ claudeApiKey: value });
      setValue("");
      setMsg("Guardado");
      onSaved();
    } catch {
      setMsg("Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHead
        icon={KeyRound}
        title="Configuración de API"
        subtitle="Su clave de API para funciones de análisis de IA"
      />
      <label className="block text-xs font-medium text-muted mb-1">Clave de API de Claude</label>
      <div className="flex gap-2">
        <input
          type="password"
          className="field mono flex-1"
          placeholder={data.claudeApiKeySet ? MASK + " (configurada)" : "sk-ant-…"}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button className="btn btn-primary shrink-0" disabled={!value || saving} onClick={save}>
          {saving ? <Loader2 size={15} className="animate-spin" /> : "Guardar"}
        </button>
      </div>
      {msg && <p className="text-xs text-muted mt-2">{msg}</p>}
    </Card>
  );
}

/* ── Sector benchmark APIs ───────────────────────────────────── */
function SectorApisCard({ data, onChanged }: { data: AppSettings; onChanged: () => void }) {
  const [editing, setEditing] = useState<SectorApiInput | null>(null);

  return (
    <Card>
      <CardHead
        icon={ShieldCheck}
        title="APIs de Benchmarks por Sector"
        subtitle="Configure claves de API para obtener datos del sector regulado. Cualquier país y sector."
        right={
          <button
            className="btn btn-primary shrink-0"
            onClick={() => setEditing({ provider: "", enabled: true })}
          >
            <Plus size={15} /> Agregar API de Sector
          </button>
        }
      />

      {data.sectorApis.length === 0 && !editing && (
        <StateBlock kind="empty" message="Aún no hay fuentes configuradas." />
      )}

      <div className="space-y-3">
        {data.sectorApis.map((api) => (
          <SectorApiRow
            key={api.id}
            api={api}
            onEdit={() =>
              setEditing({
                provider: api.provider,
                providerName: api.providerName,
                apiName: api.apiName,
                country: api.country,
                sector: api.sector,
                baseUrl: api.baseUrl,
                proxyUrl: api.proxyUrl,
                enabled: api.enabled,
              })
            }
            onChanged={onChanged}
          />
        ))}
      </div>

      {editing && (
        <SectorApiEditor
          initial={editing}
          existing={data.sectorApis.find((a) => a.provider === editing.provider)}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onChanged();
          }}
        />
      )}
    </Card>
  );
}

function statusChip(api: SectorApi) {
  if (api.lastTestStatus === "success")
    return <Chip tone="ok"><Wifi size={12} /> Conexión exitosa</Chip>;
  if (api.lastTestStatus === "error")
    return <Chip tone="alert">Error de conexión</Chip>;
  return <Chip tone="muted">Sin probar</Chip>;
}

function SectorApiRow({
  api,
  onEdit,
  onChanged,
}: {
  api: SectorApi;
  onEdit: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function toggleEnabled() {
    setBusy(true);
    try {
      await settingsApi.update({ sectorApis: [{ provider: api.provider, enabled: !api.enabled }] });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm(`¿Eliminar la fuente "${api.providerName || api.provider}"?`)) return;
    setBusy(true);
    try {
      await settingsApi.remove(api.provider);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-line p-4 flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="min-w-0 flex-1">
        <div className="font-display text-sm font-bold text-ink truncate">
          {api.providerName || api.provider}
          {api.apiName && <span className="font-normal text-muted"> · {api.apiName}</span>}
        </div>
        <div className="text-xs text-muted truncate mono mt-0.5">
          {[api.country, api.sector, api.baseUrl].filter(Boolean).join(" · ")}
          {api.lastTestDate && ` · Última prueba: ${new Date(api.lastTestDate).toLocaleDateString()}`}
        </div>
      </div>
      <div className="shrink-0">{statusChip(api)}</div>
      <button className="shrink-0" onClick={toggleEnabled} disabled={busy} title="Habilitar/Deshabilitar">
        <Chip tone={api.enabled ? "ok" : "muted"}>{api.enabled ? "Habilitado" : "Deshabilitado"}</Chip>
      </button>
      <button className="btn btn-ghost shrink-0" onClick={onEdit}>Editar</button>
      <button className="text-muted hover:text-alert shrink-0" onClick={remove} disabled={busy} title="Eliminar">
        <Trash2 size={16} />
      </button>
    </div>
  );
}

/* ── Add/edit editor ─────────────────────────────────────────── */
function SectorApiEditor({
  initial,
  existing,
  onClose,
  onSaved,
}: {
  initial: SectorApiInput;
  existing?: SectorApi;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = !existing;
  const [form, setForm] = useState<SectorApiInput>(initial);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testMsg, setTestMsg] = useState("");
  const [err, setErr] = useState("");

  function set<K extends keyof SectorApiInput>(k: K, v: SectorApiInput[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function save() {
    if (!form.provider) {
      setErr("El identificador del proveedor es obligatorio (ej. sb_do).");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await settingsApi.update({ sectorApis: [form] });
      onSaved();
    } catch {
      setErr("Error al guardar.");
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setTesting(true);
    setTestMsg("");
    try {
      const r = await settingsApi.test(form);
      setTestMsg((r.status === "success" ? "✓ " : "✗ ") + r.detail + (r.viaProxy ? " (vía proxy)" : ""));
    } catch {
      setTestMsg("✗ Error al probar la conexión.");
    } finally {
      setTesting(false);
    }
  }

  const Field = ({ label, k, placeholder, type = "text" }: { label: string; k: keyof SectorApiInput; placeholder?: string; type?: string }) => (
    <div>
      <label className="block text-xs font-medium text-muted mb-1">{label}</label>
      <input
        type={type}
        className="field"
        placeholder={placeholder}
        value={(form[k] as string) ?? ""}
        onChange={(e) => set(k, e.target.value as SectorApiInput[keyof SectorApiInput])}
      />
    </div>
  );

  const secretPlaceholder = (isSet?: boolean) => (isSet ? MASK + " (sin cambios)" : "");

  return (
    <div className="mt-4 rounded-xl border border-linestrong bg-surface2 p-4">
      <div className="font-display text-sm font-bold text-ink mb-3">
        {isNew ? "Nueva fuente de datos" : `Editar: ${existing?.providerName || existing?.provider}`}
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-muted mb-1">Identificador (provider)</label>
          <input
            className="field mono"
            placeholder="sb_do"
            value={form.provider}
            disabled={!isNew}
            onChange={(e) => set("provider", e.target.value)}
          />
        </div>
        <Field label="Nombre" k="providerName" placeholder="Superintendencia de Bancos (SB)" />
        <Field label="Nombre de la API" k="apiName" placeholder="API de Estadísticas del Sistema Financiero" />
        <Field label="País" k="country" placeholder="DO" />
        <Field label="Sector" k="sector" placeholder="banking" />
        <Field label="URL base" k="baseUrl" placeholder="https://apis.sb.gob.do/estadisticas/v2" />
        <div>
          <label className="block text-xs font-medium text-muted mb-1">Clave de API</label>
          <input type="password" className="field mono" placeholder={secretPlaceholder(existing?.apiKeySet)}
            value={form.apiKey ?? ""} onChange={(e) => set("apiKey", e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted mb-1">Clave secundaria</label>
          <input type="password" className="field mono" placeholder={secretPlaceholder(existing?.apiKeySecondarySet)}
            value={form.apiKeySecondary ?? ""} onChange={(e) => set("apiKeySecondary", e.target.value)} />
        </div>
        <Field label="URL del proxy (Cloudflare Worker)" k="proxyUrl" placeholder="https://…workers.dev" />
        <div>
          <label className="block text-xs font-medium text-muted mb-1">Secreto del proxy</label>
          <input type="password" className="field mono" placeholder={secretPlaceholder(existing?.proxySecretSet)}
            value={form.proxySecret ?? ""} onChange={(e) => set("proxySecret", e.target.value)} />
        </div>
      </div>

      <label className="flex items-center gap-2 mt-3 text-sm text-body">
        <input type="checkbox" checked={form.enabled ?? true} onChange={(e) => set("enabled", e.target.checked)} />
        Habilitado
      </label>

      {testMsg && <p className="text-xs mt-2 text-body">{testMsg}</p>}
      {err && <p className="text-xs mt-2 text-alert">{err}</p>}

      <div className="flex gap-2 mt-4">
        <button className="btn btn-primary" disabled={saving} onClick={save}>
          {saving ? <Loader2 size={15} className="animate-spin" /> : "Guardar"}
        </button>
        <button className="btn btn-ghost" disabled={testing} onClick={test}>
          {testing ? <Loader2 size={15} className="animate-spin" /> : "Probar conexión"}
        </button>
        <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
      </div>
    </div>
  );
}
