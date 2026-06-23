import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
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
  /** Optional header-right slot (e.g. an audience selector). */
  actions?: ReactNode;
}

/** Card that loads a contextual AI insight (comparative / sector / scenario),
 * showing a "Generando…" state while Claude responds (~10-15s) then the markdown. */
export function AiInsightCard({ title, subtitle, icon = Sparkles, depsKey, fetcher, actions }: Props) {
  const { t } = useTranslation();
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
      <CardHead icon={icon} title={title} subtitle={subtitle} right={actions} />
      <AiInsightBody
        loading={loading}
        error={error}
        ai={ai}
        unavailableHint={t("widgets.aiUnavailable")}
      />
    </Card>
  );
}
