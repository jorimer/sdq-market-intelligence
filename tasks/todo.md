# La fila del BVAR sin medida — plan

## Qué es esa fila, determinado y no supuesto

`bvar_minnesota.5v.v1` · `bcrd.xls.pib_2018.serie_original_indice` · horizonte 2026-Q3 ·
h=2 · as_of 2026-09-05 · revisión 0 · **punto 0,7373** · `measure` NULL.

El punto se leyó de `GET /api/v1/registry/macro_forecast` (la señal proyectada del eje), sin
generar ningún informe.

### Evidencia 1 — CRONOLOGÍA (la que cierra el caso)

| hecho | UTC |
|---|---|
| la cascada de `macro-canonical-sync` escribió la fila | **2026-09-05 11:19:55** |
| se ESCRIBIÓ el commit que pasa `pib_real` a interanual (`0d5ce2d6`) | 2026-09-05 15:53:40 |
| se mergeó a main (PR #1117) | 2026-09-05 20:07:51 |
| primer despliegue posterior al merge | ~2026-09-05 20:30 |

La fila es **4 h 34 min anterior a que el commit existiera**. No hubo ninguna corrida de
`macro-canonical-sync` entre el despliegue del cambio y mi emisión manual de las 21:52 —el
`last_run` del sync era el de las 11:19:55—, y mi emisión reportó `skipped_duplicate: 1`, o
sea que la fila ya estaba. Se produjo con el bloque en **DLOG**: su punto es un `dlog_pct`.

### Evidencia 2 — la magnitud, computada sobre el dato real de prod

Reproduje el modelo con las cinco series de producción, en las dos medidas:

| bloque | trimestres | 2026-Q3 | trayectoria |
|---|---:|---:|---|
| TRIMESTRAL (`dlog` ×100) | 76 (hasta 2026-Q1) | **1,6892** | −0,87 · 1,69 · 1,14 · 1,08 |
| INTERANUAL (`yoy` %) | 73 (hasta 2026-Q1) | **5,5672** | 5,32 · 5,57 · 5,37 · 5,11 |

Ninguna reproduce 0,7373 EXACTO —el dato se movió desde entonces, y los 76 vs 73 trimestres
confirman el costo de arranque que el propio commit declaró—, pero la separación no admite
duda: la trayectoria interanual **no baja de 5,11** en ningún horizonte. Y sobre el
observado, el QoQ promedia +1,13 % (rango reciente −1,60 … +3,08) contra +4,54 % del YoY.

## Lo que apareció al ir a estamparla, y es peor

**El `backtest_id` NO incluye la medida.** Es
`{model_id}|{target_series}|+{h}T`, y `_del_conjunto` filtra por model_id, serie, revisión,
estado y `h`. Comprobado: la fila vieja (trimestral) y las que el BVAR emite hoy
(interanuales) caen en **el mismo conjunto**.

O sea que estampar la medida y no tocar nada más cambia una brecha VISIBLE —una fila listada
como impuntuable— por una corrupción INVISIBLE: un RMSE que promedia el error de una tasa
trimestral con el de tasas interanuales, publicado en la sección de desempeño como si fuera
un solo número. Es «solo se ordena lo comparable» exactamente: un score armado sobre otra
unidad no rankea contra el resto.

**No es hipotético y no depende de esta fila.** Cualquier motor que cambie su transformación
—que es lo que acaba de pasar— parte su propio track record en dos poblaciones y las promedia
sin que nada avise.

## El arreglo

### 1 · La medida entra en la identidad del conjunto

`backtest_id` pasa a `{model_id}|{target_series}|{measure}|+{h}T`. La definición se muda a
`shared/registry/signals.py`, al lado del campo que documenta el formato, porque hoy hay DOS
constructores —`ledger.backtest_id` y `bvar.ProyeccionBVAR._backtest_id`— y una copia a mano
de un serializador ya borró la tasa de 38 entidades en este repo. Consumidores:
`_del_conjunto` (que además filtra por medida), `desempeno.filas` (que agrupa por ella) y
`procedencia.meta_de`.

Con esto, la fila vieja forma su propio conjunto de n=1: no ancla —correcto, el modelo
cambió— y **no contamina** el del modelo vigente.

### 2 · Recién entonces, la fila se estampa

Migración con la evidencia adentro, acotada a lo que se probó:
`measure is null` **y** `model_id like 'bvar_minnesota.%'` **y** la serie del PIB **y**
`as_of <= '2026-09-05'`. El `measure is null` ya implica «escrita antes de que el arreglo se
desplegara»; la cota de `as_of` está para que la afirmación quede verificable y para que la
migración no diga nada sobre una fila que alguien inserte después.

### 3 · Verificar en prod

Que la señal del registro deje de decir «unidad sin declarar» y que el readiness deje de
contar `1 SIN PODER PUNTUARSE`. Recomputar readiness ANTES de leerlo.

## Tests, contra el código viejo primero

- **El que importa**: dos filas del mismo modelo, mismo horizonte relativo y misma serie, con
  MEDIDAS distintas, no caen en el mismo `track_record`. Hoy caen, y el RMSE las promedia.
- Los dos constructores de `backtest_id` (ledger y bvar) dan la MISMA cadena.
- `desempeno` publica un renglón por medida, no uno mezclado.
- La migración estampa esa fila y no toca ninguna otra.

## Los tres gates

`pytest modules/ shared/ -q` · `ruff check modules/ shared/ app/` ·
`mypy shared/ modules/ app/ --no-incremental | mypy-baseline filter` (exit code del FILTRO).
