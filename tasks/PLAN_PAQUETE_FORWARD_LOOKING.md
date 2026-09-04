# PLAN FINO — Paquete forward-looking · procedencia, persistencia, proyección, valuación

> v1 · 2026-09-03 · Desglose ejecutable, paso a paso. Introduce el **primer componente
> prospectivo** de SDQMIP: los 17 ejes actuales describen lo que pasó; esto abre la vía
> para decir algo sobre lo que va a pasar sin romper la disciplina de procedencia.
>
> **Specs rectoras:** `docs/SPEC_PROCEDENCIA_PROYECCION.md` (vocabulario),
> `docs/SPEC_PERSISTENCIA_SERIES_BCRD.md` (datos),
> `docs/SPEC_MOTOR_PROYECCION_MACRO.md` (modelos), `docs/SPEC_VALUADOR_ENTIDADES.md` (eje nuevo).
>
> **Cómo se ejecuta (no negociable, doctrina de calidad):** UNA tarea a la vez. Antes de
> implementar cada T, Claude Code confirma su plan fino con el dueño. Antes de cerrar:
> sensor mostrado + reviewer subagent en lo no trivial. Prohibido correr el lote de corrido.
>
> Las firmas, líneas y cifras citadas fueron leídas del código al 2026-09-03 y auditadas
> en dos rondas. Si un archivo cambió, **releer antes de tocar** — no asumir.

---

## Principios del paquete (no cambian)

- **Una proyección no es dato real, ni rúbrica, ni brecha.** Es una cuarta cosa, con
  requisitos de entrada propios: modelo, intervalo y error de backtest fuera de muestra.
- **Ancla pero no cubre.** `PROJECTED` puede sostener una afirmación; **nunca** suma a
  `coverage_real`. Si sumara, cualquier producto podría inflar su cobertura proyectando lo
  que no midió. Esa asimetría es el paquete entero.
- **El ledger antes que el modelo.** Un producto de proyección que sale sin registro de
  pronósticos nunca lo retrofitea, porque hacerlo obligaría a admitir que los primeros
  trimestres no se midieron.
- **No competimos con el BCRD proyectando PIB anual.** La ventaja es oportunidad
  (nowcast antes de la cifra), granularidad (17 sectores) y verificabilidad (track record
  publicado).
- **La escala de letras SDQ-AAA…D está RETIRADA** (`CLAUDE.md`). El guard
  `test_sin_notacion_heredada.py` lee `ast` sobre `modules/` y `shared/` — **no cubre los
  `.md`**. En documentación la disciplina es manual. El eje `valuation` no produce letras
  ni bandas: su salida es valor en RD$ y múltiplo implícito derivado.
- **Nunca importar de otro módulo.** Si `valuation` necesita algo de `banking_score`, se
  promueve a `shared/`, no se copia. Hay una violación cruzada en producción
  (`insurance_intel/scoring/perfil_sdq.py:546`); no se replica.

## Los TRES gates de CI (los tres, no solo pytest)

```bash
pytest modules/ shared/ -q
ruff check modules/ shared/ app/                      # ruff==0.16.0
mypy shared/ modules/ app/ 2>&1 | mypy-baseline filter # mypy==1.17.1 + baseline
```

`mypy-baseline` sale con código NO CERO también cuando **resolviste** deuda ("Great
work!"). Mirá el **exit code**, no el texto. Y corré mypy sobre `shared/ modules/ app/`
completo — sobre un subdirectorio, el resto del baseline aparece como resuelto y el
veredicto miente.

---

## Mapa de bloques y dependencias

```
T-PS-0 (seco) ──▶ T-PS-1..4 ──┐
                               ├──▶ T-MP-0..6 ──▶ T-VL-0..8
T-PP-1..2 ─────▶ T-PP-3..6 ───┘
```

`T-PS` y `T-PP` son independientes entre sí: **pueden ir en paralelo**. `T-MP` requiere
ambos bloques completos. `T-VL` requiere `T-MP`.

| Bloque | Tareas | Spec |
|---|---|---|
| **PS** — Persistencia de series BCRD | T-PS-0 … T-PS-4 | `SPEC_PERSISTENCIA_SERIES_BCRD` |
| **PP** — Procedencia de proyección | T-PP-1 … T-PP-6 | `SPEC_PROCEDENCIA_PROYECCION` |
| **MP** — Motor de proyección macro | T-MP-0 … T-MP-6 | `SPEC_MOTOR_PROYECCION_MACRO` |
| **VL** — Valuador de entidades | T-VL-0 … T-VL-8 | `SPEC_VALUADOR_ENTIDADES` |

## Criterio de cierre del paquete

Cierra cuando: (a) `coverage_real` de los 17 productos existentes es **idéntico** antes y
después, verificado por diff de `scripts/build_estado.py`; (b) una pregunta prospectiva con
proyección admisible pasa el gate de honestidad y sin backtest no pasa; (c) el nowcast le
gana a un random walk fuera de muestra; (d) el test de identidad del valuador y su hermano
están verdes; (e) los tres gates de CI verdes en todo el paquete.

---

## GATE PREVIO · Decisiones del dueño

Tres decisiones fijadas en los specs que **conviene cerrar antes** de arrancar T-PP-1 y
T-VL-3. No bloquean T-PS.

> **GATE CERRADO — 2026-09-04, las tres confirmadas por el dueño.**

- [x] **Asimetría de cobertura** (`SPEC_PROCEDENCIA` §3.3): `PROJECTED` ancla pero **no suma
      a `coverage_real`**. CONFIRMADO. `coverage_projected` va al lado, como propiedad
      hermana; ningún producto existente mueve su cobertura.
- [x] **`MIN_OOS = 12`** (`SPEC_PROCEDENCIA` §3.4): CONFIRMADO tal cual. Queda como
      constante de archivo, recalibrable por PR con justificación.
- [x] **`N ≥ 8`** (`SPEC_VALUADOR` §5.4): CONFIRMADO tal cual.

---

# BLOQUE PS · Persistencia de series BCRD

> ## ⚠️ Correcciones verificadas antes de T-PS-0 · 2026-09-03, rama `claude/bcrd-canonical-ingest-phase0-efa957`
>
> **Estado: la corrida en seco de T-PS-0 TODAVÍA NO SE EJECUTÓ.** Lo de abajo sale de
> verificación estática contra el código y de lecturas de solo-lectura sobre la base dev.
> Lo que solo puede responder la corrida (conteos de §4.1, diff de colisiones) sigue
> abierto y está marcado como tal.
>
> **C1 · Las specs rectoras no están en el repositorio.** `docs/SPEC_PERSISTENCIA_SERIES_BCRD.md`
> y este mismo plan existen únicamente como archivos SIN COMMITEAR en el checkout principal,
> que está parado en `claude/los-22-tramites-con-nombre`. No están en ninguna rama ni en el
> historial. Cualquier worktree que trabaje el paquete arranca ciego. Copiados a esta rama
> el 2026-09-03 (`docs/` y `tasks/`, idénticos por md5) — **el original sigue donde estaba
> y no se tocó.** Decisión pendiente del dueño: cuál de las dos copias es la fuente de verdad.
>
> **C2 · Las referencias a `service.py` y `canonical.py` apuntan a otra base.** Se
> escribieron contra el checkout principal. Contra `main` (e46dfbe, base de esta rama):
>
> | Citado | Real en `main` | Qué es |
> |---|---|---|
> | `service.py:425` | **`:455`** | `persisted = ... if persist_series else 0` |
> | `service.py:501` | **`:531`** | ídem con `persist` |
> | `service.py:388-390` | **`:418-420`** | firma de `run_excel_batch` |
> | `service.py:477` | **`:507`** | firma de `ingest_canonical` |
> | `service.py:526` | **`:556`** | `start_canonical_ingest_background` |
> | `service.py:641` | **`:669`** | `start_excel_batch_background` |
> | `service.py:45-96` | **`:64-127`** | `_upsert_records` |
> | `service.py:88` | **`:118`** | `row.value = r.value` incondicional (el bug de §2.2.1) |
> | `service.py:1049` | **`:1079`** | `_infer_frequency` |
> | `canonical.py:125`, «24 entradas» | **`:228`, `50` entradas** | `REGISTRY` |
> | `models.py:41` | **`:40`** | `frequency String(20)` |
> | `dataset.py:30` | **`:29`** | `IMAE_INDEX_CODE` |
>
> `api/router.py:548, 599` y `operations.py:196, 243-251` **sí** son correctas.
> Regla que el propio plan ya trae y que acá aplica: **releer antes de tocar.**
>
> **C3 · `REGISTRY` tiene 50 entradas, no 24.** Los commits #1001 y #1006 agregaron 26
> series de IPC generadas (5 quintiles, 5 costo de canasta, 12 grupos COICOP, 4 regiones).
> Ninguna existe en la base contra la que se escribió el spec. Son 26 archivos fuente
> únicos.
>
> **C4 · El inventario de entradas sin `excel_series_suffix` es de 17, no de 2.**
> Esto no es un detalle: es la lista de excepciones que T-PS-4 tiene que congelar, y pasa
> de dos líneas a un tercio del registro. Además de `pib_nominal_gasto` e
> `inflacion_interanual`: `ipc_subyacente`, `balanza_pagos_mbp6`, `balanza_pagos_mbp5`,
> `remesas`, `pii_mbp6`, `pii_mbp5`, `tpm`, `agregados_monetarios`, `base_monetaria`,
> `tasa_activa`, `tasa_pasiva`, `tipo_cambio`, `tasa_ocupacion`, `tasa_desocupacion`,
> `llegada_turistas`.
>
> **C5 · La «corrida en seco» de T-PS-0, tal como está escrita, NO es seca.**
> `_upsert_excel_report` (`service.py:406`) escribe SIEMPRE, con `persist=False` incluido:
> `ingest_canonical` upserta una fila de `mm_excel_reports` por archivo pase lo que pase.
> `persist` solo gobierna `mm_series`. Correr el paso 1 contra la base del dueño la muta.
> **T-PS-0 se corre contra una COPIA de la base dev.**
>
> **C6 · `frequency` colisiona en DOS vocabularios, y eso rompe la cascada de T-PS-1.**
> `CanonicalSeries.frequency` está en español (`mensual` 41 · `anual` 5 · `trimestral` 4);
> `ExtractionSpec.frequency` (`bcrd_excel/spec.py:78`), el esquema del intérprete
> (`interpreter.py:49`) y `_infer_frequency` (`service.py:1079`) están en inglés
> (`monthly` | `quarterly` | `annual` | `unknown`). La cascada canónico → spec → inferencia
> escribiría los dos idiomas en la misma columna, y la aserción de §4 «el `frequency` de la
> fila coincide con el del canónico» **sería falsa por construcción** para toda serie
> resuelta por el escalón 2 o 3. **T-PS-1 necesita fijar el vocabulario ANTES de propagar
> nada.** El comentario de `models.py:40` ya declara el inglés.
>
> **C7 · Confirmado sin necesidad de la corrida — §2.1, §2.2 y las trampas 2 y 3.**
> Base dev (solo lectura): `mm_series` = **509 filas**, **7** `series_code`, 491 de ellas de
> `bcrd.inflacion.inflacion.interanual`; el corpus Excel no aparece. `frequency` NULL en
> **509/509** — el backfill de T-PS-1 es sobre el 100% de la tabla, no sobre un resto.
> Trampa 2: `PIB_sectores_origen.xls` **no está** en `REGISTRY` y **sí** está en el catálogo
> — confirmada. Trampa 3: la única entrada de IMAE es `imae_2018.xlsx` con
> `excel_series_suffix="serie_original_variacion_porcentual_interanual"`; `imae.xlsx` no
> figura en `REGISTRY`, así que el apuntador de la trampa 1 está bien **en el canónico**
> (queda por barrer si algún consumidor apunta al congelado). El índice no se declara y
> `tpm_modeling/dataset.py:29` lo consume igual — confirmada.
>
> **C8 · `comunicado_tpm` NO existe en la base dev.** Responde por adelantado el paso 4 de
> T-MP-0: la tabla no está (solo `tpm_forecast_log`, 2 filas), y `mm_series` no tiene una
> sola fila de `bcrd.xls.imae_2018.*`. El `[Likely]` de §3.4 del spec —que el panel de
> `tpm_modeling` está vacío en este entorno— queda **confirmado**.
>
> **C9 · Costo de la corrida, a medir y reportar.** `ingest_canonical` cablea
> `use_claude=True` y no expone `force`. `structure_hash` incluye `nrows x ncols`
> (`workbook.py:77`), así que un archivo con datos nuevos **cambia de hash y se re-infiere
> con Claude**. La caché de descargas local es del 23-jul y el `imae_2018.xlsx` remoto tiene
> `last-modified` 2026-08-25: para decidir con el dato de hoy hay que descargar fresco, y
> eso implica re-inferencia. Se mide el número de llamadas y el costo, y se reporta.
>
> **Sigue abierto, solo lo contesta la corrida:** los conteos de §4.1 —sobre todo si
> `pib_real` llega a 60 trimestres, que es el gate de T-MP-0 paso 2— y el diff de
> colisiones que cambian valor.


> **Causa raíz, verificada:** el pipeline de ingesta Excel **funciona**. `persisted = 0`
> es un flag `persist=False` por defecto en los cinco niveles de la cadena
> (`service.py:425, 501, 388-390, 477, 526, 641`; `api/router.py:548, 599`), no un ETL
> faltante. Los 10 archivos corrieron en modo reporte de cobertura: extrajeron, contaron y
> descartaron. El único punto cableado en `True` es la operación programada
> `macro-canonical-sync` (`operations.py:196`), que aparentemente nunca corrió.

## T-PS-0 · Corrida en seco y diff — `scripts/` (NUEVO, descartable)

**Esta tarea NO termina en merge. Termina en decisión del dueño.**

### Pre-requisitos de lectura
- [ ] `docs/SPEC_PERSISTENCIA_SERIES_BCRD.md` §2.1 (causa raíz), §2.4 (las tres trampas), §3.1.
- [ ] `modules/macro_monitor/service.py`: `_upsert_records` (**`:64-127`**), `ingest_canonical` (**`:507`**). ⚠️ C2
- [ ] `shared/data/bcrd_excel/canonical.py`: `CanonicalSeries` (`:27`), `REGISTRY` (**`:228`, `50` entradas**, 26 archivos fuente). ⚠️ C3

### Pasos atómicos
- [ ] **1.** Script instrumentado en `scripts/`, marcado como descartable en el propio archivo, que vuelca a JSON los registros que *habría* escrito.
      ⚠️ **C5 — dos correcciones al método:** (a) se corre contra una **COPIA** de la base dev,
      porque `_upsert_excel_report` escribe `mm_excel_reports` aunque `persist=False`; (b) se
      llama `ingest_canonical(db, persist=True)` con `service._upsert_records` **interceptado**:
      el wrapper captura los registros y delega en el `_upsert_records` REAL contra una base
      scratch vacía. Con `persist=False` no se ejercita la rama que se va a encender —se mediría
      el camino viejo— y se perderían el dedupe, el filtro `_sin_sujeto` y el `infer_nature`.
- [ ] **2.** Informe de diff contra `mm_series` con: `series_code` nuevos · colisiones · **colisiones que cambian valor** (cifra crítica, con series/period/viejo/nuevo) · registros con `value=None` que colisionarían con un valor no nulo.
- [ ] **3.** Verificar los conteos de §4.1. **`pib_real` es el número que decide** si el BVAR de T-MP-3 procede.
- [ ] **4.** Confirmar o refutar las tres trampas de §2.4: apuntador a `imae_2018.xlsx` y no al congelado · `PIB_sectores_origen.xls` fuera de `REGISTRY` · del IMAE solo se ingiere la variación interanual, no el índice.
- [ ] **5.** Inventario completo de entradas de `REGISTRY` sin `excel_series_suffix`.
      ⚠️ **C4 — ya levantado: son 17 de 50**, no dos. Lista completa en el bloque de correcciones.
      Lo que queda para la corrida: qué `series_code` produce de hecho cada uno de esos 17
      archivos, para separar «no tiene puente» de «además no tiene serie».

### Sensor T-PS-0 (criterio de parada)
- [ ] Informe en `tasks/` con los cinco puntos y recomendación explícita de encender o no.
- [ ] **NO encender `persist=True`. NO abrir PR de código productivo.** El dueño revisa el diff: una colisión que cambia un valor histórico es alarma, no detalle de merge.
- [ ] Si algún supuesto del spec resulta falso, se reporta con evidencia y **se corrige el spec** — no se fuerza la realidad para que encaje.

---

## T-PS-1 · `frequency` y el guard de nulos — `modules/macro_monitor/service.py` (EDIT)

### Pre-requisitos de lectura
- [ ] T-PS-0 aprobado por el dueño. Si no, parar.
- [ ] `service.py:64-127` `_upsert_records` completo, con atención a la rama `else` (**`:118`**). ⚠️ C2
- [ ] `models/models.py:22-51` (`mm_series`), en particular `frequency String(20)` (**`:40`**) y `UniqueConstraint("series_code","period")` (`:26`).

### Pasos atómicos
- [ ] **0.** ⚠️ **C6 — FIJAR EL VOCABULARIO ANTES DE PROPAGAR NADA.** La cascada cruza dos
      idiomas: el canónico dice `mensual|trimestral|anual`, y el spec de extracción
      (`spec.py:78`), el esquema del intérprete (`interpreter.py:49`) y `_infer_frequency`
      dicen `monthly|quarterly|annual|unknown`. Propagar tal cual escribe los dos en la
      misma columna y vuelve **falsa por construcción** la aserción de §4 «coincide con el
      canónico». `models.py:40` ya declara el inglés en su comentario: decidir y normalizar
      en un solo punto, del lado de la escritura.
- [ ] **1.** Propagar `frequency` en `_upsert_records` con la cascada de §3.2: canónico → spec de extracción (`bcrd_excel/spec.py:78`) → `_infer_frequency` (**`service.py:1079`**) como último recurso **y marcado en `note`**.
- [ ] **2.** Migración Alembic con backfill de `frequency` en las filas existentes. Una columna a medias es peor que vacía: invita a confiar en ella.
      ⚠️ **C7 — el backfill es sobre el 100% de la tabla:** `frequency` es NULL en **509/509**.
- [ ] **3.** **Guard de nulos en el upsert (§2.2.1).** **`service.py:118`** hace `row.value = r.value` incondicional, incluido `None`. La regla "último gana salvo nulo" vive solo en el dedupe intra-lote. Un lote posterior con un vacío **borra un valor ya publicado**. Aplicar `if r.value is not None:` en la rama `else`.

### Sensor T-PS-1
- [ ] Test que persiste un valor, corre un segundo lote con `value=None` para la misma `(series_code, period)`, y verifica que **el valor sobrevive**. Es un bug de pérdida de datos, no una mejora.
- [ ] Test: toda fila escrita tras el cambio tiene `frequency` no nulo, y coincide con el canónico cuando la serie está en `REGISTRY`.

---

## T-PS-2 · Series faltantes en el canónico — `shared/data/bcrd_excel/canonical.py` (EDIT)

### Pasos atómicos
- [ ] **1.** Entrada `pib_sectores_origen` (§3.3): trimestral, declarando `homogenization`, `rationale` y `robustness` como las otras 24.
- [ ] **2.** Entrada `imae_indice` (§3.4): mismo `source_file="imae_2018.xlsx"`, pero `excel_series_suffix="serie_original_indice"`. **La serie YoY existente (`:171`) NO se toca** — son dos series, no una corregida.
- [ ] **3.** Documentar en el propio registro por qué hacen falta las dos: la YoY no permite construir el agregado trimestral que la bridge equation necesita, y `tpm_modeling` ya consume el índice por `series_code` (`tpm_modeling/dataset.py:30`) sin que el canónico lo declare.

### Sensor T-PS-2
- [ ] Corrida en seco de las dos entradas nuevas: cobertura por sector de `pib_sectores_origen` y continuidad de `imae_indice`, antes de persistir.

---

## T-PS-3 · Encender la ingesta — `modules/macro_monitor/operations.py` (EDIT)

### Pasos atómicos
- [ ] **1.** Verificar que `macro-canonical-sync` (`operations.py:196, 243-251`, `default_interval_hours=720`) esté activa en la consola de Ops.
- [ ] **2.** Verificar `control_de_tamano` del motor antes de encender: la cascada de recálculo no debe disparar reprocesamiento masivo al llegar dato nuevo.
- [ ] **3.** Encender y confirmar los conteos de §4.1 contra la realidad.

### Sensor T-PS-3
- [ ] Conteos confirmados **o replanteados con evidencia**. Si `pib_real` < 60 trimestres, **avisar al dueño antes de que T-MP entre a build**.
- [ ] Diff de `scripts/build_estado.py` antes/después adjunto al PR.

---

## T-PS-4 · Integridad permanente — `modules/macro_monitor/tests/test_persistencia_canonica.py` (NUEVO)

### Pasos atómicos
- [ ] **1.** Las 7 aserciones de §4. **Ojo con la primera:** las claves de `REGISTRY` son slugs (`pib_real`) y los `series_code` son jerárquicos (`bcrd.xls.<archivo>.<métrica>`); el puente es `excel_series_suffix`. El test se escribe **contra el sufijo**, con lista explícita de excepciones y motivo por entrada.
      ⚠️ **C4 — la lista de excepciones tiene 17 entradas, no dos**, y hay que darle un motivo
      a cada una. Un test que las meta a todas en una excepción genérica deja de detectar la
      ingesta rota que §4 existe para detectar: 17 de 50 sin cubrir no es una excepción, es un
      agujero. ⚠️ **C6** — la aserción de coincidencia con el canónico depende del vocabulario.
- [ ] **2.** Continuidad sin huecos > 2 períodos en `pib_real`, `imae_indice` e `ipc_general`. Un hueco de un trimestre en el medio es invisible al ojo y fatal para un modelo con rezagos.
- [ ] **3.** Aserción anti-regresión del guard de nulos: ningún valor pasa de no-nulo a nulo entre corridas.

### Sensor T-PS-4
- [ ] Las 7 verdes en CI. Los tres gates verdes.

---

# BLOQUE PP · Procedencia de proyección

> **Punto de enganche, verificado:** `SubQuestion.anchored`
> (`shared/research/models.py:77-80`) devuelve `self.state in (REAL, RUBRIC)`. Esa línea
> es el interruptor. Y `is_forward_looking` (`decompose.py:179-189`) + `_forward_gaps`
> (`orchestrator.py:114-127`) ya detectan lo prospectivo — hoy lo declaran brecha
> ("no se estima"). Falta la vía legítima al otro lado del `if`.

## T-PP-1 · Vocabulario — `shared/registry/signals.py` (EDIT)

### Pre-requisitos de lectura
- [ ] `docs/SPEC_PROCEDENCIA_PROYECCION.md` completo, sobre todo §3.2 y §3.3.
- [ ] `shared/registry/signals.py`: constantes (`:24-26`), `_STATE_ALIASES` (`:48-52`), `normalize_state` (`:55`), `VariableSignal` (`:65-113`), `_real_credit` (`:155-159`).
- [ ] Gate previo de decisiones del dueño resuelto.

### Pasos atómicos
- [ ] **1.** `PROJECTED = "projected"`, tupla `STATES = (REAL, RUBRIC, PROJECTED, GAP)`, alias en `_STATE_ALIASES` (`projected|proyeccion|proyección|forecast|nowcast`).
- [ ] **2.** `normalize_state` **sigue** mandando lo desconocido a `GAP`. Una cadena no reconocida nunca escala a proyección.
- [ ] **3.** Dataclass `ProjectionMeta` frozen con los campos de §3.2. **`model_id` incluye modelo + variante + versión en un solo identificador: NO agregar `model_version` aparte** — versionar dos veces admite que se contradigan.
- [ ] **4.** `projection: Optional[ProjectionMeta] = None` en `VariableSignal`.

### Sensor T-PP-1
- [ ] Tests de normalización: cada alias mapea a `PROJECTED`; una cadena desconocida sigue dando `GAP`.

---

## T-PP-2 · Cobertura y su asimetría — `shared/registry/signals.py` (EDIT)

### Pasos atómicos
- [ ] **1.** `_projected_credit(s)` devuelve `s.real_fraction if s.state == PROJECTED else 0.0`. **`real_fraction`, no `1.0` plano** — simetría con `_real_credit`; un `1.0` plano sobreestimaría la cobertura proyectada en paneles parciales.
- [ ] **2.** `AxisRegistry.coverage_projected` como propiedad **hermana**. `coverage_real` no cambia de definición ni de valor.
- [ ] **3.** `state_counts` (`:147`) y `DataRegistry.summary.by_state` (`:173`) inicializan las 4 claves. Nota: ambos ya acumulan con `.get(k, 0)`, así que hoy **no explotan** con una clave nueva; el cambio es de consistencia de reporte, para que un eje sin proyecciones diga `projected: 0` en vez de omitir la clave.

### Sensor T-PP-2 (el punto de todo el bloque)
- [ ] `shared/registry/tests/test_cobertura_no_se_infla_con_proyeccion.py`: construir un `AxisRegistry` mixto, calcular `coverage_real`, convertir una señal `GAP` en `PROJECTED` admisible, recalcular. **`coverage_real` DEBE SER IDÉNTICO.** `coverage_projected` debe subir.
- [ ] Diff de `scripts/build_estado.py` antes/después adjunto al PR. **Si la cobertura de alguno de los 17 productos se movió aunque sea un decimal, es un bug.**
- [ ] Sin este test verde, el PR no se mergea.

---

## T-PP-3 · Gate de admisión — `shared/registry/projection.py` (NUEVO)

### Pasos atómicos
- [ ] **1.** `projection_is_admissible(meta) -> Tuple[bool, str]` con **todas** las condiciones de rechazo de §3.4, incluidas: intervalos anidados (el de 90% contiene al de 80%) · niveles duplicados · `n_oos_overlapping` no puede ser `None` · `as_of` posterior al fin del período de `horizon`.
- [ ] **2.** `MIN_OOS = 12` en constante de archivo, recalibrable por PR con justificación en el propio PR.
- [ ] **3.** Una proyección que no pasa se degrada a `GAP` y el `str` de la tupla alimenta la nota del `DeclaredGap`. **El motivo no se descarta** — el reporte debe decir *por qué* no se estimó.

### Sensor T-PP-3
- [ ] Tabla de casos límite cubierta, uno por condición de rechazo.

---

## T-PP-4 · Anclaje condicionado — `shared/research/models.py` + `orchestrator.py` (EDIT)

**Leer dos veces antes de implementar.**

### Pre-requisitos de lectura
- [ ] `shared/research/models.py`: `Evidence` (`:19-44`), `_evidence_state` (`:47-60`), `SubQuestion` (`:63`), `anchored` (`:77-80`).
- [ ] `shared/research/orchestrator.py:105-115` (donde se asigna `sq.state = REAL`) y `_forward_gaps` (`:114-127`).
- [ ] `shared/knowledge/ingest.py:36-85` `registry_passages`.

### Pasos atómicos
- [ ] **1.** `anchored` con **desempaquetado de la tupla**:
      ```python
      if self.state == PROJECTED:
          ok, _motivo = projection_is_admissible(self.projection)
          return ok
      return self.state in (REAL, RUBRIC)
      ```
      No es estilo. `projection_is_admissible` devuelve `Tuple[bool, str]` y **una tupla no
      vacía es siempre truthy**: retornarla directo hace que toda señal proyectada quede
      anclada, con o sin backtest — lo contrario exacto de lo que este bloque existe para lograr.
- [ ] **2.** Cableado de `ProjectionMeta` hasta `SubQuestion`, **tres puntos** (§3.4): `registry_passages` propaga la meta al `meta` del pasaje · `Evidence` gana el campo · `orchestrator.py:110` asigna `sq.state` y `sq.projection`.
- [ ] **3.** **NO cablear en `_evidence_state`.** Esa función recibe un `Dict` y devuelve un `str`: no tiene acceso a la `SubQuestion` ni puede escribir en ella, solo clasifica.
- [ ] **4.** `_forward_gaps` consulta el gate antes de declarar brecha.

### Sensor T-PP-4
- [ ] `shared/research/tests/test_proyeccion_sin_backtest_no_ancla.py`, tres casos: `projection=None` · `ProjectionMeta` sin `backtest_id` · `n_oos = MIN_OOS - 1`. Los tres **`anchored is False`** — con `is False`, no `not anchored`.
- [ ] Round-trip: pregunta prospectiva con proyección admisible → `GATE_REPORT`; la misma sin backtest → `GATE_SCOPING`.

---

## T-PP-5 · Prosa — `shared/registry/provenance.py` (EDIT)

### Pasos atómicos
- [ ] **1.** `projection_sentence(axis)` integrada en `provenance_paragraph` (`:140`).
- [ ] **2.** La forma canónica de §3.5 lleva **cuatro elementos**: error de backtest · calibración empírica del intervalo · solapamiento cuando existe · corte de información. Cuando `n_oos_overlapping` es `False`, esa cláusula se **omite** (no se escribe "no se solapan", que sería ruido).
- [ ] **3.** El error va **en la misma frase** que la proyección, nunca en limitaciones al final. Enterrarlo en el apéndice es la práctica que la plataforma existe para no repetir.

### Sensor T-PP-5
- [ ] Golden test de la prosa, con y sin solapamiento.

---

## T-PP-6 · Cerebro y API — `shared/narrative/cerebro.py`, `shared/data_api/router.py` (EDIT)

### Pasos atómicos
- [ ] **1.** Cuarto párrafo en `EPISTEMIC_STANDARD` (texto literal en §3.6). Va en el **núcleo**, no en `AXIS_DOCTRINE`: la regla es de la casa, no de macro.
- [ ] **2.** Bloque `quality` de `shared/data_api/router.py:485-536`: sumar `coverage_projected` y `state_counts.projected`. Es aditivo; ningún consumidor existente se rompe.
- [ ] **3.** Grepear `by_state` en `frontend/` antes de mergear.

### Sensor T-PP-6
- [ ] Barra de insight sin regresión: declarar incertidumbre no es lo mismo que no concluir, y la regla POSTURA sigue vigente con test.
- [ ] Contrato de API verificado como aditivo.

---

# BLOQUE MP · Motor de proyección macro

> **Precondición dura:** T-PS y T-PP completos. Sin series persistidas y sin la categoría
> `PROJECTED`, esto no arranca.
> **Ubicación:** `modules/macro_monitor/forecasting/`, **no un eje nuevo**. `macro` ya está
> productizado, tiene motor de frescura registrado, y la proyección es una capa sobre sus
> mismas series.

## T-MP-0 · Los tres gates de viabilidad

**Antes de escribir una línea de modelo.**

### Pasos atómicos
> **T-MP-0 CORRIDO — 2026-09-04, contra la base espejo de producción. Los tres pasan.**

- [x] **1.** `imae_indice` persistido: `bcrd.xls.imae_2018.serie_original_indice`, **235
      observaciones mensuales** 2007-01 → 2026-07, ninguna nula. PASA.
- [x] **2.** `pib_real`: `bcrd.xls.pib_2018.serie_original_indice`, **77 trimestres**
      2007-Q1 → 2026-Q1, **cero huecos**, ninguna nula. PASA con holgura (77 vs 60): el BVAR
      procede como está especificado.
- [x] **3.** `pib_sectores_origen`: **24 de 24 actividades** continuas, 33 trimestres cada
      una, cero huecos, cero nulas. PASA (el piso eran 12).
      ⚠️ **Pero la PROFUNDIDAD es 33 trimestres, no ~76**: el cuadro por actividad arranca en
      **2018-Q1**, no en 2007 como estimaba §4.1 del spec de persistencia. Con `MIN_OOS = 12`,
      un backtest sectorial se come más de un tercio de la muestra. La sección sectorial es
      viable por el criterio del plan, pero lo que puede AFIRMAR es más chico de lo que el
      spec suponía — y eso es una decisión de alcance, no un detalle.
      ⚠️ Un falso negativo evitado al medir: apuntar al bloque `indices_de_volumen_encadenados`
      (8 series, los agregados) en vez de `indice_de_volumen_por_actividad_economica` daba
      «3 de 3» y el gate habría dicho NO PUBLICA.
- [x] **4.** ⚠️ **C8 — verificado 2026-09-03, base dev: `comunicado_tpm` NO existe.** Solo está
      `tpm_forecast_log` (2 filas), y `mm_series` no tiene una sola fila de
      `bcrd.xls.imae_2018.*`. El panel de `tpm_modeling` está vacío: el `[Likely]` de §3.4 del
      spec queda confirmado. T-MP-3 **no puede apoyarse en la regla de reacción todavía**.

### Sensor T-MP-0
- [ ] Los tres conteos por escrito. Sin dependencias nuevas que instalar.

---

## T-MP-1 · Ledger primero — `forecasting/ledger.py` + `models.py` (NUEVO)

**El ledger va antes que el modelo. No se negocia (§1 del spec).**

### Pre-requisitos de lectura
- [ ] `SPEC_MOTOR_PROYECCION_MACRO` §3.6, §3.6.1, §3.6.2, §3.7.
- [ ] `tpm_modeling/models.py` (`tpm_forecast_log`) como patrón — y como antipatrón: **no tiene `UniqueConstraint`**.

### Pasos atómicos
- [ ] **1.** Estructura de `forecasting/` según §3.1.
- [ ] **2.** ORM `ForecastLog` / `mm_forecast_log`. **Clave única de CINCO campos**, incluido `revision`.
- [ ] **3.** `status` es **solo** `pending | scored` — ciclo de vida de puntuación. El linaje va en `superseded_by`, columna aparte. Un diseño que ponga `"superseded"` como `status` saca la revisión 0 del cómputo y **borra el pronóstico original del historial**, que es lo contrario de lo que `revision` viene a impedir (§3.6.1).
- [ ] **4.** Puntuación automática (§3.7): operación que busca `pending` con observado disponible en `mm_series`, calcula errores, marca `scored`. **Automática, no manual** — un proceso que requiere que alguien se acuerde deja de correr el trimestre en que el resultado es malo.
- [ ] **5.** Puntuar los **dos** niveles de intervalo: `interval_hit_80` e `interval_hit_90`.
- [ ] **6.** Migración Alembic.

### Sensor T-MP-1
- [ ] Test del `UniqueConstraint` incluyendo el caso corrección: revisión 1 entra, **revisión 0 sigue `scored` y sigue contando en el track record**.
- [ ] Ledger escribe y puntúa con datos sintéticos, end-to-end.

---

## T-MP-2 · Nowcast — `forecasting/nowcast.py` + `panel.py` (NUEVO)

### Pre-requisitos de lectura
- [ ] `SPEC_MOTOR_PROYECCION_MACRO` §3.2 completo.
- [ ] `tpm_modeling/dataset.py:28-40` (`PUBLICATION_LAG_DAYS`), `:155` (`build_panel`), `:43-51` (`PanelRow`).
- [ ] `tpm_modeling/backtest.py:34` (`MIN_TRAIN = 90`) y `:164` (`run_backtest`).

### Pasos atómicos
- [ ] **1.** Panel point-in-time con rezagos de publicación. **Las claves de `PUBLICATION_LAG_DAYS` son `series_code` completos**, no nombres cortos: `PUBLICATION_LAG_DAYS["imae"]` es `KeyError`.
- [ ] **2.** **Paso 1 del nowcast:** imputación AR(p) de los meses faltantes del trimestre, estimada con información disponible al `as_of`. Con `m = 3` no corre.
- [ ] **3.** **Paso 2:** agregar el índice mensual a trimestral (promedio) y regresar. **UN solo regresor agregado**, no tres coeficientes mensuales — eso último es MIDAS y está fuera de alcance.
- [ ] **4.** **Tres variantes** (`m=1, m=2, m=3`), cada una con su `model_id` (`bridge_imae_pib.m1.v1`, `.m2.v1`, `.m3.v1`) y **su propio backtest**. No reportar un error promedio entre ellas.
- [ ] **5.** Backtest expanding-window con `MIN_TRAIN` **trimestral propio**. `MIN_TRAIN=90` de `tpm_modeling` es mensual y con ~76 trimestres `run_backtest` devuelve `ok: False` siempre. **Reimplementar el patrón, no reutilizar la constante.** Estimado: ~40 de entrenamiento, ~36 fuera de muestra.
- [ ] **6.** Benchmark naive (random walk) desde esta tarea, no al final.

### Sensor T-MP-2
- [ ] RMSE fuera de muestra por variante; `n_oos` y `n_oos_overlapping` declarados.
- [ ] **Gate:** si el nowcast no le gana consistentemente al random walk, no se publica. Es gate, no riesgo a monitorear.

---

## T-MP-3 · BVAR — `forecasting/bvar.py` (NUEVO)

### Pasos atómicos
- [ ] **1.** Prior Minnesota por **dummy observations sobre OLS** (Bañbura, Giannone & Reichlin). **NO añadir `statsmodels`**: ofrece `VAR`/`VARMAX`/`VECM`, **no** BVAR con prior Minnesota. Añadirlo no resolvería nada.
- [ ] **2.** Hiperparámetros: **`λ₂ = 1` fijo** (lo impone el prior conjugado — no se puede tener verosimilitud marginal en forma cerrada y `λ₂` libre a la vez), **`λ₃ = 2`**, y **`λ₁` por verosimilitud marginal en la ventana de ENTRENAMIENTO**.
- [ ] **3.** El error fuera de muestra **no se mira** para elegir hiperparámetros. Es la vía más fácil de contaminar el backtest: **revisión explícita de este punto en el PR**.
- [ ] **4.** La restricción `λ₂ = 1` se declara en la metodología del reporte, no se esconde.
- [ ] **5.** Enganche con `tpm_modeling` (§3.4): la TPM sale de la regla de reacción ya estimada, no se asume constante. Acoplamiento por lectura dentro del mismo módulo — no cruza frontera.
- [ ] **6.** Salida: distribución predictiva → punto e intervalos 80% y 90%.

### Sensor T-MP-3
- [ ] **Test de límites, obligatorio:** con tightness → 0 el estimador converge al random walk; con tightness → ∞, al OLS sin restringir. Un error de álgebra rompe al menos uno de los dos extremos. Es la única defensa contra un bug silencioso en código que nadie va a auditar línea por línea.
- [ ] Backtest 1 a 8 pasos; cobertura empírica de los dos niveles reportada.

---

## T-MP-4 · Sectorial — `forecasting/sectoral.py` (NUEVO)

### Pasos atómicos
- [x] **1.** Proyección de los 17 sectores con **restricción de agregación**: la suma ponderada reconcilia con el PIB agregado proyectado. El sustrato NO es el cuadro de incidencias —que no cierra en el archivo del BCRD: `VA+impuestos−PIB` nunca da cero, |d| medio 0,22 pp y máximo 1,29, y `Σ(3 grupos)−VA` da −1,945 en 2021-Q4— sino el **cuadro nominal**, donde `17 actividades + impuestos = PIB` da error **0,000000000** en los 33 trimestres.
- [x] **2.** Método elegido **con la data en mano**: persistencia encogida (λ=0,7, re-elegida en cada ventana) más reconciliación proporcional al peso. RMSE **3,07 pp** contra **4,45** de la proporción pura, **+31,2 %**. La regresión sobre el agregado —el «factor model» con factor observado— NO le gana a la proporción pura ni con el agregado realizado a la vista.
- [x] **3.** Un sector con huecos **no se proyecta**: se declara brecha, y la brecha viaja hasta la salida.

### Sensor T-MP-4
- [x] Reconciliación exacta (`Σ wᵢ·gᵢ == g_PIB`, test con `abs=1e-12`); sectores no proyectables declarados.
- [x] La partición 17+impuestos=PIB se **comprueba en el dato en cada llamada**, no se supone.
- [x] `verificar_componentes` delata un código movido: ocho de las 18×2 series dependen de una partición del spec interpretado y su pérdida sería silenciosa.

> **Límite declarado, no escondido.** Con índices encadenados la agregación exacta contra el
> PIB *publicado* es imposible: reconstruirlo desde las 17 actividades con pesos nominales
> deja 0,149 pp de error medio (máx 0,63) — **más ajustado que el propio cuadro de
> incidencias del BCRD** (0,22 / 1,29). La reconciliación es exacta contra el agregado que
> publicamos, y esa distancia va a la metodología.

---

## T-MP-5 · Procedencia y reporte — `products.py`, `variable_signals()` (EDIT)

> **Corrección al plan.** Decía «`products.py`, `variable_signals()` (EDIT)». No existe un
> `modules/macro_monitor/products.py`: el producto del eje es `MacroProduct` y vive en
> **`app/products_macro.py`**; y `variable_signals()` **no existía** —había que crearlo, no
> editarlo—. El eje caía al fallback a-nivel-producto.

### Pasos atómicos
- [x] **1.** `variable_signals()` NUEVO en `app/products_macro.py`, con `state=PROJECTED` y `ProjectionMeta` completo para lo proyectado.
- [x] **2.** **El ledger es la fuente de verdad**: `forecasting/procedencia.py` DERIVA la meta en cada lectura y no la guarda en ningún lado. `track_record()` es el único que computa `n_oos`, error, calibración y solapamiento.
- [x] **3.** `coverage_real` no se infla: las señales proyectadas entran con **peso 0**, porque las dos coberturas son ponderadas y una proyectada con peso > 0 entraría al denominador y la BAJARÍA. Hay test que compara con y sin. Corolario: `coverage_projected` del eje da 0,0 y **no es un bug** — mide sustitución del índice, y el índice macro es real.
- [x] **4.** Sección «Desempeño de nuestras proyecciones anteriores» **en el cuerpo** de los dos niveles nombrados, con su texto **computado** del ledger (`forecasting/desempeno.py`), nunca redactado por un modelo. Aparece con o sin resultados.
- [x] **4b.** `forecasting/emision.py`: sin emisión el cableado nunca lleva corriente y no se puede verificar. Nowcast m1/m2 + los horizontes con track record del BVAR; los escenarios se CUENTAN y no se escriben.
- [ ] **5.** SKU y tarifa. **Bloqueado por una decisión del dueño**, no por trabajo: los SKU derivan del `sector_key` (`insight:macro`, `deep_dive:macro`) y el precio ya es una fila de base (`create_tariff`), así que «no hardcodear precio» ya se cumple. Lo que falta decidir es si la proyección se vende **dentro** del eje macro o como SKU aparte — y que §5 pide «suscripción trimestral» cuando `VALID_INTERVALS` solo tiene `once | monthly | annual`.

### Sensor T-MP-5
- [x] Una proyección **sin backtest en el ledger no ancla**: sale con `n_oos = 0` y el gate la rechaza con su motivo, en vez de silenciarse.
- [x] `coverage_real` idéntico con y sin las señales proyectadas.
- [x] `ESTADO_BACKTEST` de clase ya presente en `MacroProduct`.
- [ ] Corrida end-to-end de una pregunta prospectiva contra datos reales — va con T-MP-6, que es quien programa la emisión.

### Lo que la medición destapó (dos defectos VIVOS, ajenos al plan)

Al medir la cobertura por variable en vez de suponerla:

1. **El factor de ACTIVIDAD estaba sin dato en producción.** La doctrina apuntaba a
   `bcrd.xls.imae_2018.variacion_porcentual_interanual`, que la API de prod devuelve **vacía**.
   El código real es `…imae_2018.serie_original_variacion_porcentual_interanual`: **223 obs
   hasta 2026-07**. El comentario del YAML decía que ese código ya se había arreglado una vez
   en 2026 — se rompió de nuevo y nada falló, porque el fixture del test se escribió COPIANDO
   la doctrina.
2. **Una mina de doble escalado en la TPM, que puse yo.** La ingesta canónica ya corrige la
   fracción a por-ciento (`escala_curada`, con tope), y la doctrina seguía declarando
   `scale: 100.0`. Producción todavía sirve los valores viejos, así que no falló; **en cuanto
   la sincronización corriera, la TPM se publicaba como «525 %»** en el contrato que
   `banking_score` consume. Cura: un solo dueño de la escala + guard estructural.

---

## T-MP-6 · Operación y calendario — `operations.py` (EDIT)

### Pasos atómicos
- [x] **1.** `macro-forecast-emit` registrada, **anclada al calendario TRIMESTRAL de la fuente y no al reloj** (un intervalo relativo se desfasa solo: así se sirvió Q1 en informes de agosto en el sync de comercio), con `periodo_actual` para que el scheduler distinga «al día» de «falta un trimestre». Cascada `macro-canonical-sync → macro-forecast-emit` verificada por test.
- [x] **2.** El rezago que manda es el del **IMAE (45 días)**, no el del PIB (60): el valor del nowcast es justamente la ventana de ~15 días entre los dos, y disparar al rezago del PIB llegaría cuando el BCRD ya publicó. `anclaje="trimestral"` usa 45 días, que es el número medido. **El calendario COMERCIAL (cuándo recibe el suscriptor) sigue siendo decisión del dueño** — ver el bloque de decisiones abiertas.
- [x] **3.** Corrida end-to-end contra el corpus real, y **encontró un defecto que ningún test unitario tenía**: `emitir` escribía pronósticos de horizontes **ya cerrados** al corte. El gate los rechaza al publicar, pero eso llega tarde — la fila quedaba en el ledger y `puntuar_pendientes` **no consulta el gate**: los habría puntuado contra un observado que ya existía cuando se escribieron, inflando el track record con retrospectiva. La regla ahora se aplica al ESCRIBIR.

### Sensor T-MP-6
- [x] Cadena completa verificada: emisión → ledger congelado con su `as_of` → meta derivada → veredicto del gate. En el corte válido: 2 pronósticos escritos, 6 escenarios contados y no escritos, 0 vencidos; segunda corrida 0 escritos / 2 duplicados. El gate dice **NO ancla** con `n_oos = 0`, que es el estado honesto del día uno.
- [x] Una emisión vacía **se explica y no falla**: en la ventana entre los dos rezagos la cifra está DETERMINADA por identidad, y decir «sin estimación» haría parecer que falló un modelo que está de más.

---

## T-MP-7 · El producto de proyecciones como eje propio — `products_forecast.py` (NUEVO)

> Nació de una decisión del dueño («se vende aparte») y de una medición que la primera forma
> de cumplirla NO soportaba.

### Lo que se midió antes de construir

| `special:macro-forecast` | |
|---|---|
| ¿es suscripción? | **no** — `is_subscription_sku` solo admite insight/all_access/enterprise |
| intervalos | **solo `once`** — incompatible con el cobro anual decidido |
| acceso que concede | **ninguno** — `sku_grants` devuelve `[]` |

Un `special:` es, por diseño, una compra puntual cotizada a medida cuya entrega media un
analista. Segunda decisión: **eje propio del catálogo**, que gana `insight:macro_forecast`
con intervalos mensual/anual y grants reales **sin tocar `shared/billing`** — código de cobro
en vivo. Comprobado: `allowed_intervals` → `['monthly','annual']`, `sku_grants` →
`[('macro_forecast','insight')]`.

### Pasos atómicos
- [x] **1.** `CatalogEntry` + `MacroForecastProduct` en `modules/macro_monitor/`, con su motor y no en `app/`.
- [x] **2.** Tres niveles. El tercero **no es relleno para cumplir el contrato**: es donde viven los ESCENARIOS a 3-8 trimestres, que deliberadamente no llevan track record.
- [x] **3.** Toda la prosa se **COMPUTA**. No pasa por el motor de IA, y no es una omisión: un informe de errores, coberturas empíricas y una reconciliación exacta no tiene nada que redactar. Un modelo escribiéndola inventaría los números que el producto existe para probar.
- [x] **4.** `variable_signals()` con peso REAL —acá el índice ES la proyección, así que `coverage_projected` sí dice algo, a diferencia del eje macro—. Una proyección que no pasa el gate sale como **GAP con su motivo**, no como `PROJECTED` degradada.
- [x] **5.** Las **cuatro superficies** que el framework exigía, encontradas corriendo sus tests en vez de recordándolas: etiqueta de archivo, resumidor de data-pull, keywords de ruteo y el tercer nivel. Es el patrón del anuario —cuatro registros de a uno, ninguno falla— pero esta vez los guards los cazaron todos.
- [x] **6.** Muestra curada que se renderiza en los tres niveles, y que enseña a propósito **un resultado incómodo**: una proyección que no alcanza a anclar y un intervalo del 90 % que sobre-cubre.
- [ ] **7.** **Tarifa: falta que el dueño fije el precio.** No se hardcodea; se publica con `create_tariff` y hasta entonces el nivel queda inactivo, que es el comportamiento correcto.

### Sensor T-MP-7
- [x] El eje **no invade** a los productos en producción: las seis preguntas típicas de los otros ejes rutean igual que antes. Con keywords amplias el test falla; con keywords vacías falla el contraejemplo. Los dos lados.
- [x] `insight:macro_forecast` admite `annual` y concede grant — comprobado, no supuesto.
- [x] El catálogo del frontend se arma del API: no hay lista hardcodeada que actualizar (verificado).

---

# BLOQUE VL · Valuador de entidades (eje `valuation`)

> **Precondición:** T-MP completo — el valuador consume ROE proyectado.
> **Qué es y qué no:** responde *cuánto vale*, no *qué tan sano está*. `banking_score` ya
> responde lo segundo (Perfil SDQ, propensión a quiebra, alertas tempranas) y **ninguna de
> esas salidas se convierte en un valor**.

## T-VL-0 · Desacople de clientes SIB — `shared/data/` (REFACTOR)

Refactor puro, sin riesgo de negocio. Desbloquea todo el bloque.

### Pre-requisitos de lectura
- [ ] `shared/data/sib_client.py:1-6` (el docstring que declara la regla) y el shim en `modules/banking_score/external/sib_client.py:1-18`.

### Pasos atómicos
- [ ] **1.** Promover a `shared/data/` los tres clientes que traen balance completo y hoy viven en `modules/banking_score/external/`: `sib_data_client`, `sib_historical_client`, `simbad_client`. Dejar shims de compatibilidad, igual que se hizo con `sib_client`.
- [ ] **2.** Regla dura: `valuation` importa de `shared.data`, **nunca** de `modules.banking_score.*`.

### Sensor T-VL-0
- [ ] Tests de `banking_score` verdes **sin cambios**.

---

## T-VL-1 · Datos reales — BLOQUEANTE

### Pasos atómicos
- [ ] **1.** Ingesta real de balance y resultados por entidad y período. `banking_data` tiene 700 filas con `source='manual'` — residuo sintético; el seed ya no fabrica financieros, solo el catálogo de 35 entidades.
- [ ] **2.** El valuador **no se construye sobre eso**: datos sintéticos producen valuaciones sintéticas.

### Sensor T-VL-1
- [ ] Patrimonio y utilidad reconciliados contra el estado publicado de **al menos 3 entidades**.
- [ ] Test que rechaza `source='manual'`.

---

## T-VL-2 · Alta del eje — `modules/valuation/` (NUEVO)

### Pre-requisitos de lectura
- [ ] `shared/products/registry.py:20-27` (`CatalogEntry`), `:31-78` (`PRODUCT_CATALOG`), `:87` (`register_product`).
- [ ] `shared/products/contract.py:300` (`Protocol SectorProduct`).
- [ ] `modules/pension_intel/` como plantilla de estructura.

### Pasos atómicos
- [ ] **1.** `CatalogEntry("valuation", ...)` en `PRODUCT_CATALOG`.
- [ ] **2.** Estructura de `modules/valuation/` según §7 del spec.
- [ ] **3.** `register_product(SECTOR_KEY, ...)` al final de `products.py`.
- [ ] **4.** Cuatro puntos de cableado en `app/main.py`: import del router (~`:110`), `include_router(prefix="/api/v1/valuation")` (~`:138`), `import modules.valuation.operations` (~`:222`), `import modules.valuation.products` (~`:249`).
- [ ] **5.** `ESTADO_BACKTEST` de clase.
- [ ] **6.** `AXIS_DOCTRINE["valuation"]` y `AUDIENCE_FRAMES["valuation"]` en `cerebro.py` (`:302`, `:572`). La primera audiencia declarada es el default.
- [ ] **7.** Migración Alembic `{rev12hex}_add_valuation.py`.

### Sensor T-VL-2
- [ ] Test de contrato de producto verde.

---

## T-VL-3 · Costo de capital — `engine/cost_of_capital.py` (NUEVO)

### Pasos atómicos
- [ ] **1.** `Ke = Rf + β × ERP + CRP`, con descomposición auditable de los cuatro términos.
- [ ] **2.** **La beta NO se desapalanca.** Hamada supone que la deuda es financiamiento y que hay un apalancamiento óptimo separable de la operación; en un banco los depósitos son **materia prima** y esa premisa es falsa — contradiría el argumento de §2 del propio spec. Beta de equity de comparables LATAM, directa.
- [ ] **3.** `β` y `ERP` viajan como `RUBRIC`, no como dato real.
- [ ] **4.** `Ke` se reporta como **rango**, nunca como punto. Tabla de sensibilidad en pasos de 50 pb.
- [ ] **5.** **Decidir y declarar la moneda funcional antes de escribir el motor** (§4.1). `Ke` en USD con `ROE` en RD$ es un error silencioso. **Consultar al dueño si no está fijada.**

### Sensor T-VL-3
- [ ] Test que impide el cruce de monedas.
- [ ] Si el valor cambia de signo dentro del rango razonable de `Ke`, **eso es el hallazgo** y va en el resumen ejecutivo.

---

## T-VL-4 · Excess Return — `engine/excess_return.py` + `terminal.py` (NUEVO)

**Acá se decide si el modelo es correcto.**

### Pasos atómicos
- [ ] **1.** Fórmula de §2, con el terminal como **perpetuidad de residual income** y **descontado por `(1+Ke)^T`**. Si el terminal se calcula sobre utilidad, el modelo dice que una entidad con `ROE = Ke` vale más que su libro — que es falso.
- [ ] **2.** **Clean surplus no se cumple** en el balance SIB (revaluaciones, ajustes de inversiones disponibles para la venta). Reconciliar `BV` período a período contra el patrimonio publicado y reportar la diferencia como **partida explícita**. No absorberla.
- [ ] **3.** **El ROE se recalcula sobre patrimonio de APERTURA** a partir de utilidad y patrimonio. La SIB publica ROE sobre patrimonio promedio; son bases distintas y mezclarlas introduce error sistemático proporcional al crecimiento. El publicado queda como control de consistencia, no como insumo.
- [ ] **4.** `g < Ke` estrictamente, verificado antes de calcular (§8.2). Con `g = b × ROE` esa condición no está garantizada. Si se viola, se acorta el horizonte explícito y se declara.

### Sensor T-VL-4 (los dos tests van juntos)
- [ ] **Test de identidad:** con `ROE = Ke` en todo el horizonte, `valor == BV₀` exacto.
- [ ] **Test hermano:** con `ROE = Ke + 1pp` constante, el valor supera al libro en exactamente el VP de esa diferencia sobre la trayectoria de patrimonio.
- [ ] **Por qué ambos:** con `RI = 0`, un terminal sin descontar sigue siendo 0 y un `BV` mal proyectado se multiplica por cero. El test de identidad solo detecta **uno** de los tres defectos posibles (terminal sobre utilidad); los otros dos los ejerce el hermano. Sin ambos, no hay verificación.

---

## T-VL-5 · Vista board — snapshot, narrativa, render

### Pasos atómicos
- [ ] **1.** Salida: valor con rango por sensibilidad a `Ke` · múltiplo implícito P/B **derivado, no asumido** · descomposición libro vs exceso · spread `ROE − Ke` histórico y proyectado · serie de creación/destrucción de valor.
- [ ] **2.** **El resumen ejecutivo abre con `ROE − Ke`, no con el valor.** Un board que ve el spread entiende la palanca; uno que ve solo el valor discute el supuesto.
- [ ] **3.** Procedencia por componente según §6 del spec.

### Sensor T-VL-5
- [ ] Barra de insight ≥ 4/5 en 4 de 5 entidades reales.

---

## T-VL-6 · Regresión P/B — `engine/pb_regression.py` + `panel/latam_comparables.py` (NUEVO)

### Pasos atómicos
- [ ] **1.** `P/B_i = f(ROE, crecimiento, volatilidad de resultados, tamaño, calidad de cartera)` sobre panel de bancos cotizados LATAM.
- [ ] **2.** Cruzado con Excess Return: **dos motores independientes, un rango**. Si divergen mucho, la divergencia **es información** y se reporta — no se promedia.

### Sensor T-VL-6
- [ ] `R²` y error fuera de muestra reportados sobre el panel.

---

## T-VL-7 · Panel de transacciones — `panel/transactions.py` (NUEVO)

**Es investigación de campo, no ingesta.** No está en ninguna API: son operaciones
bancarias RD/Caribe de la última década, en un mercado con pocas transacciones y
divulgación irregular.

### Sensor T-VL-7
- [ ] `N ≥ 8` con precio sobre valor libro verificable, **o** el gate queda cerrado y se declara.

---

## T-VL-8 · Vista M&A — SOLO tras el gate

### Pasos atómicos
- [ ] **1.** Verificar las tres condiciones de §5.4: `N ≥ 8` · `R²` y error OOS reportados · `Ke` con backtest contra las transacciones del panel.
- [ ] **2.** Mientras no se cumplan: el motor existe, corre y tiene tests, pero **su salida no sale del sistema**.
- [ ] **3.** Implementar como **bandera de readiness del tier**, NO como código comentado.

---

# Puntos de parada obligatoria

Cuatro momentos donde Claude Code **para y consulta al dueño**:

| # | Dónde | Por qué |
|---|---|---|
| 1 | **T-PS-0**, siempre | Termina en revisión humana del diff. Una colisión que cambia un valor histórico es alarma. |
| 2 | **T-MP-0**, si `pib_real` < 60 trimestres | El BVAR no procede como está especificado; hay que replantear el modelo. |
| 3 | **T-MP-6**, calendario de publicación | Decisión comercial, no técnica. |
| 4 | **T-VL-3**, moneda funcional | Si no quedó fijada antes, no se escribe el motor. |

---

# Fuera de alcance (explícito)

- **No** se migra ningún producto existente a `PROJECTED`. Los 17 ejes siguen siendo
  retrospectivos hasta que alguien lo decida, producto por producto.
- **No** `statsmodels` ni ninguna dependencia nueva.
- **No** MIDAS, factores dinámicos, DSGE, ni ML para el punto central de la proyección.
- **No** escenarios condicionales ("¿qué pasa si el turismo cae 10%?") — candidato a tier
  alto por encargo, en otro spec.
- **No** proyección fiscal ni de balanza de pagos, ni de los otros 16 ejes.
- **No** empresas no financieras en `valuation` (existe
  `SDQ Bank Scoring/cash_flow_reconstruction_spec.md.pdf` para eso, en otro spec), ni
  fiduciarias, seguros, pensiones, ni capital económico regulatorio.
- **No** vista de inversionista de deuda en `valuation`: esa pregunta —distancia al
  default— ya la responden `propension_quiebra.py` (40 KB) y `early_warning.py` (58 KB) en
  `banking_score`. Empaquetarla como producto propio es un spec aparte y más corto.
- **No** versionado formal de artefactos de modelo. `model_id` es un string con convención.

---

# Registro de lecciones

Después de cualquier corrección del dueño, actualizar `tasks/lessons.md` con: síntoma,
causa raíz, regla a seguir en el futuro, disparador.

**Lección de partida, ya pagada en este paquete:** los cuatro specs pasaron dos rondas de
auditoría contra código y acumularon 21 correcciones, entre ellas un `anchored` que
siempre devolvía `True` por una tupla sin desempaquetar, un `status = "superseded"` que
borraba el track record, una dependencia ordenada sobre una premisa falsa
(`statsmodels` no trae BVAR-Minnesota) y una fórmula de valuación cuyo test de
verificación no detectaba dos de los tres defectos que decía cubrir. **Disparador:** todo
spec que fije una fórmula, una clave de base de datos o un predicado booleano se audita
contra código antes de entrar a build, no después.
