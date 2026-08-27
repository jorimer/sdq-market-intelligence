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

/** Lo que producción devuelve hoy para cada producto. */
const CORTES = ["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31",
                "2024-12-31", "2024-09-30"];
const ANIOS = ["2025", "2024"];
const ANUAL = { sector: "banking_year_review", periods: ANIOS };

describe("fusionarPeriodos", () => {
  it("el año y sus cortes conviven, el año PRIMERO", () => {
    const out = fusionarPeriodos("banking", CORTES, ANUAL);
    expect(out.map((o) => o.value)).toEqual([
      "2026-03-31",
      "anual:2025", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31",
      "anual:2024", "2024-12-31", "2024-09-30",
    ]);
  });

  it("NINGÚN corte desaparece al agregar el anual", () => {
    const out = fusionarPeriodos("banking", CORTES, ANUAL);
    const cortesQueQuedaron = out.filter((o) => !o.esAnual).map((o) => o.period);
    // Es la afirmación literal del defecto: agregar, no sustituir.
    expect(cortesQueQuedaron).toEqual(CORTES);
  });

  it("cada opción dice QUIÉN la sirve y con QUÉ período", () => {
    const out = fusionarPeriodos("banking", CORTES, ANUAL);
    const anual = out.find((o) => o.esAnual)!;
    const corte = out.find((o) => o.period === "2025-12-31")!;
    // El anual se pide POR AÑO al producto anual…
    expect(anual).toMatchObject({ sector: "banking_year_review", period: "2025" });
    // …y el corte por FECHA al trimestral. Cruzarlos es el error que esto impide.
    expect(corte).toMatchObject({ sector: "banking", period: "2025-12-31" });
  });

  it("sin producto anual la lista queda EXACTAMENTE como antes", () => {
    const out = fusionarPeriodos("banking", CORTES, null);
    expect(out.map((o) => o.value)).toEqual(CORTES);
    expect(out.every((o) => !o.esAnual && o.sector === "banking")).toBe(true);
  });

  it("un año sin cortes propios igual aparece", () => {
    // El anual puede tener años que el trimestral ya no lista (paneles con distinta
    // profundidad). Descartarlos escondería lecturas que sí se pueden pedir.
    const out = fusionarPeriodos("banking", ["2025-12-31"],
                                 { sector: "x", periods: ["2025", "2019"] });
    expect(out.map((o) => o.value)).toEqual(["anual:2025", "2025-12-31", "anual:2019"]);
  });

  it("un período con forma desconocida se CONSERVA al final, no se descarta", () => {
    // Un producto puede servir «2025-H1» o algo que este código no sabe agrupar. Tirarlo
    // haría desaparecer una lectura sin aviso — la regla de siempre: declarar, no rellenar.
    const out = fusionarPeriodos("banking", ["2025-12-31", "ultimo"], ANUAL);
    expect(out.map((o) => o.value)).toEqual([
      "anual:2025", "2025-12-31", "anual:2024", "ultimo",
    ]);
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
