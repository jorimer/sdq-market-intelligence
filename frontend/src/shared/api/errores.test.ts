/**
 * El `detail` de FastAPI tiene TRES formas y el frontend las leía como si tuviera una.
 *
 * El caso real: un Deep Dive que el usuario no tiene contratado devuelve 402 con
 * `detail = {message, tier, required_tier, user_tier}`. La pantalla hacía
 * `typeof detail === "string" ? detail : generico` y mostraba «No se pudo cargar el
 * producto» — un problema de PERMISOS disfrazado de falla técnica, sin decir qué plan hacía
 * falta. Y donde el patrón era `detail || fallback`, el objeto pasaba entero a React.
 */
import { describe, expect, it } from "vitest";

import { detalleDeError, estadoDeError, mensajeDeError } from "./errores";

const err = (status: number, detail: unknown) => ({ response: { status, data: { detail } } });

describe("mensajeDeError", () => {
  it("devuelve el texto cuando el detail es un string (el caso normal)", () => {
    expect(mensajeDeError(err(400, "Período inválido."), "x")).toBe("Período inválido.");
  });

  it("EL CASO DEL 402: saca el mensaje del objeto de upsell, no el genérico", () => {
    const upsell = {
      message: "Tu plan (free) no incluye el nivel deep_dive. Requiere el plan enterprise o superior.",
      tier: "deep_dive",
      required_tier: "enterprise",
      user_tier: "free",
    };
    expect(mensajeDeError(err(402, upsell), "No se pudo cargar el producto."))
      .toBe(upsell.message);
  });

  it("saca el mensaje del 429 de cuota de la API de datos", () => {
    const cuota = {
      code: "quota_exhausted",
      message: "Se agotó la cuota mensual de la llave.",
      message_en: "Monthly quota exhausted for this key.",
      retry_after_seconds: 60,
    };
    expect(mensajeDeError(err(429, cuota), "x")).toBe("Se agotó la cuota mensual de la llave.");
  });

  it("junta los mensajes del 422 de validación de FastAPI", () => {
    const validacion = [
      { loc: ["body", "period"], msg: "field required", type: "value_error.missing" },
      { loc: ["body", "scope"], msg: "str type expected", type: "type_error.str" },
    ];
    expect(mensajeDeError(err(422, validacion), "x"))
      .toBe("field required · str type expected");
  });

  it("nunca devuelve [object Object]", () => {
    for (const d of [{ tier: "deep_dive" }, [{ loc: ["body"] }], { message: 42 }, {}]) {
      const msg = mensajeDeError(err(400, d), "respaldo");
      expect(msg).toBe("respaldo");
      expect(msg).not.toContain("object Object");
    }
  });

  it("cae al respaldo ante un fallo de red (sin response) o un detail vacío", () => {
    expect(mensajeDeError(new Error("Network Error"), "respaldo")).toBe("respaldo");
    expect(mensajeDeError(err(500, ""), "respaldo")).toBe("respaldo");
    expect(mensajeDeError(err(500, "   "), "respaldo")).toBe("respaldo");
    expect(mensajeDeError(undefined, "respaldo")).toBe("respaldo");
    expect(mensajeDeError(null, "respaldo")).toBe("respaldo");
  });

  it("nunca devuelve vacío: un cartel de error en blanco no informa nada", () => {
    for (const e of [err(400, ""), err(400, {}), err(400, []), new Error("x"), null]) {
      expect(mensajeDeError(e, "respaldo").length).toBeGreaterThan(0);
    }
  });
});

describe("detalleDeError / estadoDeError", () => {
  it("dan acceso a los CAMPOS para quien necesite más que el mensaje", () => {
    const e = err(402, { message: "m", required_tier: "enterprise" });
    expect((detalleDeError(e) as { required_tier: string }).required_tier).toBe("enterprise");
    expect(estadoDeError(e)).toBe(402);
  });

  it("estadoDeError es undefined en un fallo de red", () => {
    expect(estadoDeError(new Error("Network Error"))).toBeUndefined();
  });
});
