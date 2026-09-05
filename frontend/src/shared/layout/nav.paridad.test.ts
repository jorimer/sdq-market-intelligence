import { describe, expect, it } from "vitest";
import { NAV } from "./nav";
// `?raw` de Vite y no `node:fs`: el tsconfig del frontend es de navegador y no trae los
// tipos de Node, así que leer el archivo con `fs` compila en el test y ROMPE `tsc`.
import appSrc from "../../App.tsx?raw";

import es from "../i18n/es.json";
import en from "../i18n/en.json";
import fr from "../i18n/fr.json";

/**
 * Paridad entre las TRES superficies de un ítem del menú: la ruta que declara,
 * la ruta que la app registra, y su etiqueta en cada idioma.
 *
 * Existe por un modo de falla concreto y repetido: a un tipo nuevo le faltaron
 * CUATRO registros de a uno —endpoint, plantilla, etiqueta y lista— y **ninguno
 * falló**; cada uno lo hacía desaparecer en un lugar distinto. Acá el equivalente
 * es un ítem del sidebar que apunta a una ruta que nadie registró (clic → pantalla
 * en blanco) o que no tiene etiqueta en un idioma (aparece la clave cruda, que se
 * ve como un bug de datos y no como uno de traducción).
 *
 * El test barre TODO el menú, no el ítem del día: una lista escrita a mano se
 * queda corta justo en el que se agregó después.
 */

const RUTAS_DE_LA_APP = new Set(
  [...appSrc.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]),
);

const ITEMS = NAV.flatMap((g) => g.items.map((i) => ({ grupo: g.key, ...i })));

/** El barrido tiene que ENCONTRAR algo: un `flatMap` vacío pasaría todo en verde. */
it("el menú tiene ítems que revisar", () => {
  expect(ITEMS.length).toBeGreaterThan(10);
  expect(RUTAS_DE_LA_APP.size).toBeGreaterThan(10);
});

describe("cada ítem del menú lleva a una ruta registrada", () => {
  it.each(ITEMS)("$grupo · $to", ({ to }) => {
    const registrada =
      RUTAS_DE_LA_APP.has(to) ||
      // Rutas con parámetro (/datos/:fuente) o índices que el sidebar apunta por prefijo.
      [...RUTAS_DE_LA_APP].some(
        (r) => r.includes(":") && new RegExp(`^${r.replace(/:[^/]+/g, "[^/]+")}$`).test(to),
      );
    expect(registrada, `«${to}» está en el sidebar y no hay <Route> que la sirva`).toBe(true);
  });
});

const LOCALES: Record<string, Record<string, unknown>> = { es, en, fr };

describe("cada ítem del menú tiene etiqueta en los tres idiomas", () => {
  it.each(ITEMS)("$to", ({ to }) => {
    for (const [loc, dic] of Object.entries(LOCALES)) {
      const items = (dic as any)?.sidebar?.items ?? {};
      expect(
        items[to],
        `«${to}» no tiene etiqueta en ${loc}: el menú muestra la clave cruda`,
      ).toBeTruthy();
    }
  });
});

describe("cada grupo del menú tiene título en los tres idiomas", () => {
  it.each(NAV.map((g) => ({ key: g.key })))("$key", ({ key }) => {
    for (const [loc, dic] of Object.entries(LOCALES)) {
      const grupos = (dic as any)?.sidebar?.groups ?? {};
      expect(grupos[key], `el grupo «${key}» no tiene título en ${loc}`).toBeTruthy();
    }
  });
});

it("Proyecciones Macro vive en Herramientas, junto a las otras cuatro", () => {
  const tools = NAV.find((g) => g.key === "tools");
  expect(tools).toBeTruthy();
  const rutas = tools!.items.map((i) => i.to);
  expect(rutas).toContain("/tools/proyecciones");
  // Convive con las que ya estaban: agregar una no puede desplazar a otra.
  for (const r of ["/tools/research", "/brand-intel", "/tools/deal-scoring", "/tools/market-brief"]) {
    expect(rutas, `«${r}» desapareció del grupo`).toContain(r);
  }
});
