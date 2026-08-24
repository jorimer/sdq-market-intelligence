/**
 * REGLA ESTRUCTURAL: nadie lee `response.data.detail` a mano; se pasa por `mensajeDeError`.
 *
 * **Por qué estructural y no una lección escrita.** `VigilarButton` YA resolvía bien el 402
 * —leía `detail.message` cuando el detail era un objeto— y ninguna de las otras diecinueve
 * pantallas se enteró. La regla ya se conocía y el defecto reapareció en el archivo de al
 * lado, que es el patrón que en este repo ya falló de sobra.
 *
 * Las dos formas de leerlo mal fallan distinto y las dos son malas:
 *
 * - `detail || fallback` → con un objeto devuelve el OBJETO y React no lo puede renderizar.
 * - `typeof detail === "string" ? detail : fallback` → no rompe, pero TIRA el mensaje que el
 *   backend mandó. Así, un 402 de upsell se leía como «No se pudo cargar el producto».
 *
 * No lo caza el compilador: casi todos los sitios afirmaban `{ detail?: string }` con un
 * `as`, o sea le MENTÍAN a TypeScript sobre una forma que el backend no garantiza.
 *
 * Alcance declarado: se busca el ACCESO (`?.response?.data?.detail`), no la palabra `detail`
 * —que es un campo legítimo de varias respuestas de éxito— ni las anotaciones de tipo. Si
 * mañana alguien lee el detail por otra ruta (desestructurando `data`, por ejemplo), este
 * barrido no lo ve: la regla cubre la forma que produjo el defecto, no todas las imaginables.
 */
import { describe, expect, it } from "vitest";

/** El acceso al detail de un error, en cualquiera de sus grafías con o sin `?.`. */
const ACCESO_A_DETAIL = /\bresponse\s*\??\.\s*data\s*\??\.\s*detail\b/g;

/** Único archivo autorizado a leerlo: el que centraliza la interpretación. */
const AUTORIZADO = "/src/shared/api/errores.ts";

const FUENTES = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("el detail de la API se interpreta en un solo lugar", () => {
  // Prueba NEGATIVA: sin esto, un glob que deje de matchear daría cero infractores y cero
  // archivos, y el test pasaría en verde sin haber leído nada.
  it("el barrido encuentra el frontend", () => {
    expect(Object.keys(FUENTES).length).toBeGreaterThan(50);
  });

  it("el archivo autorizado existe y es el que sabe leer las tres formas", () => {
    expect(FUENTES[AUTORIZADO]).toBeDefined();
    expect(FUENTES[AUTORIZADO]).toMatch(ACCESO_A_DETAIL);
  });

  it("ninguna otra fuente accede a response.data.detail", () => {
    const infractoras: string[] = [];
    for (const [archivo, texto] of Object.entries(FUENTES)) {
      if (archivo === AUTORIZADO) continue;
      if (/\.test\.(ts|tsx)$/.test(archivo)) continue;
      const golpes = [...texto.matchAll(ACCESO_A_DETAIL)];
      if (golpes.length) infractoras.push(`${archivo} (${golpes.length})`);
    }
    expect(
      infractoras,
      "Estas fuentes leen el detail a mano. El detail de FastAPI puede ser texto, objeto " +
        "(402 de upsell, 429 de cuota) o lista (422 de validación): usá mensajeDeError(e, " +
        `respaldo) de ${AUTORIZADO}.`,
    ).toEqual([]);
  });
});
