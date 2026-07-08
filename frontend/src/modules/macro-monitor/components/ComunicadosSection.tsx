import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  Landmark,
  Activity,
  ExternalLink,
  TrendingUp,
  AlertTriangle,
  BarChart3,
  ListChecks,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardHead, StatTile, Chip, StateBlock, LoadingGrid } from "@/shared/ui/primitives";
import { Tone } from "@/shared/lib/bands";
import {
  getComunicados,
  getComunicadoLatest,
  Comunicado,
  ComunicadoLatest,
  TpmAction,
} from "../api";

type Status = "loading" | "error" | "empty" | "ready";

const ACTION_TONE: Record<TpmAction, Tone> = { hold: "muted", cut: "ok", hike: "alert" };

function actionLabel(a: TpmAction | null, t: TFunction): string {
  return a ? t(`datos.comunicados.decision.${a}`) : "—";
}

function ActionChip({ action, t }: { action: TpmAction | null; t: TFunction }) {
  if (!action) return <span className="text-muted">—</span>;
  return <Chip tone={ACTION_TONE[action]}>{actionLabel(action, t)}</Chip>;
}

/** BCRD monetary-policy decisions (TPM) — timeline + table + latest-decision digest.
 * Self-loading; embeddable inside the Datos·Macro console. */
export function ComunicadosSection() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [rows, setRows] = useState<Comunicado[]>([]);
  const [latest, setLatest] = useState<ComunicadoLatest | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [{ comunicados }, l] = await Promise.all([getComunicados(24), getComunicadoLatest()]);
      setRows(comunicados);
      setLatest(l);
      setStatus(comunicados.length === 0 ? "empty" : "ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Serie para el timeline: de la más antigua a la más reciente (el paso de la TPM).
  const series = useMemo(
    () =>
      [...rows]
        .filter((r) => r.status === "ok" && r.tpm_level != null && r.date)
        .sort((a, b) => (a.date! < b.date! ? -1 : 1))
        .map((r) => ({ date: r.date as string, tpm: r.tpm_level as number })),
    [rows],
  );

  const intro = (
    <p className="text-sm text-muted max-w-2xl mb-4">{t("datos.comunicados.intro")}</p>
  );

  if (status === "loading") {
    return (
      <div>
        {intro}
        <LoadingGrid />
      </div>
    );
  }
  if (status === "error") {
    return (
      <div>
        {intro}
        <StateBlock
          kind="error"
          message={t("datos.comunicados.loadError")}
          action={
            <button onClick={load} className="btn btn-ghost">
              {t("datos.comunicados.retry")}
            </button>
          }
        />
      </div>
    );
  }
  if (status === "empty") {
    return (
      <div>
        {intro}
        <StateBlock kind="empty" message={t("datos.comunicados.empty")} />
      </div>
    );
  }

  const changes = rows.filter((r) => r.action === "cut" || r.action === "hike").length;
  const latestTpm = series.length ? series[series.length - 1].tpm : null;

  return (
    <div>
      {intro}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label={t("datos.comunicados.statComunicados")} value={rows.length} />
        <StatTile label={t("datos.comunicados.statChanges")} value={changes} />
        <StatTile
          label={t("datos.comunicados.statLatestTpm")}
          value={latestTpm != null ? `${latestTpm}%` : "—"}
        />
        <StatTile
          label={t("datos.comunicados.statLatestDecision")}
          value={latest ? actionLabel(latest.action, t) : "—"}
        />
      </div>

      {series.length > 1 && (
        <Card className="mb-5">
          <CardHead
            icon={Activity}
            title={t("datos.comunicados.timelineTitle")}
            subtitle={t("datos.comunicados.timelineSub")}
          />
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "var(--muted)" }}
                stroke="var(--border-strong)"
                tickFormatter={(d: string) => (d || "").slice(0, 7)}
                minTickGap={24}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "var(--muted)" }}
                stroke="var(--border-strong)"
                width={44}
                domain={["dataMin - 0.5", "dataMax + 0.5"]}
                tickFormatter={(v: number) => `${v}%`}
              />
              <Tooltip
                formatter={(v: number | string) => [`${v}%`, "TPM"]}
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--line)",
                  borderRadius: 10,
                  fontSize: 12,
                }}
              />
              <Line
                type="stepAfter"
                dataKey="tpm"
                stroke="var(--c1)"
                strokeWidth={2}
                dot={{ r: 2.5, fill: "var(--c1)" }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      <div className="grid lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2">
          <Card>
            <CardHead
              icon={Landmark}
              title={t("datos.comunicados.tableTitle")}
              subtitle={t("datos.comunicados.tableSub", { count: rows.length })}
            />
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted border-b border-line">
                    <th className="py-2 px-1 font-medium">{t("datos.comunicados.colDate")}</th>
                    <th className="py-2 px-1 font-medium">{t("datos.comunicados.colDecision")}</th>
                    <th className="py-2 px-1 font-medium text-right">{t("datos.comunicados.colTpm")}</th>
                    <th className="py-2 px-1 font-medium text-right">{t("datos.comunicados.colChange")}</th>
                    <th className="py-2 px-1 font-medium text-right">{t("datos.comunicados.colBcrd")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-b border-line/60 last:border-0">
                      <td className="py-2.5 px-1 mono text-body">{r.date ?? "—"}</td>
                      <td className="py-2.5 px-1">
                        <ActionChip action={r.action} t={t} />
                      </td>
                      <td className="py-2.5 px-1 text-right mono text-ink font-semibold tabular-nums">
                        {r.tpm_level != null ? `${r.tpm_level}%` : "—"}
                      </td>
                      <td className="py-2.5 px-1 text-right mono text-body tabular-nums">
                        {r.action === "cut" && r.bps_change ? `−${r.bps_change}` : ""}
                        {r.action === "hike" && r.bps_change ? `+${r.bps_change}` : ""}
                        {(!r.bps_change || r.action === "hold") && "—"}
                      </td>
                      <td className="py-2.5 px-1 text-right">
                        <a
                          href={r.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                        >
                          {t("datos.comunicados.view")} <ExternalLink size={12} />
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <div>
          <Card>
            {latest ? (
              <LatestDigest latest={latest} t={t} />
            ) : (
              <p className="text-sm text-muted py-6 text-center">{t("datos.comunicados.noLatest")}</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function LatestDigest({ latest, t }: { latest: ComunicadoLatest; t: TFunction }) {
  const d = latest.digest;
  return (
    <div>
      <CardHead
        icon={TrendingUp}
        title={t("datos.comunicados.latestTitle")}
        subtitle={latest.date ?? ""}
        right={
          <a
            href={latest.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline shrink-0"
          >
            {t("datos.comunicados.view")} <ExternalLink size={12} />
          </a>
        }
      />

      <div className="mb-4 flex items-center gap-2">
        <ActionChip action={latest.action} t={t} />
        {latest.tpm_level != null && (
          <span className="text-sm mono font-semibold text-ink tabular-nums">
            {t("datos.comunicados.tpmLabel")}: {latest.tpm_level}%
          </span>
        )}
      </div>

      {d?.resumen && <p className="text-sm text-body leading-relaxed mb-5">{d.resumen}</p>}

      {d?.cifras && d.cifras.length > 0 && (
        <div className="mb-5">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted mb-2">
            <BarChart3 size={14} /> {t("datos.comunicados.keyFigures")}
          </div>
          <div className="grid grid-cols-2 gap-2">
            {d.cifras.map((c, i) => (
              <div key={i} className="rounded-[10px] bg-surface2 p-2.5">
                <div className="text-xs text-muted truncate" title={c.etiqueta}>
                  {c.etiqueta}
                </div>
                <div className="text-sm font-bold text-ink mono mt-0.5 tabular-nums">{c.valor}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {d?.hallazgos && d.hallazgos.length > 0 && (
        <div className="mb-5">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted mb-2">
            <ListChecks size={14} /> {t("datos.comunicados.findings")}
          </div>
          <ul className="space-y-1.5">
            {d.hallazgos.map((h, i) => (
              <li key={i} className="flex gap-2 text-sm text-body">
                <span className="text-accent shrink-0">•</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {d?.riesgos && d.riesgos.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold text-muted mb-2">
            <AlertTriangle size={14} /> {t("datos.comunicados.risks")}
          </div>
          <ul className="space-y-1.5">
            {d.riesgos.map((r, i) => (
              <li key={i} className="flex gap-2 text-sm text-body">
                <span className="text-warn shrink-0">•</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
