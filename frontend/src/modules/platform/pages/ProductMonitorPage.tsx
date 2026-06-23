import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Boxes, RefreshCw, ChevronDown, Check, X } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Chip,
  StateBlock,
  Skeleton,
} from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { useAuth } from "@/shared/auth/AuthContext";
import {
  getProductReadiness,
  recomputeProductReadiness,
  activateProduct,
  deactivateProduct,
  type ProductMatrix,
  type ProductLevel,
  type ProductSector,
} from "../api";

const TIERS = ["pulse", "insight", "deep_dive"] as const;
const GATES = ["g1", "g2", "g3", "g4", "g5"] as const;

/** Tono del semáforo de readiness según el umbral del nivel. */
function readinessTone(level: ProductLevel, implemented: boolean): "ok" | "warn" | "alert" | "muted" {
  if (!implemented) return "muted";
  if (level.is_active || level.can_activate) return "ok";
  if (level.readiness >= level.threshold * 0.6) return "warn";
  return "alert";
}

function pct(x: number): string {
  return `${fmtNum(x * 100, 0)}%`;
}
/** % con 1 decimal — para el tooltip de bloqueo (evita "75% < 75%" en casos límite). */
function pct1(x: number): string {
  return `${fmtNum(x * 100, 1)}%`;
}
/** Gate G1-G5 más débil de un nivel (para nombrar el faltante en el tooltip). */
function weakestGate(level: ProductLevel): typeof GATES[number] | null {
  if (!level.gates) return null;
  return GATES.reduce((a, b) => (level.gates![b] < level.gates![a] ? b : a));
}

export function ProductMonitorPage() {
  const { t } = useTranslation();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");

  const [matrix, setMatrix] = useState<ProductMatrix | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState<string | null>(null); // "recompute" | "{sector}:{tier}"
  const [expanded, setExpanded] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () =>
    getProductReadiness()
      .then((m) => { setMatrix(m); setStatus("ready"); })
      .catch(() => setStatus("error"));

  useEffect(() => { load(); }, []);

  const onRecompute = async () => {
    setBusy("recompute");
    setMsg(null);
    try {
      const r = await recomputeProductReadiness();
      setMatrix(r.matrix);
    } catch {
      setMsg(t("platform.productMonitor.recomputeError"));
    } finally {
      setBusy(null);
    }
  };

  const onToggle = async (sector: string, level: ProductLevel) => {
    const key = `${sector}:${level.tier}`;
    setBusy(key);
    setMsg(null);
    try {
      if (level.is_active) {
        await deactivateProduct(sector, level.tier);
      } else {
        await activateProduct(sector, level.tier);
      }
      await load();
    } catch (e) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const status = (e as any)?.response?.status;
      setMsg(status === 409
        ? t("platform.productMonitor.activateBlocked")
        : t("platform.productMonitor.toggleError"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow={t("platform.productMonitor.eyebrow")}
        title={t("platform.productMonitor.title")}
        sub={t("platform.productMonitor.sub")}
      />

      {!isAdmin ? (
        <StateBlock kind="forbidden" message={t("platform.productMonitor.forbidden")} />
      ) : status === "loading" ? (
        <Skeleton className="h-96" />
      ) : status === "error" ? (
        <StateBlock kind="error" message={t("platform.productMonitor.loadError")} />
      ) : matrix ? (
        <Card>
          <CardHead
            icon={Boxes}
            title={t("platform.productMonitor.gridTitle")}
            subtitle={t("platform.productMonitor.gridSubtitle")}
            right={
              <button onClick={onRecompute} disabled={busy === "recompute"} className="btn btn-ghost !py-1.5 shrink-0">
                <RefreshCw className={`w-3.5 h-3.5 ${busy === "recompute" ? "animate-spin" : ""}`} />
                {t("platform.productMonitor.recompute")}
              </button>
            }
          />

          {/* Leyenda: distingue publicado / cableado-no-publicado / sin cablear */}
          <div className="flex flex-wrap items-center gap-2 mb-3 text-xs">
            <Chip tone="ok">{t("platform.productMonitor.legendPublished")}</Chip>
            <Chip tone="warn">{t("platform.productMonitor.legendWired")}</Chip>
            <Chip tone="muted">{t("platform.productMonitor.legendNotWired")}</Chip>
            <span className="text-faint">{t("platform.productMonitor.legendNote")}</span>
          </div>
          {msg && <p className="text-xs text-alert mb-3" role="alert">{msg}</p>}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-2 font-medium">{t("platform.productMonitor.colSector")}</th>
                  {TIERS.map((tier) => (
                    <th key={tier} className="py-2 px-2 font-medium text-center">
                      {t(`platform.productMonitor.tier.${tier}`)}
                      <span className="block text-[10px] text-faint tabular-nums">
                        {t("platform.productMonitor.thresholdShort", { v: pct(matrix.thresholds[tier] ?? 0) })}
                      </span>
                    </th>
                  ))}
                  <th className="py-2 px-2" />
                </tr>
              </thead>
              <tbody>
                {matrix.sectors.map((sector) => (
                  <SectorRow
                    key={sector.sector_key}
                    sector={sector}
                    isAdmin={isAdmin}
                    busy={busy}
                    expanded={expanded === sector.sector_key}
                    onExpand={() => setExpanded(expanded === sector.sector_key ? null : sector.sector_key)}
                    onToggle={onToggle}
                    t={t}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <StateBlock kind="empty" message={t("platform.productMonitor.empty")} />
      )}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function SectorRow({ sector, isAdmin, busy, expanded, onExpand, onToggle, t }: {
  sector: ProductSector;
  isAdmin: boolean;
  busy: string | null;
  expanded: boolean;
  onExpand: () => void;
  onToggle: (sector: string, level: ProductLevel) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any;
}) {
  return (
    <>
      <tr className="border-b border-line/60 align-middle">
        <td className="py-2 px-2 min-w-0">
          <div className="text-ink truncate" title={sector.display_name}>{sector.display_name}</div>
          <div className="text-[11px] text-faint truncate" title={sector.source}>{sector.source}</div>
        </td>
        {TIERS.map((tier) => {
          const level = sector.levels.find((l) => l.tier === tier);
          if (!level) return <td key={tier} className="py-2 px-2 text-center text-faint">—</td>;
          const tone = readinessTone(level, sector.implemented);
          const key = `${sector.sector_key}:${tier}`;
          return (
            <td key={tier} className="py-2 px-2 text-center">
              <div className="flex flex-col items-center gap-1">
                <span className="mono tabular-nums text-ink">{pct(level.readiness)}</span>
                {!sector.implemented ? (
                  <Chip tone="muted">{t("platform.productMonitor.notWired")}</Chip>
                ) : level.is_active ? (
                  <Chip tone="ok">{t("platform.productMonitor.published")}</Chip>
                ) : (
                  <Chip tone={tone === "alert" ? "alert" : "warn"}>{t("platform.productMonitor.wired")}</Chip>
                )}
                {isAdmin && sector.implemented && (
                  level.is_active ? (
                    <button onClick={() => onToggle(sector.sector_key, level)} disabled={busy === key}
                      className="btn btn-ghost !py-1 !px-2 text-xs">
                      <X className="w-3 h-3" /> {t("platform.productMonitor.unpublish")}
                    </button>
                  ) : (
                    <button onClick={() => onToggle(sector.sector_key, level)}
                      disabled={busy === key || !level.can_activate}
                      title={level.can_activate ? undefined : (() => {
                        const base = t("platform.productMonitor.belowThreshold",
                          { r: pct1(level.readiness), v: pct1(level.threshold) });
                        const w = weakestGate(level);
                        return w ? `${base} · ${t("platform.productMonitor.missingGate", { g: t(`platform.productMonitor.gate.${w}`) })}` : base;
                      })()}
                      className="btn btn-ghost !py-1 !px-2 text-xs disabled:opacity-40">
                      <Check className="w-3 h-3" /> {t("platform.productMonitor.publish")}
                    </button>
                  )
                )}
              </div>
            </td>
          );
        })}
        <td className="py-2 px-2 text-right">
          <button onClick={onExpand} className="btn btn-ghost !py-1 !px-2" aria-label={t("platform.productMonitor.toggleDetail")}>
            <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? "rotate-180" : ""}`} />
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-surface2/60">
          <td colSpan={5} className="px-2 py-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {TIERS.map((tier) => {
                const level = sector.levels.find((l) => l.tier === tier);
                if (!level) return null;
                return (
                  <div key={tier} className="rounded-lg border border-line p-3">
                    <div className="text-xs font-medium text-ink mb-2">
                      {t(`platform.productMonitor.tier.${tier}`)} · {pct(level.readiness)}
                    </div>
                    <div className="space-y-1.5">
                      {GATES.map((g) => {
                        const v = level.gates ? level.gates[g] : 0;
                        return (
                          <div key={g}>
                            <div className="flex justify-between text-[11px] text-muted">
                              <span>{t(`platform.productMonitor.gate.${g}`)}</span>
                              <span className="mono tabular-nums">{pct(v)}</span>
                            </div>
                            <div className="h-1.5 rounded bg-surface2 overflow-hidden">
                              <div className="h-full bg-accent" style={{ width: `${Math.round(v * 100)}%` }} />
                            </div>
                            {level.detail?.[g] && (
                              <div className="text-[10px] text-faint truncate" title={level.detail[g]}>{level.detail[g]}</div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
