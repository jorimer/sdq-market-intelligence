import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHead, Tabs } from "@/shared/ui/primitives";
import { MacroApiSection } from "../components/MacroApiSection";
import { MacroExcelSection } from "../components/MacroExcelSection";
import { PublicationsSection } from "@/modules/publications/components/PublicationsSection";

const TABS = [
  { id: "api", label: "Series · API" },
  { id: "excel", label: "Histórico · Excel" },
  { id: "publicaciones", label: "Publicaciones" },
];

const STORAGE_KEY = "datos-macro-tab";

/** Datos · Macroeconómico (BCRD) — the single operational console for the BCRD
 * source: live API series, the AI-native Excel history engine, and the official
 * publications (PDF → AI digest). */
export function DatosMacroPage() {
  const [params, setParams] = useSearchParams();
  const initial =
    params.get("tab") || localStorage.getItem(STORAGE_KEY) || "api";
  const [tab, setTab] = useState(TABS.some((t) => t.id === initial) ? initial : "api");

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
        eyebrow="BCRD · Fuente de datos"
        title="Datos · Macroeconómico"
        sub="Consola operativa del Banco Central: series por API, histórico vía Excel (motor AI-native) y publicaciones oficiales."
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
