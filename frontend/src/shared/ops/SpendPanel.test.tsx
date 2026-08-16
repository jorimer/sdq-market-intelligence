/**
 * El panel de gasto tumbó la consola de Operaciones entera en producción:
 * «Cannot read properties of undefined (reading 'toFixed')».
 *
 * La lección no es «faltó un guard». Es que un panel de OBSERVABILIDAD no puede tumbar la
 * pantalla que observa: se monta dentro de la consola de Operaciones, así que cualquier
 * excepción suya se lleva puestas las tarjetas de las tareas —incluidos los interruptores
 * para apagar la que está gastando—. El formateador tiene que tolerar lo que no esperaba.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const getLlmSpend = vi.fn();
vi.mock("./api", () => ({
  getLlmSpend: (...a: unknown[]) => getLlmSpend(...a),
}));

import { SpendPanel } from "./SpendPanel";

/** La carga REAL que devolvió producción el 2026-08-16. */
const REAL = {
  desde: "2026-07-17",
  hasta: "2026-08-16",
  costo_total_usd: 4.7882,
  llamadas_totales: 135,
  por_disparador: [
    {
      clave: "GET /api/v1/products/banking/deep_dive/report",
      costo_usd: 3.9679,
      llamadas: 103,
      hits_de_cache: 0,
      generaciones_reales: 103,
    },
    {
      clave: "desconocido",
      costo_usd: 0.7849,
      llamadas: 20,
      hits_de_cache: 0,
      generaciones_reales: 20,
    },
  ],
  por_motivo: [
    {
      clave: "guard_numerico",
      costo_usd: 1.5259,
      llamadas: 70,
      hits_de_cache: 0,
      generaciones_reales: 70,
    },
  ],
  por_modulo: [
    {
      clave: "banking",
      costo_usd: 3.9679,
      llamadas: 103,
      hits_de_cache: 0,
      generaciones_reales: 103,
    },
  ],
};

beforeEach(() => {
  getLlmSpend.mockReset();
});

describe("SpendPanel", () => {
  it("renderiza la carga real de producción sin romperse", async () => {
    getLlmSpend.mockResolvedValue(REAL);
    render(<SpendPanel />);
    await waitFor(() => expect(screen.getByText("$4.79")).toBeTruthy());
    expect(screen.getByText(/deep_dive/)).toBeTruthy();
  });

  it("NO tumba la consola cuando una cifra viene ausente", async () => {
    // El caso que rompió producción: una fila sin `costo_usd`. Da igual por qué llegó así
    // —un contrato viejo en caché, un despliegue a medias, un campo que el backend deje de
    // mandar—: el panel que observa no puede llevarse puesta la pantalla observada.
    getLlmSpend.mockResolvedValue({
      ...REAL,
      costo_total_usd: undefined,
      por_disparador: [{ clave: "roto", llamadas: 1, hits_de_cache: 0, generaciones_reales: 1 }],
    });
    render(<SpendPanel />);
    await waitFor(() => expect(screen.getByText("roto")).toBeTruthy());
    // Se muestra un guion en vez de una cifra inventada, y la consola sigue en pie.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("tolera una respuesta sin los repartos", async () => {
    getLlmSpend.mockResolvedValue({ desde: "2026-08-01", hasta: "2026-08-16" });
    render(<SpendPanel />);
    await waitFor(() => expect(screen.getAllByText("—").length).toBeGreaterThan(0));
  });

  it("muestra el error del servicio sin propagarlo", async () => {
    getLlmSpend.mockRejectedValue(new Error("500"));
    render(<SpendPanel />);
    await waitFor(() => expect(getLlmSpend).toHaveBeenCalled());
    expect(screen.queryByText("$4.79")).toBeNull();
  });
});
