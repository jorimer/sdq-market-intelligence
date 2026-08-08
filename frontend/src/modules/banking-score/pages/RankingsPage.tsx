import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";
import client from "@/shared/api/client";
import { EntityInsightDrawer } from "../components/EntityInsightDrawer";
import { PageHead, Card, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { useApp, periodToDate } from "@/shared/context/AppContext";
import { ENTITY_TYPES, entityTypeLabel } from "../entityTypes";

interface Rank {
  rank: number;
  /** Posición DENTRO del propio tipo — la única comparable. */
  rank_in_type: number;
  bank_id: string;
  bank_name: string;
  bank_type: string | null;
  overall_score: number;
  // Perfil SDQ — los dos ejes que reemplazan la lectura del símbolo único.
  ejecucion: number | null;
  banda_ejecucion: string | null;
  resiliencia: number | null;
  banda_resiliencia: string | null;
  /** DEPRECADO: convive durante la transición a Perfil SDQ. */
  rating_tier: string;
  period_end: string;
}

/** Banda → tono, compartido con el componente PerfilSDQ. */
function tonoBanda(banda: string | null): string {
  switch (banda) {
    case "Sólida":
    case "Sobresaliente":
      return "bg-ok-soft text-ok";
    case "Adecuada":
    case "Competitiva":
      return "bg-accent-soft text-accent-ink";
    case "En vigilancia":
    case "Rezagada":
      return "bg-warn-soft text-warn";
    case "Frágil":
    case "Deficiente":
      return "bg-alert-soft text-alert";
    default:
      return "bg-surface2 text-muted";
  }
}

function CeldaEje({ score, banda }: { score: number | null; banda: string | null }) {
  return (
    <div className="flex items-center justify-end gap-2">
      <span className="mono text-ink">{score == null ? "—" : score.toFixed(1)}</span>
      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${tonoBanda(banda)}`}>
        {banda ?? "sin dato"}
      </span>
    </div>
  );
}

/** Orden de presentación de los grupos: de mayor a menor peso en el sistema. */
const ORDEN_TIPOS = ENTITY_TYPES.map((o) => o.value).filter(Boolean);

/**
 * Agrupa por tipo de entidad preservando el orden interno que trae la API.
 *
 * El ranking global mezcla familias que no son comparables entre sí: una casa de cambio
 * y un banco múltiple no compiten por lo mismo ni se financian igual. Ordenados en una
 * sola lista, las cambiarias coparon las primeras diez posiciones del sistema financiero
 * — que es justo la lectura de símbolo único que Perfil SDQ vino a reemplazar.
 */
export function agruparPorTipo(rows: Rank[]): Array<{ tipo: string; filas: Rank[] }> {
  const porTipo = new Map<string, Rank[]>();
  for (const r of rows) {
    const k = r.bank_type ?? "";
    if (!porTipo.has(k)) porTipo.set(k, []);
    porTipo.get(k)!.push(r);
  }
  const conocidos = ORDEN_TIPOS.filter((t) => porTipo.has(t));
  // Un tipo que el catálogo del frontend no conoce todavía se muestra igual, al final:
  // omitirlo escondería entidades sin avisar.
  const resto = [...porTipo.keys()].filter((t) => !ORDEN_TIPOS.includes(t)).sort();
  return [...conocidos, ...resto].map((tipo) => ({ tipo, filas: porTipo.get(tipo)! }));
}

export function RankingsPage() {
  const { t } = useTranslation();
  const { period } = useApp();
  const periodEnd = periodToDate(period);
  const [rankings, setRankings] = useState<Rank[]>([]);
  const [entityType, setEntityType] = useState("");
  const [loading, setLoading] = useState(true);
  const [latestFallback, setLatestFallback] = useState(false);
  const [selectedBank, setSelectedBank] = useState<string | null>(null);

  // Solo se agrupa en la vista "Todos": con un tipo elegido la lista ya es homogénea y
  // una sola cabecera de grupo repetida no aporta nada.
  const agrupado = entityType === "";
  const grupos = agrupado
    ? agruparPorTipo(rankings)
    : [{ tipo: entityType, filas: rankings }];

  // Un tipo con submodelo listo que no trae ninguna fila en el período NO se omite en
  // silencio: se nombra. Es el caso de las fiduciarias, que cierran en diciembre y por
  // tanto no existen en un corte trimestral — sin esta línea simplemente desaparecen.
  const tiposAusentes = agrupado
    ? ENTITY_TYPES.filter(
        (o) => o.value && o.submodelReady && !grupos.some((g) => g.tipo === o.value),
      ).map((o) => entityTypeLabel(o.value, t))
    : [];

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
        eyebrow={t("banking.rankEyebrow")}
        title={t("banking.rankTitle")}
        sub={t("banking.rankSub")}
        right={
          <select
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            className="field !w-auto"
            title={t("banking.rankTypeSelect")}
          >
            {ENTITY_TYPES.map((opt) => (
              <option key={opt.value} value={opt.value}>{t(`banking.entityType.${opt.value || "all"}`, opt.label)}</option>
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
        <StateBlock kind="empty" message={t("banking.rankEmpty")} />
      ) : (
        <Card>
          {agrupado && (
            <p className="text-xs text-muted mb-3">{t("banking.rankGroupNote")}</p>
          )}
          {tiposAusentes.length > 0 && (
            <p className="text-xs text-muted mb-3">
              {t("banking.rankTypesAbsent", { types: tiposAusentes.join(", ") })}
            </p>
          )}
          {latestFallback && (
            <p className="text-xs text-muted mb-3">
              {t("banking.rankFallbackPrefix")}<span className="text-body font-medium">{t("banking.rankFallbackBold")}</span>{t("banking.rankFallbackSuffix")}
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-2 font-medium">#</th>
                  <th className="py-2 px-2 font-medium">{t("banking.rankColEntity")}</th>
                  <th className="py-2 px-2 font-medium text-right">{t("banking.rankColScore")}</th>
                  <th className="py-2 px-2 font-medium text-right">Ejecución</th>
                  <th className="py-2 px-2 font-medium text-right">Resiliencia</th>
                  <th className="py-2 px-2 font-medium text-right">{t("banking.rankColPeriod")}</th>
                  <th className="w-8" />
                </tr>
              </thead>
              {grupos.map(({ tipo, filas }) => (
                <tbody key={tipo || "sin-tipo"}>
                  {agrupado && (
                    <tr className="bg-surface2">
                      <th
                        colSpan={7}
                        scope="colgroup"
                        className="py-1.5 px-2 text-left text-xs font-semibold text-body"
                      >
                        {tipo ? entityTypeLabel(tipo, t) : t("banking.rankTypeUnknown")}
                        <span className="ml-2 font-normal text-muted">
                          {t("banking.rankGroupCount", { count: filas.length })}
                        </span>
                      </th>
                    </tr>
                  )}
                  {filas.map((r) => (
                    <tr
                      key={r.bank_name}
                      className="border-b border-line/60 last:border-0 hover:bg-surface2 cursor-pointer"
                      onClick={() => setSelectedBank(r.bank_id)}
                      tabIndex={0}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelectedBank(r.bank_id))}
                    >
                      {/* Agrupados, el # es la posición DENTRO del tipo: es la única que
                          compara cosas comparables. Sin agrupar, el orden ya es de un solo
                          tipo y `rank` global coincide con la posición mostrada. */}
                      <td className="py-2.5 px-2 mono text-faint">
                        {agrupado ? r.rank_in_type : r.rank}
                      </td>
                      <td className="py-2.5 px-2 text-ink truncate">{r.bank_name}</td>
                      <td className="py-2.5 px-2 text-right mono font-semibold text-ink">
                        {fmtNum(r.overall_score, 1)}
                      </td>
                      <td className="py-2.5 px-2 text-right">
                        <CeldaEje score={r.ejecucion} banda={r.banda_ejecucion} />
                      </td>
                      <td className="py-2.5 px-2 text-right">
                        <CeldaEje score={r.resiliencia} banda={r.banda_resiliencia} />
                      </td>
                      <td className="py-2.5 px-2 text-right mono text-xs text-muted">{r.period_end}</td>
                      <td className="py-2.5 pr-2 text-right">
                        <ChevronRight className="w-4 h-4 text-faint inline-block" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              ))}
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
