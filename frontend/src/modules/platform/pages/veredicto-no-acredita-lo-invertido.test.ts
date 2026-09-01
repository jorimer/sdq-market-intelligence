/**
 * REGLA ESTRUCTURAL: un IC no acredita nada solo por excluir el cero.
 *
 * **El caso que la motivó (2026-09-01).** `ciExcludesZero` devuelve `true` también cuando el
 * intervalo cae ENTERO POR DEBAJO de cero, y la fila del eje sectorial pintaba
 * «Significativo» con eso solo. Mientras el encabezado del reporte llevaba el desenlace de
 * empleo (−0,008, no concluyente) el defecto estaba dormido; al pasar el encabezado al
 * desenlace PRIMARIO —inversión, −0,274 con IC [−0,46; −0,088]— se habría despertado y la
 * página de metodología habría publicado «Significativo» sobre un resultado INVERTIDO que,
 * además, EMPATA con ordenar por tamaño del sector.
 *
 * Los dos hechos los computa el backend (`invertido`, `empata_con_el_score`) y esta pantalla
 * los lee. Lo que este test protege es que los siga leyendo: un mapeo que vuelva a decidir
 * solo con el intervalo compila, pasa los tests de render y miente en una tabla que se
 * presenta como la credencial de la plataforma.
 */
import { describe, expect, it } from "vitest";

const FUENTES = import.meta.glob("/src/modules/platform/pages/MetodologiaPage.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("el veredicto del eje sectorial no acredita un resultado invertido ni un empate", () => {
  it("el mapeo consulta `invertido` y `empata_con_el_score`", () => {
    const textos = Object.values(FUENTES);
    expect(textos.length).toBe(1);
    const fuente = textos[0];
    const i = fuente.indexOf("function mapSector");
    expect(i).toBeGreaterThan(-1);
    const cuerpo = fuente.slice(i, fuente.indexOf("\nfunction ", i + 1));

    expect(cuerpo).toContain("invertido");
    expect(cuerpo).toContain("empata_con_el_score");
    expect(cuerpo).toContain("vInverted");
    expect(cuerpo).toContain("vTiedWithSize");
  });

  it("`sig` no puede ser el intervalo a secas", () => {
    const fuente = Object.values(FUENTES)[0];
    const i = fuente.indexOf("function mapSector");
    const cuerpo = fuente.slice(i, fuente.indexOf("\nfunction ", i + 1));
    // La prueba negativa: así se escribía antes, y así compila y miente.
    expect(cuerpo).not.toMatch(/\bsig:\s*sig\b/);
    expect(cuerpo).not.toMatch(/const\s+sig\s*=\s*ciExcludesZero\([^)]*\)\s*;/);
  });
});
