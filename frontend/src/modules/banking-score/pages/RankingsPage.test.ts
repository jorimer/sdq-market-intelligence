import { describe, expect, it } from "vitest";
import { agruparPorTipo } from "./RankingsPage";

/**
 * El ranking global mezcla familias no comparables. Ordenado en una sola lista, las
 * cambiarias coparon las primeras diez posiciones del sistema financiero dominicano —
 * la lectura de símbolo único que Perfil SDQ vino a reemplazar.
 */
const fila = (bank_type: string | null, bank_name: string, rank: number, rank_in_type: number) =>
  ({ bank_type, bank_name, rank, rank_in_type } as never);

describe("agruparPorTipo", () => {
  it("agrupa por tipo y respeta el orden del catálogo, no el del score", () => {
    const g = agruparPorTipo([
      fila("cambiaria", "Santalucia", 1, 1),
      fila("banca_multiple", "Popular", 2, 1),
      fila("cambiaria", "Phierro", 3, 2),
      fila("banca_multiple", "Citibank", 4, 2),
    ]);
    expect(g.map((x) => x.tipo)).toEqual(["banca_multiple", "cambiaria"]);
    expect(g[0].filas.map((f) => f.bank_name)).toEqual(["Popular", "Citibank"]);
  });

  it("preserva el orden interno que trae la API", () => {
    const g = agruparPorTipo([
      fila("banca_multiple", "A", 1, 1),
      fila("banca_multiple", "B", 2, 2),
      fila("banca_multiple", "C", 3, 3),
    ]);
    expect(g[0].filas.map((f) => f.bank_name)).toEqual(["A", "B", "C"]);
  });

  it("no pierde entidades de un tipo que el catálogo no conoce", () => {
    const g = agruparPorTipo([
      fila("banca_multiple", "Popular", 1, 1),
      fila("tipo_nuevo_del_backend", "Entidad X", 2, 1),
    ]);
    expect(g.flatMap((x) => x.filas)).toHaveLength(2);
    expect(g[g.length - 1].tipo).toBe("tipo_nuevo_del_backend");
  });

  it("no pierde entidades sin tipo asignado", () => {
    const g = agruparPorTipo([fila(null, "Sin tipo", 1, 1)]);
    expect(g).toHaveLength(1);
    expect(g[0].tipo).toBe("");
    expect(g[0].filas[0].bank_name).toBe("Sin tipo");
  });

  it("toda fila de entrada aparece exactamente una vez en la salida", () => {
    const filas = [
      fila("cambiaria", "a", 1, 1), fila("fiduciaria", "b", 2, 1),
      fila("aap", "c", 3, 1), fila(null, "d", 4, 1),
      fila("banca_multiple", "e", 5, 1), fila("desconocido", "f", 6, 1),
    ];
    const salida = agruparPorTipo(filas).flatMap((x) => x.filas);
    expect(salida).toHaveLength(filas.length);
    expect(new Set(salida.map((f) => f.bank_name)).size).toBe(filas.length);
  });
});
