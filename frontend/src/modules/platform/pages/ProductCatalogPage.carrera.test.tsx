/**
 * Cambiar de período mientras un informe se genera: la carrera que costó plata real.
 *
 * **El hecho, del registro de producción del 2026-08-27.** Tres ensamblados del MISMO Deep
 * Dive (Bonao, 2025-03-31) corriendo a la vez, lanzados con 22 y 47 segundos de diferencia,
 * de 109, 96 y 73 segundos. Nadie que ve un error a los cien segundos reintenta a los
 * veintidós: los encendió el selector de período. Se cobraron las tres y no se entregó
 * ninguna.
 *
 * **Y el síntoma que lo disfrazaba.** La respuesta que volvía última escribía en pantalla
 * aunque ya no fuera la pedida. Por eso apareció «Error al cargar» sobre un corte que el
 * usuario ya había abandonado — el fallo era de una petición vieja, y el cartel señalaba al
 * período equivocado. Diagnosticar eso desde la pantalla era imposible.
 *
 * Las dos defensas se prueban por separado a propósito: el aborto apaga el trabajo, y el
 * número de orden protege la pantalla aunque el aborto no llegue a tiempo (una respuesta ya
 * en el cable llega igual). Una sola de las dos deja la mitad del defecto.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const getProductCatalog = vi.fn();
const getProductPeriods = vi.fn();
const getProductScopeOptions = vi.fn();
/** Cada llamada queda registrada con su período y su señal de aborto. */
const llamadas: { periodo: string; signal?: AbortSignal;
                  resolver: (r: unknown) => void; rechazar: (e: unknown) => void }[] = [];

vi.mock("../api", async (importActual) => ({
  ...(await importActual<typeof import("../api")>()),
  getProductCatalog: () => getProductCatalog(),
  getProductPeriods: (...a: unknown[]) => getProductPeriods(...a),
  getProductScopeOptions: (...a: unknown[]) => getProductScopeOptions(...a),
  getProductReport: (_s: string, _t: string, opts: { period?: string }, signal?: AbortSignal) =>
    new Promise((resolver, rechazar) => {
      llamadas.push({ periodo: opts.period || "", signal, resolver, rechazar });
    }),
  downloadProductReport: vi.fn(),
  downloadProductSample: vi.fn(),
}));

vi.mock("@/shared/context/AppContext", () => ({
  useApp: () => ({ period: "2026-Q1" }),
  periodToDate: () => "2026-03-31",
}));

import "@/shared/i18n/config";
import { ProductCatalogPage } from "./ProductCatalogPage";

const PERIODOS = ["2025-12-31", "2025-09-30", "2025-03-31"];

/**
 * Vacía las microtareas pendientes para que la respuesta que acabamos de resolver tenga su
 * OPORTUNIDAD REAL de escribir en la pantalla.
 *
 * Sin esto, afirmar una AUSENCIA dentro de `waitFor` pasa en el primer intento —antes de que
 * el `setState` llegue— y el test queda ciego. Me pasó acá: con la guarda de secuencia
 * desactivada a mano, la respuesta vieja SÍ pisaba la pantalla y el test seguía en verde.
 */
const vaciarPendientes = () => act(async () => { await Promise.resolve(); });

const informe = (periodo: string) => ({
  sector_key: "banking", tier: "pulse", period: periodo, entity_name: null,
  payload: {}, narratives: {},
  commercial: { price_band: null, watermark: null, audience: "mercado",
                cadence: "periodic", sections: [], staff_preview: false },
});

async function abrir() {
  getProductCatalog.mockResolvedValue({
    user_tier: "enterprise",
    sectors: [{
      sector_key: "banking", display_name: "SDQ Banking Intelligence",
      levels: [{ tier: "pulse", unlocked: true, staff_preview: false, required_tier: "free",
                 price_band: "abierto", audience: "mercado", sample_available: false,
                 requires_scope: false, scope_kind: "entity" }],
    }],
  });
  getProductPeriods.mockResolvedValue(PERIODOS);
  getProductScopeOptions.mockResolvedValue([]);
  render(<ProductCatalogPage />);
  const ver = await screen.findAllByRole("button", { name: /ver/i });
  await userEvent.click(ver[0]);
  return await screen.findByRole("combobox");
}

describe("cambiar de período con un informe en vuelo", () => {
  beforeEach(() => { vi.clearAllMocks(); llamadas.length = 0; });

  it("ABORTA la generación anterior en vez de dejar dos corriendo", async () => {
    const select = await abrir();
    await waitFor(() => expect(llamadas.length).toBe(1));   // la carga inicial
    expect(llamadas[0].signal?.aborted).toBe(false);

    await userEvent.selectOptions(select, "2025-09-30");
    await waitFor(() => expect(llamadas.length).toBe(2));
    expect(llamadas[0].signal?.aborted, "la primera sigue corriendo").toBe(true);
    expect(llamadas[1].signal?.aborted).toBe(false);
  });

  it("una respuesta VIEJA que llega tarde no pisa la pantalla", async () => {
    const select = await abrir();
    await waitFor(() => expect(llamadas.length).toBe(1));
    await userEvent.selectOptions(select, "2025-09-30");
    await waitFor(() => expect(llamadas.length).toBe(2));

    // La segunda contesta primero; la primera llega DESPUÉS, como pasó en producción.
    llamadas[1].resolver(informe("2025-09-30"));
    // Se afirma sobre el período DEL INFORME («Período: …»), no sobre la fecha suelta: la
    // fecha también está en las opciones del selector, y buscarla ahí daría un test que
    // pasa por el motivo equivocado.
    await screen.findByText("Período: 2025-09-30");
    llamadas[0].resolver(informe("2025-12-31"));
    await vaciarPendientes();

    expect(screen.queryByText("Período: 2025-12-31")).not.toBeInTheDocument();
    expect(screen.getByText("Período: 2025-09-30")).toBeInTheDocument();
  });

  it("el FALLO de una petición abandonada no pinta un cartel de error", async () => {
    const select = await abrir();
    await waitFor(() => expect(llamadas.length).toBe(1));
    await userEvent.selectOptions(select, "2025-03-31");
    await waitFor(() => expect(llamadas.length).toBe(2));

    // La abandonada falla (el proxy le cortó la conexión a los ~100 s). Antes esto ponía
    // «Error al cargar» encima del período que el usuario acababa de elegir.
    llamadas[0].rechazar({ response: { status: 502, data: {} } });
    llamadas[1].resolver(informe("2025-03-31"));

    await screen.findByText("Período: 2025-03-31");
    expect(screen.queryByText(/Error al cargar/i)).not.toBeInTheDocument();
  });

  it("un aborto NUESTRO nunca se muestra como fallo", async () => {
    const select = await abrir();
    await waitFor(() => expect(llamadas.length).toBe(1));
    await userEvent.selectOptions(select, "2025-09-30");
    await waitFor(() => expect(llamadas.length).toBe(2));

    // Axios rechaza la abortada igual que cualquier otra: sin este caso, cambiar de período
    // dejaba un cartel de error por haber cambiado de período.
    llamadas[0].rechazar({ code: "ERR_CANCELED", name: "CanceledError" });
    await vaciarPendientes();
    expect(screen.queryByText(/Error al cargar/i)).not.toBeInTheDocument();
  });
});
