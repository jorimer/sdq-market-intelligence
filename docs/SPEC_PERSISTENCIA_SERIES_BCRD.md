# SPEC — Persistencia de series BCRD: encender lo que ya funciona

> Versión v0.1 · 2026-09-03 · Documento de construcción.
> Etiquetas de confianza: **[Certain]** verificable contra código/doc citado ·
> **[Likely]** inferencia fuerte, no probada · **[Guessing]** supuesto a validar ·
> **[Lock]** decisión ya tomada por el dueño.

> **Disciplina de notación.** La escala SDQ-AAA…D está RETIRADA. El guard
> `test_sin_notacion_heredada.py` lee `ast` sobre `modules/` y `shared/`, **no cubre
> `.md`**. Disciplina manual.

> **Precondición de datos** de `SPEC_MOTOR_PROYECCION_MACRO` y, por transitividad, de
> `SPEC_VALUADOR_ENTIDADES`. Sin las series trimestrales persistidas no hay nada que
> proyectar.

---

## 0. Qué se construye (BLUF)

**Casi nada de código nuevo. El pipeline ya existe y funciona.**

El diagnóstico inicial —"el extractor lee y no persiste, hay que escribir el ETL"— es
**falso**. Verificado contra código: la escritura está implementada y probada; está
detrás de un flag booleano que vale `False` por defecto en los cuatro niveles de la
cadena, endpoints incluidos. Los 10 archivos de `mm_excel_reports` corrieron en modo
reporte de cobertura: extrajeron 2.996 y 4.620 observaciones, las contaron, y las
descartaron en memoria.

Lo que este spec hace:

1. Enciende la ingesta con `persist=True` de forma controlada y auditable.
2. Corrige un defecto real de contrato: `frequency` nunca se escribe y se re-adivina al
   leer — material para PIB trimestral.
3. Resuelve que `PIB_sectores_origen.xls` **no está** en el registro canónico.
4. Deja una verificación de integridad que corre siempre, no una sola vez.

---

## 1. Principio rector

> Antes de escribir código nuevo, verificar si el existente está apagado.

Este documento existe porque la diferencia entre "no está construido" y "está construido
y en `False`" son semanas de trabajo. La regla general que deja: **ningún diagnóstico de
brecha de datos se acepta sin haber leído el flag.**

---

## 2. Estado real (verificado contra código, 2026-09-03)

### 2.1 La causa raíz

`modules/macro_monitor/service.py:425`:

```python
persisted = _upsert_records(db, r.records) if persist_series else 0
```

Y `service.py:501`, misma forma con `persist`.

Defaults en cadena — **[Certain]**, los cinco:

| Ruta | Firma | Default |
|---|---|---|
| `service.py:388-390` | `run_excel_batch(..., persist_series: bool = False, ...)` | `False` |
| `service.py:477` | `ingest_canonical(db, *, persist: bool = False)` | `False` |
| `service.py:526` | `start_canonical_ingest_background(*, persist: bool = False)` | `False` |
| `service.py:641` | `start_excel_batch_background(..., persist_series: bool = False, ...)` | `False` |
| `api/router.py:548, 599` | `persist: bool = Query(False, ...)` | `False` |

El único punto cableado en `True`: `modules/macro_monitor/operations.py:196` —
`result = ingest_canonical(db, persist=True)`, registrada como `"macro-canonical-sync"`
(`operations.py:243-251`) con `default_interval_hours=720`.

**[Likely]** Esa operación nunca corrió en el entorno inspeccionado. `mm_series` tiene
509 filas, dominadas por una sola serie de inflación mensual; el corpus Excel no aparece.

### 2.2 El defecto real

`_upsert_records` (`service.py:45-96`) escribe `series_code, period, value, unit, source,
published_at, license, nature`. **No escribe `frequency`**, aunque:

- la columna existe (`models/models.py:41`, `frequency String(20)`),
- el spec de extracción la conoce (`shared/data/bcrd_excel/spec.py:78`),
- y al leer se re-adivina con `_infer_frequency` (`service.py:1049`).

**[Certain]** Para una serie trimestral que se va a usar en un modelo con rezagos de
publicación, inferir la frecuencia del formato del período en vez de leerla del registro
es una fuente de error silencioso.

### 2.2.1 Segundo defecto: el upsert pisa dato bueno con `None`

**[Certain]** `service.py:88` — en la rama de actualización:

```python
row.value = r.value   # incondicional, incluido r.value = None
```

La regla "último gana **salvo nulo**" vive únicamente en el dedupe intra-lote
(`service.py:45-96`), no en el upsert contra la fila persistida. Consecuencia: un lote
posterior que traiga un vacío —una celda no publicada todavía, un parse fallido— **borra
un valor ya publicado y correcto**.

Esto es más grave que el `frequency` faltante, porque destruye información en vez de
omitirla, y lo hace en silencio. El fix es el mismo guard de nulos que ya existe aguas
arriba, aplicado también en la rama `else`:

```python
if r.value is not None:
    row.value = r.value
```

### 2.3 Identidad de serie

`models/models.py:22-51` — `mm_series`:
`UniqueConstraint("series_code", "period", name="uq_mm_series_period")`.

**[Certain]** La identidad de una **observación** es `(series_code, period)`. La identidad
de una **serie** es `series_code` solo: la frecuencia no forma parte de ninguna de las dos.
Consecuencia: dos frecuencias de la misma métrica necesitan códigos distintos, y el código
jerárquico `bcrd.xls.<archivo>.<metrica>` ya lo permite.

`value Float NULL` — NULL significa faltante y **no se interpola** (regla del proyecto,
`SPECS_OVERVIEW.md`).

### 2.4 Registro canónico

`shared/data/bcrd_excel/canonical.py` — `CanonicalSeries` (`:27`), **24 entradas** en
`REGISTRY` (`:125`). Las relevantes para proyección:

| Clave | Archivo | Frecuencia | `excel_series_suffix` | Línea |
|---|---|---|---|---|
| `pib_real` | `pib_2018.xlsx` | trimestral | `serie_original_indice` (`:180`) | `:174` |
| `pib_deflactor` | `pib_deflactor_2018.xlsx` | trimestral | `deflactor_del_pib` (`:195`) | `:190` |
| `pib_nominal_gasto` | `pib_gasto.xls` | anual | **ninguno** | `:183` |
| `imae` | `imae_2018.xlsx` | mensual | `serie_original_variacion_porcentual_interanual` (`:171`) | `:163` |
| `ipc_general` | `ipc_base_2019-2020.xls` | mensual | `indice` (`:134`) | `:128` |
| `inflacion_interanual` | `ipc_base_2019-2020.xls` | mensual | **ninguno** | `:147` |

**[Certain] Tres trampas, y la tercera rompe el nowcast:**

1. El canónico apunta a `imae_2018.xlsx`, **no** a `imae.xlsx` — este último quedó
   congelado en oct-2024 (el propio comentario del registro lo dice). Las 2.996
   observaciones del reporte salieron del archivo congelado. Usarlo para nowcast sería
   proyectar con datos de hace dos años.
2. `PIB_sectores_origen.xls` —de donde salieron las 4.620 observaciones trimestrales—
   **no está en `REGISTRY`**. Vino de un barrido de catálogo, no del canónico. Es
   justamente la serie que el eje `economic_structure` y la desagregación sectorial
   necesitan.
3. **El canónico ingiere del IMAE la variación interanual, no el índice.** El
   `excel_series_suffix` es `serie_original_variacion_porcentual_interanual`. La bridge
   equation de `SPEC_MOTOR_PROYECCION_MACRO` §3.2 necesita el **índice** para agregarlo a
   trimestre; con la serie YoY no se puede construir el agregado trimestral correcto.
   Además `tpm_modeling` ya consume `bcrd.xls.imae_2018.serie_original_indice`
   (`dataset.py:30`) — o sea, el índice hace falta y hoy no está declarado en el canónico.

   **[Lock] Fix (§3.4):** añadir una entrada canónica para el índice del IMAE, con clave
   propia (`imae_indice`) y su propio `series_code`. La serie YoY se conserva: son dos
   series, no una corregida.

### 2.5 Dependencias de modelado

`requirements.txt:8-12`: `xgboost>=2.0`, `scikit-learn>=1.4`, `scipy>=1.12`,
`pandas>=2.1`, `numpy>=1.26`. **`statsmodels` NO está** — el docstring de
`tpm_modeling/features.py:5-6` lo documenta: «El HP-filter se implementa con `scipy` (NO
statsmodels, que no está en requirements)». Se resuelve en
`SPEC_MOTOR_PROYECCION_MACRO`, no aquí.

---

## 3. Diseño

### 3.1 Fase 0 — encender, en seco y con diff

**[Lock]** No se enciende `persist=True` a ciegas sobre una base con datos. Secuencia:

1. Correr `ingest_canonical(db, persist=False)` y volcar los registros que *habría*
   escrito a un artefacto JSON.
2. Diferenciar contra `mm_series` actual: cuántos códigos nuevos, cuántos colisionan con
   los 509 existentes, cuántas colisiones cambian de valor.
3. Revisión humana del diff. Una colisión que cambia un valor histórico es una señal de
   alarma, no un detalle de merge.
4. Recién entonces, `persist=True`.

`_upsert_records` dedupe por `(series, period)` con "último gana salvo nulo"
(`service.py:45-96`) — **[Certain]** eso significa que una corrida mal ordenada puede
pisar dato bueno con dato viejo. De ahí el paso 2.

### 3.2 Escribir `frequency`

En `_upsert_records`, propagar `frequency` desde el registro extraído a la columna.
Regla de resolución, en orden:

1. `CanonicalSeries.frequency` si el código pertenece al registro canónico.
2. El `frequency` del spec de extracción (`bcrd_excel/spec.py:78`).
3. `_infer_frequency` como último recurso, **con `note` que lo declare**.

**[Lock]** Backfill de las 509 filas existentes en la misma migración. Una columna a
medias es peor que vacía: invita a confiar en ella.

### 3.3 Promover `PIB_sectores_origen.xls` al canónico

Entrada nueva en `REGISTRY` con clave `pib_sectores_origen`, frecuencia trimestral,
declarando `homogenization`, `rationale` y `robustness` como el resto de las 24.

**[Guessing]** Que las 4.620 observaciones sean directamente utilizables. El barrido de
catálogo no aplica las mismas validaciones que el canónico. La fase de verificación
(§4) tiene que confirmar cobertura por sector y continuidad de la serie antes de
declararla apta.

### 3.4 IMAE: apuntador y serie faltante

Dos cosas distintas:

1. **Apuntador.** Verificar que la ingesta usa `imae_2018.xlsx`. Si algún consumidor
   apunta al `imae.xlsx` congelado, se corrige y se documenta en el PR. La serie congelada
   no se borra — se marca.
2. **[Lock] Serie faltante.** Entrada canónica nueva `imae_indice`, con
   `excel_series_suffix="serie_original_indice"`, mismo `source_file`. Sin ella no hay
   nowcast: es el insumo de la bridge equation, y `tpm_modeling` ya lo consume por
   `series_code` (`dataset.py:30`) sin que el canónico lo declare.

**[Likely]** Que `tpm_modeling` funcione hoy leyendo un `series_code` que ningún camino
canónico persiste sugiere que su panel también está vacío en este entorno — consistente
con que `comunicado_tpm` no exista en la base local. Verificar en la fase 0.

### 3.5 Encender la operación programada

`"macro-canonical-sync"` con `default_interval_hours=720` (30 días) es correcto para un
corpus que se actualiza mensual/trimestral. Se verifica que esté activa en la consola de
Ops y que su cascada de recálculo alcance a los ejes que consumen macro.

---

## 4. Verificación de integridad (permanente, no de una vez)

Test nuevo, `modules/macro_monitor/tests/test_persistencia_canonica.py`:

| Aserción | Por qué |
|---|---|
| Cada `CanonicalSeries` **con `excel_series_suffix`** tiene ≥1 fila en `mm_series` bajo el `series_code` que ese sufijo construye | Detecta ingesta silenciosamente rota |
| Las entradas **sin** `excel_series_suffix` están en una lista explícita de excepciones, con motivo | Que falte el puente es un hecho, no un olvido |
| Toda fila tiene `frequency` no nulo | El defecto de §2.2 no vuelve |
| El `frequency` de la fila coincide con el del canónico | Detecta cruce de códigos |
| Ninguna serie trimestral tiene períodos con formato mensual | Detecta parse equivocado |
| Continuidad: sin huecos > 2 períodos en `pib_real`, `imae_indice` e `ipc_general` | Un hueco silencioso rompe cualquier modelo con rezagos |
| Ningún valor persistido pasa de no-nulo a nulo entre corridas | El defecto de §2.2.1 no vuelve |

**[Certain] Nota de implementación:** las claves de `REGISTRY` son slugs (`pib_real`) y
los `series_code` de `mm_series` son jerárquicos (`bcrd.xls.<archivo>.<métrica>`). El
puente entre ambos es `excel_series_suffix`, y al menos dos entradas no lo tienen:
**`pib_nominal_gasto`** (`canonical.py:183`) e **`inflacion_interanual`** (`:147`). Un test
que asuma correspondencia 1:1 entre las 24 claves y 24 series persistidas falla por
construcción — de ahí la segunda aserción. El inventario completo de entradas sin puente se
levanta en la fase 0 y se congela como lista de excepciones con motivo por entrada.

**[Lock]** La continuidad se verifica en test, no en revisión visual. Un hueco de un
trimestre en el medio de la serie es invisible al ojo y fatal para un modelo.

### 4.1 Conteo esperado tras encender

**[Guessing]** — a confirmar con el diff de §3.1, no a asumir:

| Serie | Frecuencia | Profundidad esperada | Obs. esperadas |
|---|---|---|---|
| `pib_real` | trimestral | 2007→2026 (retropolado) | ~76 |
| `imae_indice` (nueva, §3.4) | mensual | 2007→2026 | ~230 |
| `imae` (YoY, existente) | mensual | 2007→2026 | ~230 |
| `ipc_general` | mensual | 1984→2026 | ~500 |
| `pib_sectores_origen` | trimestral × 17 sectores | 2007→2026 | ~1.300 |

Si `pib_real` sale con menos de 60 observaciones trimestrales, el BVAR del spec de
proyección no es viable como está especificado y hay que replantearlo. **Ese es el
número que decide.**

---

## 5. Fases de build

| Fase | Alcance | Cierre |
|---|---|---|
| 0 | Corrida en seco + diff contra `mm_series` + revisión humana | Diff adjunto al PR, cero colisiones que cambien valores históricos |
| 1 | `frequency` en `_upsert_records` + migración de backfill | Test de frecuencia verde sobre las 509 filas viejas |
| 2 | `pib_sectores_origen` al canónico | Cobertura por sector verificada |
| 3 | Encendido de `persist=True` + operación programada activa | Conteos de §4.1 confirmados o replanteados |
| 4 | Test de integridad permanente | Las 7 aserciones de §4 verdes en CI |

Los tres gates de CI aplican íntegros (`CLAUDE.md`): `pytest`, `ruff check`, y
`mypy | mypy-baseline filter` mirando el **exit code**, no el texto.

---

## 6. Riesgos

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Encender `persist=True` pisa las 509 filas existentes con dato peor | Alta | Fase 0 obligatoria. El diff es el gate. |
| Las 4.620 obs de `PIB_sectores_origen` tienen huecos o cambio de base | Media | Test de continuidad §4; si falla, se declara brecha y no se usa |
| El retropolado 2007 del PIB base 2018 no es comparable con el tramo reciente | Media | Se declara en `homogenization` del canónico y llega al reporte por procedencia |
| El backfill de `frequency` adivina mal en series viejas | Baja | Cascada de §3.2: canónico → spec → inferencia con nota. Lo inferido queda marcado. |
| La cascada de recálculo de Ops dispara reprocesamiento masivo al llegar dato nuevo | Media | Verificar `control_de_tamano` del motor antes de encender la operación |

---

## 7. Fuera de alcance v1

- **No** se añade `statsmodels`. Esa decisión es del spec de proyección.
- **No** se ingiere ninguna fuente nueva. Solo se enciende y sanea lo que el canónico ya
  declara, más `pib_sectores_origen`.
- **No** se toca `banking_data` ni el histórico SIB. Eso vive en `SPEC_VALUADOR_ENTIDADES`.
- **No** se resuelven las series marcadas 🔴 en `SERIES_CANONICAS_BCRD.md` que fallan por
  el lado del BCRD (`historico_tasas`, `historico_ipc`). Se declaran brecha.

---

## 8. Próximos pasos

1. Correr la fase 0 y llevar el diff a revisión. **Es el único paso que no se puede
   automatizar** — alguien tiene que mirar las colisiones.
2. Confirmar el conteo de `pib_real`. Si es < 60 trimestres, avisar antes de que
   `SPEC_MOTOR_PROYECCION_MACRO` entre a build.
3. Fases 1-4 en dos PRs.

---

## 9. Referencias

- `docs/SERIES_CANONICAS_BCRD.md` — estado por serie, incluidas las 🔴
- `docs/bcrd_estadisticas_catalog.md` — catálogo completo del CDN
- `docs/SPEC_PROCEDENCIA_PROYECCION.md` — el vocabulario que consume lo persistido aquí
- `shared/data/bcrd_excel/canonical.py`, `modules/macro_monitor/service.py`
