import type { TFunction } from "i18next";

/**
 * El título con que la app encabeza una sección del informe.
 *
 * 1. La entrada del EJE, `platform.catalog.sectionBySector.<eje>.<sección>`. Una misma clave
 *    puede titularse distinto según el producto —`recommendation` es «Recomendación» en banca
 *    y «Lectura para decisión» en el resto del catálogo— y una sola entrada no sirve a los dos.
 * 2. La general, `platform.catalog.section.<sección>`.
 * 3. La clave con espacios, que es lo que nunca debería verse.
 *
 * Qué entradas tienen que existir —y que digan lo mismo que el PDF— lo exige
 * `shared/products/tests/test_toda_seccion_tiene_titulo_en_la_app.py`. Que ninguna pantalla
 * arme la clave general por su cuenta, saltándose el eje, lo exige
 * `sectionTitle.paridad.test.ts`.
 *
 * `sectorKey` es el del producto que SIRVIÓ el informe (`report.sector_key`), no el de la
 * tarjeta: la lectura del año de banca la sirve `banking_year_review`.
 */
export function sectionTitle(t: TFunction, sectorKey: string, section: string): string {
  const general = t(`platform.catalog.section.${section}`, {
    defaultValue: section.replace(/_/g, " "),
  });
  return t(`platform.catalog.sectionBySector.${sectorKey}.${section}`, { defaultValue: general });
}
