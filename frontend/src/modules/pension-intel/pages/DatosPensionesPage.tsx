import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PiggyBank } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { OperationsConsole } from "@/shared/ops/OperationsConsole";
import {
  getPensionPulse,
  pulseHasData,
  HEADLINE_CCI,
  HEADLINE_SDP,
  HEADLINE_COMMISSIONS,
  PensionPulse,
} from "../api";

/** "Estado del dato" panel: coverage + provenance of the persisted SIPEN data. */
function PensionesOverview() {
  const { t } = useTranslation();
  const [pulse, setPulse] = useState<PensionPulse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    getPensionPulse()
      .then((p) => { setPulse(p); setState("ready"); })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading")
    return <Card><StateBlock kind="loading" message={t("datos.pensiones.ovLoading")} /></Card>;
  if (state === "error")
    return <Card><StateBlock kind="error" message={t("datos.pensiones.ovError")} /></Card>;

  const p = pulse!;
  const has = pulseHasData(p);
  const cci = p.headline?.[HEADLINE_CCI] ?? null;
  const sdp = p.headline?.[HEADLINE_SDP] ?? null;
  const commissions = p.headline?.[HEADLINE_COMMISSIONS] ?? null;

  return (
    <Card>
      <CardHead
        icon={PiggyBank}
        title={t("datos.pensiones.ovTitle")}
        subtitle={t("datos.pensiones.ovSub")}
        right={<Chip tone={has ? "ok" : "muted"}>{has ? t("datos.pensiones.realChip") : t("datos.pensiones.noData")}</Chip>}
      />
      {!has ? (
        <p className="text-sm text-muted mt-3">{t("datos.pensiones.ovEmptyHint")}</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-3">
          <StatTile label={t("datos.pensiones.statPeriod")} value={p.period ?? "—"} />
          <StatTile label={t("datos.pensiones.statCci")} value={cci != null ? fmtNum(cci, 1) : "—"} unit="%" />
          <StatTile label={t("datos.pensiones.statSdp")} value={sdp != null ? fmtNum(sdp, 1) : "—"} unit="%" />
          <StatTile label={t("datos.pensiones.statCommissions")} value={commissions != null ? fmtNum(commissions, 0) : "—"} unit="RD$ MM" />
          <StatTile label={t("datos.pensiones.statAfp")} value={p.entity_count ?? "—"} />
          <StatTile label={t("datos.pensiones.statSource")} value={t("datos.pensiones.sourceValue")} />
        </div>
      )}
    </Card>
  );
}

/** Datos · Pensiones (SIPEN): estado del dato + operación de sync. */
export function DatosPensionesPage() {
  const { t } = useTranslation();
  return (
    <OperationsConsole
      eyebrow={t("datos.pensiones.eyebrow")}
      title={t("datos.pensiones.title")}
      sub={t("datos.pensiones.sub")}
      filter={(op) => op.name.startsWith("sipen-")}
      emptyMessage={t("datos.pensiones.empty")}
      overview={<PensionesOverview />}
    />
  );
}
