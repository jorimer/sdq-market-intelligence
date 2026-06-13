import { useEffect, useState } from "react";
import type { AiInsight } from "@/shared/ui/insight-types";

interface Options<T> {
  /** Pull the AI insight out of a fetched payload (e.g. `d => d.ai_insight`). */
  pickAi: (data: T) => AiInsight | null;
  /** Whether to run phase 2 (AI) after phase 1. Defaults to always. Use to skip
   * the AI round-trip when there is no data to reason about (e.g. indicator N/D). */
  shouldFetchAi?: (data: T) => boolean;
}

interface Result<T> {
  data: T | null;
  ai: AiInsight | null;
  loading: boolean;
  aiLoading: boolean;
  error: boolean;
}

/** Two-phase insight loader, factored out of the banking-score drawers.
 * Phase 1 fetches deterministic data (`withAi=false`) and renders immediately;
 * phase 2 fetches the AI insight (`withAi=true`) in the background (~10-15s) and
 * fills it in. The AI round-trip never blocks or breaks phase 1. */
export function useTwoPhaseInsight<T>(
  fetchFn: (withAi: boolean) => Promise<T>,
  depsKey: string,
  { pickAi, shouldFetchAi }: Options<T>,
): Result<T> {
  const [data, setData] = useState<T | null>(null);
  const [ai, setAi] = useState<AiInsight | null>(null);
  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    setAiLoading(false);
    setData(null);
    setAi(null);
    // Phase 1: fast data (no AI) → render immediately.
    fetchFn(false)
      .then((d) => {
        if (!active) return;
        setData(d);
        setAi(pickAi(d));
        setLoading(false);
        if (shouldFetchAi && !shouldFetchAi(d)) return;
        // Phase 2: AI insight in the background; fill it in when ready.
        setAiLoading(true);
        fetchFn(true)
          .then((full) => active && setAi(pickAi(full)))
          .catch(() => undefined)
          .finally(() => active && setAiLoading(false));
      })
      .catch(() => {
        if (!active) return;
        setError(true);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [depsKey]);

  return { data, ai, loading, aiLoading, error };
}
