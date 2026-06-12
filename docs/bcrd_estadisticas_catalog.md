# Catálogo de estadísticas históricas del BCRD (Excel)

Inventario de los archivos Excel de series históricas del Banco Central, para el
ETL de backfill del eje Macroeconómico (las 23 series que el API solo da como
snapshot tienen histórico profundo en estos Excel).

## Descubrimiento (cómo se enumera)

La web del BCRD (jQuery, no SPA) carga la lista de documentos de cada sector por
AJAX desde **`https://www.bancentral.gov.do/a/CustomView/<articleId>-<slug>`**
(GET público, devuelve HTML con los links del CDN). Los archivos viven en
`https://cdn.bancentral.gov.do/documents/estadisticas/<sector>/documents/<archivo>.{xlsx,xls}`.

Inventario completo (708 archivos) en [`bcrd_estadisticas_catalog.json`](bcrd_estadisticas_catalog.json).

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

## Lista cabecera curada (~22 archivos, 95% del valor)

Alcance acordado: framework de ETL + estos archivos (no los 708). El resto se
suma después con solo un config.

### Sector Real
- `imae.xlsx` — IMAE (actividad económica, mensual desde 2007)
- `pib.xls` / `pib_2018.xlsx` — PIB
- `pib_gasto.xls` — PIB por gasto
- `pib_origen_anual.xls` — PIB por origen
- `fbkf.xlsx` — Formación bruta de capital fijo

### Precios
- `ipc.xls` — IPC general (último empalme)
- `ipc_grupos.xls` — IPC por grupos

### Sector Externo
- `bpagos.xls` — Balanza de pagos
- `reservas_internacionales.xlsx` — Reservas internacionales
- `Remesas_6.xlsx` — Remesas
- `DeudaBC.xlsx` — Deuda
- `piianual.xls` — Posición de inversión internacional

### Sector Monetario y Financiero
- `agregados_monetarios.xlsx` — Agregados monetarios (M1, M2…)
- `base_monetaria.xlsx` — Base monetaria
- `panorama_sf.xlsx` — Panorama del sistema financiero
- `tf_activa.xls` / `tf_pasiva.xls` — Tasas de interés activa/pasiva
- `Serie_TPM.xlsx` — Tasa de Política Monetaria

### Turismo
- `lleg_total.xls` — Llegada total de turistas

### Mercado Cambiario
- `TASA_DOLAR_REFERENCIA_MC.xlsx` — Tipo de cambio de referencia

### Mercado de Trabajo
- `tasa_ocupacion.xls` / `tasa_desocupacion.xls` — Ocupación / desocupación

## Plan de build (iterativo)

1. **Framework**: descarga (xls/xlsx) + parser config-driven (hoja, filas de
   cabecera, encoding de período año/mes, columnas→series) + upsert MacroSeries
   (reusar `_upsert_records`) + endpoint admin de backfill por archivo.
2. **Iteración 1**: IMAE + IPC + reservas (prueba la arquitectura end-to-end).
3. **Iteraciones 2..N**: un config por archivo cabecera, inspeccionando el layout.

Relacionado: [[bcrd-live-connector]] (API live + backfill IPC/FX ya hechos).
