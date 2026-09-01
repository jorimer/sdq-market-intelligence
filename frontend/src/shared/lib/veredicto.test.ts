/**
 * El veredicto de una señal de validación: UN cuerpo, y ninguna superficie que lo reescriba.
 *
 * **Los dos casos que lo motivaron, con un día de diferencia.**
 *
 * 1. `ciExcludesZero` devuelve `true` también cuando el intervalo cae ENTERO POR DEBAJO de
 *    cero, y las filas decidían con eso solo. Al pasar el encabezado del Gate E sectorial al
 *    desenlace primario (−0,274, IC [−0,46; −0,088]) la tabla de Metodología habría publicado
 *    «Significativo» sobre un resultado INVERTIDO.
 * 2. Arreglé esa página y dejé la pestaña de validación del propio producto, en el MISMO
 *    commit: siguió pintando un chip verde de «significativo» sobre esa cifra. Es el defecto
 *    que este repo ya acumuló ocho veces —el guard existe en un motor y falta en el otro— y
 *    la cura acordada para la reincidencia no es una lección escrita sino un cuerpo único
 *    más un barrido que exija que todas las superficies lo usen.
 */
import { describe, expect, it } from "vitest";

import { acredita, ciExcluyeCero, claveDeVeredicto } from "./veredicto";

describe("la regla del veredicto", () => {
  it("un intervalo que cruza el cero no concluye", () => {
    expect(claveDeVeredicto({ ic_ci: [-0.254, 0.239] })).toBe("inconcluso");
    expect(acredita({ ic_ci: [-0.254, 0.239] })).toBe(false);
  });

  it("un intervalo ENTERO por debajo de cero está invertido, no acreditado", () => {
    // El caso real: el Gate E sectorial contra intensidad de IED.
    expect(claveDeVeredicto({ ic_ci: [-0.46, -0.088] })).toBe("invertido");
    expect(acredita({ ic_ci: [-0.46, -0.088] })).toBe(false);
    // Y `ciExcluyeCero` por sí solo diría que sí: es justo lo que hacía la página.
    expect(ciExcluyeCero([-0.46, -0.088])).toBe(true);
  });

  it("`invertido` se DERIVA cuando el motor no lo emite", () => {
    // Los motores que miden con Gini no traen la bandera. Si el veredicto dependiera de que
    // exista, esos ejes acreditarían un resultado del lado equivocado.
    expect(claveDeVeredicto({ ic_ci: [-0.5, -0.2] })).toBe("invertido");
    // Y si el motor la emite, manda la del motor.
    expect(claveDeVeredicto({ ic_ci: [0.2, 0.5], invertido: true })).toBe("invertido");
  });

  it("un empate con el control por tamaño NO es una credencial", () => {
    expect(claveDeVeredicto({ ic_ci: [0.195, 0.457], empata_con_el_score: true })).toBe("empata");
    expect(acredita({ ic_ci: [0.195, 0.457], empata_con_el_score: true })).toBe(false);
  });

  it("y solo entonces acredita", () => {
    expect(claveDeVeredicto({ ic_ci: [0.2, 0.5], empata_con_el_score: false })).toBe("acredita");
    expect(acredita({ ic_ci: [0.2, 0.5], empata_con_el_score: false })).toBe(true);
  });

  it("sin control no se sabe, y «no sé» no acredita un empate ni lo descarta", () => {
    // Es la brecha declarada de banca y del eje social: se acredita por intervalo, y el
    // test de abajo las nombra para que la brecha tenga dueño en vez de desaparecer.
    expect(claveDeVeredicto({ ic_ci: [0.2, 0.5] })).toBe("acredita");
  });
});

/** Superficies que renderizan un veredicto de validación y por qué se revisan. */
const SUPERFICIES = [
  "/src/modules/platform/pages/MetodologiaPage.tsx",
  "/src/modules/sector-intel/components/ValidationTab.tsx",
];

const FUENTES = import.meta.glob("/src/**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("ninguna superficie reescribe la regla", () => {
  it("el barrido encuentra las superficies que dice revisar", () => {
    // Un `@parametrize` vacío sale verde sin haber probado nada.
    for (const ruta of SUPERFICIES) expect(FUENTES[ruta], ruta).toBeTypeOf("string");
  });

  it("todas usan el cuerpo compartido", () => {
    for (const ruta of SUPERFICIES) {
      expect(FUENTES[ruta], ruta).toContain("@/shared/lib/veredicto");
      expect(FUENTES[ruta], ruta).toMatch(/\bclaveDeVeredicto\s*\(/);
    }
  });

  it("ninguna decide el veredicto con un intervalo a secas", () => {
    const infractoras: string[] = [];
    for (const [ruta, texto] of Object.entries(FUENTES)) {
      if (/\.test\.tsx?$/.test(ruta)) continue;
      // Una copia local de la regla: es exactamente como volvió a divergir la última vez.
      if (/function\s+ciExcludesZero\s*\(/.test(texto)) infractoras.push(ruta);
    }
    expect(infractoras).toEqual([]);
  });
});
