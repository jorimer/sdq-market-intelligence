import { useTranslation } from "react-i18next";
import { Languages } from "lucide-react";
import { SUPPORTED_LANGS, setLanguage, type Lang } from "@/shared/i18n/config";

/** Selector de idioma (ES/EN/FR) — persiste en localStorage vía setLanguage. */
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const current = (SUPPORTED_LANGS as readonly string[]).includes(i18n.language)
    ? (i18n.language as Lang)
    : "es";

  return (
    <label className="shrink-0 hidden sm:flex items-center gap-1.5 rounded-[10px] border border-line h-9 px-2 text-muted hover:text-ink transition"
           title={t("lang.label")}>
      <Languages size={14} className="shrink-0" />
      <select
        value={current}
        onChange={(e) => setLanguage(e.target.value as Lang)}
        aria-label={t("lang.label")}
        className="bg-transparent text-xs font-medium outline-none cursor-pointer pr-0.5"
      >
        {SUPPORTED_LANGS.map((l) => (
          <option key={l} value={l}>{t(`lang.${l}`)}</option>
        ))}
      </select>
    </label>
  );
}
