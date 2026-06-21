import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { CalendarClock } from "lucide-react";
import { useApp, dateToPeriod } from "@/shared/context/AppContext";
import { useAuth } from "@/shared/auth/AuthContext";
import { getBankPeriods } from "../api";

/** Fetch + cache the period-ends each entity has data for. Pass the ids in use
 * (1 for the single-entity pages, up to 4 for Comparar); each id is fetched once. */
export function useBankPeriods(ids: string[]): {
  periodsOf: (id: string) => string[] | undefined;
  loading: boolean;
} {
  const [map, setMap] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(false);
  const inflight = useRef<Set<string>>(new Set());

  useEffect(() => {
    const pending = ids.filter((id) => id && map[id] === undefined && !inflight.current.has(id));
    if (!pending.length) return;
    pending.forEach((id) => inflight.current.add(id));
    setLoading(true);
    let active = true;
    Promise.all(
      pending.map((id) =>
        getBankPeriods(id)
          .then((periods) => ({ id, periods }))
          .catch(() => ({ id, periods: [] as string[] })),
      ),
    ).then((results) => {
      pending.forEach((id) => inflight.current.delete(id));
      if (!active) return;
      setMap((prev) => {
        const next = { ...prev };
        results.forEach(({ id, periods }) => (next[id] = periods));
        return next;
      });
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  return { periodsOf: (id) => map[id], loading };
}

export type PeriodVerdict =
  | { available: true }
  | { available: false; kind: "none" | "annual" | "pending" | "absent"; latestLabel: string | null };

const isDecember = (iso: string) => iso.endsWith("-12-31");

/** Classify whether `globalLabel` is available for an entity given the period-ends
 * it has data for. Distinguishes a genuine gap from "exists but not yet loaded":
 * - none    → the entity has no data at all
 * - annual  → entity reports yearly (all-December periods); a quarter is expected N/D
 * - pending → the period exists system-wide (other entities have it) but not here —
 *             likely not yet ingested; honest wording, never "no existe"
 * - absent  → the period isn't in the system for anyone */
export function evaluatePeriod(
  globalLabel: string,
  entityPeriodsISO: string[],
  systemLabels: string[],
): PeriodVerdict {
  const entityLabels = entityPeriodsISO
    .map(dateToPeriod)
    .filter((l): l is string => !!l);
  if (entityLabels.includes(globalLabel)) return { available: true };

  const latestLabel = entityLabels[0] ?? null;
  if (!entityPeriodsISO.length) return { available: false, kind: "none", latestLabel: null };

  // Annual reporters (all-December history) only "expectedly" lack non-Q4 quarters.
  // A missing Q4 (December) is the yearly figure itself just not loaded yet → pending.
  const annual = entityPeriodsISO.length >= 2 && entityPeriodsISO.every(isDecember);
  if (annual && !globalLabel.endsWith("-Q4")) return { available: false, kind: "annual", latestLabel };
  if (systemLabels.includes(globalLabel)) return { available: false, kind: "pending", latestLabel };
  return { available: false, kind: "absent", latestLabel };
}

function message(
  verdict: Exclude<PeriodVerdict, { available: true }>,
  globalLabel: string,
  t: TFunction,
  entityName?: string,
): string {
  const who = entityName ? entityName : t("banking.thisEntity");
  switch (verdict.kind) {
    case "none":
      return t("banking.periodNoneMsg", { who });
    case "annual":
      return t("banking.periodAnnualMsg", { who, period: globalLabel });
    case "pending":
      return t("banking.periodPendingMsg", { who, period: globalLabel });
    case "absent":
      return t("banking.periodAbsentMsg", { period: globalLabel });
  }
}

/** Honest, themed notice for a period an entity lacks, with a one-click jump to its
 * latest available period and (for admins, when the data is just pending load) a
 * shortcut to the data console to trigger the sync. Renders null when available. */
export function PeriodNoticeBox({
  verdict,
  entityName,
  className = "",
}: {
  verdict: PeriodVerdict;
  entityName?: string;
  className?: string;
}) {
  const { period, setPeriod } = useApp();
  const { hasRole } = useAuth();
  const { t } = useTranslation();
  if (verdict.available) return null;

  return (
    <div className={`rounded-[10px] bg-warn-soft text-warn px-3 py-2.5 text-sm flex flex-wrap items-center gap-x-3 gap-y-1.5 ${className}`}>
      <span className="flex items-center gap-2 min-w-0">
        <CalendarClock className="w-4 h-4 shrink-0" />
        <span>{message(verdict, period, t, entityName)}</span>
      </span>
      {verdict.latestLabel && (
        <button
          onClick={() => setPeriod(verdict.latestLabel!)}
          className="underline font-medium hover:opacity-80 shrink-0"
        >
          {t("banking.periodViewLabel", { label: verdict.latestLabel })}
        </button>
      )}
      {verdict.kind === "pending" && hasRole("admin") && (
        <Link to="/datos/banca" className="underline font-medium hover:opacity-80 shrink-0">
          {t("banking.periodLoadData")}
        </Link>
      )}
    </div>
  );
}

/** Convenience for single-entity pages (Scoring / Escenarios / Reportes): returns
 * whether the action should be blocked and the notice node to render. */
export function useEntityPeriodGuard(bankId: string, entityName?: string): {
  blocked: boolean;
  notice: ReactNode;
} {
  const { period, periods } = useApp();
  const { periodsOf } = useBankPeriods(bankId ? [bankId] : []);

  if (!bankId) return { blocked: false, notice: null };
  const entityPeriods = periodsOf(bankId);
  if (entityPeriods === undefined) return { blocked: false, notice: null }; // still loading

  const verdict = evaluatePeriod(period, entityPeriods, periods);
  return {
    blocked: !verdict.available,
    notice: verdict.available ? null : <PeriodNoticeBox verdict={verdict} entityName={entityName} className="mt-3" />,
  };
}
