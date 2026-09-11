import i18next from "i18next";
import { describe, expect, it } from "vitest";
import { sectionTitle } from "./sectionTitle";

type Catalogo = { section: Record<string, string>; sectionBySector?: Record<string, Record<string, string>> };

const ES: Catalogo = {
  section: { recommendation: "Lectura para decisión", limitations: "Limitaciones" },
  sectionBySector: { banking: { recommendation: "Recomendación" } },
};
const EN: Catalogo = {
  section: { recommendation: "Reading for decision-making", limitations: "Limitations" },
  sectionBySector: { banking: { recommendation: "Recommendation" } },
};

/** Un i18next aislado, con el mismo `fallbackLng` que la app. */
async function traductor(lng: string, en: Catalogo = EN) {
  return i18next.createInstance().init({
    lng,
    fallbackLng: "es",
    resources: {
      es: { translation: { platform: { catalog: ES } } },
      en: { translation: { platform: { catalog: en } } },
    },
  });
}

describe("sectionTitle", () => {
  it("la entrada del eje gana a la general", async () => {
    expect(sectionTitle(await traductor("es"), "banking", "recommendation")).toBe("Recomendación");
  });

  it("un eje sin entrada propia no hereda la de otro: usa la general", async () => {
    expect(sectionTitle(await traductor("es"), "insurance", "recommendation")).toBe(
      "Lectura para decisión",
    );
  });

  it("resuelve en el idioma pedido, y sin entrada del eje cae a la general", async () => {
    const t = await traductor("en");
    expect(sectionTitle(t, "banking", "recommendation")).toBe("Recommendation");
    expect(sectionTitle(t, "banking", "limitations")).toBe("Limitations");
  });

  it("sin ninguna entrada, la clave con espacios", async () => {
    expect(sectionTitle(await traductor("es"), "banking", "delta_mensual")).toBe("delta mensual");
  });

  it("una entrada del eje que falta en inglés cae al ESPAÑOL, no a la general inglesa", async () => {
    // Por esto el guard de Python exige las entradas por eje en los TRES idiomas: con
    // `fallbackLng: "es"`, omitir una en `en.json` no da el título general en inglés.
    const t = await traductor("en", { section: EN.section });
    expect(sectionTitle(t, "banking", "recommendation")).toBe("Recomendación");
  });
});
