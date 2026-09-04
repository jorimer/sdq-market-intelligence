# INFORME — Fase 0 (T-PS-0): corrida en seco de la ingesta canónica BCRD

> 2026-09-03 · rama `claude/bcrd-canonical-ingest-phase0-efa957` · base `main` (e46dfbe)
> Spec: `docs/SPEC_PERSISTENCIA_SERIES_BCRD.md` §3.1 · Plan: `tasks/PLAN_PAQUETE_FORWARD_LOOKING.md` T-PS-0
>
> **Recomendación: NO encender `persist=True` tal como está. Sí encenderlo acotado.**
> Detalle en §6. `persist=True` no se encendió en esta sesión.

---

## 0. BLUF

La corrida escribiría **55.759 observaciones en 600 series nuevas**, con **cero colisiones**
contra las 509 filas existentes. El gate que el plan fijó para T-PS-0 —«cero colisiones que
cambien valores históricos»— **pasa, y pasa por vacío**: no hay una sola colisión.

`pib_real` da **77 trimestres** (2007-Q1→2026-Q1), sin huecos y sin nulos. **El BVAR de
T-MP-3 procede** como está especificado.

Pero la corrida destapó **dos defectos que el spec no anticipó**, y uno de ellos es de
pérdida de datos silenciosa dentro del propio lote: **29.427 duplicados intra-lote con
valores DISTINTOS**, resueltos por «último gana» según el orden de lectura. Están acotados
a **4 archivos** y **no tocan ninguna serie de la vía de proyección**.

---

## 1. Cómo se corrió (y por qué el método del spec no servía)

- `ingest_canonical(db, **persist=True**)` con `service._upsert_records` **interceptado**:
  el wrapper captura los registros y delega en el `_upsert_records` REAL contra una base
  scratch vacía. Con `persist=False` no se ejercita la rama que se va a encender: se
  mediría el camino viejo, y se perderían el dedupe, el filtro `_sin_sujeto` y el
  `infer_nature` de producción.
- `db` apunta a una **copia** de la base dev. **La «corrida en seco» del spec no es seca:**
  `_upsert_excel_report` (`service.py:406`) escribe siempre, con `persist=False` incluido.
  Comprobado: la copia pasó de 10 a 35 filas en `mm_excel_reports` con `mm_series` intacta
  en 509. Contra la base del dueño, el paso 1 tal como estaba escrito habría escrito 25 filas.
- La base del dueño quedó **intacta**, verificado por md5 antes y después de las tres
  corridas (`e9c2e4d2f026a4d36389f68639778ea4`).
- Descarga fresca (no se reusó la caché del 23-jul).
- Script descartable: `scripts/dry_run_canonical_ingest.py`. Artefacto:
  `/tmp/fase0_bcrd_would_write.json` (12 MB).

**Resultado de la corrida:** 26 archivos · 16 ok · 10 marcados · **0 fallidos** · 75,2 s ·
**6 llamadas al modelo, US$ 0,0956** (18.668 tokens in / 2.638 out). Re-corridas con caché
caliente: 10 s y **US$ 0**, con cifras **idénticas** — la corrida es determinista.

---

## 2. E1 · Diff contra `mm_series`

| | |
|---|---:|
| Filas actuales en `mm_series` | 509 |
| `series_code` actuales | 7 |
| Observaciones que se escribirían | **55.759** |
| `series_code` que se escribirían | **600** |
| `series_code` **nuevos** | **600** |
| **Colisiones `(series_code, period)`** | **0** |
| **Colisiones que CAMBIAN valor** | **0** ← cifra crítica |
| **`value=None` que pisaría un no-nulo** (§2.2.1) | **0** |
| `series_code` actuales que la corrida NO toca | 7 (los 7) |

**Por qué cero, y qué significa.** Las 7 series vivas están en otro espacio de nombres: el
conector de API (`bcrd.inflacion.*`, `bcrd.sector_externo.reservas_internacionales.brutas`)
y los códigos cortos del snapshot (`gdp_growth`, `public_debt_gdp`…). El motor de Excel
escribe bajo `bcrd.xls.<archivo>.<métrica>`. **Nunca se cruzan.**

Corolario que conviene no perder: encender la ingesta **no actualiza** las series que hoy
consumen los productos. Las deja intactas y agrega 600 al lado. Reservas, por ejemplo,
quedaría con `...reservas_internacionales.brutas` (API, 1 obs) y
`bcrd.xls.reservas_internacionales.reservas_brutas` (Excel, historia larga) conviviendo.
Cuál cita cada consumidor es una decisión que hoy nadie tomó.

El riesgo que motivaba el gate —pisar dato histórico bueno— **no se materializa en esta
corrida**. El defecto §2.2.1 sigue siendo real en el código; simplemente no tiene nada que
pisar todavía. Cuando `mm_series` tenga las 600 series, la segunda corrida **sí** entra por
la rama `else` de `service.py:118`.

---

## 3. E2 · Conteos de §4.1

| Serie | Frec. | Esperado §4.1 | **Real** | Rango | Huecos | Nulos internos |
|---|---|---:|---:|---|---:|---:|
| `pib_real` (`pib_2018.serie_original_indice`) | trimestral | ~76 | **77** | 2007-Q1→2026-Q1 | 0 | 0 |
| `imae_indice` (`imae_2018.serie_original_indice`) | mensual | ~230 | **235** | 2007-01→2026-07 | 0 | 0 |
| IMAE YoY (`imae_2018.variacion_porcentual_interanual`) | mensual | ~230 | **235** (223 no nulos) | 2007-01→2026-07 | 0 | 12 |
| `ipc_general` (`ipc_base_2019_2020.indice`) | mensual | ~500 | **511** | 1984-01→2026-07 | 0 | 0 |
| `pib_sectores_origen` | trimestral ×17 | ~1.300 | **0** | — | — | — |
| `pib_deflactor` | trimestral | — | **33** | 2018-Q1→2026-Q1 | 0 | 0 |

**El número que decide: `pib_real` = 77 trimestres ≥ 60. El BVAR de T-MP-3 procede.**
El spec estimó ~76 y la realidad dio 77: la estimación era buena.

`pib_sectores_origen` da **0 porque no está en `REGISTRY`** y `ingest_canonical` solo recorre
el canónico. Es exactamente lo que T-PS-2 paso 1 viene a arreglar. Nota para T-MP-0 paso 3:
la cobertura por sector **no se puede evaluar todavía** — no hay dato.

`pib_deflactor` solo llega a **33 trimestres desde 2018-Q1**, no a la profundidad de
`pib_real`. Si algún modelo lo necesita alineado con el PIB, la ventana común es 33, no 77.

---

## 4. E3 · Las tres trampas de §2.4

**Trampa 1 — CONFIRMADA (el canónico está bien).** El único prefijo IMAE producido es
`bcrd.xls.imae_2018`. El `imae.xlsx` congelado **no se ingirió**: no está en `REGISTRY`.
La fila de `imae.xlsx` en `mm_excel_reports` es del barrido viejo, no de esta corrida.
Queda pendiente barrer si algún **consumidor** apunta al congelado; el canónico no.

**Trampa 2 — CONFIRMADA.** `PIB_sectores_origen.xls` **no está en `REGISTRY`**, sí está en
el catálogo, y **no produjo ninguna serie** en la corrida.

**Trampa 3 — REFUTADA, y lo que hay debajo es peor.** El spec dice que del IMAE «solo se
ingiere la variación interanual, no el índice». Las dos mitades son falsas:

1. **El índice SÍ se ingiere.** `ingest_canonical` ingiere **archivos completos**, no series
   por sufijo: dedupe por `source_file` y `ingest_excel` sobre el archivo entero. De
   `imae_2018.xlsx` salen **las 12 series**, incluida `serie_original_indice` (235 obs, sin
   huecos ni nulos). **`excel_series_suffix` NO gobierna la ingesta** — es un puente de
   documentación y verificación, nada más.
2. **La variación interanual NO se ingiere por el puente que el canónico declara.** La
   entrada `imae` declara `excel_series_suffix="serie_original_variacion_porcentual_interanual"`
   y **ninguna** de las 12 series producidas termina así. La que existe se llama
   `variacion_porcentual_interanual`, sin el prefijo `serie_original_`.

   **`imae` es la ÚNICA de las 33 entradas con sufijo cuyo puente no resuelve a nada.**
   Las otras 32 resuelven.

**Consecuencia para T-PS-2 paso 2:** añadir `imae_indice` **no es lo que hace fluir el
dato** —ya fluye—; es lo que hace que el registro **declare** lo que ya fluye, y lo que
permite que el test de §4 lo vigile. Y hay un trabajo que el plan no tiene: **corregir el
sufijo roto de la entrada `imae`**.

---

## 5. E4 · Inventario de entradas sin `excel_series_suffix`

**17 de 50** (el spec decía «al menos dos»). Las 17 apuntan a archivos que **sí producen
series**: no es que falte el dato, falta el puente. Es la lista de excepciones que T-PS-4
tiene que congelar con motivo por entrada.

| clave | archivo | series | obs |
|---|---|---:|---:|
| `inflacion_interanual` | `ipc_base_2019-2020.xls` | 5 | 2.555 |
| `ipc_subyacente` | `ipc_subyacente_base_2019-2020.xlsx` | 2 | 638 |
| `pib_nominal_gasto` | `pib_gasto.xls` | 36 | 828 |
| `balanza_pagos_mbp6` | `bpagos_6.xls` | 57 | 912 |
| `balanza_pagos_mbp5` | `bpagos.xls` | 54 | 972 |
| `remesas` | `Remesas_6.xlsx` | 1 | 204 |
| `pii_mbp6` | `piianual_6.xlsx` | 130 | 2.210 |
| `pii_mbp5` | `piianual.xls` | 96 | 960 |
| `tpm` | `Serie_TPM.xlsx` | 3 | 813 |
| `agregados_monetarios` | `agregados_monetarios.xlsx` | 10 | 2.960 |
| `base_monetaria` | `base_monetaria.xlsx` | 14 | 4.060 |
| `tasa_activa` | `taap_activad.xlsx` | 16 | 1.840 |
| `tasa_pasiva` | `taap_pasivad.xlsx` | 14 | 1.610 |
| `tipo_cambio` | `TASA_DOLAR_REFERENCIA_MC.xlsx` | 15 | 3.449 |
| `tasa_ocupacion` | `tasa_ocupacion.xls` | 3 | 84 |
| `tasa_desocupacion` | `tasa_desocupacion.xls` | 6 | 121 |
| `llegada_turistas` | `lleg_total.xls` | 59 | 15.757 |

**Trampa para quien escriba el test de T-PS-4:** el prefijo del código **no es el nombre del
archivo**. `default_prefix` lo *slugifica* y lo pasa a minúsculas: `ipc_base_2019-2020.xls`
→ `bcrd.xls.ipc_base_2019_2020`, `TASA_DOLAR_REFERENCIA_MC.xlsx` →
`bcrd.xls.tasa_dolar_referencia_mc`, `Serie_TPM.xlsx` → `bcrd.xls.serie_tpm`. Un test que
componga `bcrd.xls.{stem}.{sufijo}` a mano falla en **10 de los 26** archivos del canónico.
El test tiene que usar `default_prefix`, no reconstruir el prefijo.

---

## 6. Hallazgo NUEVO · «último gana» resuelve 29.427 conflictos en silencio

De 151.507 registros crudos se escriben 55.759. La caída cierra exacta:

| | |
|---|---:|
| crudos | 151.507 |
| − descartados por `_sin_sujeto` (código desempatado por coordenada) | 1.108 |
| − duplicados `(series_code, period)` dentro del lote | 94.640 |
| **= escritos** | **55.759** |

Un duplicado que repite la misma cifra es inocuo. **29.427 de esos duplicados traen un
valor DISTINTO** para la misma `(series_code, period)`, y `_upsert_records` los resuelve
con «último gana» —por orden de lectura, sin registro y sin veto—. Afecta a **176 de las
600 series**, concentradas en **4 archivos**:

| archivo | resoluciones silenciosas |
|---|---:|
| `TASA_DOLAR_REFERENCIA_MC.xlsx` (`tipo_cambio`) | 20.047 |
| `lleg_total.xls` (`llegada_turistas`) | 4.555 |
| `piianual_6.xlsx` (`pii_mbp6`) | 2.970 |
| `piianual.xls` (`pii_mbp5`) | 1.855 |

**El mecanismo en el peor caso es un error de granularidad, no de duplicación.**
`TASA_DOLAR_REFERENCIA_MC.xlsx` es una serie **diaria**, y la identidad de una observación
es `(series_code, period)` con el período normalizado a mes: los ~30 días de un mes colapsan
en una clave y **sobrevive uno solo, arbitrario**. `...diaria.compra` queda con 429
observaciones «mensuales» de 1991-01 a 2026-09 — una tasa suelta por mes, presentada como si
fuera el dato del mes. Y hay una serie `...diaria.dia` cuyos valores son **31, 28, 30**: es
la columna del **día del mes**, persistida como si fuera una medición.

En `piianual` el mecanismo es otro: códigos sin sujeto único (`...piianual_6.activos`) donde
varias filas distintas del cuadro colapsan en un mismo nombre. No lo atrapa `_sin_sujeto`,
que solo veta el sufijo `_c<n>`.

**Ninguna de las cuatro toca la vía de proyección.** Verificado explícitamente:
`pib_2018.*`, `imae_2018.*`, `ipc_base_2019_2020.*` y `pib_deflactor_2018.*` **no aparecen**
entre las 176 conflictivas.

---

## 7. Hallazgo NUEVO · `frequency` sale NULL en las 55.759

Las 55.759 filas se escribirían con `frequency = None`, igual que las 509 actuales
(NULL en 509/509). Encender antes de T-PS-1 **multiplica por 110 el backfill**: de 509 filas
a 56.268. Es un argumento de **orden**, no de riesgo: T-PS-1 antes que T-PS-3.

Recordatorio de la corrección C6: la cascada de T-PS-1 cruza dos vocabularios —el canónico
en español (`mensual|trimestral|anual`), el extractor y `_infer_frequency` en inglés
(`monthly|quarterly|annual|unknown`)—. Hay que fijar uno antes de propagar.

---

## 8. Recomendación

**NO encender `persist=True` sobre el canónico completo.** No por lo que el gate de T-PS-0
vigilaba —ahí el resultado es limpio: cero colisiones, cero valores pisados— sino por §6:
se escribirían 176 series cuyo valor lo eligió el orden de lectura, y al menos una
(`tipo_cambio`) con un error de granularidad que la vuelve engañosa, no incompleta. Publicar
una tasa de cambio «mensual» que en realidad es un día suelto del mes es peor que no tenerla.

**SÍ encender acotado, y ya.** La vía de proyección está limpia y verificada: `pib_2018`,
`imae_2018`, `ipc_base_2019_2020` y `pib_deflactor_2018` — 0 colisiones, 0 huecos, 0 nulos
internos, 0 conflictos de «último gana». Son las cuatro que T-MP necesita. Encenderlas
desbloquea el bloque MP sin cargar con los 4 archivos problemáticos.

**Orden sugerido, con lo que cambia respecto del plan:**

1. **T-PS-1 primero** (`frequency` + guard de nulos de §2.2.1), con el vocabulario fijado.
   Antes de que el backfill pase de 509 a 56.268 filas.
2. **Encendido acotado** a los 4 archivos de la vía de proyección. Requiere un parámetro que
   hoy no existe: `ingest_canonical` es todo-o-nada sobre el canónico.
3. **T-PS-2** con **tres** trabajos, no dos: `pib_sectores_origen`, `imae_indice`, y
   **corregir el sufijo roto de la entrada `imae`**.
4. **Triaje de los 4 archivos conflictivos** antes de incluirlos. `tipo_cambio` necesita una
   decisión de diseño: una serie diaria no entra en `(series_code, period)` mensual.
5. **T-PS-4** con la lista de 17 excepciones y el test escrito contra `default_prefix`.

**Correcciones al spec que quedan pendientes de aplicar** (§2.4 trampa 3 es falsa; `REGISTRY`
son 50 y no 24; el inventario son 17 y no 2; la corrida en seco no es seca; las líneas de
`service.py` están corridas ~30). Están volcadas como C1–C9 en
`tasks/PLAN_PAQUETE_FORWARD_LOOKING.md`.

---

## 9. Evidencia

| Qué | Dónde |
|---|---|
| Artefacto con las 55.759 observaciones | `/tmp/fase0_bcrd_would_write.json` (12 MB) |
| Script descartable | `scripts/dry_run_canonical_ingest.py` |
| Logs de las 3 corridas | scratchpad, `corrida_fase0*.log` |
| md5 base del dueño, antes y después | `e9c2e4d2f026a4d36389f68639778ea4` (sin cambios) |

---

# ANEXO — Encendido acotado ejecutado (2026-09-03)

> Autorizado por el dueño tras §8. Commits `eab91d0` (código + tests) y `29fb59d` (docs).
> Decisiones tomadas: el guard de nulos va en este PR; el alcance es **cablear + verificar
> en dev**, sin desplegar a producción.

## A.1 Qué se cableó

- **`canonical.PERSISTIBLES_VERIFICADOS`** — los 4 archivos, con el motivo de cada exclusión
  y qué falta para levantarla. Declarada como transitoria en el propio código.
- **`ingest_canonical(solo_archivos=...)`** — acota lo que se **escribe**, no lo que se lee:
  los 26 archivos se siguen recorriendo y reportando en `mm_excel_reports`, porque ese
  reporte es el instrumento con el que se decide qué habilitar después. Lo omitido se
  declara en el resultado (`skipped_by_scope`) y en el log. Default `None` = comportamiento
  histórico, para que nadie reciba un recorte por sorpresa.
- **`operations.py`** — `macro-canonical-sync` pasa la lista blanca.
- **Guard de nulos §2.2.1** — `if r.value is not None:` en la rama de actualización.

## A.2 Sensores

**S1 · guard de nulos, con dientes.** El test entre corridas se corrió **primero contra el
código viejo** y falló con el síntoma exacto: `AssertionError: assert None == 3.14`. Con el
fix, verde. Los otros dos tests nuevos (que un valor real posterior SÍ actualiza, y que un
período nulo se completa cuando el dato aparece) pasan en ambos: son la contracara, para que
el guard no congele la serie.

**S2 · el alcance acota.** Cuatro tests, corridos contra la firma vieja: **fallaron los
cuatro**. Fijan la semántica, no la lista: se escribe lo acotado, se reporta todo, sin
`persist` no se escribe nada, y un archivo habilitado tiene que existir en el `REGISTRY`.

**S3 · corrida real contra copia de la base dev.**

| | corrida 1 | corrida 2 |
|---|---:|---:|
| archivos leídos / reportados | 26 | 26 |
| ok · marcados · fallidos | 16 · 10 · 0 | 16 · 10 · 0 |
| omitidos por alcance | 22 | 22 |
| observaciones persistidas | 5.881 | 5.881 |
| `mm_series` | **6.390** filas · 34 series | **6.390** filas · 34 series |

**Idempotencia: 0 claves que aparezcan o desaparezcan, 0 valores que cambien, y 0 valores
no-nulos que pasen a nulo** — el guard §2.2.1 verificado en vivo, no solo en test. Las 4
series de la vía de proyección quedan completas (77 · 235 · 511 · 33, todas sin nulos) y
**las 7 series preexistentes quedan intactas: 0 cambios**.

**S4 · los tres gates.** `ruff`: verde. `mypy | mypy-baseline filter`: **exit code 0**.
`pytest`: 7.433 pasados con un fallo que **causé yo** —el guard estructural
`test_directorio_sqlite.py` detectó que el script descartable construía un engine sin
`ensure_sqlite_directory`—. Corregido en el script (el guard tenía razón; eximirlo habría
sido apagar el instrumento) y re-corrido en verde.

## A.3 Hallazgo del entorno: la base dev está una migración atrás

La primera corrida real falló en los 4 archivos con
`sqlite3.OperationalError: no such column: mm_series.nature`. **No es de este cambio:** la
corrida en seco escribía en una base creada desde el ORM y solo LEÍA la dev por SQL crudo,
así que el atraso no se veía. Le falta exactamente una columna (`nature`).

Dos cosas que esto deja dichas, y que importan para el despliegue:

1. La verificación se hizo sobre una copia con la columna agregada. La base dev del dueño
   **no se tocó** — sigue atrasada, y desatascar alembic en dev es trabajo aparte.
2. **El modo de fallo es benigno pero silencioso en el agregado.** `ingest_canonical` captura
   la excepción por archivo, hace `rollback` y sigue: la operación termina «ok» reportando
   `failed: 4` y `persisted: 0`. Nadie ve un error; se ve un contador. Quien despliegue esto
   tiene que mirar `persisted`, no el estado de la operación.

## A.4 Qué sigue

- **No se desplegó a producción.** En prod la base no está vacía y el diff de la fase 0 fue
  contra dev: antes de desplegar hay que repetir el diff contra prod.
- **T-PS-1** (`frequency` + vocabulario C6). Las 5.881 filas entraron con `frequency` NULL;
  el backfill futuro es de 6.390 filas, no de 56.268.
- **T-PS-2**, con tres trabajos: `pib_sectores_origen`, `imae_indice` y **corregir el sufijo
  roto de la entrada `imae`**.
- **Triaje de los 4 archivos excluidos** para levantar la lista blanca, empezando por la
  decisión de diseño de `tipo_cambio` (serie diaria en una identidad mensual).

---

# ANEXO II — T-PS-1: la cadencia se persiste (2026-09-03)

> Decisiones del dueño: cascada **«el período manda, el canónico verifica»** (corrige el
> §3.2 del spec) y **migración + verificación en dev**, sin desplegar.
> El paso 3 de T-PS-1 —el guard de nulos— ya iba en el anexo anterior.

## B.1 Lo que la investigación cambió

**No eran dos vocabularios, eran tres en el mismo campo.** `inference.py:509` escribía
`frequency="trimestral"` mientras sus hermanas de `:489` y `:525` escribían `"quarterly"` y
`"annual"` — tres líneas de distancia, misma función. El caché de layouts tenía los cuatro
valores conviviendo: `quarterly`, `annual`, `None` y `trimestral`. Corregido, y vigilado por
un test **estructural** que lee el código con `ast`: el defecto vivía en una rama de tres, y
un test de comportamiento solo cubre la rama que su fixture activa.

**El vocabulario lo decidió un contrato vivo, no una preferencia.** `mm_series.frequency` se
sirve por `/series` de la Data API, que consume PMS, hoy derivándose al leer con una función
que devuelve inglés; y lo escriben en inglés otros siete sitios (`insurance_intel` ×5,
`pension_intel` ×2). Persistir español habría cambiado `quarterly` → `trimestral` en una
respuesta que ya se sirve.

**El §3.2 del spec no se sostiene, y se corrige.** Ordenaba canónico → spec de extracción →
inferencia, marcando lo inferido en un campo `note`. Tres problemas medidos: `mm_series` **no
tiene columna `note`**, así que lo inferido quedaría indistinguible de lo declarado —
justo lo que la doctrina prohíbe; `spec.frequency` viene **`None` en 2 de los 4 archivos**
encendidos; y la declaración del canónico es por SERIE mientras la ingesta es por ARCHIVO
(`imae_2018.xlsx` produce doce series). La etiqueta del período, en cambio, **no es una
inferencia**: la fija el parser y determina la cadencia fila por fila, con cobertura 100%.

Así que la declaración no RESUELVE: **VERIFICA**. Donde declarado y derivado discrepan hay un
eje temporal mal leído, y eso se declara (`cadence_mismatches`) en vez de resolverse en
silencio eligiendo uno.

## B.2 Qué se construyó

- **`shared/data/series_cadence.py`** — hermano de `series_nature.py`. Se promovió a
  `shared/` en vez de escribir una tercera copia del helper que ya duplicaban
  `insurance_intel` y `pension_intel`.
- **`_upsert_records`** puebla `frequency` por fila. Un solo punto de escritura, por donde
  pasan los seis llamadores.
- **`_discrepancias_de_cadencia`** en `ingest_canonical`.
- **Migración `a4c7e1b9d302`**, data-only, con las máscaras `LIKE` independientes del orden
  de ejecución.

## B.3 Sensores

| Sensor | Resultado |
|---|---|
| S1 · se escribe la cadencia | **Verde, con dientes probados**: contra el código viejo salía `{None}` |
| S2 · el contrato de `/series` no se mueve | **Verde: 7 series, 0 cambios de valor** — el sensor que decidió el vocabulario |
| S3 · la discrepancia se declara | Verde, incluido que las 17 entradas sin puente no dan falso positivo |
| S4 · backfill sobre copia de dev | **509 → 0 NULL** (16 quarterly + 493 monthly), **0 valores alterados** |
| S4b · corrida real, 3 veces | 6.390 filas · **0 con `frequency` NULL** · 0 fuera del vocabulario · **0 discrepancias** · idempotente en valor Y en cadencia |
| S5 · los tres gates | `ruff` verde · `mypy` **exit 0** · `pytest` 7.447 |

## B.4 Dos defectos míos que los tests existentes cazaron

**Un diagnóstico que rompía lo que diagnostica.** Puse la verificación de cadencia ANTES del
upsert y sin proteger: un registro con otra forma levantaba `AttributeError` dentro del
`try` del bucle, que lo cuenta como archivo fallido — **los 26 pasaban a `failed` y no se
persistía nada**. Lo cazó `test_ingest_canonical_continues_after_a_failing_file`, que ya
existía. Movido después del upsert y aislado: un diagnóstico observa, no vetea.

**Un test que fijaba el bug.** `test_calibration.py:160` afirmaba
`spec.frequency == "trimestral"`. No estaba protegiendo el vocabulario: lo estaba clavando
en el valor equivocado.

Y el gate mintió una vez: corrí `pytest ... | tail` y el `$?` era el de `tail`, no el de
pytest — «exit code 0» con dos fallos en el resumen. Es la lección que este repo ya tenía
escrita; la línea de resumen es lo que hay que leer.

## B.5 Qué sigue

- **T-PS-2**, con tres trabajos: `pib_sectores_origen`, `imae_indice` y corregir el sufijo
  roto de la entrada `imae`.
- **Triaje de los 4 archivos excluidos**, empezando por `tipo_cambio`: una serie diaria no
  entra en una identidad `(series_code, period)` mensual.
- **Prod**: repetir el diff antes de desplegar, y desatascar alembic en dev (le falta
  `mm_series.nature`) para poder correr la migración ahí.

---

# ANEXO III — T-PS-2: las series que faltaban en el canónico (2026-09-03)

> Decisiones del dueño: arreglar el nombrado además de declarar, y extender el guard.

## C.1 El puente del IMAE: cuál era la correcta se COMPUTÓ

La entrada declaraba `serie_original_variacion_porcentual_interanual` y **ninguna** de las 12
series del archivo termina así. Cuatro candidatas llevan «interanual» en el nombre; contra la
YoY calculada del índice original, sobre 223 períodos:

| candidata | error medio |
|---|---:|
| **`variacion_porcentual_interanual`** | **0,00000 pp** |
| `interanual` | 0,31017 pp |
| `variacion_porcentual_acumulada` | 1,87588 pp |
| `interanual_acumulada` | 1,89979 pp |

Elegir por parecido de rótulo es exactamente cómo se llegó al sufijo roto. Corregido, más la
entrada `imae_indice`: **34 entradas con puente, 0 sin resolver** (antes, 1).

## C.2 El spec nombra el archivo equivocado — se corrige §3.3

| archivo | `last-modified` | contenido |
|---|---|---|
| `PIB_sectores_origen.xls` (el del spec) | **2019-02-23** | «Trim Acum 91-14»: termina en 2014, base vieja |
| **`pib_origen_2018.xlsx`** (el vigente) | **2026-06-29** | 4 hojas, base 2018, 2018-Q1→2025-Q4 |

Es **la trampa 1 otra vez**: el BCRD migró a un archivo base 2018 y el anterior quedó quieto,
igual que `imae.xlsx`. Promover el del spec habría metido al registro una serie de hace una
década que además mezcla períodos anuales y trimestrales.

## C.3 Por qué el PIB sectorial no se nombraba, y qué costaba

El archivo repite cada sector en tres bloques —nivel, tasa de crecimiento, incidencia— así
que sus hojas de volumen encadenado llegan con **64 filas ambiguas**. El pedido de nombres
tenía `max_tokens=2000`: 64 nombres jerárquicos no entran, la respuesta se cortaba a mitad
del bloque de herramienta y se parseaba a **cero nombres**.

Y fallaba **en silencio y pagando**: el log lo decía en INFO —«Claude nombró 0 de 64 filas
ambiguas»—, costaba US$0,11 por nada, y las 128 series quedaban con el número de fila como
nombre. Las hojas hermanas (32 filas) sí entraban: por eso el mismo archivo tenía la mitad de
sus series bien nombradas y la otra mitad no. **Que el TAMAÑO del pedido decida en silencio si
el nombrado ocurre** era el defecto.

Se pide por lotes de 24, con los nombres ya usados compartidos entre lotes —la regla de no
fusionar dos series vale para el pedido entero, no por lote— y el «0 de N» pasa a WARNING.
Resultado: **de 128 series con coordenada a 1**, en 3 lotes por hoja, US$0,23 por el archivo
(que se cachea por layout y se paga una vez).

Y los nombres se verificaron contra el dato, no se aceptaron: **29 de 31** series del bloque
de tasas coinciden con la YoY computada de su nivel con error < 1e-6; las otras 2 son filas de
encabezado sin nivel que comparar. Cero discrepancias.

## C.4 El guard veta ahora las DOS coordenadas

`_sin_sujeto` cubría `_c<n>` (columna) y dejaba pasar `_r<n>` (fila). `agropecuario_r46` dice
en qué FILA estaba, no si mide el nivel, la tasa o la incidencia — la misma pérdida de sujeto
por el otro eje. No vetó nada de lo existente: había **cero** códigos `_rNN` en las 600 series
del canónico. Es la red para la única fila que el modelo no llegó a nombrar (`salud_r69`).

## C.5 Lo que T-PS-2 destapa y NO resuelve

**El nombrado era necesario pero no suficiente.** Con los nombres arreglados, el archivo sigue
sin poder persistirse:

| hoja | series | obs | dup. con valor distinto | series con períodos mezclados |
|---|---:|---:|---:|---:|
| `PIB$_Trim` | 65 | 2.080 | **0** | **0** |
| `PIBK_Trim` | 97 | 3.104 | **0** | **0** |
| `PIB$_Trim_Acum` | 65 | 650 | 252 | 65 |
| `PIBK_Trim_Acum` | 98 | 3.136 | 1.408 | 98 |

Las dos hojas trimestrales —justo las que T-MP necesita— extraen **limpias**. Las dos
acumuladas mezclan períodos anuales y trimestrales dentro de la misma serie. Como la ingesta
es por ARCHIVO y no por hoja, el libro entero queda fuera de `PERSISTIBLES_VERIFICADOS`, y la
entrada entra al registro en `yellow` declarando exactamente esto.

Para habilitarlo hacen falta **una de dos**: arreglar el parseo de las acumuladas, o que el
alcance de escritura se pueda declarar por HOJA y no solo por archivo.

## C.6 Sensores

| Sensor | Resultado |
|---|---|
| S1 · puentes del IMAE | Verde; los 4 fallaban contra el código anterior |
| S2 · ninguna entrada con puente sin resolver | **34 con puente, 0 sin resolver.** Más dos guards: lo habilitado debe ser `green`, y el registro no puede apuntar a un archivo congelado |
| S3 · la ingesta encendida no se mueve | 6.390 filas, **0 valores y 0 cadencias cambiados**, 0 discrepancias; `omitidos` 22 → 23 |
| S4 · los tres gates | `ruff` verde · `mypy` **exit 0**, sin sumar baseline · `pytest` verde |

---

# ANEXO IV — Alcance de escritura POR HOJA (2026-09-03)

> Sale del hallazgo de T-PS-2: un libro con hojas buenas y hojas rotas quedaba entero afuera
> porque la ingesta es por archivo.

## D.1 Diseño

- **Una sola estructura.** `PERSISTIBLES_VERIFICADOS` pasa de lista a
  `{archivo: None | [hojas]}`: `None` habilita el archivo entero, una lista habilita solo esas
  hojas. Dos estructuras paralelas —archivos por un lado, hojas por otro— se desincronizan.
- **El filtro es por prefijo de código**, `bcrd.xls.<archivo>.<slug_de_hoja>.`, armado con el
  `_slug` y el `default_prefix` del propio motor. Reconstruir a mano un identificador derivado
  es cómo se llega a un filtro que no encuentra nada y se lee como que la hoja venía vacía.
- **⚠️ El punto final del prefijo no es cosmético.** `pib_trim` es prefijo de `pib_trim_acum`:
  sin él, habilitar la hoja limpia arrastra la rota — exactamente lo que este alcance existe
  para impedir. Demostrado: el filtro sin punto devuelve `['pib_trim', 'pib_trim_acum']`.
- **Declarar hojas que no producen nada FALLA ruidosamente.** Un nombre mal escrito, o un libro
  de una sola hoja (donde el motor no pone segmento de hoja), quedan como `failed` con el
  motivo en el reporte. Escribir cero en silencio se lee, meses después, como que la fuente
  dejó de traer datos.

## D.2 Resultado

| | |
|---|---:|
| `mm_series` | **6.390 → 11.574** filas |
| series nuevas | **162** (65 de `PIB$_Trim` + 97 de `PIBK_Trim`) |
| rango | 2018-Q1 → 2025-Q4, **una sola cadencia**: `quarterly` |
| observaciones de las dos hojas ACUMULADAS | **0** |
| series con coordenada (`_cN`/`_rN`) persistidas | **0** |
| idempotencia (2ª corrida) | 0 valores, 0 cadencias, 0 claves de diferencia |
| discrepancias de cadencia | 0 |

Las 162 series quedan repartidas en cuatro bloques **nombrados**: nivel (67), ponderación
(32), incidencia (32) y tasas de crecimiento (31). El guard vetó `salud_r69` —la única fila
que el modelo no llegó a nombrar—, que es el comportamiento correcto: se declara la ausencia
en vez de publicar una serie que no dice qué mide.

## D.3 El guard de robustez, ahora por hoja

`robustness` sigue describiendo el ARCHIVO. La regla pasa a: un archivo habilitado **entero**
debe ser `green`; uno habilitado **por hojas** puede ser `yellow` —eso es justamente lo que
`yellow` significa: parte del libro no extrae limpio— siempre que nombre cuáles. Una lista
vacía se rechaza: sería habilitar nada pareciendo que se habilitó algo.

## D.4 Qué queda

- **Las dos hojas acumuladas** (`PIB$_Trim_Acum`, `PIBK_Trim_Acum`) siguen fuera: mezclan
  períodos anuales y trimestrales en la misma serie, con 1.660 duplicados de valores
  distintos. Entran cuando su parseo se arregle.
- **Los 4 archivos con «último gana»** (`TASA_DOLAR_REFERENCIA_MC`, `lleg_total`, `piianual_6`,
  `piianual`), empezando por la decisión de diseño de `tipo_cambio`: una serie **diaria** no
  entra en una identidad `(series_code, period)` mensual.
- **Producción**: repetir el diff antes de desplegar, y desatascar alembic en dev.
