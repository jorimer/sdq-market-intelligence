import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
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
  const { t } = useTranslation();
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
        message={t("platform.dataSources.loadError")}
        action={
          <button className="btn btn-soft" onClick={reload}>
            {t("platform.dataSources.retry")}
          </button>
        }
      />
    );

  return (
    <div className="space-y-5">
      <ClaudeKeyCard data={data} onSaved={reload} t={t} />
      <SectorApisCard data={data} onChanged={reload} t={t} />
    </div>
  );
}

/* ── Claude API key + global Cloudflare proxy ────────────────── */
function ClaudeKeyCard({ data, onSaved, t }: { data: AppSettings; onSaved: () => void; t: TFunction }) {
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
      setProxyMsg(t("platform.dataSources.saved"));
      onSaved();
    } catch {
      setProxyMsg(t("platform.dataSources.saveError"));
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
      setMsg(t("platform.dataSources.saved"));
      onSaved();
    } catch {
      setMsg(t("platform.dataSources.saveError"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHead
        icon={KeyRound}
        title={t("platform.dataSources.apiTitle")}
        subtitle={t("platform.dataSources.apiSub")}
      />
      <label className="block text-xs font-medium text-muted mb-1">{t("platform.dataSources.claudeKey")}</label>
      <div className="flex gap-2">
        <input
          type="password"
          className="field mono flex-1"
          placeholder={data.claudeApiKeySet ? `${MASK} (${t("platform.dataSources.configured")})` : "sk-ant-…"}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button className="btn btn-primary shrink-0" disabled={!value || saving} onClick={save}>
          {saving ? <Loader2 size={15} className="animate-spin" /> : t("platform.dataSources.save")}
        </button>
      </div>
      {msg && <p className="text-xs text-muted mt-2">{msg}</p>}

      {/* Global Cloudflare WAF proxy — one credential for all sources behind the WAF. */}
      <div className="mt-5 pt-4 border-t border-line">
        <label className="block text-xs font-medium text-muted mb-1">{t("platform.dataSources.proxyTitle")}</label>
        <p className="text-[11px] text-faint mb-2">
          {t("platform.dataSources.proxyDesc")}
        </p>
        <div className="space-y-2">
          <input
            className="field mono w-full"
            placeholder={t("platform.dataSources.proxyUrlPh")}
            value={proxyUrl}
            onChange={(e) => setProxyUrl(e.target.value)}
          />
          <div className="flex gap-2">
            <input
              type="password"
              className="field mono flex-1"
              placeholder={data.cloudflareProxySecretSet ? `${MASK} (${t("platform.dataSources.configuredM")})` : "X-Proxy-Secret"}
              value={proxySecret}
              onChange={(e) => setProxySecret(e.target.value)}
            />
            <button
              className="btn btn-primary shrink-0"
              disabled={savingProxy || (!proxyUrl && !proxySecret)}
              onClick={saveProxy}
            >
              {savingProxy ? <Loader2 size={15} className="animate-spin" /> : t("platform.dataSources.save")}
            </button>
          </div>
        </div>
        {proxyMsg && <p className="text-xs text-muted mt-2">{proxyMsg}</p>}
      </div>
    </Card>
  );
}

/* ── Sector benchmark APIs ───────────────────────────────────── */
function SectorApisCard({ data, onChanged, t }: { data: AppSettings; onChanged: () => void; t: TFunction }) {
  const [editing, setEditing] = useState<SectorApiInput | null>(null);

  return (
    <Card>
      <CardHead
        icon={ShieldCheck}
        title={t("platform.dataSources.sectorApisTitle")}
        subtitle={t("platform.dataSources.sectorApisSub")}
        right={
          <button
            className="btn btn-primary shrink-0"
            onClick={() => setEditing({ provider: "", enabled: true })}
          >
            <Plus size={15} /> {t("platform.dataSources.addSectorApi")}
          </button>
        }
      />

      {data.sectorApis.length === 0 && !editing && (
        <StateBlock kind="empty" message={t("platform.dataSources.noneConfigured")} />
      )}

      <div className="space-y-3">
        {data.sectorApis.map((api) => (
          <SectorApiRow
            key={api.id}
            api={api}
            t={t}
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
          t={t}
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

function statusChip(api: SectorApi, t: TFunction) {
  if (api.lastTestStatus === "success")
    return <Chip tone="ok"><Wifi size={12} /> {t("platform.dataSources.connOk")}</Chip>;
  if (api.lastTestStatus === "error")
    return <Chip tone="alert">{t("platform.dataSources.connError")}</Chip>;
  return <Chip tone="muted">{t("platform.dataSources.untested")}</Chip>;
}

function SectorApiRow({
  api,
  onEdit,
  onChanged,
  t,
}: {
  api: SectorApi;
  onEdit: () => void;
  onChanged: () => void;
  t: TFunction;
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
    if (!confirm(t("platform.dataSources.confirmRemove", { name: api.providerName || api.provider }))) return;
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
          {api.lastTestDate && ` · ${t("platform.dataSources.lastTest", { date: new Date(api.lastTestDate).toLocaleDateString() })}`}
        </div>
      </div>
      <div className="shrink-0">{statusChip(api, t)}</div>
      <button className="shrink-0" onClick={toggleEnabled} disabled={busy} title={t("platform.dataSources.toggleTitle")}>
        <Chip tone={api.enabled ? "ok" : "muted"}>{api.enabled ? t("platform.dataSources.enabled") : t("platform.dataSources.disabled")}</Chip>
      </button>
      <button className="btn btn-ghost shrink-0" onClick={onEdit}>{t("platform.dataSources.edit")}</button>
      <button className="text-muted hover:text-alert shrink-0" onClick={remove} disabled={busy} title={t("platform.dataSources.delete")}>
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
  t,
}: {
  initial: SectorApiInput;
  existing?: SectorApi;
  onClose: () => void;
  onSaved: () => void;
  t: TFunction;
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
      setErr(t("platform.dataSources.providerRequired"));
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await settingsApi.update({ sectorApis: [form] });
      onSaved();
    } catch {
      setErr(t("platform.dataSources.editorSaveError"));
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setTesting(true);
    setTestMsg("");
    try {
      const r = await settingsApi.test(form);
      setTestMsg((r.status === "success" ? "✓ " : "✗ ") + r.detail + (r.viaProxy ? ` (${t("platform.dataSources.viaProxy")})` : ""));
    } catch {
      setTestMsg(t("platform.dataSources.testError"));
    } finally {
      setTesting(false);
    }
  }

  const secretPlaceholder = (isSet?: boolean) => (isSet ? `${MASK} (${t("platform.dataSources.unchanged")})` : "");

  return (
    <div className="mt-4 rounded-xl border border-linestrong bg-surface2 p-4">
      <div className="font-display text-sm font-bold text-ink mb-3">
        {isNew ? t("platform.dataSources.newSource") : t("platform.dataSources.editSource", { name: existing?.providerName || existing?.provider })}
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <LabeledInput label={t("platform.dataSources.fProvider")} mono disabled={!isNew}
          placeholder="sb_do" value={form.provider} onChange={(v) => set("provider", v)} />
        <LabeledInput label={t("platform.dataSources.fName")} placeholder={t("platform.dataSources.phProviderName")}
          value={form.providerName ?? ""} onChange={(v) => set("providerName", v)} />
        <LabeledInput label={t("platform.dataSources.fApiName")} placeholder={t("platform.dataSources.phApiName")}
          value={form.apiName ?? ""} onChange={(v) => set("apiName", v)} />
        <LabeledInput label={t("platform.dataSources.fCountry")} placeholder="DO"
          value={form.country ?? ""} onChange={(v) => set("country", v)} />
        <LabeledInput label={t("platform.dataSources.fSector")} placeholder="banking"
          value={form.sector ?? ""} onChange={(v) => set("sector", v)} />
        <LabeledInput label={t("platform.dataSources.fBaseUrl")} placeholder="https://apis.sb.gob.do/estadisticas/v2"
          value={form.baseUrl ?? ""} onChange={(v) => set("baseUrl", v)} />
        <LabeledInput label={existing?.needsSecondary ? t("platform.dataSources.fApiKeyPrimary") : t("platform.dataSources.fApiKeyToken")}
          type="password" mono
          placeholder={secretPlaceholder(existing?.apiKeySet)}
          value={form.apiKey ?? ""} onChange={(v) => set("apiKey", v)} />
        {/* Secondary key only for Azure-APIM sources (SIB); BCRD etc. use a single token. */}
        {existing?.needsSecondary && (
          <LabeledInput label={t("platform.dataSources.fApiKeySecondary")} type="password" mono
            placeholder={secretPlaceholder(existing?.apiKeySecondarySet)}
            value={form.apiKeySecondary ?? ""} onChange={(v) => set("apiKeySecondary", v)} />
        )}
      </div>
      {/* The Cloudflare proxy is now a single global credential (top card), not per-source. */}

      <label className="flex items-center gap-2 mt-3 text-sm text-body">
        <input type="checkbox" checked={form.enabled ?? true} onChange={(e) => set("enabled", e.target.checked)} />
        {t("platform.dataSources.enabled")}
      </label>

      {testMsg && <p className="text-xs mt-2 text-body">{testMsg}</p>}
      {err && <p className="text-xs mt-2 text-alert">{err}</p>}

      <div className="flex gap-2 mt-4">
        <button className="btn btn-primary" disabled={saving} onClick={save}>
          {saving ? <Loader2 size={15} className="animate-spin" /> : t("platform.dataSources.saveBtn")}
        </button>
        <button className="btn btn-ghost" disabled={testing} onClick={test}>
          {testing ? <Loader2 size={15} className="animate-spin" /> : t("platform.dataSources.testConn")}
        </button>
        <button className="btn btn-ghost" onClick={onClose}>{t("platform.dataSources.cancel")}</button>
      </div>
    </div>
  );
}
