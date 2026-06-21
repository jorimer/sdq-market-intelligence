import { useTranslation } from "react-i18next";
import { Skeleton, StateBlock } from "@/shared/ui/primitives";
import { Markdown } from "@/shared/ui/Markdown";
import type { AiInsight } from "@/shared/ui/insight-types";

interface Props {
  /** True while the AI insight is being generated (~10-15s). */
  loading: boolean;
  /** Hard error generating the insight (only the standalone card surfaces this). */
  error?: boolean;
  ai: AiInsight | null;
  /** Copy shown when the insight is unavailable (no API key / static fallback). */
  unavailableHint: string;
}

/** Shared body for every AI-insight surface (card + drawer sections): renders the
 * "Generando…" skeleton, the unavailable hint, or the markdown + provenance footer.
 * Pure presentational — fetching/two-phase logic lives in the caller / useTwoPhaseInsight. */
export function AiInsightBody({ loading, error = false, ai, unavailableHint }: Props) {
  const { t } = useTranslation();
  if (loading) {
    return (
      <div className="space-y-2">
        <p className="text-xs text-muted">{t("widgets.aiGenerating")}</p>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    );
  }
  if (error) {
    return <StateBlock kind="error" message={t("widgets.aiError")} />;
  }
  if (!ai || ai.model_used === "static_fallback") {
    return <p className="text-sm text-muted leading-relaxed">{unavailableHint}</p>;
  }
  return (
    <div>
      <Markdown text={ai.text} />
      <div className="text-xs text-muted mt-3">
        {t("widgets.aiByModel", { model: ai.model_used })}
        {ai.from_cache ? ` · ${t("widgets.aiCached")}` : ""}. {t("widgets.aiVerify")}
      </div>
    </div>
  );
}
