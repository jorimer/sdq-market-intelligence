/**
 * La fusión de los dos calendarios: el del producto y el de su hermano ANUAL.
 *
 * **Lo que se protege.** Que las DOS lecturas convivan. El dueño lo pidió tres veces —«era
 * agregar el anual, no sustituir el último cuarto por el anual»— y las tres veces yo entregué
 * una sola: primero el corte de diciembre rotulado como si fuera el año, después el corte
 * solo y el año en otra tarjeta.
 *
 * Son dos productos distintos, cada uno con su acceso y su tipo de informe. Por eso cada
 * opción viaja con QUIÉN la sirve y con QUÉ período: pedirle `2025` al producto trimestral, o
 * `2025-12-31` al anual como si fuera un corte, son los dos errores que esto hace imposibles.
 */
import { describe, expect, it } from "vitest";

import { fusionarPeriodos, nombreCortoDeProducto } from "../api";

/** Lo que producción devuelve hoy para `banking`: cortes MÁS años cerrados. */
const PERIODOS = ["2026-03-31", "2025", "2025-12-31", "2025-09-30", "2025-06-30",
                  "2025-03-31", "2024", "2024-12-31", "2024-09-30"];

describe("fusionarPeriodos", () => {
  it("el año y sus cortes conviven, el año PRIMERO", () => {
    expect(fusionarPeriodos("banking", PERIODOS).map((o) => o.value)).toEqual([
      "2026-03-31",
      "2025", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31",
      "2024", "2024-12-31", "2024-09-30",
    ]);
  });

  it("NINGÚN corte desaparece al agregar el año", () => {
    // La afirmación literal del pedido: agregar, no sustituir.
    const cortes = PERIODOS.filter((p) => p.includes("-"));
    const quedaron = fusionarPeriodos("banking", PERIODOS)
      .filter((o) => !o.esAnual).map((o) => o.period);
    expect(quedaron).toEqual(cortes);
  });

  it("el año lo sirve el MISMO producto, no otro", () => {
    // Enrutarlo al producto anual fue lo que hizo que los dos sirvieran el mismo informe.
    // Acá el año es una lectura del panel trimestral: la sirve quien se está mirando.
    const out = fusionarPeriodos("banking", PERIODOS);
    for (const o of out) expect(o.sector).toBe("banking");
    expect(out.find((o) => o.esAnual)).toMatchObject({ period: "2025", esAnual: true });
  });

  it("un producto que solo sirve AÑOS queda entero como anual", () => {
    // Es el caso de «SDQ Banking · Revisión Anual», cuyos períodos son años.
    const out = fusionarPeriodos("banking_year_review", ["2025", "2024", "2023"]);
    expect(out.map((o) => o.value)).toEqual(["2025", "2024", "2023"]);
    expect(out.every((o) => o.esAnual)).toBe(true);
  });

  it("sin años la lista queda EXACTAMENTE como antes", () => {
    const cortes = ["2026-03-31", "2025-12-31", "2025-09-30"];
    const out = fusionarPeriodos("banking", cortes);
    expect(out.map((o) => o.value)).toEqual(cortes);
    expect(out.every((o) => !o.esAnual)).toBe(true);
  });

  it("un período con forma desconocida se CONSERVA al final, no se descarta", () => {
    // Tirar lo que no se entiende haría desaparecer una lectura sin aviso: la regla de
    // siempre — declarar, no rellenar.
    const out = fusionarPeriodos("banking", ["2025", "2025-12-31", "ultimo"]);
    expect(out.map((o) => o.value)).toEqual(["2025", "2025-12-31", "ultimo"]);
  });
});

describe("nombreCortoDeProducto", () => {
  it("quita la familia y deja lo que distingue", () => {
    expect(nombreCortoDeProducto("SDQ Banking · Revisión Anual")).toBe("Revisión Anual");
  });

  it("un nombre sin separador se devuelve entero", () => {
    expect(nombreCortoDeProducto("SDQ Banking Intelligence")).toBe("SDQ Banking Intelligence");
  });
});
