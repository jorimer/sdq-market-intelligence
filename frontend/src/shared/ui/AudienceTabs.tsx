import { useTranslation } from "react-i18next";

interface Props {
  value: string;
  onChange: (a: string) => void;
  /** Audience keys, in display order (first is the default). */
  options: readonly string[];
  /** i18n key prefix; each option label is `${labelPrefix}.${option}`. */
  labelPrefix: string;
  /** i18n key for the group aria-label. */
  ariaLabelKey?: string;
}

/** Generic segmented audience selector for the Cerebro insight (any axis). Orients the
 * "y por tanto" — same facts, different reading. Theme-aware via tokens. */
export function AudienceTabs({ value, onChange, options, labelPrefix, ariaLabelKey }: Props) {
  const { t } = useTranslation();
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabelKey ? t(ariaLabelKey) : undefined}
      className="inline-flex flex-wrap gap-1 p-0.5 rounded-lg bg-surface2"
    >
      {options.map((a) => {
        const active = a === value;
        return (
          <button
            key={a}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(a)}
            className={
              "px-2.5 py-1 text-xs rounded-md transition-colors " +
              (active
                ? "bg-surface text-ink shadow-sm font-medium"
                : "text-muted hover:text-body")
            }
          >
            {t(`${labelPrefix}.${a}`)}
          </button>
        );
      })}
    </div>
  );
}
