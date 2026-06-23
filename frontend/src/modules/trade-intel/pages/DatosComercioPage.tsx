import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Boxes } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { OperationsConsole } from "@/shared/ops/OperationsConsole";
import { getTradeScore, TradeScore } from "../api";

/** "Estado del dato" panel: coverage + provenance of the persisted DGA trade data. */
function ComercioOverview() {
  const { t } = useTranslation();
  const [score, setScore] = useState<TradeScore | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    getTradeScore()
      .then((s) => { setScore(s); setState("ready"); })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading")
    return <Card><StateBlock kind="loading" message={t("datos.comercio.ovLoading")} /></Card>;
  if (state === "error")
    return <Card><StateBlock kind="error" message={t("datos.comercio.ovError")} /></Card>;

  const s = score!;
  return (
    <Card>
      <CardHead
        icon={Boxes}
        title={t("datos.comercio.ovTitle")}
        subtitle={t("datos.comercio.ovSub")}
        right={<Chip tone={s.has_score ? "ok" : "muted"}>{s.has_score ? t("datos.comercio.realChip") : t("datos.comercio.noData")}</Chip>}
      />
      {!s.has_score ? (
        <p className="text-sm text-muted mt-3">
          {t("datos.comercio.ovEmptyHint")}
        </p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-3">
          <StatTile label={t("datos.comercio.statPeriod")} value={s.period ?? "—"} />
          <StatTile label={t("datos.comercio.statChapters")} value={s.n_products_export ?? "—"} />
          <StatTile label={t("datos.comercio.statExport")} value={fmtNum(s.total_exports, 0)} unit="M US$" />
          <StatTile label={t("datos.comercio.statImport")} value={fmtNum(s.total_imports, 0)} unit="M US$" />
          <StatTile label={t("datos.comercio.statResilience")} value={fmtNum(s.resilience_score, 1)} />
          <StatTile label={t("datos.comercio.statDiversification")} value={fmtNum(s.export_diversification, 1)} />
          <StatTile
            label={t("datos.comercio.statImportDep")}
            value={s.import_dependency != null ? fmtPct(s.import_dependency * 100, 0) : "—"}
          />
          <StatTile label={t("datos.comercio.statSource")} value={t("datos.comercio.sourceValue")} />
        </div>
      )}
    </Card>
  );
}

/** Datos · Comercio (DGA/Aduanas): estado del dato + operación de sync. */
export function DatosComercioPage() {
  const { t } = useTranslation();
  return (
    <OperationsConsole
      eyebrow={t("datos.comercio.eyebrow")}
      title={t("datos.comercio.title")}
      sub={t("datos.comercio.sub")}
      filter={(op) => op.name.startsWith("dga-")}
      emptyMessage={t("datos.comercio.empty")}
      overview={<ComercioOverview />}
    />
  );
}
