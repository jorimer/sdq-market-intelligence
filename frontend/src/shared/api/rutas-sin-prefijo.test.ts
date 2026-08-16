/**
 * REGLA ESTRUCTURAL: ninguna llamada repite el prefijo que ya trae `baseURL`.
 *
 * **El caso que la motivó.** El cliente compartido tiene `baseURL = "/api/v1"`, y una
 * función nueva escribió la ruta como `"/api/v1/operations/llm-spend"`. El resultado fue
 * `/api/v1/api/v1/...` — una ruta que NO existe y que, como el mismo servicio sirve el SPA
 * y la API, devuelve **HTTP 200 con el HTML de la aplicación** en lugar de un 404. El panel
 * quedó mostrando «no se pudo consultar» en producción sin ninguna pista del motivo.
 *
 * No lo caza el compilador (es una cadena), ni los tests del componente (mockean el módulo
 * de API), ni el linter. Lo único que lo caza es leer las rutas y exigir la regla.
 *
 * Se comprueba sobre TODOS los archivos del frontend, no solo el que falló: el mismo error
 * escrito en otro módulo produce el mismo silencio. Se leen con `import.meta.glob` de Vite
 * y no con `node:fs` a propósito — el build type-checkea los tests, y traer APIs de Node
 * a un proyecto de navegador rompe la compilación.
 */
import { describe, expect, it } from "vitest";

/** El prefijo que `client` ya aporta; repetirlo es el defecto. */
const PREFIJO = "/api/v1";

/** `client.get("...")`, `client.post(\`...\`)`, etc. — la ruta es el primer argumento. */
const LLAMADA =
  /\bclient\s*\.\s*(?:get|post|put|patch|delete)\s*(?:<[^>]*>)?\s*\(\s*([`"'])([^`"']*)\1/g;

const FUENTES = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("las rutas del cliente no repiten el prefijo de baseURL", () => {
  it("ninguna llamada empieza con /api/v1", () => {
    const infractoras: string[] = [];
    let revisadas = 0;

    for (const [archivo, texto] of Object.entries(FUENTES)) {
      if (/\.test\.(ts|tsx)$/.test(archivo)) continue;
      for (const m of texto.matchAll(LLAMADA)) {
        revisadas += 1;
        if (m[2].startsWith(PREFIJO)) infractoras.push(`${archivo} → ${m[2]}`);
      }
    }

    // Si el detector deja de encontrar llamadas se volvió decorativo, y lo que hay que
    // arreglar es el detector — no celebrar el verde.
    expect(revisadas).toBeGreaterThan(20);
    expect(
      infractoras,
      "Estas rutas repiten el prefijo que `baseURL` ya aporta. El resultado es " +
        "/api/v1/api/v1/… , que no existe y devuelve el HTML del SPA con HTTP 200 en vez " +
        "de un 404:\n  " +
        infractoras.join("\n  "),
    ).toEqual([]);
  });
});
