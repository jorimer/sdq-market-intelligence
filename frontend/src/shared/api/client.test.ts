import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import axios, { type AxiosAdapter } from "axios";
import client from "@/shared/api/client";

// Adapter falso: en vez de pegarle a la red, resuelve devolviendo el config de la
// request para poder inspeccionar los headers que el interceptor agregó.
function echoAdapter(): AxiosAdapter {
  return async (config) =>
    ({ data: config, status: 200, statusText: "OK", headers: {}, config }) as never;
}

describe("client — request interceptor (cookies httpOnly + idioma)", () => {
  beforeEach(() => {
    localStorage.clear();
    client.defaults.adapter = echoAdapter();
  });
  afterEach(() => localStorage.clear());

  it("usa withCredentials (la sesión viaja en cookie, no en header)", () => {
    expect(client.defaults.withCredentials).toBe(true);
  });

  it("NO adjunta Authorization aunque exista un token legado en localStorage", async () => {
    localStorage.setItem("access_token", "tok-legado");
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

function reject401(): AxiosAdapter {
  return async (config) =>
    Promise.reject({
      config,
      response: { status: 401, data: {}, statusText: "Unauthorized", headers: {}, config },
      isAxiosError: true,
    });
}

describe("client — response interceptor (401 → refresh vía cookie)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("en 401 intenta el refresh por cookie y, si falla, redirige a /login", async () => {
    vi.stubGlobal("location", { href: "", pathname: "/banking-score" } as Location);
    const refresh = vi.spyOn(axios, "post").mockRejectedValue({
      isAxiosError: true,
      response: { status: 401 },
    });
    client.defaults.adapter = reject401();

    await expect(client.get("/protegido")).rejects.toBeTruthy();
    expect(refresh).toHaveBeenCalledWith(
      "/api/v1/auth/refresh", {}, { withCredentials: true },
    );
    expect(window.location.href).toContain("/login");
  });

  it("estando YA en /login no redirige (evita el loop de recargas)", async () => {
    vi.stubGlobal("location", { href: "", pathname: "/login" } as Location);
    vi.spyOn(axios, "post").mockRejectedValue({
      isAxiosError: true,
      response: { status: 401 },
    });
    client.defaults.adapter = reject401();

    await expect(client.get("/auth/me")).rejects.toBeTruthy();
    expect(window.location.href).toBe("");
  });

  it("un 401 del propio /auth/login NO dispara refresh (credenciales malas)", async () => {
    vi.stubGlobal("location", { href: "", pathname: "/login" } as Location);
    const refresh = vi.spyOn(axios, "post");
    client.defaults.adapter = reject401();

    await expect(client.post("/auth/login", {})).rejects.toBeTruthy();
    expect(refresh).not.toHaveBeenCalledWith(
      "/api/v1/auth/refresh", {}, { withCredentials: true },
    );
  });

  it("si el refresh FUNCIONA, reintenta la request original", async () => {
    vi.stubGlobal("location", { href: "", pathname: "/banking-score" } as Location);
    vi.spyOn(axios, "post").mockResolvedValue({ status: 200, data: {} });
    let calls = 0;
    client.defaults.adapter = async (config) => {
      calls += 1;
      if (calls === 1) {
        return Promise.reject({
          config,
          response: { status: 401, data: {}, statusText: "Unauthorized", headers: {}, config },
          isAxiosError: true,
        });
      }
      return { data: "ok", status: 200, statusText: "OK", headers: {}, config } as never;
    };

    const res = await client.get("/protegido");
    expect(res.data).toBe("ok");
    expect(calls).toBe(2);
    expect(window.location.href).toBe("");
  });
});
