/**
 * El selector de PERÍODO del catálogo: el año Y el cuarto trimestre, los dos.
 *
 * **El defecto, en sus dos formas.** Primero el corte de diciembre se rotulaba «2025-12-31 ·
 * cierre anual 2025»: una sola entrada que prometía el año y entregaba el corte. Al quitar
 * ese rótulo quedó la otra mitad del error — el corte solo, y el año en otra tarjeta del
 * catálogo. El dueño tuvo que decirlo tres veces: **«era agregar el anual, no sustituir el
 * último cuarto por el anual»**.
 *
 * **Por qué son dos y no una.** La ventana móvil de doce meses toca UNA magnitud —la utilidad
 * neta, o sea ROA y ROE—; los otros diecinueve indicadores son fotos al 31 de diciembre y el
 * score es una lectura AL CORTE. Diciembre dice cómo ESTÁ la entidad ese día; cómo le FUE en
 * el ejercicio lo entrega `banking_year_review`, un producto de catálogo con sus propios tres
 * niveles, que se pide POR AÑO.
 *
 * **Por qué es un test de la PANTALLA.** `fusionarPeriodos` tiene su propio test y estaba
 * bien; lo que fallaba era lo que la pantalla hacía con el resultado. Acá se comprueba que
 * elegir el año PIDA el producto anual — no que la lista tenga la forma correcta.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const getProductCatalog = vi.fn();
const getProductPeriods = vi.fn();
const getProductReport = vi.fn();
const getProductScopeOptions = vi.fn();
const descargar = vi.fn();

vi.mock("../api", async (importActual) => ({
  ...(await importActual<typeof import("../api")>()),   // `fusionarPeriodos` es el REAL
  getProductCatalog: () => getProductCatalog(),
  getProductPeriods: (...a: unknown[]) => getProductPeriods(...a),
  getProductReport: (...a: unknown[]) => getProductReport(...a),
  getProductScopeOptions: (...a: unknown[]) => getProductScopeOptions(...a),
  downloadProductReport: (...a: unknown[]) => descargar(...a),
  downloadProductSample: vi.fn(),
}));

vi.mock("@/shared/context/AppContext", () => ({
  useApp: () => ({ period: "2026-Q1" }),
  periodToDate: () => "2026-03-31",
}));

import "@/shared/i18n/config"; // i18n real: se afirma contra el texto que ve el usuario
import { ProductCatalogPage } from "./ProductCatalogPage";

/** Los períodos REALES que producción devuelve para `banking` (producto trimestral). */
/** Afirmar una AUSENCIA sin vaciar antes pasa en el primer intento, antes del `setState`.
 *  Ya me dejó dos tests ciegos en este mismo archivo de al lado. */
const vaciar = () => act(async () => { await Promise.resolve(); });

const PERIODOS_TRIMESTRALES = [
  "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31",
  "2025", "2024",
];
/** Sin años: un producto cuyo calendario son solo cortes. */
const SOLO_CORTES = ["2026-03-31", "2025-12-31", "2025-09-30"];

const NIVEL = {
  tier: "pulse", unlocked: true, staff_preview: false, required_tier: "free",
  price_band: "abierto", audience: "mercado", sample_available: false,
  requires_scope: false, scope_kind: "entity",
};

/** El catálogo REAL: dos productos, y el trimestral declara a su hermano anual. */
const CATALOGO = {
  user_tier: "enterprise",
  sectors: [
    { sector_key: "banking", display_name: "SDQ Banking Intelligence",
      annual_companion: "banking_year_review", levels: [NIVEL] },
    { sector_key: "banking_year_review", display_name: "SDQ Banking · Revisión Anual",
      annual_companion: null, levels: [NIVEL] },
  ],
};

async function abrirElDrawer(periodos: string[]) {
  getProductCatalog.mockResolvedValue(CATALOGO);
  getProductPeriods.mockResolvedValue(periodos);
  getProductScopeOptions.mockResolvedValue([]);
  getProductReport.mockImplementation((sk: string, _t: string, o: { period?: string }) =>
    Promise.resolve({
      sector_key: sk, tier: "pulse", period: o.period || null, entity_name: null,
      payload: {}, narratives: {},
      commercial: { price_band: null, watermark: null, audience: "mercado",
                    cadence: "periodic", sections: [], staff_preview: false },
    }));
  render(<ProductCatalogPage />);
  const ver = await screen.findAllByRole("button", { name: /ver/i });
  await userEvent.click(ver[0]);          // la PRIMERA tarjeta es el producto trimestral
  const select = await screen.findByRole("combobox");
  await waitFor(() => expect(within(select).getAllByRole("option").length)
    .toBeGreaterThan(periodos.length - 1));
  return select;
}

describe("el selector de período del catálogo", () => {
  beforeEach(() => vi.clearAllMocks());

  it("ofrece el AÑO y el cuarto trimestre — los dos", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "2026-03-31",
      "2025 · año completo", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31",
      "2024 · año completo", "2024-12-31",
    ]);
  });

  it("ningún corte se PIERDE al agregar el año", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    const rotulos = within(select).getAllByRole("option").map((o) => o.textContent);
    for (const p of PERIODOS_TRIMESTRALES.filter((x) => x.includes("-"))) {
      expect(rotulos).toContain(p);
    }
  });

  it("el año se le pide al MISMO producto, no al anual", async () => {
    // Enrutarlo al producto anual fue lo que hizo que los dos sirvieran el mismo informe.
    // Acá el año es una lectura del panel trimestral: la sirve quien se está mirando.
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    getProductReport.mockClear();
    await userEvent.selectOptions(select, "2025");
    await waitFor(() => expect(getProductReport).toHaveBeenCalled());
    const llamadas = getProductReport.mock.calls;
    const [sectorPedido, , opts] = llamadas[llamadas.length - 1];
    expect(sectorPedido).toBe("banking");
    expect((opts as { period?: string }).period).toBe("2025");
  });

  it("elegir un corte sigue pidiendo la fecha", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    getProductReport.mockClear();
    await userEvent.selectOptions(select, "2025-12-31");
    await waitFor(() => expect(getProductReport).toHaveBeenCalled());
    const llamadas = getProductReport.mock.calls;
    const [sectorPedido, , opts] = llamadas[llamadas.length - 1];
    expect(sectorPedido).toBe("banking");
    expect((opts as { period?: string }).period).toBe("2025-12-31");
  });

  it("el encabezado NO se contradice con el título", async () => {
    // Llegó a decir «SDQ Banking · Revisión Anual» sobre un título que decía «SDQ Banking
    // Intelligence». Esa contradicción era el síntoma del ruteo cruzado.
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    await userEvent.selectOptions(select, "2025");
    await vaciar();
    expect(screen.queryByText(/Revisión Anual ·/)).not.toBeInTheDocument();
    expect(screen.getByText(/SDQ Banking Intelligence ·/)).toBeInTheDocument();
  });

  it("al elegir diciembre, apunta al año que está en ESTA misma lista", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    await userEvent.selectOptions(select, "2025-12-31");
    const aviso = await screen.findByText(/en esta misma lista/i);
    expect(aviso.textContent).toMatch(/31 de diciembre de 2025/);
    expect(aviso.textContent).toMatch(/2025 · año completo/);
  });

  it("sobre el AÑO no aparece el aviso: ya estás en la lectura que nombra", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    await userEvent.selectOptions(select, "2025");
    await vaciar();
    expect(screen.queryByText(/en esta misma lista/i)).not.toBeInTheDocument();
  });

  it("en un corte que NO es diciembre tampoco aparece", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    await userEvent.selectOptions(select, "2025-09-30");
    await vaciar();
    expect(screen.queryByText(/en esta misma lista/i)).not.toBeInTheDocument();
  });

  it("sin años en el calendario, la lista y el aviso quedan como antes", async () => {
    const select = await abrirElDrawer(SOLO_CORTES);
    expect(within(select).getAllByRole("option").map((o) => o.textContent))
      .toEqual(SOLO_CORTES);
    await userEvent.selectOptions(select, "2025-12-31");
    await vaciar();
    expect(screen.queryByText(/en esta misma lista/i)).not.toBeInTheDocument();
  });

  it("la DESCARGA usa el período que estás viendo", async () => {
    const select = await abrirElDrawer(PERIODOS_TRIMESTRALES);
    await userEvent.selectOptions(select, "2025");
    await vaciar();
    const panel = select.closest("aside, div[class*=fixed]") as HTMLElement;
    const enPanel = within(panel ?? document.body).getAllByRole("button", { name: /pdf/i });
    await userEvent.click(enPanel[enPanel.length - 1]);
    const bajadas = descargar.mock.calls;
    const [clave, , , opts] = bajadas[bajadas.length - 1];
    expect(clave).toBe("banking");
    expect((opts as { period?: string }).period).toBe("2025");
  });
});
