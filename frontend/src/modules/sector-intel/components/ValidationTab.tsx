import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck, RefreshCw, AlertTriangle, BarChart3 } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { I18N_DE_VEREDICTO, acredita, claveDeVeredicto } from "@/shared/lib/veredicto";
import {
  getSectorValidation,
  runSectorGateE,
  SectorGateEControl,
  SectorGateEOutcome,
  SectorGateEReport,
} from "../api";

function fmtDate(iso?: string): string {
  return iso
    ? new Date(iso).toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" })
    : "—";
}
function fmtRho(x: number | null | undefined): string {
  return x == null ? "—" : (x >= 0 ? "+" : "") + x.toFixed(3);
}
function fmtPp(x: number | null | undefined): string {
  return x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)} pp`;
}

/**
 * Una FILA de desenlace: su IC, su intervalo y —pegado— su control por tamaño.
 *
 * El control no es un extra: sin él, «el índice ordena» y «el tamaño ordena y el índice lo
 * copia» son indistinguibles, y son conclusiones opuestas. Por eso esta fila no sabe
 * renderizar un IC solo: o trae el control, o dice que no lo tiene.
 */
function FilaDeDesenlace({
  titulo,
  detalle,
  senal,
  control,
  primario,
}: {
  titulo?: string;
  detalle?: string;
  senal: { mean_yearly_ic?: number | null; ic_ci?: [number | null, number | null];
           n_observations?: number; invertido?: boolean };
  control?: SectorGateEControl | null;
  primario?: boolean;
}) {
  const { t } = useTranslation();
  const juzgable = { ic_ci: senal.ic_ci, invertido: senal.invertido,
                     empata_con_el_score: control?.empata_con_el_score };
  const clave = claveDeVeredicto(juzgable);
  const ci = senal.ic_ci;
  return (
    <div className={`rounded-[10px] p-3.5 ${primario ? "bg-surface-2" : "bg-surface"} border border-grid`}>
      <div className="flex items-start justify-between gap-3 mb-1.5">
        <div>
          <p className="text-xs font-semibold text-ink">{titulo ?? "—"}</p>
          {detalle && <p className="text-xs text-faint mt-0.5">{detalle}</p>}
        </div>
        <Chip tone={acredita(juzgable) ? "ok" : "warn"}>{t(I18N_DE_VEREDICTO[clave])}</Chip>
      </div>
      <p className="mono text-xs text-body tabular-nums">
        {fmtRho(senal.mean_yearly_ic)}
        {ci && ci[0] != null && (
          <span className="text-faint"> · IC 95% {fmtRho(ci[0])} … {fmtRho(ci[1])}</span>
        )}
        {senal.n_observations != null && (
          <span className="text-faint"> · n={fmtNum(senal.n_observations, 0)}</span>
        )}
      </p>
      {control?.mean_yearly_ic != null ? (
        <p className="mt-2 text-xs text-muted">
          <span className="font-semibold text-ink">{t("sector.valSizeControlTitle")}</span>{" "}
          {t("sector.valSizeControlValue", {
            ic: fmtRho(control.mean_yearly_ic),
            lo: fmtRho(control.ic_ci?.[0] ?? null),
            hi: fmtRho(control.ic_ci?.[1] ?? null),
          })}{" "}
          {control.veredicto}
        </p>
      ) : (
        <p className="mt-2 text-xs text-faint">{t("sector.valSizeControlMissing")}</p>
      )}
    </div>
  );
}

/** Per-year Spearman as a centered diverging bar (−1 … +1). */
function YearBars({ rows }: { rows: NonNullable<SectorGateEReport["by_year"]> }) {
  return (
    <div className="space-y-2.5 mt-1">
      {rows.map((r) => {
        const v = r.spearman ?? 0;
        const w = Math.min(50, Math.abs(v) * 50);
        return (
          <div key={r.year} className="flex items-center gap-3">
            <span className="w-12 shrink-0 mono text-xs text-ink">{r.year}</span>
            <div className="relative flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
              <div className="absolute left-1/2 top-0 h-full w-px bg-grid" />
              <div
                className="absolute top-0 h-full bg-accent"
                style={
                  v >= 0
                    ? { left: "50%", width: `${w}%` }
                    : { right: "50%", width: `${w}%` }
                }
              />
            </div>
            <span className="w-24 shrink-0 text-right mono text-xs text-body tabular-nums">
              {fmtRho(r.spearman)} <span className="text-faint">· n={r.n}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function ValidationTab() {
  const { t } = useTranslation();
  const [report, setReport] = useState<SectorGateEReport | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getSectorValidation());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, [load]);

  const stopPoll = () => {
    if (poll.current) {
      window.clearInterval(poll.current);
      poll.current = null;
    }
  };

  const regenerate = async () => {
    if (busy) return;
    stopPoll();
    setBusy(true);
    const before = report?.generated_at;
    try {
      const res = await runSectorGateE();
      if (!res.started) {
        setBusy(false);
        return;
      }
      let ticks = 0;
      poll.current = window.setInterval(async () => {
        ticks += 1;
        try {
          const r = await getSectorValidation();
          if (r.generated_at && r.generated_at !== before) {
            setReport(r);
            setBusy(false);
            stopPoll();
          } else if (ticks > 30) {
            setBusy(false);
            stopPoll();
          }
        } catch {
          setBusy(false);
          stopPoll();
        }
      }, 3000);
    } catch {
      setBusy(false);
      stopPoll();
    }
  };

  const regenBtn = (
    <button onClick={regenerate} disabled={busy} className="btn btn-ghost !py-1.5">
      <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} />
      {busy ? t("sector.valRegenBusy") : t("sector.valRegen")}
    </button>
  );

  if (status === "loading") return <StateBlock kind="loading" message={t("sector.valLoading")} />;
  if (status === "error") return <StateBlock kind="error" message={t("sector.valError")} />;
  if (!report?.has_report || report.has_data === false) {
    return (
      <div>
        <div className="flex justify-end mb-3">{regenBtn}</div>
        <StateBlock
          kind="empty"
          message={report?.reason ?? t("sector.valEmpty")}
        />
      </div>
    );
  }

  // El veredicto lo decide el cuerpo COMPARTIDO con la tabla de Metodología. Acá vivía
  // `ciExcludesZero(report.ic_ci)` a secas, y como ese intervalo excluye el cero POR ABAJO,
  // esta pestaña pintaba un chip verde de «significativo» sobre un resultado invertido que
  // además empata con ordenar por tamaño del sector.
  const sig = acredita(report);
  const ci = report.ic_ci;
  const pooledCi = report.spearman_pooled_ci;
  const qs = report.quintile_spread;

  // El PRIMARIO primero: es el desenlace que el índice dice anticipar, y el que encabeza el
  // reporte. El orden no es estético — quien lea solo la primera fila tiene que leer ésa.
  const primarioClave = report.outcome_primario;
  const desenlaces = Object.entries(report.outcomes ?? {})
    .map(([clave, o]: [string, SectorGateEOutcome]) => ({
      clave,
      o,
      control: o.control_solo_tamano?.intensidad ?? null,
      esPrimario: clave === primarioClave,
    }))
    .sort((a, b) => Number(b.esPrimario) - Number(a.esPrimario));
  const bloquePrimario = desenlaces.find((d) => d.esPrimario)?.o;
  const contrasteNivel = bloquePrimario?.contraste_nivel ?? null;
  const controlNivel = bloquePrimario?.control_solo_tamano?.nivel ?? null;
  const notaContraste = bloquePrimario?.nota_contraste;

  return (
    <div>
      {/* Disclaimer honesto — prominente */}
      <div className="mb-4 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">{t("sector.valDisclaimerStrong")}</span>{" "}
          {report.disclaimer}
        </p>
      </div>

      <div className="flex items-center justify-between mb-3 gap-3">
        <span className="text-xs text-muted">
          {t("sector.valOutcomeLabel")} <span className="text-body">{report.outcome}</span> ·{" "}
          {report.resolution}
          {report.generated_at && <> · {fmtDate(report.generated_at)}</>}
        </span>
        {regenBtn}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-3">
        <StatTile label={t("sector.valStatIcMean")} value={fmtRho(report.mean_yearly_ic)} />
        <StatTile
          label={t("sector.valStatIcCi", { n: report.n_years ?? "—" })}
          value={ci && ci[0] != null ? `${fmtRho(ci[0])} … ${fmtRho(ci[1])}` : "—"}
        />
        <StatTile
          label={t("sector.valStatPartial")}
          value={`${fmtRho(report.spearman_partial_growth)}${
            report.spearman_partial_n ? ` · n=${report.spearman_partial_n}` : ""
          }`}
        />
        <StatTile
          label={t("sector.valStatObs")}
          value={t("sector.valObsValue", { n: fmtNum(report.n_observations, 0), branches: report.n_branches })}
        />
      </div>

      {/* LOS DOS DESENLACES. El eje corrió su backtest contra dos —la inversión realizada,
          que es la que el índice dice anticipar, y el empleo formal, que NO lo es— y la
          pantalla mostraba uno solo: el que estuviera en el encabezado plano. Un eje que
          corre dos backtests y publica uno esconde un resultado.
          Cada IC va con SU control por tamaño pegado, o con el aviso de que no lo tiene. */}
      {desenlaces.length > 0 && (
        <div className="mb-5">
          <p className="text-xs text-muted mb-2">{t("sector.valOutcomesTitle")}</p>
          <div className="grid md:grid-cols-2 gap-3">
            {desenlaces.map(({ clave, o, control, esPrimario }) => (
              <FilaDeDesenlace
                key={clave}
                titulo={o.que_mide}
                detalle={
                  esPrimario ? t("sector.valOutcomePrimary") : t("sector.valOutcomeSecondary")
                }
                senal={o}
                control={control}
                primario={esPrimario}
              />
            ))}
          </div>
          {/* EL CONTRASTE DE NIVEL, con SU control. Es la cifra que más se parece a una
              credencial —positiva y con el intervalo del lado bueno— y hasta hoy viajaba en
              el payload sin el control que la califica. */}
          {contrasteNivel && (
            <div className="mt-3">
              <FilaDeDesenlace
                titulo={t("sector.valLevelContrastTitle")}
                detalle={notaContraste}
                senal={contrasteNivel}
                control={controlNivel}
              />
            </div>
          )}
        </div>
      )}

      {/* Secundario, etiquetado: el ρ apilado (sobrestima la precisión) */}
      <p className="text-xs text-faint mb-5">
        {t("sector.valPooledPrefix", { rho: fmtRho(report.spearman_pooled) })}
        {pooledCi && pooledCi[0] != null && t("sector.valPooledCi", { lo: fmtRho(pooledCi[0]), hi: fmtRho(pooledCi[1]) })}
        {t("sector.valPooledMid")}
        <span className="text-muted">{t("sector.valPooledBold")}</span>
        {t("sector.valPooledSuffix")}
      </p>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHead
            icon={ShieldCheck}
            title={t("sector.valIcYearTitle")}
            subtitle={t("sector.valIcYearSubtitle", { y0: report.years?.[0], y1: report.years?.[1] })}
            right={
              <Chip tone={sig ? "ok" : "warn"}>
                {sig ? t("sector.valSigYes") : t("sector.valSigNo")}
              </Chip>
            }
          />
          {report.by_year && <YearBars rows={report.by_year} />}
          <p className="mt-3 text-xs text-muted">
            {sig ? (
              <>
                {t("sector.valSigYesPrefix")}<span className="font-medium">{t("sector.valSigYesBold")}</span>{t("sector.valSigYesSuffix")}
              </>
            ) : (
              <>
                {t("sector.valSigNoPrefix")}<span className="font-medium">{t("sector.valSigNoBold1")}</span>{t("sector.valSigNoMid")}
                <span className="font-medium">{t("sector.valSigNoBold2")}</span>{t("sector.valSigNoSuffix")}
              </>
            )}
          </p>
        </Card>

        <Card>
          <CardHead
            icon={BarChart3}
            title={t("sector.valQuintileTitle")}
            subtitle={t("sector.valQuintileSubtitle", { yearsPart: qs?.n_years ? ` (${qs.n_years})` : "" })}
          />
          {qs ? (
            <div className="space-y-3 mt-1">
              <StatTile label={t("sector.valQHigh")} value={fmtPp(qs.top_iai_mean_growth)} />
              <StatTile label={t("sector.valQLow")} value={fmtPp(qs.bottom_iai_mean_growth)} />
              <div className="border-t border-grid pt-3">
                <StatTile label={t("sector.valQSpread")} value={fmtPp(qs.spread)} />
              </div>
              <p className="text-xs text-muted">
                {t("sector.valQDirNote", { dir: qs.spread > 0 ? t("sector.valDirPositive") : t("sector.valDirNegative"), spread: fmtPp(qs.spread) })}
              </p>
            </div>
          ) : (
            <StateBlock kind="empty" message={t("sector.valQEmpty")} />
          )}
        </Card>
      </div>
    </div>
  );
}
