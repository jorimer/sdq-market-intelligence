import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { History, TrendingDown, FileText, ExternalLink } from "lucide-react";
import { PageHead, Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import {
  getCohortBacktest,
  getForensic,
  getForensicNarrative,
  forensicReportUrl,
  getHistoricalEntities,
  type CohortResponse,
  type ForensicNarrative,
  type ForensicPackage,
  type HistoricalEntity,
} from "../api";

/** Render mínimo de la narrativa (## encabezados · **negrita** · párrafos). */
function renderNarrative(md: string): JSX.Element[] {
  const out: JSX.Element[] = [];
  const bold = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((seg, i) =>
      seg.startsWith("**") && seg.endsWith("**") ? (
        <strong key={i} className="text-ink">
          {seg.slice(2, -2)}
        </strong>
      ) : (
        <span key={i}>{seg}</span>
      ),
    );
  md.split("\n").forEach((raw, i) => {
    const s = raw.trim();
    if (!s || s === "---") return;
    if (s.startsWith("## "))
      out.push(
        <h3 key={i} className="font-display text-[15px] font-bold text-ink mt-4 mb-1.5">
          {s.slice(3)}
        </h3>,
      );
    else out.push(
      <p key={i} className="text-sm text-body mb-2">
        {bold(s)}
      </p>,
    );
  });
  return out;
}

/** Etiquetas legibles de los códigos de alerta del motor de Alerta Temprana. */
const ALERT_LABEL: Record<string, string> = {
  salto_morosidad: "Salto de morosidad",
  brecha_provisiones: "Brecha de provisiones",
  estres_liquidez: "Estrés de liquidez / fuga de depósitos",
  crecimiento_anomalo: "Crecimiento anómalo de activos",
  fondeo_caro: "Fondeo por encima del sistema",
  solvencia_piso: "Solvencia cerca del piso",
  concentracion: "Concentración elevada",
};

const CHART_H = 240;
const axisTick = { fontSize: 11, fill: "var(--muted)" };
const tooltipStyle = {
  borderRadius: 8,
  fontSize: 12,
  background: "var(--surface)",
  border: "1px solid var(--border)",
  color: "var(--ink)",
};

function monthLabel(fecha: string): string {
  return fecha.slice(0, 7);
}

export function HistoricoPage() {
  const [cohort, setCohort] = useState<CohortResponse | null>(null);
  const [entities, setEntities] = useState<HistoricalEntity[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [pkg, setPkg] = useState<ForensicPackage | null>(null);
  const [narrative, setNarrative] = useState<ForensicNarrative | null>(null);
  const [narrStatus, setNarrStatus] = useState<"idle" | "loading" | "error" | "ready">("idle");
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [detailStatus, setDetailStatus] = useState<"idle" | "loading" | "error" | "ready">("idle");

  useEffect(() => {
    (async () => {
      try {
        const [c, ents] = await Promise.all([getCohortBacktest(), getHistoricalEntities(true)]);
        setCohort(c);
        setEntities(ents);
        const firstFound = c.cohort.find((r) => r.found);
        setSelected(firstFound?.nombre ?? ents[0]?.nombre ?? "");
        setStatus("ready");
      } catch {
        setStatus("error");
      }
    })();
  }, []);

  const loadDetail = useCallback(async (nombre: string) => {
    if (!nombre) return;
    setDetailStatus("loading");
    try {
      setPkg(await getForensic(nombre));
      setDetailStatus("ready");
    } catch {
      setDetailStatus("error");
    }
  }, []);

  const loadNarrative = useCallback(async (nombre: string) => {
    if (!nombre) return;
    setNarrStatus("loading");
    setNarrative(null);
    try {
      setNarrative(await getForensicNarrative(nombre));
      setNarrStatus("ready");
    } catch {
      setNarrStatus("error");
    }
  }, []);

  useEffect(() => {
    if (selected) {
      loadDetail(selected);
      loadNarrative(selected);
    }
  }, [selected, loadDetail, loadNarrative]);

  const chartData = useMemo(
    () =>
      (pkg?.series ?? []).map((p) => ({
        mes: monthLabel(p.fecha),
        morosidad: p.morosidad_pct,
        cobertura: p.cobertura_pct,
        depMoM: p.dep_mom_pct,
      })),
    [pkg],
  );

  const moraPeak = useMemo(() => {
    const vals = (pkg?.series ?? []).map((p) => p.morosidad_pct).filter((v): v is number => v != null);
    return vals.length ? Math.max(...vals) : null;
  }, [pkg]);

  if (status === "loading") return <StateBlock kind="loading" />;
  if (status === "error")
    return (
      <StateBlock
        kind="error"
        message="No se pudo cargar el histórico. Verifica que la carga de datos (Cronología SB) haya corrido en la Consola de Operación."
      />
    );

  return (
    <div className="space-y-5">
      <PageHead
        eyebrow="Cronología SB · 1947→"
        title="Histórico · Anatomía de quiebras"
        sub="Reconstrucción del deterioro de las entidades que salieron del sistema, con el motor de Alerta Temprana aplicado a su dato mensual real."
      />

      {/* Cohorte: la validación con dato real */}
      <Card>
        <CardHead
          icon={History}
          title="Backtest de Alerta Temprana"
          subtitle="Meses de anticipación de la primera alerta de cluster antes del colapso"
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted border-b border-line">
                <th className="py-2 pr-3 font-medium">Entidad</th>
                <th className="py-2 pr-3 font-medium">Episodio</th>
                <th className="py-2 pr-3 font-medium">Inicio (cluster)</th>
                <th className="py-2 pr-3 font-medium text-right">Anticipación</th>
              </tr>
            </thead>
            <tbody>
              {cohort?.cohort.map((r) => (
                <tr key={r.nombre} className="border-b border-line/60">
                  <td className="py-2 pr-3 text-ink">{r.nombre}</td>
                  <td className="py-2 pr-3 text-muted">{r.episodio}</td>
                  <td className="py-2 pr-3 mono">{r.onset_cluster ?? "—"}</td>
                  <td className="py-2 pr-3 text-right mono font-semibold">
                    {r.lead_months != null ? (
                      <Chip tone={r.lead_months >= 10 ? "ok" : "warn"}>{r.lead_months} meses</Chip>
                    ) : (
                      <Chip tone="muted">sin cluster</Chip>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted mt-3">
          Los ratios detectan insolvencia, no fraude: donde el cluster llega tarde o no llega
          (Baninter, Banco Global), la contabilidad ocultó el deterioro.
        </p>
      </Card>

      {/* Selector de entidad */}
      <div className="flex items-center gap-3">
        <label className="text-sm text-muted shrink-0" htmlFor="hist-entity">
          Entidad
        </label>
        <select
          id="hist-entity"
          className="field max-w-md"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
        >
          {entities.map((e) => (
            <option key={e.nombre} value={e.nombre}>
              {e.nombre}
            </option>
          ))}
        </select>
      </div>

      {/* Detalle forense */}
      {detailStatus === "loading" && <StateBlock kind="loading" />}
      {detailStatus === "error" && (
        <StateBlock kind="error" message="No se pudo cargar el análisis forense de esta entidad." />
      )}
      {detailStatus === "ready" && pkg && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatTile label="Inicio del deterioro" value={pkg.backtest.onset_cluster ?? "—"} />
            <StatTile
              label="Anticipación al colapso"
              value={pkg.backtest.lead_months != null ? `${pkg.backtest.lead_months}` : "—"}
              unit="meses"
            />
            <StatTile label="Morosidad máxima" value={fmtNum(moraPeak)} unit="%" />
            <StatTile
              label="Meses en alerta"
              value={`${pkg.backtest.n_high_months}`}
              unit={`de ${pkg.meta.n_periodos}`}
            />
          </div>

          <Card>
            <CardHead
              icon={TrendingDown}
              title="Riesgo de crédito y colchón de provisiones"
              subtitle="Morosidad (+90d) y cobertura de provisiones, mensual"
            />
            <ResponsiveContainer width="100%" height={CHART_H}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                <XAxis dataKey="mes" tick={axisTick} stroke="var(--border-strong)" minTickGap={28} />
                <YAxis tick={axisTick} stroke="var(--border-strong)" />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => `${fmtNum(v)}%`} />
                <Line
                  type="monotone"
                  dataKey="morosidad"
                  name="Morosidad %"
                  stroke="var(--alert)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="cobertura"
                  name="Cobertura %"
                  stroke="var(--teal)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
            <div className="flex gap-4 text-xs text-muted mt-2">
              <span className="inline-flex items-center gap-1.5">
                <i className="inline-block w-3.5 h-0.5 rounded" style={{ background: "var(--alert)" }} />
                Morosidad
              </span>
              <span className="inline-flex items-center gap-1.5">
                <i className="inline-block w-3.5 h-0.5 rounded" style={{ background: "var(--teal)" }} />
                Cobertura
              </span>
            </div>
          </Card>

          <Card>
            <CardHead title="Fuga de depósitos" subtitle="Variación intermensual de depósitos del público" />
            <ResponsiveContainer width="100%" height={CHART_H}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                <XAxis dataKey="mes" tick={axisTick} stroke="var(--border-strong)" minTickGap={28} />
                <YAxis tick={axisTick} stroke="var(--border-strong)" />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => `${fmtNum(v)}%`} />
                <Bar dataKey="depMoM" name="Δ depósitos %">
                  {chartData.map((d, i) => (
                    <Cell key={i} fill={(d.depMoM ?? 0) < 0 ? "var(--alert)" : "var(--ok)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>

          <Card>
            <CardHead title="Qué habría marcado el modelo, y cuándo" subtitle="Alertas por período" />
            {pkg.backtest.timeline.length === 0 ? (
              <p className="text-sm text-muted">Sin alertas en la ventana.</p>
            ) : (
              <ul className="space-y-2">
                {pkg.backtest.timeline.map((t) => (
                  <li key={t.period} className="flex items-start gap-3 text-sm">
                    <span className="mono text-accent-ink font-semibold shrink-0 w-20">{t.period}</span>
                    <span className="flex flex-wrap gap-1.5">
                      {t.alerts.map((a, i) => (
                        <Chip key={i} tone={a.severity === "alta" ? "alert" : "warn"}>
                          {ALERT_LABEL[a.code] ?? a.code}
                        </Chip>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHead
              icon={FileText}
              title="Lectura forense"
              subtitle="Anatomía de la quiebra, escrita por el Cerebro sobre el dato real"
              right={
                <a
                  href={forensicReportUrl(pkg.meta.nombre)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-soft inline-flex items-center gap-1.5 text-sm shrink-0"
                >
                  <ExternalLink size={15} />
                  Ver informe completo
                </a>
              }
            />
            {narrStatus === "loading" && (
              <p className="text-sm text-muted">Generando la lectura forense…</p>
            )}
            {narrStatus === "error" && (
              <p className="text-sm text-muted">No se pudo generar la lectura en este momento.</p>
            )}
            {narrStatus === "ready" && narrative && (
              narrative.degraded || !narrative.narrative ? (
                <p className="text-sm text-muted">
                  La lectura narrativa no está disponible ahora (motor IA sin presupuesto). Los datos
                  y el backtest de arriba son completos; el informe descargable incluye los gráficos.
                </p>
              ) : (
                <div>{renderNarrative(narrative.narrative)}</div>
              )
            )}
          </Card>

          <p className="text-xs text-muted">
            Fuente: Superintendencia de Bancos · Cronología SB (estados financieros mensuales, dato
            real). El capital regulatorio Basilea no existe pre-2004; el apalancamiento
            patrimonio/activos es el proxy. Informe retrospectivo, no una calificación emitida en su
            momento.
          </p>
        </div>
      )}
    </div>
  );
}

export default HistoricoPage;
