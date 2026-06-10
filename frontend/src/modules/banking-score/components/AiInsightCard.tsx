import { useEffect, useRef, useState } from "react";
import { Sparkles, type LucideIcon } from "lucide-react";
import { Card, CardHead, Skeleton, StateBlock } from "@/shared/ui/primitives";
import { Markdown } from "@/shared/ui/Markdown";
import type { AiInsight } from "../api";

interface Props {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  /** Changing this string re-runs the fetch (e.g. the compared entity ids). */
  depsKey: string;
  fetcher: () => Promise<AiInsight | null>;
}

/** Card that loads a contextual AI insight (comparative / sector / scenario),
 * showing a "Generando…" state while Claude responds (~10-15s) then the markdown. */
export function AiInsightCard({ title, subtitle, icon = Sparkles, depsKey, fetcher }: Props) {
  const [ai, setAi] = useState<AiInsight | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    setAi(null);
    fetcherRef.current()
      .then((r) => active && setAi(r))
      .catch(() => active && setError(true))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [depsKey]);

  const unavailable = !ai || ai.model_used === "static_fallback";

  return (
    <Card>
      <CardHead icon={icon} title={title} subtitle={subtitle} />
      {loading ? (
        <div className="space-y-2">
          <p className="text-xs text-muted">Generando análisis de IA… (~10–15s)</p>
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      ) : error ? (
        <StateBlock kind="error" message="No se pudo generar el análisis de IA." />
      ) : unavailable ? (
        <p className="text-sm text-muted leading-relaxed">
          El análisis de IA no está disponible (clave de Anthropic no configurada).
        </p>
      ) : (
        <div>
          <Markdown text={ai!.text} />
          <div className="text-xs text-muted mt-3">
            Generado por IA ({ai!.model_used}){ai!.from_cache ? " · caché" : ""}. Verifica antes de decidir.
          </div>
        </div>
      )}
    </Card>
  );
}
