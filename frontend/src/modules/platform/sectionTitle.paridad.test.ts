/**
 * REGLA ESTRUCTURAL: el título de una sección del informe se resuelve en UN solo lugar.
 *
 * **El caso que la motivó.** La página armaba la clave a mano —`platform.catalog.section.<clave>`—
 * y una misma entrada servía a todos los ejes: la app le decía «Recomendación» a todo
 * producto cuyo PDF dice «Lectura para Decisión». La cura es buscar primero la entrada del EJE
 * (`sectionBySector`) y recién después la general; y esa cura vale solo si nadie vuelve a armar
 * la clave general por su cuenta en otra pantalla, que la saltaría sin fallar.
 *
 * Qué entradas por eje deben existir lo exige el lado de Python
 * (`shared/products/tests/test_toda_seccion_tiene_titulo_en_la_app.py`), que es el que puede
 * leer los PDFs del backend. Los archivos se leen con `import.meta.glob` y no con `node:fs`:
 * el build type-checkea los tests (ver `shared/api/rutas-sin-prefijo.test.ts`).
 */
import { describe, expect, it } from "vitest";

const FUENTES = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** El único archivo que puede armar la clave de un título de sección. */
const RESOLVEDOR = "/src/modules/platform/sectionTitle.ts";
const CLAVE_GENERAL = "platform.catalog.section.";

describe("el título de sección se resuelve en un solo lugar", () => {
  it("nadie fuera del resolvedor arma la clave general", () => {
    const fuera = Object.entries(FUENTES)
      .filter(([archivo]) => !/\.test\.(ts|tsx)$/.test(archivo) && archivo !== RESOLVEDOR)
      .filter(([, texto]) => texto.includes(CLAVE_GENERAL))
      .map(([archivo]) => archivo);
    expect(fuera).toEqual([]);
  });

  it("el barrido leyó el frontend y encontró el resolvedor", () => {
    // Un glob vacío deja el test de arriba en verde sin haber leído nada.
    expect(Object.keys(FUENTES).length).toBeGreaterThan(50);
    expect(FUENTES[RESOLVEDOR] ?? "").toContain("sectionBySector");
  });
});
