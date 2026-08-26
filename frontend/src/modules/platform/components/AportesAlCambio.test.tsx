/**
 * La tabla «qué movió el score» en la vista in-app.
 *
 * La fixture NO está escrita a mano: es la salida literal de
 * `shared.narrative.derived.aportes_al_cambio`, copiada de una corrida real. Importa que sea
 * así — al escribir el lector supuse una forma «por componente» y la real es «por ventana»,
 * con los aportes anidados adentro. Una fixture inventada habría pasado contra un lector roto.
 *
 * Lo que se protege:
 *   * que la tabla muestre el APORTE (delta × peso) y no el delta a secas — son cosas
 *     distintas y confundirlas fue lo que hizo que un informe atribuyera un deterioro al
 *     «colapso de eficiencia» cuando la eficiencia había MEJORADO;
 *   * que la fila de total esté, porque es lo que vuelve la atribución auditable;
 *   * que un payload sin la tabla no rompa la vista ni dibuje una tabla vacía.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AportesAlCambio } from "./AportesAlCambio";
import { reportAportes, type ProductReport } from "../api";

/** Salida literal de `aportes_al_cambio`, de una corrida real del backend. */
const SALIDA_DEL_BACKEND = [
  {
    ventana: "el último trimestre",
    cambio_total: 1.56,
    aportes: [
      { componente: "calidad", delta_score: -1.0, peso: 0.34, aporte_al_cambio: -0.34 },
      { componente: "solidez", delta_score: 5.0, peso: 0.38, aporte_al_cambio: 1.9 },
    ],
    principal: "solidez",
    cuota_del_principal_pct: 121.8,
    lectura: "en el último trimestre el score subió 1.56 puntos…",
  },
  {
    ventana: "el último año",
    cambio_total: 2.1,
    aportes: [
      { componente: "calidad", delta_score: -5.0, peso: 0.34, aporte_al_cambio: -1.7 },
      { componente: "solidez", delta_score: 10.0, peso: 0.38, aporte_al_cambio: 3.8 },
    ],
    principal: "solidez",
    cuota_del_principal_pct: 181.0,
    lectura: "en el último año el score subió 2.10 puntos…",
  },
];

function informe(payload: unknown): ProductReport {
  return {
    sector_key: "banking", tier: "deep_dive", period: "2025-03-31",
    entity_name: "Asociación Bonao de Ahorros y Préstamos",
    payload: payload as Record<string, unknown>,
    narratives: {},
    commercial: {
      price_band: null, watermark: null, audience: "x", cadence: "on_demand",
      sections: [], staff_preview: false,
    },
  };
}

describe("reportAportes", () => {
  it("lee la forma REAL del backend (por ventana, con los aportes anidados)", () => {
    const v = reportAportes(informe({ scoring_result: { aportes_al_cambio: SALIDA_DEL_BACKEND } }));
    expect(v.map((x) => x.ventana)).toEqual(["el último trimestre", "el último año"]);
    expect(v[0].aportes.map((a) => a.componente)).toEqual(["calidad", "solidez"]);
    expect(v[0].cambio_total).toBe(1.56);
  });

  it("un payload sin la tabla devuelve vacío en vez de romper", () => {
    expect(reportAportes(informe({}))).toEqual([]);
    expect(reportAportes(informe({ scoring_result: {} }))).toEqual([]);
    expect(reportAportes(informe({ scoring_result: { aportes_al_cambio: "roto" } }))).toEqual([]);
  });
});

describe("<AportesAlCambio />", () => {
  it("muestra el APORTE (delta × peso), no el delta a secas", () => {
    render(<AportesAlCambio ventanas={reportAportes(
      informe({ scoring_result: { aportes_al_cambio: SALIDA_DEL_BACKEND } }))} />);
    // solidez en el trimestre: delta 5.0, peso 0.38 → aporte +1.90. El 5.00 NO debe salir.
    expect(screen.getByText("+1.90")).toBeInTheDocument();
    expect(screen.queryByText("+5.00")).not.toBeInTheDocument();
    expect(screen.getByText("−0.34")).toBeInTheDocument();
  });

  it("muestra el cambio total de cada ventana: es lo que vuelve auditable la atribución", () => {
    render(<AportesAlCambio ventanas={reportAportes(
      informe({ scoring_result: { aportes_al_cambio: SALIDA_DEL_BACKEND } }))} />);
    expect(screen.getByText("+1.56")).toBeInTheDocument();
    expect(screen.getByText("+2.10")).toBeInTheDocument();
  });

  it("una columna por ventana, en el orden del backend", () => {
    render(<AportesAlCambio ventanas={reportAportes(
      informe({ scoring_result: { aportes_al_cambio: SALIDA_DEL_BACKEND } }))} />);
    const encabezados = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(encabezados.slice(1)).toEqual(["el último trimestre", "el último año"]);
  });

  it("sin datos NO dibuja una tabla vacía", () => {
    const { container } = render(<AportesAlCambio ventanas={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
