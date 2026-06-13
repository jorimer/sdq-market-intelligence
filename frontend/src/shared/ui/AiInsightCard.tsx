import { useEffect, useRef, useState } from "react";
import { Sparkles, type LucideIcon } from "lucide-react";
import { Card, CardHead } from "@/shared/ui/primitives";
import { AiInsightBody } from "@/shared/ui/AiInsightBody";
import type { AiInsight } from "@/shared/ui/insight-types";

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

  return (
    <Card>
      <CardHead icon={icon} title={title} subtitle={subtitle} />
      <AiInsightBody
        loading={loading}
        error={error}
        ai={ai}
        unavailableHint="El análisis de IA no está disponible (clave de Anthropic no configurada)."
      />
    </Card>
  );
}
