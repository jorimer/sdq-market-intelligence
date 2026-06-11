import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import client from "@/shared/api/client";
import { RatingBadge } from "../components/RatingBadge";
import { EntityInsightDrawer } from "../components/EntityInsightDrawer";
import { PageHead, Card, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { useApp, periodToDate } from "@/shared/context/AppContext";

const ENTITY_TYPES = [
  { value: "", label: "Todos los tipos" },
  { value: "banca_multiple", label: "Banca múltiple" },
  { value: "aap", label: "AAyP" },
  { value: "banco_ahorro_credito", label: "Ahorro y crédito" },
  { value: "corporacion_credito", label: "Corp. de crédito" },
  { value: "cambiaria", label: "Cambiaria" },
  { value: "fiduciaria", label: "Fiduciaria" },
];

interface Rank {
  rank: number;
  bank_id: string;
  bank_name: string;
  bank_type: string | null;
  overall_score: number;
  rating_tier: string;
  period_end: string;
}

export function RankingsPage() {
  const { period } = useApp();
  const periodEnd = periodToDate(period);
  const [rankings, setRankings] = useState<Rank[]>([]);
  const [entityType, setEntityType] = useState("");
  const [loading, setLoading] = useState(true);
  const [latestFallback, setLatestFallback] = useState(false);
  const [selectedBank, setSelectedBank] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLatestFallback(false);
    const fetchRankings = (withPeriod: boolean) =>
      client.get<{ rankings: Rank[] }>("/banking-score/rankings", {
        params: {
          ...(withPeriod ? { period_end: periodEnd } : {}),
          ...(entityType ? { entity_type: entityType } : {}),
        },
      });

    fetchRankings(true)
      .then(async (r) => {
        let rows = r.data.rankings ?? [];
        // Some entity types report annually (e.g. fiduciarias, Dic-31) and have no
        // data at a quarterly period. Fall back to the latest rating per entity.
        if (rows.length === 0) {
          const r2 = await fetchRankings(false);
          rows = r2.data.rankings ?? [];
          if (active && rows.length > 0) setLatestFallback(true);
        }
        if (active) setRankings(rows);
      })
      .catch(() => active && setRankings([]))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [entityType, periodEnd]);

  return (
    <div>
      <PageHead
        eyebrow="SIB"
        title="Ranking de entidades"
        sub="Entidades financieras ordenadas por score SDQ. Filtra por tipo de entidad supervisada."
        right={
          <select
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            className="field !w-auto"
            title="Tipo de entidad"
          >
            {ENTITY_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        }
      />

      {loading ? (
        <Card>
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        </Card>
      ) : rankings.length === 0 ? (
        <StateBlock kind="empty" message="No hay ratings para este tipo de entidad." />
      ) : (
        <Card>
          {latestFallback && (
            <p className="text-xs text-muted mb-3">
              No hay datos en el período seleccionado para este tipo (p. ej. las
              fiduciarias reportan anualmente). Mostrando el <span className="text-body font-medium">último rating disponible</span> por entidad.
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-2 font-medium">#</th>
                  <th className="py-2 px-2 font-medium">Entidad</th>
                  <th className="py-2 px-2 font-medium text-right">Score</th>
                  <th className="py-2 px-2 font-medium text-center">Rating</th>
                  <th className="py-2 px-2 font-medium text-right">Período</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {rankings.map((r) => (
                  <tr
                    key={r.bank_name}
                    className="border-b border-line/60 last:border-0 hover:bg-surface2 cursor-pointer"
                    onClick={() => setSelectedBank(r.bank_id)}
                    tabIndex={0}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelectedBank(r.bank_id))}
                  >
                    <td className="py-2.5 px-2 mono text-faint">{r.rank}</td>
                    <td className="py-2.5 px-2 text-ink truncate">{r.bank_name}</td>
                    <td className="py-2.5 px-2 text-right mono font-semibold text-ink">
                      {fmtNum(r.overall_score, 1)}
                    </td>
                    <td className="py-2.5 px-2 text-center">
                      <RatingBadge tier={r.rating_tier} size="sm" />
                    </td>
                    <td className="py-2.5 px-2 text-right mono text-xs text-muted">{r.period_end}</td>
                    <td className="py-2.5 pr-2 text-right">
                      <ChevronRight className="w-4 h-4 text-faint inline-block" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {selectedBank && (
        <EntityInsightDrawer bankId={selectedBank} onClose={() => setSelectedBank(null)} />
      )}
    </div>
  );
}
