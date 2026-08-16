/**
 * Una ruta de API inexistente devuelve HTTP 200 con el HTML del SPA: el mismo servicio
 * sirve la aplicación y la API, y el catch-all del frontend atiende antes que el 404.
 *
 * Axios lo resuelve como ÉXITO. El componente lee un campo de una cadena de HTML, obtiene
 * `undefined` y revienta en el primer `.toFixed()` / `.map()` / `.length`. Tumbó la
 * consola de Operaciones entera durante un despliegue, porque la réplica que atendió
 * todavía no tenía el endpoint. Le puede pasar a cualquier módulo.
 */
import { describe, it, expect } from "vitest";
import client from "./client";

type Handler = (r: unknown) => unknown;

/** El interceptor de éxito registrado por el cliente. */
function onFulfilled(): Handler {
  const h = client.interceptors.response as unknown as {
    handlers: { fulfilled: Handler }[];
  };
  return h.handlers[0].fulfilled;
}

const respuesta = (contentType: string, url = "/operations/llm-spend") => ({
  data: "<!doctype html><html><body>SPA</body></html>",
  headers: { "content-type": contentType },
  config: { url, baseURL: "/api/v1" },
});

describe("el HTML del SPA no pasa por dato", () => {
  it("rechaza cuando una ruta de API devuelve HTML", async () => {
    await expect(
      Promise.resolve(onFulfilled()(respuesta("text/html; charset=utf-8"))),
    ).rejects.toThrow(/HTML de la aplicación/);
  });

  it("deja pasar el JSON normal", () => {
    const ok = {
      data: { costo_total_usd: 1 },
      headers: { "content-type": "application/json" },
      config: { url: "/operations/llm-spend", baseURL: "/api/v1" },
    };
    expect(onFulfilled()(ok)).toBe(ok);
  });

  it("no molesta a una descarga de HTML que NO es de la API", () => {
    const doc = {
      data: "<html></html>",
      headers: { "content-type": "text/html" },
      config: { url: "https://otro.sitio/pagina", baseURL: "" },
    };
    expect(onFulfilled()(doc)).toBe(doc);
  });
});
