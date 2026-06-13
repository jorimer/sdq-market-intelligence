import { useEffect, useState } from "react";
import { Trophy, PieChart, ChevronRight } from "lucide-react";
import client from "@/shared/api/client";
import { RatingBadge } from "../components/RatingBadge";
import { EntityInsightDrawer } from "../components/EntityInsightDrawer";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { MarketConcentrationCard } from "../components/MarketConcentrationCard";
import { getSectorInsight } from "../api";
import {
  PageHead,
  Card,
  CardHead,
  StatTile,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { ENTITY_TYPES, isCreditModel, isSubmodelReady, entityTypeLabel } from "../entityTypes";

type Status = "loading" | "error" | "ready";

interface Stats {
  total_records: number;
  total_entities: number;
  total_ratings: number;
  period_end: string | null;
}
interface Rank {
  rank: number;
  bank_id: string;
  bank_name: string;
  overall_score: number;
  rating_tier: string;
}

export function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [rankings, setRankings] = useState<Rank[]>([]);
  const [status, setStatus] = useState<Status>("loading");
  const [area, setArea] = useState(""); // entity_type filter ("" = todos)
  const [selectedBank, setSelectedBank] = useState<string | null>(null);

  useEffect(() => {
    setStatus("loading");
    Promise.all([
      client.get<Stats>("/banking-score/stats"),
      client.get<{ rankings: Rank[] }>("/banking-score/rankings", {
        params: area ? { entity_type: area } : {},
      }),
    ])
      .then(([s, r]) => {
        setStats(s.data);
        setRankings(r.data.rankings ?? []);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [area]);

  const areaTabs = (
    <div className="flex flex-wrap gap-1.5 mb-5">
      {ENTITY_TYPES.map((t) => (
        <button
          key={t.value}
          onClick={() => setArea(t.value)}
          className={`px-3 py-1.5 rounded-full text-sm font-medium border transition ${
            area === t.value
              ? "bg-accent text-white border-accent"
              : "bg-surface text-body border-line hover:border-linestrong"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );

  const head = (
    <PageHead
      eyebrow="SIB · SIMBAD"
      title="Financiero"
      sub="Score de entidad financiera explicable y auditable para el universo supervisado por la SIB (Financial Entity Score)."
    />
  );

  if (status === "loading") return <div>{head}{areaTabs}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        {areaTabs}
        <StateBlock kind="error" message="No se pudieron cargar los datos del sector. Reintenta." />
      </div>
    );

  // Submodels without data yet (fiduciarias — not exposed by the SIB API).
  if (!isSubmodelReady(area)) {
    return (
      <div>
        {head}
        {areaTabs}
        <StateBlock
          kind="soon"
          title="Submodelo en construcción"
          message={`El análisis de ${entityTypeLabel(area).toLowerCase()} usa indicadores propios (no el modelo crediticio). Su submodelo está en desarrollo.`}
        />
      </div>
    );
  }

  // Cambiarias use their own (non-credit) submodel — surface that honestly.
  const submodelNote = !isCreditModel(area)
    ? `${entityTypeLabel(area)}: submodelo propio (capitalización, liquidez operativa, eficiencia y márgenes) — no el modelo crediticio.`
    : null;

  const top = rankings.slice(0, 5);
  const avg = rankings.length
    ? rankings.reduce((s, b) => s + b.overall_score, 0) / rankings.length
    : null;

  // Rating-tier distribution from the full ranking.
  const tierCounts = rankings.reduce<Record<string, number>>((acc, r) => {
    acc[r.rating_tier] = (acc[r.rating_tier] ?? 0) + 1;
    return acc;
  }, {});
  const tiers = Object.entries(tierCounts).sort((a, b) => b[1] - a[1]);
  const maxTier = Math.max(...tiers.map(([, c]) => c), 1);

  return (
    <div>
      {head}
      {areaTabs}

      {submodelNote && (
        <p className="text-sm text-muted mb-4">{submodelNote}</p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label="Entidades" value={area ? rankings.length : (stats?.total_entities ?? 0)} />
        <StatTile label="Score promedio" value={fmtNum(avg, 1)} />
        <StatTile label="Ratings calculados" value={area ? rankings.length : (stats?.total_ratings ?? 0)} />
        <StatTile label="Último período" value={stats?.period_end ?? "—"} />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card>
          <CardHead icon={Trophy} title="Top entidades" subtitle="Por score SDQ" />
          {top.length === 0 ? (
            <p className="text-sm text-muted py-4 text-center">Sin ratings calculados.</p>
          ) : (
            <div className="space-y-1">
              {top.map((bank) => (
                <button
                  key={bank.bank_name}
                  onClick={() => setSelectedBank(bank.bank_id)}
                  className="w-full flex items-center justify-between gap-3 py-2 border-b border-line/60 last:border-0 hover:bg-surface2 text-left"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="w-6 shrink-0 mono text-sm text-faint">{bank.rank}</span>
                    <span className="text-sm text-ink truncate">{bank.bank_name}</span>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="mono text-sm font-semibold text-ink">
                      {fmtNum(bank.overall_score, 1)}
                    </span>
                    <RatingBadge tier={bank.rating_tier} size="sm" />
                    <ChevronRight className="w-4 h-4 text-faint" />
                  </div>
                </button>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <CardHead icon={PieChart} title="Distribución por rating" subtitle="Entidades por nivel SDQ" />
          {tiers.length === 0 ? (
            <p className="text-sm text-muted py-4 text-center">Sin datos.</p>
          ) : (
            <div className="space-y-2.5">
              {tiers.map(([tier, count]) => (
                <div key={tier} className="flex items-center gap-3">
                  <div className="w-20 shrink-0">
                    <RatingBadge tier={tier} size="sm" />
                  </div>
                  <div className="flex-1 h-2 rounded-full bg-surface2 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${(count / maxTier) * 100}%` }}
                    />
                  </div>
                  <span className="shrink-0 mono text-sm text-body w-6 text-right">{count}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Market structure of the EIF universe — only on the system (all) view. */}
      {area === "" && <MarketConcentrationCard />}

      {rankings.length > 0 && (
        <div className="mt-5">
          <AiInsightCard
            title="Panorama del sector (IA)"
            subtitle={area ? entityTypeLabel(area) : "Todo el sistema financiero"}
            depsKey={`${area}|${stats?.period_end ?? ""}`}
            fetcher={() => getSectorInsight(area)}
          />
        </div>
      )}

      {selectedBank && (
        <EntityInsightDrawer bankId={selectedBank} onClose={() => setSelectedBank(null)} />
      )}
    </div>
  );
}
