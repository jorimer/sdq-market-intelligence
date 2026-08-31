import { useState } from "react";
import {
  ScanSearch,
  FileText,
  FileType2,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  CircleDashed,
} from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock } from "@/shared/ui/primitives";
import { Markdown } from "@/shared/ui/Markdown";
import type { Tone } from "@/shared/lib/bands";
import {
  runResearch,
  downloadResearchDeliverable,
  type ResearchAnswer,
  type ResearchSubQuestion,
  type AnchorState,
} from "../api";

/* ──────────────────────────────────────────────────────────────────
 * Research a Medida — motor de pregunta libre con procedencia honesta.
 * El comprador escribe una pregunta; el motor la descompone, ancla cada
 * sub-afirmación a dato real / rúbrica declarada / brecha, y decide si
 * entrega un informe completo o un scoping report (gate de honestidad).
 * Docs: docs/SPEC_MOTOR_RESEARCH_CUSTOM.md.
 * ────────────────────────────────────────────────────────────────── */

const STATE_META: Record<
  AnchorState,
  { label: string; tone: Tone; icon: typeof CheckCircle2; iconClass: string }
> = {
  real: { label: "Dato real", tone: "ok", icon: CheckCircle2, iconClass: "text-ok" },
  rubric: { label: "Rúbrica declarada", tone: "warn", icon: AlertCircle, iconClass: "text-warn" },
  gap: { label: "Brecha", tone: "alert", icon: CircleDashed, iconClass: "text-alert" },
};

const SECTION_TITLES: Record<string, string> = {
  resumen_ejecutivo: "Resumen ejecutivo",
  dictamen: "Dictamen integrado",
  evidencia: "Evidencia por motor",
  respuesta_a_su_pregunta: "Respuesta a su pregunta",
  hallazgos: "Hallazgos",
  metodologia: "Metodología",
  fuentes: "Fuentes",
  limitaciones: "Limitaciones",
  resumen_scoping: "Alcance",
  lo_que_si_se_puede: "Lo que se puede contestar hoy",
  lo_que_no_se_puede: "Lo que no se puede contestar hoy",
  que_cerraria_la_brecha: "Qué cerraría la brecha",
  // secciones profundas (Deep Dive reutilizado)
  executive_summary: "Resumen ejecutivo",
  solidez_financiera: "Solidez financiera",
  calidad_activos: "Calidad de activos",
  eficiencia_rentabilidad: "Eficiencia y rentabilidad",
  liquidez: "Liquidez",
  diversificacion: "Diversificación",
  comparative: "Posición vs pares",
  entorno_operativo: "Entorno operativo",
  mapa_sectorial: "Mapa sectorial del crédito",
  mapa_sectorial_sistema: "El crédito del sistema por sector",
  soporte_soberano: "Soporte y techo soberano",
  risk_assessment: "Evaluación de riesgo",
  early_warning: "Alerta temprana",
  recommendation: "Recomendaciones",
  limitations: "Limitaciones",
  std_methodology: "Metodología y fuentes",
  std_sources: "Fuentes y referencias",
};

function titleFor(key: string): string {
  return SECTION_TITLES[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const EXAMPLES = [
  "¿Qué tan atractivo es el sector energía para invertir y cómo mide SDQ la resiliencia energética?",
  "¿Cómo distingue el estándar de reporte de SDQ el dato real de la rúbrica declarada?",
  "¿Qué riesgo regulatorio y de gobernanza enfrenta el sector de zonas francas?",
];

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

function SubQuestionRow({ sq }: { sq: ResearchSubQuestion }) {
  const meta = STATE_META[sq.state];
  const Icon = meta.icon;
  return (
    <div className="border border-line rounded-lg p-3">
      <div className="flex items-start gap-2">
        <Icon size={18} className={`mt-0.5 shrink-0 ${meta.iconClass}`} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{sq.text}</p>
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            <Chip tone={meta.tone}>{meta.label}</Chip>
            {sq.axes.map((a) => (
              <Chip key={a} tone="muted">
                {a}
              </Chip>
            ))}
          </div>
          {sq.note && <p className="text-xs text-muted mt-1.5">{sq.note}</p>}
          {sq.evidence.length > 0 && (
            <ul className="mt-2 space-y-1">
              {sq.evidence.slice(0, 3).map((e, i) => (
                <li key={i} className="text-xs text-muted">
                  <span className="font-medium text-ink">{e.source}</span> — {e.text.slice(0, 160)}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<ResearchAnswer | null>(null);
  const [downloading, setDownloading] = useState<"pdf" | "docx" | null>(null);

  const run = async () => {
    if (question.trim().length < 5) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await runResearch(question.trim()));
    } catch {
      setError("No se pudo generar la respuesta. Reintentá en unos segundos.");
    } finally {
      setLoading(false);
    }
  };

  const download = async (fmt: "pdf" | "docx") => {
    if (!answer) return;
    setDownloading(fmt);
    try {
      await downloadResearchDeliverable(answer.question, fmt);
    } catch {
      setError("No se pudo descargar el entregable.");
    } finally {
      setDownloading(null);
    }
  };

  const isScoping = answer?.gate === "scoping";
  const order = answer?.section_order?.length
    ? answer.section_order
    : Object.keys(answer?.sections ?? {});

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Herramientas"
        title="Research a Medida"
        sub="Pregunta libre con procedencia honesta: cada afirmación ancla a dato real, rúbrica declarada o brecha — nunca se rellena."
      />

      <Card>
        <CardHead icon={ScanSearch} title="Tu pregunta" subtitle="Formulá una consulta de investigación; el motor la descompone y la ancla a evidencia." />
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run();
          }}
          rows={3}
          placeholder="Ej.: ¿Qué tan atractivo es el sector energía para invertir y cómo mide SDQ la resiliencia energética?"
          className="field w-full resize-y text-sm"
        />
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <button
            onClick={run}
            disabled={loading || question.trim().length < 5}
            className="btn btn-primary"
          >
            <Sparkles size={16} />
            {loading ? "Generando…" : "Generar"}
          </button>
          <span className="text-xs text-muted">⌘/Ctrl + Enter</span>
        </div>
        {!answer && !loading && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setQuestion(ex)}
                className="text-xs text-muted hover:text-ink border border-line rounded-full px-2.5 py-1"
              >
                {ex.length > 60 ? ex.slice(0, 57) + "…" : ex}
              </button>
            ))}
          </div>
        )}
      </Card>

      {loading && <StateBlock kind="loading" message="Descomponiendo la pregunta y recuperando evidencia con procedencia…" />}
      {error && <StateBlock kind="error" message={error} />}

      {answer && !loading && (
        <>
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Chip tone={isScoping ? "warn" : "ok"}>
                  {isScoping ? "Scoping report" : "Informe completo"}
                </Chip>
                <span className="text-sm text-muted">
                  {pct(answer.coverage_real)} dato real · {pct(answer.anchored_fraction)} con ancla
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Chip tone="ok">{answer.state_counts.real} reales</Chip>
                <Chip tone="warn">{answer.state_counts.rubric} rúbrica</Chip>
                <Chip tone="alert">{answer.state_counts.gap} brecha</Chip>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => download("pdf")}
                  disabled={downloading !== null}
                  className="btn btn-ghost"
                >
                  <FileText size={15} />
                  {downloading === "pdf" ? "…" : "PDF"}
                </button>
                <button
                  onClick={() => download("docx")}
                  disabled={downloading !== null}
                  className="btn btn-ghost"
                >
                  <FileType2 size={15} />
                  {downloading === "docx" ? "…" : "Word"}
                </button>
              </div>
            </div>
            {isScoping && (
              <p className="text-xs text-muted mt-2">
                La cobertura con ancla está por debajo del umbral: en vez de un informe con apariencia de completo,
                SDQ entrega el alcance honesto de qué se puede y no contestar hoy.
              </p>
            )}
          </Card>

          <Card>
            <CardHead icon={ScanSearch} title="Líneas de análisis" subtitle="Cada sub-pregunta y su ancla de evidencia." />
            <div className="space-y-2">
              {answer.sub_questions.map((sq, i) => (
                <SubQuestionRow key={i} sq={sq} />
              ))}
            </div>
          </Card>

          {order
            .filter((k) => answer.sections[k])
            .map((k) => (
              <Card key={k}>
                <CardHead icon={FileText} title={titleFor(k)} />
                <Markdown text={answer.sections[k]} />
              </Card>
            ))}
        </>
      )}
    </div>
  );
}
