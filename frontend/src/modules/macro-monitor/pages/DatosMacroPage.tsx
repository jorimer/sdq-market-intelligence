import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { PageHead, Tabs } from "@/shared/ui/primitives";
import { MacroApiSection } from "../components/MacroApiSection";
import { MacroExcelSection } from "../components/MacroExcelSection";
import { PublicationsSection } from "@/modules/publications/components/PublicationsSection";

const STORAGE_KEY = "datos-macro-tab";

/** Datos · Macroeconómico (BCRD) — the single operational console for the BCRD
 * source: live API series, the AI-native Excel history engine, and the official
 * publications (PDF → AI digest). */
export function DatosMacroPage() {
  const { t } = useTranslation();
  const TABS = [
    { id: "api", label: t("datos.macro.tabApi") },
    { id: "excel", label: t("datos.macro.tabExcel") },
    { id: "publicaciones", label: t("datos.macro.tabPublications") },
  ];
  const [params, setParams] = useSearchParams();
  const initial =
    params.get("tab") || localStorage.getItem(STORAGE_KEY) || "api";
  const [tab, setTab] = useState(TABS.some((tb) => tb.id === initial) ? initial : "api");

  const change = (id: string) => {
    setTab(id);
    localStorage.setItem(STORAGE_KEY, id);
    setParams((p) => {
      p.set("tab", id);
      return p;
    });
  };

  return (
    <div>
      <PageHead
        eyebrow={t("datos.macro.eyebrow")}
        title={t("datos.macro.title")}
        sub={t("datos.macro.sub")}
      />

      <div className="mb-5">
        <Tabs tabs={TABS} active={tab} onChange={change} />
      </div>

      {tab === "api" && <MacroApiSection />}
      {tab === "excel" && <MacroExcelSection />}
      {tab === "publicaciones" && <PublicationsSection />}
    </div>
  );
}
