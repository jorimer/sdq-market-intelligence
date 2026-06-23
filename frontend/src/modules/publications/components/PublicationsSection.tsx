import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  FileText,
  Calendar,
  ExternalLink,
  TrendingUp,
  AlertTriangle,
  BarChart3,
  ListChecks,
} from "lucide-react";
import { Card, CardHead, StatTile, Chip, StateBlock, LoadingGrid } from "@/shared/ui/primitives";
import { Tone } from "@/shared/lib/bands";
import {
  getPublications,
  getCatalog,
  getPublication,
  refreshPublications,
  PublicationSummary,
  CatalogReport,
  PublicationDetail,
} from "../api";

type Status = "loading" | "error" | "empty" | "ready";

const SECTOR_TONE: Record<string, Tone> = { banca: "ok", macro: "muted" };

function SectorChips({ sectors, t }: { sectors: string[]; t: TFunction }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {sectors.map((s) => (
        <Chip key={s} tone={SECTOR_TONE[s] ?? "muted"}>
          {s === "banca" ? t("datos.publications.secBanca") : s === "macro" ? t("datos.publications.secMacro") : s}
        </Chip>
      ))}
    </div>
  );
}

/** BCRD official reports (PDF → AI digest), embeddable inside the Datos·Macro
 * console. Self-loading; no page chrome of its own. */
export function PublicationsSection() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [pubs, setPubs] = useState<PublicationSummary[]>([]);
  const [catalog, setCatalog] = useState<CatalogReport[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [detail, setDetail] = useState<PublicationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string>("");

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [p, c] = await Promise.all([getPublications(), getCatalog()]);
      setPubs(p);
      setCatalog(c);
      if (p.length && !selectedId) setSelectedId(p[0].id);
      setStatus(p.length === 0 ? "empty" : "ready");
    } catch {
      setStatus("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    getPublication(selectedId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selectedId]);

  const doRefresh = async () => {
    setRefreshing(true);
    setRefreshNote("");
    try {
      const res = await refreshPublications();
      setRefreshNote(t("datos.publications.refreshOk", { count: res.ingested_ok }));
      await load();
    } catch (e: unknown) {
      const s = (e as { response?: { status?: number } })?.response?.status;
      setRefreshNote(
        s === 403
          ? t("datos.publications.refreshForbidden")
          : t("datos.publications.refreshError"),
      );
    } finally {
      setRefreshing(false);
    }
  };

  const latestPeriodByKey = useMemo(
    () => Object.fromEntries(catalog.map((c) => [c.key, c.latest_ingested_period])),
    [catalog],
  );

  const actionBar = (
    <div className="flex items-center justify-between mb-4">
      <p className="text-sm text-muted max-w-2xl">
        {t("datos.publications.intro")}
      </p>
      <button onClick={doRefresh} disabled={refreshing} className="btn btn-soft shrink-0">
        {refreshing ? t("datos.publications.checking") : t("datos.publications.findNew")}
      </button>
    </div>
  );

  if (status === "loading") {
    return (
      <div>
        {actionBar}
        <LoadingGrid />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div>
        {actionBar}
        <StateBlock
          kind="error"
          message={t("datos.publications.loadError")}
          action={
            <button onClick={load} className="btn btn-ghost">
              {t("datos.publications.retry")}
            </button>
          }
        />
      </div>
    );
  }

  if (status === "empty") {
    return (
      <div>
        {actionBar}
        <StateBlock
          kind="empty"
          message={t("datos.publications.empty")}
          action={
            <button onClick={doRefresh} disabled={refreshing} className="btn btn-primary">
              {refreshing ? t("datos.publications.searching") : t("datos.publications.findEditions")}
            </button>
          }
        />
      </div>
    );
  }

  const okCount = pubs.filter((p) => p.status === "ok").length;
  const digestCount = pubs.filter((p) => p.has_digest).length;

  return (
    <div>
      {actionBar}

      {refreshNote && (
        <div className="mb-4 text-xs text-muted rounded-[10px] bg-surface2 px-3 py-2">{refreshNote}</div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label={t("datos.publications.statCatalog")} value={catalog.length} />
        <StatTile label={t("datos.publications.statIngested")} value={okCount} />
        <StatTile label={t("datos.publications.statDigest")} value={digestCount} />
        <StatTile label={t("datos.publications.statCadence")} value={t("datos.publications.cadenceValue")} />
      </div>

      <Card className="mb-5">
        <CardHead
          icon={Calendar}
          title={t("datos.publications.calendarTitle")}
          subtitle={t("datos.publications.calendarSub")}
        />
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-line">
                <th className="py-2 px-1 font-medium">{t("datos.publications.colReport")}</th>
                <th className="py-2 px-1 font-medium">{t("datos.publications.colCadence")}</th>
                <th className="py-2 px-1 font-medium">{t("datos.publications.colSectors")}</th>
                <th className="py-2 px-1 font-medium">{t("datos.publications.colLastEdition")}</th>
                <th className="py-2 px-1 font-medium text-right">{t("datos.publications.colBcrd")}</th>
              </tr>
            </thead>
            <tbody>
              {catalog.map((c) => (
                <tr key={c.key} className="border-b border-line/60 last:border-0">
                  <td className="py-2.5 px-1 text-ink font-medium">{c.name}</td>
                  <td className="py-2.5 px-1 text-body capitalize">{c.cadence}</td>
                  <td className="py-2.5 px-1">
                    <SectorChips sectors={c.sectors} t={t} />
                  </td>
                  <td className="py-2.5 px-1 mono text-body">{latestPeriodByKey[c.key] ?? "—"}</td>
                  <td className="py-2.5 px-1 text-right">
                    <a
                      href={c.landing_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                    >
                      {t("datos.publications.view")} <ExternalLink size={12} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid lg:grid-cols-3 gap-5">
        <div>
          <Card>
            <CardHead icon={FileText} title={t("datos.publications.reportsTitle")} subtitle={t("datos.publications.reportsSub", { count: pubs.length })} />
            <ul className="space-y-2">
              {pubs.map((p) => {
                const active = p.id === selectedId;
                return (
                  <li key={p.id}>
                    <button
                      onClick={() => setSelectedId(p.id)}
                      className={`w-full text-left rounded-[10px] p-3 transition-colors ${
                        active
                          ? "bg-accent-soft ring-1 ring-accent/30"
                          : "bg-surface2 hover:ring-1 hover:ring-line"
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-semibold text-ink truncate">{p.report_name}</div>
                          <div className="text-xs text-muted mt-0.5 mono">{p.period}</div>
                        </div>
                        {p.status !== "ok" && <Chip tone="alert">{t("datos.publications.errorChip")}</Chip>}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Card>
        </div>

        <div className="lg:col-span-2">
          <Card>
            {detailLoading ? (
              <StateBlock kind="loading" message={t("datos.publications.analysisLoading")} />
            ) : detail ? (
              <DigestView detail={detail} t={t} />
            ) : (
              <p className="text-sm text-muted py-6 text-center">
                {t("datos.publications.selectReport")}
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function DigestView({ detail, t }: { detail: PublicationDetail; t: TFunction }) {
  const d = detail.digest;
  return (
    <div>
      <CardHead
        icon={FileText}
        title={detail.report_name}
        subtitle={t("datos.publications.periodPrefix", { period: detail.period })}
        right={
          <a
            href={detail.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline shrink-0"
          >
            {t("datos.publications.pdf")} <ExternalLink size={12} />
          </a>
        }
      />

      <div className="mb-4">
        <SectorChips sectors={detail.sectors} t={t} />
      </div>

      {d?.resumen && <p className="text-sm text-body leading-relaxed mb-5">{d.resumen}</p>}

      {d?.cifras?.length > 0 && (
        <div className="mb-5">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted mb-2">
            <BarChart3 size={14} /> {t("datos.publications.keyFigures")}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {d.cifras.map((c, i) => (
              <div key={i} className="rounded-[10px] bg-surface2 p-2.5">
                <div className="text-xs text-muted truncate" title={c.etiqueta}>
                  {c.etiqueta}
                </div>
                <div className="text-sm font-bold text-ink mono mt-0.5">{c.valor}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {d?.hallazgos?.length > 0 && (
        <div className="mb-5">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted mb-2">
            <ListChecks size={14} /> {t("datos.publications.findings")}
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

      {d?.riesgos?.length > 0 && (
        <div className="mb-5">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted mb-2">
            <AlertTriangle size={14} /> {t("datos.publications.risks")}
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

      {d?.relevancia && Object.keys(d.relevancia).length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold text-muted mb-2">
            <TrendingUp size={14} /> {t("datos.publications.relevanceBySector")}
          </div>
          <div className="space-y-2">
            {Object.entries(d.relevancia).map(([sector, txt]) => (
              <div key={sector} className="rounded-[10px] bg-surface2 p-3">
                <div className="mb-1">
                  <SectorChips sectors={[sector]} t={t} />
                </div>
                <p className="text-sm text-body leading-relaxed">{txt}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
