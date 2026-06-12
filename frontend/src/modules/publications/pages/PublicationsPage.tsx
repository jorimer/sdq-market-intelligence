import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FileText,
  Calendar,
  ExternalLink,
  TrendingUp,
  AlertTriangle,
  BarChart3,
  ListChecks,
} from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  StatTile,
  Chip,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
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

const SECTOR_TONE: Record<string, Tone> = {
  banca: "ok",
  macro: "muted",
};

function SectorChips({ sectors }: { sectors: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {sectors.map((s) => (
        <Chip key={s} tone={SECTOR_TONE[s] ?? "muted"}>
          {s === "banca" ? "Banca" : s === "macro" ? "Macro" : s}
        </Chip>
      ))}
    </div>
  );
}

export function PublicationsPage() {
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
      setRefreshNote(`Revisión completa · ${res.ingested_ok} informe(s) al día.`);
      await load();
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      setRefreshNote(
        status === 403
          ? "Actualizar requiere rol de administrador."
          : "No se pudo actualizar. Reintenta en unos segundos.",
      );
    } finally {
      setRefreshing(false);
    }
  };

  const latestPeriodByKey = useMemo(
    () => Object.fromEntries(catalog.map((c) => [c.key, c.latest_ingested_period])),
    [catalog],
  );

  const head = (
    <PageHead
      eyebrow="BCRD · Informes oficiales"
      title="Publicaciones BCRD"
      sub="Informes del Banco Central analizados con IA: resumen, hallazgos, cifras y riesgos. Alimentan los insights de Macro y Banca."
      right={
        <button onClick={doRefresh} disabled={refreshing} className="btn btn-soft">
          {refreshing ? "Revisando…" : "Buscar nuevas ediciones"}
        </button>
      }
    />
  );

  if (status === "loading") {
    return (
      <div>
        {head}
        <LoadingGrid />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudieron cargar las publicaciones. Reintenta en unos segundos."
          action={
            <button onClick={load} className="btn btn-ghost">
              Reintentar
            </button>
          }
        />
      </div>
    );
  }

  if (status === "empty") {
    return (
      <div>
        {head}
        <StateBlock
          kind="empty"
          message="Aún no hay publicaciones ingeridas. Busca las últimas ediciones del BCRD para empezar."
          action={
            <button onClick={doRefresh} disabled={refreshing} className="btn btn-primary">
              {refreshing ? "Buscando…" : "Buscar ediciones"}
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
      {head}

      {refreshNote && (
        <div className="mb-4 text-xs text-muted rounded-[10px] bg-surface2 px-3 py-2">
          {refreshNote}
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label="Informes en catálogo" value={catalog.length} />
        <StatTile label="Ediciones ingeridas" value={okCount} />
        <StatTile label="Con análisis IA" value={digestCount} />
        <StatTile label="Cadencia" value="Semestral" />
      </div>

      {/* Calendar / catalog */}
      <Card className="mb-5">
        <CardHead
          icon={Calendar}
          title="Catálogo & calendario"
          subtitle="Informes recurrentes del BCRD y su última edición disponible"
        />
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-line">
                <th className="py-2 px-1 font-medium">Informe</th>
                <th className="py-2 px-1 font-medium">Cadencia</th>
                <th className="py-2 px-1 font-medium">Sectores</th>
                <th className="py-2 px-1 font-medium">Última edición</th>
                <th className="py-2 px-1 font-medium text-right">BCRD</th>
              </tr>
            </thead>
            <tbody>
              {catalog.map((c) => (
                <tr key={c.key} className="border-b border-line/60 last:border-0">
                  <td className="py-2.5 px-1 text-ink font-medium">{c.name}</td>
                  <td className="py-2.5 px-1 text-body capitalize">{c.cadence}</td>
                  <td className="py-2.5 px-1">
                    <SectorChips sectors={c.sectors} />
                  </td>
                  <td className="py-2.5 px-1 mono text-body">
                    {latestPeriodByKey[c.key] ?? "—"}
                  </td>
                  <td className="py-2.5 px-1 text-right">
                    <a
                      href={c.landing_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                    >
                      Ver <ExternalLink size={12} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid lg:grid-cols-3 gap-5">
        {/* List */}
        <div>
          <Card>
            <CardHead icon={FileText} title="Informes" subtitle={`${pubs.length} ediciones`} />
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
                          <div className="text-sm font-semibold text-ink truncate">
                            {p.report_name}
                          </div>
                          <div className="text-xs text-muted mt-0.5 mono">{p.period}</div>
                        </div>
                        {p.status !== "ok" && <Chip tone="alert">error</Chip>}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Card>
        </div>

        {/* Detail */}
        <div className="lg:col-span-2">
          <Card>
            {detailLoading ? (
              <StateBlock kind="loading" message="Cargando análisis…" />
            ) : detail ? (
              <DigestView detail={detail} />
            ) : (
              <p className="text-sm text-muted py-6 text-center">
                Selecciona un informe para ver su análisis.
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function DigestView({ detail }: { detail: PublicationDetail }) {
  const d = detail.digest;
  return (
    <div>
      <CardHead
        icon={FileText}
        title={detail.report_name}
        subtitle={`Período ${detail.period}`}
        right={
          <a
            href={detail.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline shrink-0"
          >
            PDF <ExternalLink size={12} />
          </a>
        }
      />

      <div className="mb-4">
        <SectorChips sectors={detail.sectors} />
      </div>

      {d?.resumen && <p className="text-sm text-body leading-relaxed mb-5">{d.resumen}</p>}

      {d?.cifras?.length > 0 && (
        <div className="mb-5">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted mb-2">
            <BarChart3 size={14} /> Cifras clave
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
            <ListChecks size={14} /> Hallazgos
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
            <AlertTriangle size={14} /> Riesgos
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
            <TrendingUp size={14} /> Relevancia por sector
          </div>
          <div className="space-y-2">
            {Object.entries(d.relevancia).map(([sector, txt]) => (
              <div key={sector} className="rounded-[10px] bg-surface2 p-3">
                <div className="mb-1">
                  <SectorChips sectors={[sector]} />
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
