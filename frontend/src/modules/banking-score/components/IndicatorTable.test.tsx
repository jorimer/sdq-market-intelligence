import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// react-i18next: t devuelve el fallback (2º arg) o la clave — sin cargar i18n real.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}));

import { IndicatorTable } from "@/modules/banking-score/components/IndicatorTable";

/**
 * Un indicador que el motor declaró NO disponible no se publica con valor ni con score.
 *
 * Por qué existe. Cuando falta un insumo, el motor marca el indicador `available=false`, lo
 * excluye del promedio de su dimensión y renormaliza los pesos. Esta tabla no miraba esa
 * marca: leía el `raw` —que es el 0.0 por defecto de la estructura— y el `score` que la
 * curva le da a ese cero. En los indicadores INVERSOS, donde menos es mejor, el cero puntúa
 * 100, así que un dato ausente se publicaba como desempeño perfecto.
 *
 * Del lado del frontend la causa era el TIPO: `IndicatorDetail` no declaraba `available`, de
 * modo que el campo viajaba en la respuesta pero la tabla no podía verlo.
 *
 * Caso real: Deep Dive de Caribe Internacional al 2026-06-30 —corte cuyo cubo de crédito la
 * SIB no publicó— con «Concentración top-10: 0.00% · 100.0». Al cierre de 2025 la
 * concentración real era 34,90%.
 */
const SIN_DATO = { raw: 0.0, score: 100.0, available: false };
const CON_DATO = { raw: 3.56, score: 64.4, available: true };

describe("IndicatorTable · el dato ausente no se publica como perfecto", () => {
  it("no muestra el 0.0 por defecto ni lo puntúa como 100", () => {
    render(<IndicatorTable indicators={{ concentracion_top10: SIN_DATO }} />);
    expect(screen.queryByText("0.00")).toBeNull();
    expect(screen.queryByText("100.0")).toBeNull();
  });

  it("NO dibuja la fila: el documento no inventaría lo que le falta", () => {
    // Hubo una versión que la mostraba marcada «s/d». El dueño la revirtió el 2026-08-31:
    // un inventario de faltantes desvaloriza el producto. Omitirla no publica nada falso —
    // el score ya excluye esos indicadores y renormaliza los pesos.
    render(<IndicatorTable indicators={{ concentracion_top10: SIN_DATO, morosidad: CON_DATO }} />);
    expect(screen.queryByText("concentracion_top10")).toBeNull();
    expect(screen.queryByText("s/d")).toBeNull();
    expect(screen.getByText("morosidad")).toBeTruthy();
  });

  it("el indicador CON dato sigue publicando su valor y su score", () => {
    // Contra-caso: sin esto, romper la tabla entera pasaría los dos tests de arriba.
    render(<IndicatorTable indicators={{ morosidad: CON_DATO }} />);
    expect(screen.getByText("3.56")).toBeTruthy();
    expect(screen.getByText("64.4")).toBeTruthy();
  });
});
