import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import es from "./es.json";
import en from "./en.json";
import fr from "./fr.json";

export const SUPPORTED_LANGS = ["es", "en", "fr"] as const;
export type Lang = (typeof SUPPORTED_LANGS)[number];

const stored = localStorage.getItem("lang");
const initial: Lang = (SUPPORTED_LANGS as readonly string[]).includes(stored ?? "")
  ? (stored as Lang)
  : "es";

i18n.use(initReactI18next).init({
  resources: {
    es: { translation: es },
    en: { translation: en },
    fr: { translation: fr },
  },
  lng: initial,
  fallbackLng: "es",
  supportedLngs: SUPPORTED_LANGS as unknown as string[],
  interpolation: { escapeValue: false },
});

/** Cambia el idioma y lo persiste. */
export function setLanguage(lang: Lang) {
  localStorage.setItem("lang", lang);
  i18n.changeLanguage(lang);
}

export default i18n;
