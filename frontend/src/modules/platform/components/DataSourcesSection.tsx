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

/** Module-level so it keeps a stable identity across renders — defining it inside
 * the editor recreated the component every keystroke, remounting the <input> and
 * stealing focus. */
function LabeledInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  mono = false,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  mono?: boolean;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-muted mb-1">{label}</label>
      <input
        type={type}
        className={`field ${mono ? "mono" : ""}`}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

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

/* ── Claude API key + global Cloudflare proxy ────────────────── */
function ClaudeKeyCard({ data, onSaved }: { data: AppSettings; onSaved: () => void }) {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  // Global Cloudflare WAF proxy — entered once, shared by every source behind the WAF.
  const [proxyUrl, setProxyUrl] = useState(data.cloudflareProxyUrl || "");
  const [proxySecret, setProxySecret] = useState("");
  const [savingProxy, setSavingProxy] = useState(false);
  const [proxyMsg, setProxyMsg] = useState("");

  async function saveProxy() {
    setSavingProxy(true);
    setProxyMsg("");
    try {
      await settingsApi.update({
        cloudflareProxyUrl: proxyUrl,
        ...(proxySecret ? { cloudflareProxySecret: proxySecret } : {}),
      });
      setProxySecret("");
      setProxyMsg("Guardado");
      onSaved();
    } catch {
      setProxyMsg("Error al guardar");
    } finally {
      setSavingProxy(false);
    }
  }

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

      {/* Global Cloudflare WAF proxy — one credential for all sources behind the WAF. */}
      <div className="mt-5 pt-4 border-t border-line">
        <label className="block text-xs font-medium text-muted mb-1">Proxy Cloudflare (WAF)</label>
        <p className="text-[11px] text-faint mb-2">
          Credencial única para todas las fuentes detrás del WAF (hoy: SIB). Se introduce una sola vez.
        </p>
        <div className="space-y-2">
          <input
            className="field mono w-full"
            placeholder="URL del Worker (https://…workers.dev)"
            value={proxyUrl}
            onChange={(e) => setProxyUrl(e.target.value)}
          />
          <div className="flex gap-2">
            <input
              type="password"
              className="field mono flex-1"
              placeholder={data.cloudflareProxySecretSet ? MASK + " (configurado)" : "X-Proxy-Secret"}
              value={proxySecret}
              onChange={(e) => setProxySecret(e.target.value)}
            />
            <button
              className="btn btn-primary shrink-0"
              disabled={savingProxy || (!proxyUrl && !proxySecret)}
              onClick={saveProxy}
            >
              {savingProxy ? <Loader2 size={15} className="animate-spin" /> : "Guardar"}
            </button>
          </div>
        </div>
        {proxyMsg && <p className="text-xs text-muted mt-2">{proxyMsg}</p>}
      </div>
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

  const secretPlaceholder = (isSet?: boolean) => (isSet ? MASK + " (sin cambios)" : "");

  return (
    <div className="mt-4 rounded-xl border border-linestrong bg-surface2 p-4">
      <div className="font-display text-sm font-bold text-ink mb-3">
        {isNew ? "Nueva fuente de datos" : `Editar: ${existing?.providerName || existing?.provider}`}
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <LabeledInput label="Identificador (provider)" mono disabled={!isNew}
          placeholder="sb_do" value={form.provider} onChange={(v) => set("provider", v)} />
        <LabeledInput label="Nombre" placeholder="Superintendencia de Bancos (SB)"
          value={form.providerName ?? ""} onChange={(v) => set("providerName", v)} />
        <LabeledInput label="Nombre de la API" placeholder="API de Estadísticas del Sistema Financiero"
          value={form.apiName ?? ""} onChange={(v) => set("apiName", v)} />
        <LabeledInput label="País" placeholder="DO"
          value={form.country ?? ""} onChange={(v) => set("country", v)} />
        <LabeledInput label="Sector" placeholder="banking"
          value={form.sector ?? ""} onChange={(v) => set("sector", v)} />
        <LabeledInput label="URL base" placeholder="https://apis.sb.gob.do/estadisticas/v2"
          value={form.baseUrl ?? ""} onChange={(v) => set("baseUrl", v)} />
        <LabeledInput label={existing?.needsSecondary ? "Clave de API (primaria)" : "Clave de API / Token"}
          type="password" mono
          placeholder={secretPlaceholder(existing?.apiKeySet)}
          value={form.apiKey ?? ""} onChange={(v) => set("apiKey", v)} />
        {/* Secondary key only for Azure-APIM sources (SIB); BCRD etc. use a single token. */}
        {existing?.needsSecondary && (
          <LabeledInput label="Clave secundaria" type="password" mono
            placeholder={secretPlaceholder(existing?.apiKeySecondarySet)}
            value={form.apiKeySecondary ?? ""} onChange={(v) => set("apiKeySecondary", v)} />
        )}
      </div>
      {/* The Cloudflare proxy is now a single global credential (top card), not per-source. */}

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
