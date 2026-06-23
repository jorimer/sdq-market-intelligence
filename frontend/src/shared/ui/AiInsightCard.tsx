import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles, type LucideIcon } from "lucide-react";
import { Card, CardHead } from "@/shared/ui/primitives";
import { AiInsightBody } from "@/shared/ui/AiInsightBody";
import { DeepToggle } from "@/shared/ui/DeepToggle";
import type { AiInsight } from "@/shared/ui/insight-types";

interface Props {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  /** Changing this string re-runs the fetch (e.g. the compared entity ids). */
  depsKey: string;
  fetcher: () => Promise<AiInsight | null>;
  /** Opt-in extended "full analysis" version. When provided, a "Ver análisis
   * completo" toggle appears; the deep call requests ~700-1000 words. Both the
   * brief and the deep result are cached, so toggling back and forth is instant.
   * Omit on non-cerebro cards (comparative/scenario) — they have no deep mode. */
  deepFetcher?: (deep: boolean) => Promise<AiInsight | null>;
  /** Optional header-right slot (e.g. an audience selector). */
  actions?: ReactNode;
}

/** Card that loads a contextual AI insight (comparative / sector / scenario),
 * showing a "Generando…" state while Claude responds (~10-15s) then the markdown. */
export function AiInsightCard({ title, subtitle, icon = Sparkles, depsKey, fetcher, deepFetcher, actions }: Props) {
  const { t } = useTranslation();
  const [ai, setAi] = useState<AiInsight | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [deep, setDeep] = useState(false);
  // Cache by depth so toggling brief↔completo doesn't refetch.
  const cache = useRef<Record<string, AiInsight | null>>({});
  const fns = useRef({ fetcher, deepFetcher });
  fns.current = { fetcher, deepFetcher };

  // New entity / deps → drop the cache and fall back to the brief version.
  useEffect(() => {
    cache.current = {};
    setDeep(false);
  }, [depsKey]);

  useEffect(() => {
    let active = true;
    const key = deep ? "deep" : "short";
    if (key in cache.current) {
      setAi(cache.current[key]);
      setLoading(false);
      setError(false);
      return;
    }
    setLoading(true);
    setError(false);
    setAi(null);
    const run = deep && fns.current.deepFetcher
      ? fns.current.deepFetcher(true)
      : fns.current.fetcher();
    run
      .then((r) => {
        if (!active) return;
        cache.current[key] = r;
        setAi(r);
      })
      .catch(() => active && setError(true))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [depsKey, deep]);

  const depthToggle = deepFetcher
    ? <DeepToggle deep={deep} onToggle={() => setDeep((d) => !d)} disabled={loading} />
    : null;

  const right = (actions || depthToggle)
    ? <div className="flex items-center gap-3">{actions}{depthToggle}</div>
    : undefined;

  return (
    <Card>
      <CardHead icon={icon} title={title} subtitle={subtitle} right={right} />
      <AiInsightBody
        loading={loading}
        error={error}
        ai={ai}
        unavailableHint={t("widgets.aiUnavailable")}
      />
    </Card>
  );
}
