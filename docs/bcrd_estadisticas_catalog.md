# Catálogo de estadísticas históricas del BCRD (Excel)

Inventario de los archivos Excel de series históricas del Banco Central, para el
ETL de backfill del eje Macroeconómico (las 23 series que el API solo da como
snapshot tienen histórico profundo en estos Excel).

## Descubrimiento (cómo se enumera)

La web del BCRD (jQuery, no SPA) carga la lista de documentos de cada sector por
AJAX desde **`https://www.bancentral.gov.do/a/CustomView/<articleId>-<slug>`**
(GET público, devuelve HTML con los links del CDN). Los archivos viven en
`https://cdn.bancentral.gov.do/documents/estadisticas/<sector>/documents/<archivo>.{xlsx,xls}`.

Inventario completo (708 archivos) en
[`shared/data/bcrd_excel/catalog_data.json`](../shared/data/bcrd_excel/catalog_data.json)
(vive dentro del paquete del motor para que viaje con el código en el contenedor;
se carga vía `shared.data.bcrd_excel.catalog.load_catalog`).

| Sector | articleId | # archivos |
|---|---|---|
| Sector Monetario y Financiero | 2536 | 246 |
| Sector Turismo | 2537 | 221 |
| Sector Externo | 2532 | 98 |
| Mercado de Trabajo | 2539 | 58 |
| Sector Real | 2533 | 41 |
| Precios | 2534 | 30 |
| Mercado Cambiario | 2538 | 14 |
| Sector Fiscal | 2535 | (pendiente: ID/links) |
| Sistemas de Pago | 5004 | (pendiente) |

**Cada Excel tiene layout a medida** (cabeceras multi-fila, año-en-columna,
mes-en-filas, múltiples sub-series por hoja) → parser/config por archivo.


## Selección canónica (fuente de verdad)

> La lista curada de "~22 archivos cabecera" y el plan de "un config por archivo"
> que vivían aquí quedaron **superados**. El motor de ingesta AI-native infiere la
> estructura de cualquier Excel (ver `shared/data/bcrd_excel/`), y la selección de
> qué se ingiere —el set **base-homogéneo** de ~25 series canónicas, con su base,
> frecuencia, razón económica, robustez y la serie API ligada— vive en:
>
> **[`SERIES_CANONICAS_BCRD.md`](SERIES_CANONICAS_BCRD.md)** (doc) y, como dato,
> en **`shared/data/bcrd_excel/canonical.py`** (registro que alimenta la UI y la
> ingesta). No se ingieren los 708; el catálogo completo es solo descubrimiento.

Relacionado: [[bcrd-live-connector]] (API live + backfill IPC/FX), Publicaciones
(calendario e informes oficiales).
