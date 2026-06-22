import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Landmark, Info } from "lucide-react";
import { PageHead, Card, CardHead, StateBlock, LoadingGrid } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getTrusts, TrustRow } from "../api";

// Keyed by the backend-provided band text (data); only the chip color is derived here.
const BAND_CLASS: Record<string, string> = {
  "Sólida": "text-ok bg-ok-soft",
  "Estable": "text-accent-ink bg-accent-soft",
  "En vigilancia": "text-warn bg-warn-soft",
  "Frágil": "text-alert bg-alert-soft",
  "Datos insuficientes": "text-muted bg-surface2",
  "N/D": "text-muted bg-surface2",
};

function HealthBadge({ band }: { band: string }) {
  return (
    <span className={`inline-flex items-center rounded-[8px] px-2 py-0.5 text-xs font-semibold ${BAND_CLASS[band] ?? BAND_CLASS["N/D"]}`}>
      {band}
    </span>
  );
}

/** Millions of RD$ (the trust statements are in pesos). */
function mm(v: number | null | undefined): string {
  if (v === null || v === undefined) return "N/D";
  return fmtNum(v / 1_000_000, 0);
}

function dimCell(value: number | null) {
  return (
    <span className="mono text-sm text-ink tabular-nums">
      {value === null ? <span className="text-faint">N/D</span> : fmtNum(value, 0)}
    </span>
  );
}

export function FideicomisosPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<TrustRow[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    getTrusts()
      .then((r) => active && setRows(r))
      .catch(() => active && setError(true));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div>
      <PageHead
        eyebrow={t("banking.fidEyebrow")}
        title={t("banking.fidTitle")}
        sub={t("banking.fidSub")}
      />

      <Card className="mb-5">
        <div className="flex items-start gap-2 text-sm text-muted">
          <Info className="w-4 h-4 mt-0.5 shrink-0 text-faint" />
          <p className="leading-relaxed">
            {t("banking.fidInfoP1")}<span className="text-body font-medium">{t("banking.fidInfoNo")}</span>{t("banking.fidInfoMid")}<span className="text-body font-medium">{t("banking.fidInfoSolv")}</span>{t("banking.fidInfoSep")}<span className="text-body font-medium">{t("banking.fidInfoLiq")}</span>{t("banking.fidInfoAnd")}<span className="text-body font-medium">{t("banking.fidInfoSost")}</span>{t("banking.fidInfoSuffix")}
          </p>
        </div>
      </Card>

      {error ? (
        <StateBlock kind="error" message={t("banking.fidError")} />
      ) : rows === null ? (
        <LoadingGrid />
      ) : rows.length === 0 ? (
        <StateBlock kind="empty" message={t("banking.fidEmpty")} />
      ) : (
        <Card>
          <CardHead icon={Landmark} title={t("banking.fidCardTitle")} subtitle={t("banking.fidCardSubtitle", { n: rows.length })} />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-2 font-medium">{t("banking.fidColTrust")}</th>
                  <th className="py-2 px-2 font-medium">{t("banking.fidColSegment")}</th>
                  <th className="py-2 px-2 font-medium">{t("banking.fidColHealth")}</th>
                  <th className="py-2 px-2 font-medium text-center">{t("banking.fidColSolv")}</th>
                  <th className="py-2 px-2 font-medium text-center">{t("banking.fidColLiq")}</th>
                  <th className="py-2 px-2 font-medium text-center">{t("banking.fidColSost")}</th>
                  <th className="py-2 px-2 font-medium text-right">{t("banking.fidColAssets")}</th>
                  <th className="py-2 px-2 font-medium text-right">{t("banking.fidColEquity")}</th>
                  <th className="py-2 px-2 font-medium text-right">{t("banking.fidColResult")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((trust) => (
                  <tr key={trust.id} className="border-b border-line/60">
                    <td className="py-2 px-2">
                      <div className="text-body font-medium truncate max-w-[260px]" title={trust.name}>{trust.name}</div>
                      {trust.period_end && <div className="text-[10px] text-faint mono">{trust.period_end}</div>}
                    </td>
                    <td className="py-2 px-2 text-muted">{t(`banking.fidSegment.${trust.segment ?? "indeterminado"}`, "—")}</td>
                    <td className="py-2 px-2">
                      <div className="flex items-center gap-2">
                        <HealthBadge band={trust.health.band} />
                        <span className="mono text-xs text-muted tabular-nums">
                          {trust.health.overall === null ? "" : fmtNum(trust.health.overall, 0)}
                        </span>
                      </div>
                    </td>
                    <td className="py-2 px-2 text-center">{dimCell(trust.health.solvencia)}</td>
                    <td className="py-2 px-2 text-center">{dimCell(trust.health.liquidez)}</td>
                    <td className="py-2 px-2 text-center">{dimCell(trust.health.sostenibilidad)}</td>
                    <td className="py-2 px-2 text-right mono text-ink tabular-nums">{mm(trust.financials?.activos_totales)}</td>
                    <td className="py-2 px-2 text-right mono text-ink tabular-nums">{mm(trust.financials?.patrimonio_fideicomitido)}</td>
                    <td className="py-2 px-2 text-right mono text-ink tabular-nums">{mm(trust.financials?.resultado_periodo)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
