import type { TFunction } from "i18next";
import type { DimensionRow } from "@/shared/ui/DimensionBreakdown";

/**
 * Real-vs-rubric provenance tag for one index dimension, from the dataset's
 * sources map. Shared by every axis that anota procedencia por variable
 * (IAI, IDM, IRC): antes vivía copiado en cada página.
 *
 * - todas las variables "live"  → "en vivo" (ok)
 * - ninguna                     → "rúbrica"
 * - mezcla                      → "n/total en vivo" (ok)
 */
export function dimTag(
  sources: Record<string, string> | undefined,
  vars: string[],
  t: TFunction,
): DimensionRow["tag"] {
  if (!sources || vars.length === 0) return undefined;
  const live = vars.filter((v) => sources[v] === "live").length;
  if (live === 0) return { text: t("widgets.tagRubric"), ok: false };
  if (live === vars.length) return { text: t("widgets.tagLive"), ok: true };
  return { text: t("widgets.tagPartialLive", { n: live, total: vars.length }), ok: true };
}
