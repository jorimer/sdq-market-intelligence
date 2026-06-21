import { useEffect, useState } from "react";
import {
  BookOpen,
  Layers,
  Database,
  ShieldCheck,
  Scale,
  Sparkles,
  AlertTriangle,
} from "lucide-react";
import client from "@/shared/api/client";
import {
  PageHead,
  Card,
  CardHead,
  Chip,
  StateBlock,
  Skeleton,
} from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";

/* ──────────────────────────────────────────────────────────────────
 * Metodología — documento vivo de doctrina de SDQ·MIP.
 * Contenido fiel (marco de gates, fuentes, doctrina anti-fabricación,
 * SCQA) + cifras reales tiradas de endpoints existentes (pesos,
 * backtests). Cero fabricación: lo que no está calculado se declara,
 * no se inventa.
 * ────────────────────────────────────────────────────────────────── */

/* ── 1 · Marco de gates A–F (fuente: PLAN_MAESTRO §2) ─────────────── */
const GATES: { letter: string; title: string; desc: string }[] = [
  { letter: "A", title: "Integridad de fuente", desc: "Conector live, replicable por período y validado contra el portal oficial del emisor." },
  { letter: "B", title: "Prueba de la data cruda", desc: "Tests automáticos + verificación humana de cifras contra la fuente. La data se prueba, no se asume." },
  { letter: "C", title: "Analytics + score", desc: "Features e índice del eje, explicable y modelable: todo score se reconstruye desde sus componentes." },
  { letter: "D", title: "Insight de IA por página", desc: "Narrativa SCQA generada con Claude real. Una página sin insight no se considera terminada." },
  { letter: "E", title: "Backtest / validación", desc: "Score validado contra outcomes realizados. Sin esto, un score nunca se comunica como predictivo." },
  { letter: "F", title: "Operabilidad", desc: "Toda operación recurrente vive en la UI, monitoreada y agendable. Transversal a todos los gates." },
];

/* ── 2 · Fuentes y madurez por eje (ground truth, §1) ────────────── */
type DataKind = "real" | "mixed" | "monitor";
const AXES: { n: number; name: string; index: string; source: string; kind: DataKind }[] = [
  { n: 1, name: "Financiero", index: "Rating bancario (10 tiers)", source: "SIB / SIMBAD + OCR fiduciarias y cambiarias", kind: "real" },
  { n: 2, name: "Macro & fiscal", index: "Pulso macro-fiscal", source: "BCRD (API + Excel histórico) · Hacienda · DGII", kind: "monitor" },
  { n: 3, name: "Sectorial", index: "IAI · SGPS", source: "BCRD valor agregado · ENCFT empleo · TSS salario", kind: "mixed" },
  { n: 4, name: "Regulatorio & político", index: "IRMP", source: "WGI · WDI · IMF · GDELT (BigQuery)", kind: "real" },
  { n: 5, name: "Comercio", index: "Resiliencia comercial", source: "DGA aduanas · UN Comtrade", kind: "real" },
  { n: 6, name: "Social", index: "IDM", source: "ONE (pobreza · IDM · educación) · BCRD", kind: "mixed" },
  { n: 7, name: "ESG & clima", index: "IRC", source: "ND-GAIN · HURDAT2 · Ember", kind: "real" },
];

function DataBadge({ kind }: { kind: DataKind }) {
  if (kind === "real") return <Chip tone="ok">Dato real</Chip>;
  if (kind === "monitor") return <Chip tone="accent">Monitor</Chip>;
  return <Chip tone="warn">Real + rúbrica</Chip>;
}

/* ── Helpers de backtest ─────────────────────────────────────────── */
type CI = [number | null, number | null] | null | undefined;

/** Una señal es "significativa" solo si su IC bootstrap excluye el cero. */
function ciExcludesZero(ci: CI): boolean {
  if (!ci || ci[0] == null || ci[1] == null) return false;
  return (ci[0] > 0 && ci[1] > 0) || (ci[0] < 0 && ci[1] < 0);
}
function fmtCI(ci: CI, digits = 2): string {
  if (!ci || ci[0] == null || ci[1] == null) return "—";
  return `${fmtNum(ci[0], digits)} … ${fmtNum(ci[1], digits)}`;
}

interface VRow {
  axis: string;
  source: string;
  metric: string;
  value: string;
  ci: string;
  n: string;
  sig: boolean | null; // null → no calculado / no aplica
  verdict: string;
}

function notCalc(base: Pick<VRow, "axis" | "source" | "metric">): VRow {
  return { ...base, value: "—", ci: "—", n: "—", sig: null, verdict: "Sin calcular" };
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function mapBanking(d: any): VRow {
  const base = { axis: "Financiero", source: "SIB · rating", metric: "Gini · discriminación de distress" };
  if (!d || !d.computed || d.ok === false || d.gini == null) return notCalc(base);
  const sig = ciExcludesZero(d.gini_ci);
  return { ...base, value: fmtNum(d.gini, 3), ci: fmtCI(d.gini_ci), n: `${fmtNum(d.n_observations, 0)} obs · ${d.n_events} eventos`, sig, verdict: sig ? "Significativo" : "Direccional" };
}
function mapIrmp(d: any): VRow {
  const base = { axis: "Regulatorio & político", source: "WGI · IRMP", metric: "Gini · inestabilidad realizada" };
  const g = d?.governance;
  if (!d?.has_report || !g || g.gini == null) return notCalc(base);
  const sig = ciExcludesZero(g.gini_ci);
  return { ...base, value: fmtNum(g.gini, 3), ci: fmtCI(g.gini_ci), n: `${fmtNum(g.n_observations, 0)} obs · ${d.n_countries ?? "—"} países`, sig, verdict: sig ? "Significativo" : "Direccional" };
}
function mapSector(d: any): VRow {
  const base = { axis: "Sectorial", source: "ONE/BCRD · IAI", metric: "IC medio (IAI → empleo T+1)" };
  if (!d?.has_report || d?.has_data === false || d?.mean_yearly_ic == null) return notCalc(base);
  const sig = ciExcludesZero(d.ic_ci);
  return { ...base, value: fmtNum(d.mean_yearly_ic, 2), ci: fmtCI(d.ic_ci), n: `${fmtNum(d.n_observations, 0)} obs · ${d.n_years ?? "—"} años`, sig, verdict: sig ? "Significativo" : "Inconclusivo por potencia" };
}
function mapSocial(d: any): VRow {
  const base = { axis: "Social", source: "ONE · IDM", metric: "ρ convergente (IDM vs IDH regional)" };
  if (!d || d.spearman == null) return notCalc(base);
  const sig = ciExcludesZero(d.spearman_ci);
  return { ...base, value: fmtNum(d.spearman, 2), ci: fmtCI(d.spearman_ci), n: `${d.n_regions ?? "—"} regiones`, sig, verdict: sig ? "Significativo" : "Direccional" };
}
function mapTrade(d: any): VRow {
  const base = { axis: "Comercio", source: "DGA/Comtrade · resiliencia", metric: "Gini · colapso exportador" };
  const ec = d?.export_collapse;
  if (!d?.has_report || !ec || ec.gini == null) return notCalc(base);
  const sig = ciExcludesZero(ec.gini_ci);
  return { ...base, value: fmtNum(ec.gini, 3), ci: fmtCI(ec.gini_ci), n: `${fmtNum(ec.n_observations, 0)} obs · ${d.n_countries ?? "—"} países`, sig, verdict: sig ? "Significativo" : "Direccional" };
}
function mapEsg(d: any): VRow {
  const base = { axis: "ESG & clima", source: "ND-GAIN · IRC", metric: "ρ · mortalidad climática" };
  if (!d?.computed || d.spearman == null) return notCalc(base);
  const sig = ciExcludesZero(d.spearman_ci);
  return { ...base, value: fmtNum(d.spearman, 2), ci: fmtCI(d.spearman_ci), n: `${d.n_countries ?? "—"} países`, sig, verdict: sig ? "Significativo" : "Direccional" };
}
/* eslint-enable @typescript-eslint/no-explicit-any */

const MACRO_ROW: VRow = {
  axis: "Macro & fiscal",
  source: "BCRD · monitor",
  metric: "Monitor de pulso (sin score predictivo)",
  value: "—",
  ci: "—",
  n: "—",
  sig: null,
  verdict: "n/a · monitor",
};

function VerdictChip({ sig, label }: { sig: boolean | null; label: string }) {
  const tone = sig === true ? "ok" : sig === false ? "warn" : "muted";
  return <Chip tone={tone}>{label}</Chip>;
}

/* ── 3 · Digest de validación (backtest honesto) ─────────────────── */
function ValidationDigest() {
  const [rows, setRows] = useState<VRow[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    Promise.allSettled([
      client.get("/banking-score/validation/backtest"),
      client.get("/macro-political-risk/validation/backtest"),
      client.get("/sector-intel/validation"),
      client.get("/social-dev/validation/convergent"),
      client.get("/trade-intel/validation/backtest"),
      client.get("/esg-climate/backtest"),
    ])
      .then(([bank, irmp, sector, social, trade, esg]) => {
        const get = (r: PromiseSettledResult<{ data: unknown }>) =>
          r.status === "fulfilled" ? r.value.data : null;
        const out: VRow[] = [
          mapBanking(get(bank)),
          MACRO_ROW,
          mapSector(get(sector)),
          mapIrmp(get(irmp)),
          mapTrade(get(trade)),
          mapSocial(get(social)),
          mapEsg(get(esg)),
        ];
        setRows(out);
        // Solo es error si TODO falló (ninguna llamada resolvió).
        const anyOk = [bank, irmp, sector, social, trade, esg].some((r) => r.status === "fulfilled");
        setStatus(anyOk ? "ready" : "error");
      })
      .catch(() => setStatus("error"));
  }, []);

  return (
    <Card>
      <CardHead
        icon={ShieldCheck}
        title="Validación honesta — backtest por eje"
        subtitle="Cada score se valida contra outcomes realizados (Gate E). Cifras en vivo desde los reportes persistidos."
      />

      <div className="mb-4 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">Validación direccional, no grado-Basilea.</span>{" "}
          Donde el intervalo de confianza <span className="font-medium">cruza el cero</span> lo
          declaramos inconclusivo por potencia (panel pequeño), no como refutación — honestidad
          sobre la fuerza de la señal, nunca maquillaje.
        </p>
      </div>

      {status === "loading" ? (
        <div className="space-y-2">
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
        </div>
      ) : status === "error" ? (
        <StateBlock kind="error" message="No se pudieron cargar los reportes de validación." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-line">
                <th className="py-2 px-2 font-medium">Eje</th>
                <th className="py-2 px-2 font-medium">Métrica titular</th>
                <th className="py-2 px-2 font-medium text-right">Valor</th>
                <th className="py-2 px-2 font-medium text-right">IC 95%</th>
                <th className="py-2 px-2 font-medium">Muestra</th>
                <th className="py-2 px-2 font-medium text-right">Veredicto</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.axis} className="border-b border-line/60 align-top">
                  <td className="py-2.5 px-2">
                    <div className="text-ink font-medium">{r.axis}</div>
                    <div className="text-xs text-faint">{r.source}</div>
                  </td>
                  <td className="py-2.5 px-2 text-body min-w-[10rem]">{r.metric}</td>
                  <td className="py-2.5 px-2 text-right mono text-ink tabular-nums">{r.value}</td>
                  <td className="py-2.5 px-2 text-right mono text-body tabular-nums whitespace-nowrap">{r.ci}</td>
                  <td className="py-2.5 px-2 text-xs text-muted">{r.n}</td>
                  <td className="py-2.5 px-2 text-right">
                    <VerdictChip sig={r.sig} label={r.verdict} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* ── 4 · Pesos por índice (doctrina versionada) ──────────────────── */
interface WeightBlock {
  axis: string;
  direction: string;
  weights: Record<string, number>;
}

function prettify(key: string): string {
  const map: Record<string, string> = {
    solidez: "Solidez", calidad: "Calidad de activos", eficiencia: "Eficiencia",
    liquidez: "Liquidez", diversificacion: "Diversificación",
    macro: "Macroeconómica", external: "Externa", political: "Político-institucional",
    regulatory: "Regulatoria", regulation: "Regulación", events: "Eventos", business: "Negocios",
    talent: "Talento", sector: "Sector", health: "Salud", education: "Educación",
    living_standards: "Nivel de vida", inclusion: "Inclusión",
    physical_risk: "Riesgo físico", transition_risk: "Riesgo de transición",
    adaptive_capacity: "Capacidad de adaptación", governance: "Gobernanza",
    historical: "Histórico", structural: "Estructural", acceleration: "Aceleración",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function WeightCard({ block }: { block: WeightBlock }) {
  const entries = Object.entries(block.weights);
  const total = entries.reduce((s, [, w]) => s + w, 0) || 1;
  return (
    <Card>
      <CardHead icon={BookOpen} title={block.axis} subtitle={block.direction} />
      <div className="space-y-2.5">
        {entries.map(([k, w]) => (
          <div key={k} className="flex items-center gap-3">
            <span className="w-40 shrink-0 text-sm text-ink truncate">{prettify(k)}</span>
            <div className="flex-1 h-2 rounded-full bg-surface2 overflow-hidden">
              <div className="h-full rounded-full bg-accent" style={{ width: `${(w / total) * 100}%` }} />
            </div>
            <span className="shrink-0 mono text-sm font-semibold text-ink w-12 text-right tabular-nums">
              {Math.round(w * 100)}%
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function WeightsSection() {
  const [blocks, setBlocks] = useState<WeightBlock[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    Promise.allSettled([
      client.get("/banking-score/weights"),
      client.get("/macro-political-risk/weights"),
      client.get("/sector-intel/weights"),
      client.get("/social-dev/weights"),
      client.get("/esg-climate/weights"),
    ])
      .then(([bank, irmp, sector, social, esg]) => {
        const out: WeightBlock[] = [];
        if (bank.status === "fulfilled")
          out.push({ axis: "Financiero — sub-componentes", direction: "mayor score = mejor", weights: bank.value.data.weights });
        if (irmp.status === "fulfilled")
          out.push({ axis: "Regulatorio & político — IRMP", direction: irmp.value.data.direction, weights: irmp.value.data.dimension_weights });
        if (sector.status === "fulfilled") {
          out.push({ axis: "Sectorial — IAI", direction: sector.value.data.direction, weights: sector.value.data.iai_dimension_weights });
          out.push({ axis: "Sectorial — SGPS", direction: "potencial de crecimiento", weights: sector.value.data.sgps_weights });
        }
        if (social.status === "fulfilled")
          out.push({ axis: "Social & desarrollo — IDM", direction: social.value.data.direction, weights: social.value.data.dimension_weights });
        if (esg.status === "fulfilled")
          out.push({ axis: "ESG & clima — IRC", direction: esg.value.data.direction, weights: esg.value.data.dimension_weights });
        setBlocks(out);
        setStatus(out.length ? "ready" : "error");
      })
      .catch(() => setStatus("error"));
  }, []);

  if (status === "loading")
    return (
      <div className="grid lg:grid-cols-2 gap-5">
        <Skeleton className="h-56" />
        <Skeleton className="h-56" />
      </div>
    );
  if (status === "error")
    return <StateBlock kind="error" message="No se pudieron cargar las ponderaciones." />;

  return (
    <div className="grid lg:grid-cols-2 gap-5">
      {blocks.map((b) => <WeightCard key={b.axis} block={b} />)}
    </div>
  );
}

/* ── Sección con encabezado de doctrina ──────────────────────────── */
function SectionTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div className="mb-3">
      <h2 className="font-display text-lg font-bold text-ink">{children}</h2>
      {hint && <p className="text-sm text-muted mt-0.5 max-w-2xl">{hint}</p>}
    </div>
  );
}

/* ── Página ──────────────────────────────────────────────────────── */
export function MetodologiaPage() {
  return (
    <div className="space-y-10">
      <PageHead
        eyebrow="Doctrina de casa"
        title="Metodología"
        sub="Cómo se construye cada índice de SDQ·MIP: el ciclo de gates, las fuentes reales por eje, la validación honesta de cada score y la doctrina anti-fabricación que las sostiene. Todo score se reconstruye desde aquí."
      />

      {/* 1 · Marco de gates A–F */}
      <section>
        <SectionTitle hint="Cada eje recorre cinco gates en orden (A→E), con la operabilidad (F) transversal. Ningún gate se salta: define el Definition of Done parcial.">
          Marco de construcción — gates A–F
        </SectionTitle>
        <Card>
          <div className="grid md:grid-cols-2 gap-x-8 gap-y-4">
            {GATES.map((g) => (
              <div key={g.letter} className="flex items-start gap-3">
                <span className="shrink-0 grid place-items-center w-8 h-8 rounded-[9px] bg-accent-soft text-accent-ink font-display font-bold text-sm">
                  {g.letter}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-ink">{g.title}</div>
                  <p className="text-xs text-muted mt-0.5">{g.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </section>

      {/* 2 · Doctrina anti-fabricación */}
      <section>
        <SectionTitle hint="El diferenciador metodológico de SDQ: ninguna cifra se inventa. Es simétrico en ambas direcciones.">
          Doctrina anti-fabricación
        </SectionTitle>
        <div className="grid lg:grid-cols-2 gap-5">
          <Card>
            <CardHead icon={Scale} title="Dato real o rúbrica declarada — nunca inventar" />
            <p className="text-sm text-body">
              Toda cifra que se muestra es <span className="font-medium text-ink">dato real medido</span> de
              una fuente oficial, o un valor de <span className="font-medium text-ink">rúbrica declarada</span> con
              su badge visible. No hay tercer estado: un hueco de dato se rotula{" "}
              <span className="mono text-xs">N/D</span>, no se rellena con una estimación que parezca dato.
            </p>
            <ul className="mt-3 space-y-1.5 text-sm text-body list-disc pl-4">
              <li>Un score sin backtest <span className="font-medium">no se comunica como predictivo</span>.</li>
              <li>Cada sub-componente de rúbrica lleva su badge en la pantalla del eje.</li>
              <li>Los intervalos de confianza se reportan tal cual: si cruzan el cero, se dice.</li>
            </ul>
          </Card>
          <Card>
            <CardHead icon={ShieldCheck} title="Guarda anti-falsa-imposibilidad" />
            <p className="text-sm text-body">
              Un <span className="italic">“no se puede” / “no existe el dato”</span> es una afirmación
              que debe ganar su barra de evidencia, exactamente como un dato. Es el simétrico de la
              regla anterior: <span className="font-medium text-ink">dato alegado como inexistente = sospechoso</span>.
            </p>
            <p className="mt-3 text-sm text-body">
              Antes de declarar una imposibilidad se agota el catálogo completo de la fuente, las
              consultas acotadas, los portales alternativos del mismo emisor y lo que ya se está
              trayendo. Una reducción de alcance por imposibilidad no se decide en silencio: se
              surfacea con el rastro de búsqueda.
            </p>
          </Card>
        </div>
      </section>

      {/* 3 · Fuentes y madurez por eje */}
      <section>
        <SectionTitle hint="Lo que alimenta cada índice hoy en producción. El badge distingue dato real medido de los índices con sub-componentes en rúbrica declarada.">
          Fuentes reales por eje
        </SectionTitle>
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-2 font-medium w-10">#</th>
                  <th className="py-2 px-2 font-medium">Eje</th>
                  <th className="py-2 px-2 font-medium">Índice</th>
                  <th className="py-2 px-2 font-medium">Fuente live</th>
                  <th className="py-2 px-2 font-medium text-right">Dato</th>
                </tr>
              </thead>
              <tbody>
                {AXES.map((a) => (
                  <tr key={a.n} className="border-b border-line/60">
                    <td className="py-2.5 px-2 mono text-faint tabular-nums">{a.n}</td>
                    <td className="py-2.5 px-2 text-ink font-medium">{a.name}</td>
                    <td className="py-2.5 px-2 text-body">{a.index}</td>
                    <td className="py-2.5 px-2 text-xs text-muted">{a.source}</td>
                    <td className="py-2.5 px-2 text-right"><DataBadge kind={a.kind} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-start gap-2 text-xs text-faint">
            <Database className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <p>
              <span className="font-medium text-muted">Real + rúbrica:</span> el grueso es dato real
              medido; los sub-componentes sin fuente viva (inclusión financiera en Social; negocios y
              talento en el IAI sectorial) usan rúbrica declarada, señalada en cada pantalla.{" "}
              <span className="font-medium text-muted">Monitor:</span> el eje macro-fiscal vigila el
              pulso del país; no emite un score predictivo, por eso no lleva backtest.
            </p>
          </div>
        </Card>
      </section>

      {/* 4 · Validación honesta */}
      <section>
        <SectionTitle hint="Gate E: la prueba de que el score discrimina outcomes reales. Tirado en vivo de los reportes de backtest persistidos de cada eje.">
          Validación — backtest por eje
        </SectionTitle>
        <ValidationDigest />
      </section>

      {/* 5 · Pesos por índice */}
      <section>
        <SectionTitle hint="La transparencia de pesos sostiene la explicabilidad: todo score se reconstruye desde estas ponderaciones, versionadas en doctrina.">
          Ponderaciones por índice
        </SectionTitle>
        <WeightsSection />
      </section>

      {/* 6 · Insight IA / SCQA */}
      <section>
        <SectionTitle hint="La capa narrativa: cada eje con dato real explica su lectura con Claude, bajo un marco fijo.">
          Insight de IA — marco SCQA
        </SectionTitle>
        <Card>
          <CardHead
            icon={Sparkles}
            title="Narrativa explicable, no opinión de caja negra"
            subtitle="Situación · Complicación · Pregunta · Respuesta — el insight se ancla en las cifras del eje, no las reemplaza."
          />
          <div className="grid md:grid-cols-2 gap-x-8 gap-y-3 text-sm text-body">
            <p>
              Cada pantalla de eje con dato real genera su insight con <span className="font-medium text-ink">Claude
              real</span> bajo el patrón <span className="mono text-xs">SCQA</span>: parte del estado
              observado, nombra la tensión, plantea la pregunta de decisión y responde con una lectura
              accionable — siempre referida a las cifras visibles en la página.
            </p>
            <p>
              El patrón es de <span className="font-medium text-ink">dos fases</span>: primero se
              renderiza el dato (cifras, desglose, backtest); el insight se pide por separado y nunca
              bloquea la lectura. Si la IA no está disponible, la página sigue siendo completa con su
              dato. La narrativa enriquece; el dato manda.
            </p>
          </div>
        </Card>
      </section>
    </div>
  );
}
