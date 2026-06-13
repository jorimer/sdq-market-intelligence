# Registro canónico de series del BCRD — propuesta

> **Propósito.** El portal de estadísticas del BCRD tiene ~708 archivos Excel, pero
> no son 708 series: son el mismo concepto repetido en **distintas bases**
> (IPC 1999/2010/2019-2020; PIB 2007/2018), **cortes por año** (importaciones por
> año, turismo por año) y **desagregaciones/anexos**. Este documento define el
> **set canónico** (~25-30 series) que hace homogéneo el dato, cómo se ata al API
> del BCRD, y —para citar en informes— **qué base se usa, por qué (criterio del
> economista) y cuán robusto es el dato**. El resto de archivos NO se ingiere.
>
> Estado de extracción tomado del barrido del corpus (2026-06-13). "Calendario de
> publicaciones" se excluye: ya vive en la sección Publicaciones.

## Criterio de homogeneización de base (transversal)

Dos familias, dos reglas:

| Familia | Problema | Regla canónica |
|---|---|---|
| **Índices** (IPC, IMAE, PIB volumen, deflactores) | los niveles entre bases NO son comparables | usar la **base vigente** como referencia; para historia profunda, **empalmar** (chain-link) las bases viejas por su solape; exponer además la **variación interanual (YoY)**, que es invariante a la base |
| **Niveles** (reservas US$, tipo de cambio, agregados RD$, balanza US$) | sin problema de base (misma unidad) | elegir el **archivo más actual y largo** del concepto |

**Por qué YoY como ancla.** Validado empíricamente: la variación interanual derivada del IPC Excel (base 1999) coincide con la inflación interanual del API en **312/312 meses (1985-2010), Δ = 0.00**. Una tasa de crecimiento no depende de la base, así que es el dato más robusto para series con empalmes metodológicos.

## Set canónico por sector

Leyenda robustez: 🟢 extrae limpio y validable · 🟡 extrae pero requiere revisión/empalme · 🔴 el motor aún no lo extrae (trabajo de PR#4).

### Precios
| Serie | Archivo canónico | Base | Frec. | API | Homogeneización | Razón (economista) | Robustez |
|---|---|---|---|---|---|---|---|
| IPC general | `ipc_base_2019-2020.xls` | 2019-2020 | mensual | `bcrd.ipc.indice` (502) | base vigente para nivel; YoY para serie larga | base oficial vigente desde 2020; el API ya la trae profunda | 🟢 |
| IPC — empalme histórico | `ipc_base_2019-2020_serie_referencial.xlsx` | 2019-2020 (empalmada) | mensual | idem | serie referencial ya encadenada por el BCRD | el propio BCRD publica el empalme oficial; preferirlo a encadenar nosotros | 🟡 |
| Inflación interanual | derivada del IPC | n/a | mensual | `bcrd.inflacion.inflacion.interanual` (491) | YoY del IPC | invariante a la base; ancla de validación | 🟢 |
| IPC subyacente | `ipc_subyacente_base_2019-2020.xlsx` | 2019-2020 | mensual | — | base vigente | núcleo inflacionario; excluye volátiles | 🟡 |

### Sector Real
| Serie | Archivo canónico | Base | Frec. | API | Homogeneización | Razón | Robustez |
|---|---|---|---|---|---|---|---|
| IMAE | `imae.xlsx` | 2007=100 | mensual | `bcrd.sector_real.imaes` | índice + YoY | único indicador de actividad de alta frecuencia; desde 2007 | 🟢 |
| PIB real (crecimiento) | `pib_2018.xlsx` | 2018 | trimestral | — | base 2018 vigente; `*_retro` (2007 empalmado) para historia; YoY del volumen | base oficial vigente; el crecimiento es base-invariante | 🔴 (hoy da "sin series") |
| PIB nominal por gasto | `pib_gasto.xls` | corriente | anual | — | nivel corriente directo | demanda agregada (consumo, inversión, X-M) | 🟡 |
| Deflactor del PIB | `pib_deflactor_2018.xlsx` | 2018 | trimestral | — | YoY como inflación implícita | medida amplia de precios | 🔴 |

### Sector Externo
| Serie | Archivo canónico | Base | Frec. | API | Homogeneización | Razón | Robustez |
|---|---|---|---|---|---|---|---|
| Reservas internacionales (brutas/netas) | `reservas_internacionales.xlsx` | US$ MM | mensual | `…reservas_internacionales.brutas/.netas` (snapshot) | nivel directo; quiebre metodológico 2003 como series separadas | colchón externo; el API solo da el último mes → el Excel da la historia | 🟢 |
| Balanza de pagos | `bpagos.xls` (+ `bpagos__trim`) | US$ MM | anual/trim | — | nivel directo | cuenta corriente y financiera | 🟡 |
| Remesas | `Remesas_6.xlsx` | US$ MM | mensual | — | nivel directo | mayor flujo externo de divisas | 🔴 (pocas obs — revisar layout) |
| Posición de inversión internacional | `piianual.xls` / `piitrim` | US$ MM | anual/trim | — | nivel directo | posición de activos/pasivos externos | 🟡 |
| Comercio (export/import) | consolidar `Exportaciones/Importaciones_Mensuales_*` | US$ FOB/CIF | mensual | — | **consolidar los cortes anuales en una sola serie** | hoy fragmentado por año (≈57 archivos) | 🟡 (requiere consolidación) |

### Sector Monetario y Financiero
| Serie | Archivo canónico | Base | Frec. | API | Homogeneización | Razón | Robustez |
|---|---|---|---|---|---|---|---|
| Tasa de Política Monetaria | `Serie_TPM.xlsx` | % | mensual | — | nivel directo | instrumento de política | 🟢 |
| Agregados monetarios (M1, M2, …) | `agregados_monetarios.xlsx` | RD$ MM | mensual | — | nivel directo | liquidez de la economía | 🟢 |
| Base monetaria | `base_monetaria.xlsx` | RD$ MM | mensual | — | nivel directo | dinero primario | 🟡 |
| Tasa activa / pasiva | `taap_activad.xlsx` / `taap_pasivad.xlsx` | % | mensual | `…tasas_de_interes.activa/.pasiva` (snapshot) | nivel directo | costo/retorno del crédito; API solo último dato | 🟡 |
| Tasa interbancaria | `interbancarios*` | % | diaria→mensual | `…tasas_de_interes.interbancaria` | fin de mes | liquidez interbancaria | 🟡 |

### Mercado Cambiario
| Serie | Archivo canónico | Base | Frec. | API | Homogeneización | Razón | Robustez |
|---|---|---|---|---|---|---|---|
| Tipo de cambio (referencia mercado) | `TASA_DOLAR_REFERENCIA_MC.xlsx` | RD$/US$ | diaria→mensual | `…tasas_de_cambio.venta/.compra` (426) | fin de mes; el API ya lo trae mensual desde 1991 | precio de la divisa; **preferir el API** y usar el Excel solo para granularidad/pre-1991 | 🟡 |

### Mercado de Trabajo
| Serie | Archivo canónico | Base | Frec. | API | Homogeneización | Razón | Robustez |
|---|---|---|---|---|---|---|---|
| Tasa de ocupación | `tasa_ocupacion.xls` | % | trimestral | — | **ojo quiebre ENFT→ENCFT (2021)**: tratar como dos tramos | mercado laboral; cambio de encuesta no empalmable directo | 🟡 |
| Tasa de desocupación | `tasa_desocupacion.xls` | % | trimestral | — | idem | desempleo abierto | 🟡 |

### Sector Turismo
| Serie | Archivo canónico | Base | Frec. | API | Homogeneización | Razón | Robustez |
|---|---|---|---|---|---|---|---|
| Llegada total de turistas | consolidar `lleg_total_*` | personas | mensual | — | **consolidar ~33 cortes anuales en una serie** | flujo turístico, divisas; hoy 1 archivo por año | 🟡 (requiere consolidación) |
| Ocupación hotelera | consolidar `turismo_ocupacion_*` | % | mensual | — | consolidar cortes anuales | demanda hotelera | 🟡 |

## Qué se EXCLUYE (y por qué)

- **Bases superadas** (IPC 1999/2010, PIB 2007 salvo como `*_retro` para empalme) — redundantes con la base vigente.
- **Desagregaciones finas** (IPC por grupos/regiones/quintiles/artículos; tasas diarias por tipo de banco AAYP/BAC/BM/CDC; empleo por rama/categoría/nivel) — útiles para análisis puntual, no para el panel de series macro; se pueden sumar después bajo demanda.
- **Tablas insumo-producto y metodológicas** (COU, CEI, CCIS, MIPRD, anexos) — no son series de tiempo.
- **Cortes por año** ya consolidados en su serie canónica.
- **Calendario de publicaciones** — vive en la sección Publicaciones.
- **Encuesta de Gastos e Ingresos / Sector Fiscal / Sistemas de Pago** — pendientes de descubrimiento de links (dieron 0 en el inventario); se integran cuando se resuelvan.

## Resultado

De **708 archivos → ~25 series canónicas** atadas al API, cada una con base, frecuencia, profundidad y robustez declaradas. La cobertura deja de medirse como "% de 708" y pasa a ser "el set macro coherente, profundo y citable".

## Documentación in-app (a construir tras aprobación)

Cada serie canónica expone, en la app y citable en informes:
`concepto · archivo fuente · base · frecuencia · profundidad (período) · estrategia de homogeneización · razón económica · robustez · serie API ligada · resultado del cruce vs API`.
Vivirá como registro estructurado en el paquete (`shared/data/bcrd_excel/…`) y se mostrará en *Datos · Macro → Histórico · Excel → Catálogo canónico* (o en Metodología), de modo que un analista pueda referenciar "esta serie usa base 2019-2020, empalmada; robustez alta; coincide con el API en N puntos".
