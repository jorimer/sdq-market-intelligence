/**
 * El veredicto de una señal de validación — UNA regla, dos superficies.
 *
 * **Por qué vive acá.** La regla estaba escrita dos veces: en la tabla de Metodología y en la
 * pestaña de validación del eje sectorial. El 2026-09-01 arreglé la primera y dejé la segunda
 * en el mismo commit, así que la pestaña del producto siguió pintando un chip VERDE de
 * «significativo» sobre un IC de −0,274 que está invertido y que además EMPATA con ordenar
 * por tamaño del sector. Es el defecto que este repo ya acumuló ocho veces: el guard existe
 * en un motor y falta en el otro. La cura no es acordarse: es que haya un solo cuerpo.
 *
 * **Las tres razones por las que un IC que excluye el cero NO acredita nada:**
 *
 * 1. `ciExcludesZero` da `true` también cuando el intervalo cae ENTERO POR DEBAJO de cero.
 *    Eso no es una credencial: es la señal ordenando al revés.
 * 2. Un resultado que empata con su control por tamaño no dice nada que el tamaño del sujeto
 *    no explique — y en el eje sectorial el tamaño es, además, el deflactor del desenlace.
 * 3. Sin control no se sabe, y «no sé» no es «sí».
 *
 * Nada de esto se re-juzga acá: los tres hechos los computa el backend y esta capa los LEE.
 */

export type ClaveDeVeredicto =
  | "inconcluso"   // el intervalo cruza el cero: no alcanza la potencia
  | "invertido"    // el intervalo está entero del lado equivocado
  | "empata"       // el control por tamaño alcanza al score
  | "acredita";    // y solo entonces

export interface SenalValidable {
  /** El intervalo del estimador, se llame Gini, IC medio anual o ρ de Spearman. */
  ic_ci?: [number | null, number | null] | null;
  /** Lo computa el backend: el intervalo está entero por debajo de cero. */
  invertido?: boolean | null;
  /** Lo computa el backend: el control por tamaño cae dentro del intervalo del score. */
  empata_con_el_score?: boolean | null;
}

/** Un intervalo que no toca el cero — en CUALQUIERA de los dos lados. */
export function ciExcluyeCero(ci?: [number | null, number | null] | null): boolean {
  if (!ci || ci[0] == null || ci[1] == null) return false;
  return (ci[0] > 0 && ci[1] > 0) || (ci[0] < 0 && ci[1] < 0);
}

export function claveDeVeredicto(s: SenalValidable): ClaveDeVeredicto {
  const ci = s.ic_ci;
  if (!ciExcluyeCero(ci)) return "inconcluso";
  // `invertido` se DERIVA del intervalo cuando el motor no lo emite: no todos lo hacen —los
  // que miden con Gini no traen la bandera— y hacer depender el veredicto de que exista
  // dejaría a esos ejes acreditando un resultado del lado equivocado. La definición es la
  // misma en los dos casos: el intervalo entero por debajo de cero.
  const invertido = s.invertido ?? (ci![1]! < 0);
  if (invertido) return "invertido";
  if (s.empata_con_el_score === true) return "empata";
  return "acredita";
}

/** `true` SOLO cuando la señal sostiene una afirmación. Es lo que decide el color. */
export function acredita(s: SenalValidable): boolean {
  return claveDeVeredicto(s) === "acredita";
}

/** Clave de i18n de cada veredicto — la MISMA en las dos superficies. */
export const I18N_DE_VEREDICTO: Record<ClaveDeVeredicto, string> = {
  inconcluso: "platform.methodology.validation.vInconclusivePower",
  invertido: "platform.methodology.validation.vInverted",
  empata: "platform.methodology.validation.vTiedWithSize",
  acredita: "platform.methodology.validation.vSignificant",
};
