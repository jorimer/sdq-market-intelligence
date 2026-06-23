import { useTranslation } from "react-i18next";
import { Maximize2, Minimize2 } from "lucide-react";

/** "Ver análisis completo" ↔ "Ver versión breve" toggle for a cerebro insight.
 * The extended version requests ~700-1000 words (vs the focused brief default). */
export function DeepToggle({ deep, onToggle, disabled }: {
  deep: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const label = deep ? t("widgets.insightBrief") : t("widgets.insightFull");
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      title={label}
      className="inline-flex items-center gap-1.5 text-xs text-accent-ink hover:underline disabled:opacity-50 disabled:no-underline"
    >
      {deep ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
      {label}
    </button>
  );
}
