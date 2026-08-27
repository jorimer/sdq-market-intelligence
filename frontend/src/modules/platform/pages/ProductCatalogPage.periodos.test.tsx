/**
 * El selector de PERÍODO del catálogo: un corte trimestral no puede anunciarse como el año.
 *
 * **El defecto.** El corte de diciembre se rotulaba «2025-12-31 · cierre anual 2025». Leído
 * desde la pantalla, el cuarto trimestre había DESAPARECIDO: en su lugar aparecía un informe
 * anual que ese corte no entrega. El dueño lo describió exacto — «era agregar el anual, no
 * sustituir el último cuarto por el anual».
 *
 * **Por qué el rótulo era falso.** La ventana móvil de doce meses toca UNA magnitud —la
 * utilidad neta, o sea ROA y ROE—; los otros diecinueve indicadores son fotos al 31 de
 * diciembre y el score es una lectura AL CORTE. El informe de diciembre dice cómo ESTÁ la
 * entidad ese día. Cómo le FUE en el ejercicio lo entrega `banking_year_review`, que es un
 * producto aparte, está en producción y se pide POR AÑO (`2025`), no por fecha.
 *
 * **Por qué es un test de la PANTALLA y no de `cierreDeEjercicio`.** La función seguía siendo
 * correcta —diciembre es diciembre—; lo falso era lo que la pantalla hacía con ella. Un test
 * de la función habría quedado verde con el defecto puesto.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const getProductCatalog = vi.fn();
const getProductPeriods = vi.fn();
const getProductReport = vi.fn();
const getProductScopeOptions = vi.fn();

vi.mock("../api", async (importActual) => ({
  ...(await importActual<typeof import("../api")>()),
  getProductCatalog: () => getProductCatalog(),
  getProductPeriods: (...a: unknown[]) => getProductPeriods(...a),
  getProductReport: (...a: unknown[]) => getProductReport(...a),
  getProductScopeOptions: (...a: unknown[]) => getProductScopeOptions(...a),
  downloadProductReport: vi.fn(),
  downloadProductSample: vi.fn(),
}));

vi.mock("@/shared/context/AppContext", () => ({
  useApp: () => ({ period: "2026-Q1" }),
  periodToDate: () => "2026-03-31",
}));

import "@/shared/i18n/config"; // i18n real: se afirma contra el texto que ve el usuario
import { ProductCatalogPage } from "./ProductCatalogPage";

/** Los períodos REALES que producción devuelve para `banking` (producto trimestral). */
const PERIODOS_TRIMESTRALES = [
  "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31",
];
/** Los de `banking_year_review`, el producto anual: AÑOS, no fechas. */
const PERIODOS_ANUALES = ["2025", "2024", "2023"];

const CATALOGO = {
  user_tier: "enterprise",
  sectors: [{
    sector_key: "banking",
    display_name: "SDQ Banking Intelligence",
    levels: [{
      tier: "pulse", unlocked: true, staff_preview: false, required_tier: "free",
      price_band: "abierto", audience: "mercado", sample_available: false,
      requires_scope: false, scope_kind: "entity",
    }],
  }],
};

async function abrirElDrawer(periodos: string[]) {
  getProductCatalog.mockResolvedValue(CATALOGO);
  getProductPeriods.mockResolvedValue(periodos);
  getProductScopeOptions.mockResolvedValue([]);
  getProductReport.mockResolvedValue({
    sector_key: "banking", tier: "pulse", period: periodos[0], entity_name: null,
    payload: {}, narratives: {},
    commercial: { price_band: null, watermark: null, audience: "mercado",
                  cadence: "periodic", sections: [], staff_preview: false },
  });
  render(<ProductCatalogPage />);
  const ver = await screen.findAllByRole("button", { name: /ver/i });
  await userEvent.click(ver[0]);
  return await screen.findByRole("combobox");
}

describe("el selector de período del catálogo", () => {
  beforeEach(() => vi.clearAllMocks());

  it("rotula CADA corte por su fecha — diciembre incluido", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    const rotulos = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(rotulos).toEqual(PERIODOS_TRIMESTRALES);
  });

  it("ningún corte se anuncia como el informe del año", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    for (const opcion of within(select).getAllByRole("option")) {
      expect(opcion.textContent).not.toMatch(/anual|annual|annuelle/i);
    }
  });

  it("al elegir diciembre, OFRECE el producto anual en vez de fingir serlo", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    await userEvent.selectOptions(select, "2025-12-31");
    const aviso = await screen.findByText(/Revisión Anual, un producto aparte/i);
    // Dice las dos cosas: qué ES este informe y dónde está el año. Un aviso que solo
    // nombrara el otro producto dejaría creyendo que este corte no sirve para nada.
    expect(aviso.textContent).toMatch(/31 de diciembre de 2025/);
  });

  it("en un corte que NO es diciembre no aparece el aviso", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    await userEvent.selectOptions(select, "2025-09-30");
    await waitFor(() => expect(screen.queryByText(/Revisión Anual, un producto aparte/i))
      .not.toBeInTheDocument());
  });

  it("dentro del producto ANUAL el aviso no aparece: mandaría al lector donde ya está", async () => {
    // Sus períodos son AÑOS (`2025`), no fechas, así que la condición no puede dispararse.
    // Se afirma acá para que un cambio futuro a períodos con fecha rompa este test y no la
    // pantalla.
    const select = await abrirElDrawer(PERIODOS_ANUALES);
    expect(within(select).getAllByRole("option").map((o) => o.textContent))
      .toEqual(PERIODOS_ANUALES);
    expect(screen.queryByText(/producto aparte/i)).not.toBeInTheDocument();
  });
});
