import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PiggyBank, FileUp } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { OperationsConsole } from "@/shared/ops/OperationsConsole";
import {
  getPensionPulse,
  getPensionEntities,
  uploadPensionFinancials,
  pulseHasData,
  HEADLINE_CCI,
  HEADLINE_SDP,
  HEADLINE_COMMISSIONS,
  PensionPulse,
  PensionEntityRow,
} from "../api";

/** Manual upload of an AFP's estados financieros (PDF/XLSX) → activates ISA solvency. */
function FinancialsUpload() {
  const { t } = useTranslation();
  const [afps, setAfps] = useState<PensionEntityRow[]>([]);
  const [slug, setSlug] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "alert"; text: string } | null>(null);

  useEffect(() => {
    getPensionEntities().then(setAfps).catch(() => setAfps([]));
  }, []);

  const submit = async () => {
    if (!slug || !file) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await uploadPensionFinancials(slug, file);
      setMsg({ tone: "ok", text: t("datos.pensiones.efOk", { afp: r.afp, period: r.period }) });
    } catch {
      setMsg({ tone: "alert", text: t("datos.pensiones.efError") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHead icon={FileUp} title={t("datos.pensiones.efTitle")} subtitle={t("datos.pensiones.efSub")} />
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted text-xs">{t("datos.pensiones.efAfp")}</span>
          <select className="field w-56" value={slug} onChange={(e) => setSlug(e.target.value)}>
            <option value="">{t("datos.pensiones.efChoose")}</option>
            {afps.map((a) => (
              <option key={a.slug} value={a.slug}>{a.name}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted text-xs">{t("datos.pensiones.efFile")}</span>
          <input
            type="file"
            accept=".pdf,.xlsx,.xls"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm text-body file:mr-3 file:rounded-md file:border-0 file:bg-surface2 file:px-3 file:py-1.5 file:text-sm file:text-ink"
          />
        </label>
        <button onClick={submit} disabled={!slug || !file || busy} className="btn btn-primary">
          <FileUp className="w-4 h-4" />
          {busy ? t("datos.pensiones.efUploading") : t("datos.pensiones.efUpload")}
        </button>
      </div>
      <p className="mt-2 text-xs text-faint">{t("datos.pensiones.efAdminHint")}</p>
      {msg && (
        <p className={`mt-2 text-sm ${msg.tone === "ok" ? "text-ok" : "text-alert"}`}>{msg.text}</p>
      )}
    </Card>
  );
}

/** "Estado del dato" panel: coverage + provenance of the persisted SIPEN data. */
function PensionesOverview() {
  const { t } = useTranslation();
  const [pulse, setPulse] = useState<PensionPulse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    getPensionPulse()
      .then((p) => { setPulse(p); setState("ready"); })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading")
    return <Card><StateBlock kind="loading" message={t("datos.pensiones.ovLoading")} /></Card>;
  if (state === "error")
    return <Card><StateBlock kind="error" message={t("datos.pensiones.ovError")} /></Card>;

  const p = pulse!;
  const has = pulseHasData(p);
  const cci = p.headline?.[HEADLINE_CCI] ?? null;
  const sdp = p.headline?.[HEADLINE_SDP] ?? null;
  const commissions = p.headline?.[HEADLINE_COMMISSIONS] ?? null;

  return (
    <Card>
      <CardHead
        icon={PiggyBank}
        title={t("datos.pensiones.ovTitle")}
        subtitle={t("datos.pensiones.ovSub")}
        right={<Chip tone={has ? "ok" : "muted"}>{has ? t("datos.pensiones.realChip") : t("datos.pensiones.noData")}</Chip>}
      />
      {!has ? (
        <p className="text-sm text-muted mt-3">{t("datos.pensiones.ovEmptyHint")}</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-3">
          <StatTile label={t("datos.pensiones.statPeriod")} value={p.period ?? "—"} />
          <StatTile label={t("datos.pensiones.statCci")} value={cci != null ? fmtNum(cci, 1) : "—"} unit="%" />
          <StatTile label={t("datos.pensiones.statSdp")} value={sdp != null ? fmtNum(sdp, 1) : "—"} unit="%" />
          <StatTile label={t("datos.pensiones.statCommissions")} value={commissions != null ? fmtNum(commissions, 0) : "—"} unit="RD$ MM" />
          <StatTile label={t("datos.pensiones.statAfp")} value={p.entity_count ?? "—"} />
          <StatTile label={t("datos.pensiones.statSource")} value={t("datos.pensiones.sourceValue")} />
        </div>
      )}
    </Card>
  );
}

/** Datos · Pensiones (SIPEN): estado del dato + operación de sync. */
export function DatosPensionesPage() {
  const { t } = useTranslation();
  return (
    <OperationsConsole
      eyebrow={t("datos.pensiones.eyebrow")}
      title={t("datos.pensiones.title")}
      sub={t("datos.pensiones.sub")}
      filter={(op) => op.name.startsWith("sipen-")}
      emptyMessage={t("datos.pensiones.empty")}
      overview={
        <div className="space-y-5">
          <PensionesOverview />
          <FinancialsUpload />
        </div>
      }
    />
  );
}
