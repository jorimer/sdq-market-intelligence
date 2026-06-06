import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";
import client from "@/shared/api/client";
import { PageHead, Card, CardHead, StateBlock, LoadingGrid } from "@/shared/ui/primitives";

interface WeightBlock {
  axis: string;
  eyebrow: string;
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
            <span className="shrink-0 mono text-sm font-semibold text-ink w-12 text-right">
              {Math.round(w * 100)}%
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function MetodologiaPage() {
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
          out.push({ axis: "Financiero — sub-componentes", eyebrow: "SIB", direction: "mayor score = mejor", weights: bank.value.data.weights });
        if (irmp.status === "fulfilled")
          out.push({ axis: "Regulatorio & político — IRMP", eyebrow: "WGI", direction: irmp.value.data.direction, weights: irmp.value.data.dimension_weights });
        if (sector.status === "fulfilled") {
          out.push({ axis: "Sectorial — IAI", eyebrow: "ONE", direction: sector.value.data.direction, weights: sector.value.data.iai_dimension_weights });
          out.push({ axis: "Sectorial — SGPS", eyebrow: "ONE", direction: "potencial de crecimiento", weights: sector.value.data.sgps_weights });
        }
        if (social.status === "fulfilled")
          out.push({ axis: "Social & desarrollo — IDM", eyebrow: "ONE", direction: social.value.data.direction, weights: social.value.data.dimension_weights });
        if (esg.status === "fulfilled")
          out.push({ axis: "ESG & clima — IRC", eyebrow: "TCFD/ISSB", direction: esg.value.data.direction, weights: esg.value.data.dimension_weights });
        setBlocks(out);
        setStatus(out.length ? "ready" : "error");
      })
      .catch(() => setStatus("error"));
  }, []);

  const head = (
    <PageHead
      eyebrow="Doctrina de casa"
      title="Metodología"
      sub="Ponderaciones de cada índice, versionadas en doctrina. La transparencia de pesos sostiene la explicabilidad: todo score se reconstruye desde aquí."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return <div>{head}<StateBlock kind="error" message="No se pudieron cargar las ponderaciones." /></div>;

  return (
    <div>
      {head}
      <div className="grid lg:grid-cols-2 gap-5">
        {blocks.map((b) => <WeightCard key={b.axis} block={b} />)}
      </div>
    </div>
  );
}
