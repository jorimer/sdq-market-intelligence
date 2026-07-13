import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import type { AxiosAdapter } from "axios";
import client from "@/shared/api/client";

// Adapter falso: en vez de pegarle a la red, resuelve devolviendo el config de la
// request para poder inspeccionar los headers que el interceptor agregó.
function echoAdapter(): AxiosAdapter {
  return async (config) =>
    ({ data: config, status: 200, statusText: "OK", headers: {}, config }) as never;
}

describe("client — request interceptor (auth + idioma)", () => {
  beforeEach(() => {
    localStorage.clear();
    client.defaults.adapter = echoAdapter();
  });
  afterEach(() => localStorage.clear());

  it("adjunta el Bearer del access_token de localStorage", async () => {
    localStorage.setItem("access_token", "tok-123");
    const res = await client.get("/whatever");
    expect(res.data.headers.Authorization).toBe("Bearer tok-123");
  });

  it("no adjunta Authorization si no hay token", async () => {
    const res = await client.get("/whatever");
    expect(res.data.headers.Authorization).toBeUndefined();
  });

  it("manda X-Lang=es por defecto y el de localStorage si existe", async () => {
    const def = await client.get("/x");
    expect(def.data.headers["X-Lang"]).toBe("es");
    localStorage.setItem("lang", "en");
    const en = await client.get("/x");
    expect(en.data.headers["X-Lang"]).toBe("en");
  });
});

describe("client — response interceptor (401 sin refresh_token)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("limpia los tokens y redirige a /login cuando un 401 no tiene refresh_token", async () => {
    localStorage.setItem("access_token", "viejo");
    // sin refresh_token en localStorage
    vi.stubGlobal("location", { href: "" } as Location);
    // Adapter que rechaza con 401 (como haría el backend).
    client.defaults.adapter = async (config) => {
      return Promise.reject({
        config,
        response: { status: 401, data: {}, statusText: "Unauthorized", headers: {}, config },
        isAxiosError: true,
      });
    };
    await expect(client.get("/protegido")).rejects.toBeTruthy();
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(window.location.href).toContain("/login");
  });
});
