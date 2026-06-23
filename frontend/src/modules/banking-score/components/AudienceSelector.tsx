import { useTranslation } from "react-i18next";
import { AUDIENCES, type Audience } from "../audience";

interface Props {
  value: Audience;
  onChange: (a: Audience) => void;
}

/** Selector segmentado de audiencia para el insight de IA. Orienta el "y por tanto"
 * (mismos hechos, distinta lectura por audiencia). Compacto, theme-aware vía tokens. */
export function AudienceSelector({ value, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <div
      role="radiogroup"
      aria-label={t("banking.audienceLabel")}
      className="inline-flex flex-wrap gap-1 p-0.5 rounded-lg bg-surface2"
    >
      {AUDIENCES.map((a) => {
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
            {t(`banking.audience.${a}`)}
          </button>
        );
      })}
    </div>
  );
}
