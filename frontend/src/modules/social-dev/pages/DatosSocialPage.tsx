import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Users } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { OperationsConsole } from "@/shared/ops/OperationsConsole";
import { getIndicators, getDataset, IndicatorsResult, IdmDataset } from "../api";
import { IDM_DIM_VARS } from "../data";

// The social-dev data operations.
const SOCIAL_OPS = new Set([
  "one-social-sync",
  "idm-snapshot",
  "one-education-extract",
  "one-publications-sync",
]);

/** real / parcial / rúbrica for an IDM dimension, from the dataset's source map. */
function dimProvenance(t: TFunction, dimKey: string, sources: Record<string, string> | undefined) {
  const vars = IDM_DIM_VARS[dimKey] ?? [];
  if (!sources || vars.length === 0) return { text: "—", tone: "muted" as const };
  const live = vars.filter((v) => sources[v] === "live").length;
  if (live === 0) return { text: t("datos.social.provRubric"), tone: "muted" as const };
  if (live === vars.length) return { text: t("datos.social.provReal"), tone: "ok" as const };
  return { text: t("datos.social.provPartial"), tone: "warn" as const };
}

/** "Estado del dato" panel: coverage + per-dimension provenance of the IDM. */
function SocialOverview() {
  const { t } = useTranslation();
  const [ind, setInd] = useState<IndicatorsResult | null>(null);
  const [ds, setDs] = useState<IdmDataset | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    Promise.all([getIndicators(), getDataset()])
      .then(([i, d]) => { setInd(i); setDs(d); setState("ready"); })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading")
    return <Card><StateBlock kind="loading" message={t("datos.social.ovLoading")} /></Card>;
  if (state === "error")
    return <Card><StateBlock kind="error" message={t("datos.social.ovError")} /></Card>;

  const count = ind?.count ?? 0;
  // Provenance is uniform across regions; sample the first region's source map.
  const firstRegion = ds ? Object.keys(ds.sources)[0] : undefined;
  const sources = firstRegion ? ds!.sources[firstRegion] : undefined;

  return (
    <Card>
      <CardHead
        icon={Users}
        title={t("datos.social.ovTitle")}
        subtitle={t("datos.social.ovSub")}
        right={<Chip tone={count > 0 ? "ok" : "muted"}>{count > 0 ? t("datos.social.idmComputed") : t("datos.social.noData")}</Chip>}
      />
      {count === 0 ? (
        <p className="text-sm text-muted mt-3">
          {t("datos.social.ovEmptyHint")}
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-3">
            <StatTile label={t("datos.social.statRegions")} value={count} />
            <StatTile label={t("datos.social.statPeriod")} value={ind?.period ?? "—"} />
            <StatTile label={t("datos.social.statIdmMean")} value={fmtNum(ind?.distribution?.mean ?? null, 1)} />
            <StatTile label={t("datos.social.statSpread")} value={fmtNum(ind?.distribution?.spread ?? null, 1)} />
          </div>
          <div className="mt-4">
            <div className="text-xs text-muted mb-2">{t("datos.social.provByDim")}</div>
            <div className="flex flex-wrap gap-2">
              {Object.keys(IDM_DIM_VARS).map((dim) => {
                const p = dimProvenance(t, dim, sources);
                return (
                  <Chip key={dim} tone={p.tone}>
                    {t(`social.dims.${dim}`, { defaultValue: dim })}: {p.text}
                  </Chip>
                );
              })}
            </div>
            <p className="mt-2 text-[11px] text-faint">
              {t("datos.social.ovNote")}
            </p>
          </div>
        </>
      )}
    </Card>
  );
}

/** Datos · Social (ONE): estado del dato + operaciones de ingesta/cálculo. */
export function DatosSocialPage() {
  const { t } = useTranslation();
  return (
    <OperationsConsole
      eyebrow={t("datos.social.eyebrow")}
      title={t("datos.social.title")}
      sub={t("datos.social.sub")}
      filter={(op) => SOCIAL_OPS.has(op.name)}
      emptyMessage={t("datos.social.empty")}
      overview={<SocialOverview />}
    />
  );
}
