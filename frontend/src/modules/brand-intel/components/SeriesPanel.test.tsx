/**
 * El panel de series: lo que importa no es que suba, es que MUESTRE lo que descartó.
 *
 * El defecto que motiva estas pruebas fue silencioso: cuatro columnas del tablero entraron
 * como celdas vacías porque el normalizador no las reconoció, y la carga se veía exitosa.
 * Un panel que solo dice «cargado» reproduce ese defecto en la interfaz.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const uploadSales = vi.fn();
const uploadTrackerHistory = vi.fn();
vi.mock("../api", () => ({
  uploadSales: (...a: unknown[]) => uploadSales(...a),
  uploadTrackerHistory: (...a: unknown[]) => uploadTrackerHistory(...a),
}));

import { SeriesPanel } from "./SeriesPanel";

const LECTURA = {
  filas_leidas: 1494,
  filas_guardadas: 1494,
  filas_descartadas: 62,
  motivos_descarte: { "fecha ilegible": 60, "local sin id": 2 },
  locales: 43,
  plazas: ["Santo Domingo", "Santiago"],
  desde: "2026-06-01",
  hasta: "2026-06-15",
  columnas_sin_mapear: ["Ventas D.T 2026", "Gcs D.T 2026"],
  columnas_ignoradas: { "Ventas Comparativa %": "variación ya calculada" },
};

function archivo() {
  return new File([new Uint8Array([1, 2, 3])], "tablero.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

async function subirVentas(onLoaded = vi.fn()) {
  render(<SeriesPanel slug="mcdonalds" onLoaded={onLoaded} />);
  const inputs = document.querySelectorAll<HTMLInputElement>('input[type="file"]');
  expect(inputs).toHaveLength(2);          // ventas e histórico, cada una la suya
  await userEvent.upload(inputs[0], archivo());
  return onLoaded;
}

describe("SeriesPanel", () => {
  beforeEach(() => {
    uploadSales.mockReset();
    uploadTrackerHistory.mockReset();
  });

  it("muestra las filas descartadas con su motivo y las columnas sin mapear", async () => {
    uploadSales.mockResolvedValue({ lectura: LECTURA, guardado: { nuevas: 1494 } });
    const onLoaded = await subirVentas();

    await waitFor(() => expect(screen.getByText(/1494 jornadas leídas/)).toBeTruthy());
    expect(screen.getByText(/43 locales/)).toBeTruthy();
    expect(screen.getByText("2026-06-01 → 2026-06-15")).toBeTruthy();
    // Lo descartado, a la vista y con su motivo — no en un log del servidor.
    expect(screen.getByText(/62 descartadas/)).toBeTruthy();
    expect(screen.getByText(/fecha ilegible: 60/)).toBeTruthy();
    expect(screen.getByText(/local sin id: 2/)).toBeTruthy();
    // Y las columnas que el lector no reconoció, que es el defecto que se colaba.
    expect(screen.getByText(/Ventas D\.T 2026, Gcs D\.T 2026/)).toBeTruthy();
    // Las derivadas van APARTE y plegadas: si compartieran el aviso, las 27 del tablero
    // real sepultarían el caso de arriba, que es el que importa.
    expect(screen.getByText(/1 columnas ignoradas por diseño/)).toBeTruthy();
    // Cargar una serie cambia el informe: la página tiene que recargar.
    expect(onLoaded).toHaveBeenCalledOnce();
  });

  it("sirve el motivo REAL del rechazo, no un «error al subir»", async () => {
    uploadSales.mockRejectedValue({
      response: {
        data: {
          detail: "El libro no trae la hoja «Base de Datos». Las hojas presentes son: "
                + "Resumen.",
        },
      },
    });
    const onLoaded = await subirVentas();

    await waitFor(() => expect(screen.getByText(/no trae la hoja/)).toBeTruthy());
    expect(screen.getByText(/Las hojas presentes son: Resumen/)).toBeTruthy();
    // Un fallo NO dispara la recarga: no cambió nada.
    expect(onLoaded).not.toHaveBeenCalled();
  });

  it("cae a un mensaje propio cuando el servidor no explica nada", async () => {
    uploadSales.mockRejectedValue(new Error("network"));
    await subirVentas();
    await waitFor(() => expect(screen.getByText("No se pudo cargar la serie.")).toBeTruthy());
  });

  it("declara la regla de cada serie antes de subirla", () => {
    render(<SeriesPanel slug="mcdonalds" onLoaded={vi.fn()} />);
    // La idempotencia y el «solo-si-falta» se leen ANTES de cargar: son las dos preguntas
    // que alguien se hace al reenviar una entrega.
    expect(screen.getByText(/corrige las jornadas, no las duplica/)).toBeTruthy();
    expect(screen.getByText(/nunca sustituye una observación que ya está/)).toBeTruthy();
    expect(screen.getByText(/«Base de Datos», no un agregado ya calculado/)).toBeTruthy();
    expect(screen.getByText(/«KPIs»/)).toBeTruthy();
  });

  it("cada subidor llama a SU endpoint", async () => {
    uploadTrackerHistory.mockResolvedValue({ lectura: { olas: 13 }, guardado: {} });
    render(<SeriesPanel slug="mcdonalds" onLoaded={vi.fn()} />);
    const inputs = document.querySelectorAll<HTMLInputElement>('input[type="file"]');
    await userEvent.upload(inputs[1], archivo());
    await waitFor(() => expect(uploadTrackerHistory).toHaveBeenCalledOnce());
    expect(uploadSales).not.toHaveBeenCalled();
    // Sin informe de ventas, el resultado crudo se muestra igual en vez de callarse.
    await waitFor(() => expect(screen.getByText(/"olas": 13/)).toBeTruthy());
  });
});
