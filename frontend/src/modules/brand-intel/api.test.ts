/**
 * El corte elegido tiene que llegar a DOS lugares: al servidor y al nombre del archivo.
 *
 * Si viaja al servidor pero no al nombre, dos informes del mismo encargo con olas distintas
 * se sobrescriben en la carpeta de descargas y el usuario cree que el selector no funciona.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { type AxiosAdapter } from "axios";
import client from "@/shared/api/client";
import { downloadReport } from "./api";

let pedido: { url?: string; params?: Record<string, unknown> } = {};

function capturador(): AxiosAdapter {
  return async (config) => {
    pedido = { url: config.url, params: config.params };
    return { data: new Blob(["x"]), status: 200, statusText: "OK",
             headers: {}, config } as never;
  };
}

const descargas: string[] = [];

describe("downloadReport — la ola elegida", () => {
  beforeEach(() => {
    pedido = {};
    descargas.length = 0;
    client.defaults.adapter = capturador();
    // triggerDownload crea un <a download> y lo clickea: capturamos el nombre.
    globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
    globalThis.URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      descargas.push(this.download);
    });
  });

  it("sin ola no manda el parámetro y el archivo no lleva sufijo", async () => {
    await downloadReport("mcdonalds", "pdf");
    expect(pedido.url).toContain("/engagements/mcdonalds/report.pdf");
    expect(pedido.params).toBeUndefined();
    expect(descargas[0]).toBe("SDQ-MIP_informe_contexto_mcdonalds.pdf");
  });

  it("con ola la manda al servidor Y la pone en el nombre del archivo", async () => {
    await downloadReport("mcdonalds", "pdf", "2026-03");
    expect(pedido.params).toEqual({ wave: "2026-03" });
    expect(descargas[0]).toBe("SDQ-MIP_informe_contexto_mcdonalds_2026-03.pdf");
  });

  it("no deja que un código de ola raro se cuele al nombre del archivo", async () => {
    await downloadReport("mcdonalds", "docx", "Ola 5/2026");
    // El parámetro va tal cual (el servidor valida y responde 400 si no existe)…
    expect(pedido.params).toEqual({ wave: "Ola 5/2026" });
    // …pero el nombre del archivo se sanea: una barra abriría una ruta.
    expect(descargas[0]).toBe("SDQ-MIP_informe_contexto_mcdonalds_Ola52026.docx");
  });
});
