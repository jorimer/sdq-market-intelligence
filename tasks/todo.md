# El ledger de pronósticos no sabía contra QUÉ puntuar — plan

Dos defectos verificados en `modules/macro_monitor/forecasting/ledger.py`. Comparten una
causa: **`puntuar_pendientes` supone que `target_series` nombra una serie observable y que
`point` es directamente comparable con el valor de esa serie.** Ninguna de las dos
suposiciones se cumple.

## A · Las proyecciones del BVAR no se pueden puntuar NUNCA

`emision.OBJETIVO = "pib_real"` es el nombre de la variable DENTRO del bloque
(`bloque.BLOQUE[0].nombre`), no un `series_code`. Viaja al ledger como `target_series` y
`puntuar_pendientes` lo busca en `mm_series`, donde no existe.

Verificado en prod: `GET /api/v1/macro-monitor/series/pib_real` → `observations: []`.
Verificado en prod hoy (readiness de `macro_forecast`): «1 proyección(es) vigente(s);
**0 conjunto(s) con backtest puntuado**».

Consecuencia: toda fila del BVAR queda `pending` para siempre y `desempeno.seccion()`
publica «ninguna de las proyecciones emitidas alcanzó su período de cierre» — que se lee
como «los trimestres no cerraron» cuando la verdad es que **no pueden cerrar**. El
instrumento no distingue «todavía no» de «nunca».

## B · El ledger puntúa una TASA contra un NIVEL

`nowcast.estimar` devuelve `point = round(punto * 100, 4)`, o sea el Δlog del PIB **en %**
(~0,4), con `target_series = panel.PIB_CODE`. Esa serie es el **índice de volumen** (~133).
`abs_error` daría ≈ 132,75 y `desempeno.seccion()` lo publicaría como RMSE.

El BVAR tiene la misma forma: `bloque._transformar` aplica `(log b − log a) × 100`, así que
`Pronostico.punto` también es un Δlog en %.

B no explotó porque **nada está puntuado en prod todavía**. Arreglar A sin B publica un RMSE
de ~130 en la primera corrida.

## La causa raíz, y dónde ya está resuelta un nivel más arriba

`shared/data/series_nature.py` cerró exactamente esta clase de defecto para las SERIES: «el
emisor siempre declara qué mide, nosotros lo tirábamos, y cada consumidor tenía que ADIVINAR
qué transformación aplica». La corrección fue capturar la naturaleza, persistirla junto al
dato y que cada consumidor la LEA.

El ledger repite el defecto un nivel abajo: guarda un número sin declarar en qué medida está.
La cura es la misma — **la medida del punto se DECLARA al escribir y se lee al puntuar**.

Y la transformación en sí ya tiene tres copias: `panel._dlog` (sin ×100),
`bloque._transformar` (×100) y `backtest.correr:66-72` (×100, la que lo hace bien). El
ledger sería la cuarta.

## El arreglo

### 1 · `shared/data/periodos.py` gana `periodo_anterior`

Una tasa necesita contra qué medirse. No hay helper de «período anterior» por etiqueta:
`shared/operations/calendario._anterior` trabaja sobre tuplas `(año, q)` y es privado. El
archivo ya declara que es el hogar de esta pregunta y que hay copias sueltas; se agrega ahí
en vez de escribir la cuarta.

**Calendario, no «la observación anterior disponible».** Con un hueco en la serie, «la
anterior disponible» computa un cambio de dos trimestres y lo rotula de uno. Si el período
anterior de calendario falta, no se puntúa.

### 2 · `modules/macro_monitor/forecasting/medida.py` — módulo nuevo

Vocabulario + realización, puro (sin DB):

* `LEVEL = "level"` · `DLOG_PCT = "dlog_pct"` · `MEDIDAS`
* `periodos_necesarios(medida, period) -> Tuple[str, ...]` — qué hay que leer del observado
* `realizar(medida, period, observado) -> Realizacion(valor, motivo)` — `valor=None` con el
  MOTIVO nombrado, jamás 0,0

### 3 · `bloque.BloqueArmado` declara de dónde salió cada variable

`codigo_por_variable` y `medida_por_variable`. La medida del ledger sale de la MISMA
declaración que produjo el número (`Variable.transformacion`), no de una constante paralela
que se desincroniza. `MEDIDA_DE_TRANSFORMACION = {NIVEL: LEVEL, DLOG: DLOG_PCT}`.

### 4 · `bvar` transporta serie y medida

`proyectar_bloque(..., serie_objetivo=None, medida=None)` → `ProyeccionBVAR` →
`Pronostico`/`Escenario`. Opcionales porque `backtest_bvar` es numérico puro y no tiene por
qué conocerlas; la exigencia vive en la puerta del ledger (§5), que es donde importa.
`objetivo`/`target` sigue siendo el nombre de la variable del bloque — es lo que indexa la
matriz — y se conserva en `ProyeccionBVAR.target`.

### 5 · `ForecastLog.measure` + `ledger.registrar` lo EXIGE

Columna `measure` (String(16), nullable). Migración Alembic sobre el head `c3f7a2d9e814`.

`registrar(..., measure)` sin default: toda fila nueva declara su medida o lanza. Valida
también `target_series` no vacío.

`puntuar_pendientes` lee la medida y realiza el observado con `medida.realizar`. Una fila sin
medida declarada NO se puntúa (no se le supone «nivel»: eso es justo el defecto B).

`realized` pasa a guardarse **en la medida del punto** — que es lo que lo hace comparable.

### 6 · Lo vetado se LISTA: `ledger.no_puntuables(db)`

Un `pending` que no puede cerrar nunca. Dos motivos: medida no declarada, y serie sin una
sola observación en `mm_series` (que es la forma exacta del defecto A).

`desempeno.seccion()` deja de decir «todavía no cerraron» cuando la causa es otra: nombra la
causa y dice qué sí se puede esperar. Un veto silencioso se lee como que el eje no tiene
validación.

### 7 · `emision` no escribe lo que no se va a poder puntuar

`_escribir` comprueba que la serie destino tenga al menos una observación; si no, no escribe
y suma un `motivo`. Con el defecto A esto dispara con nombre y apellido en vez de callarse.
`emision` pasa `serie` y `medida` desde `armado.codigo_por_variable` /
`medida_por_variable`, y desde el nowcast (`PIB_CODE` / `DLOG_PCT`).

### 8 · `backtest.correr` usa el helper compartido

Deja de recomputar el dlog a mano (66-72). Era la tercera copia y la única correcta; ahora
es la misma que puntúa el ledger, que es el punto: si divergen, el backtest y el track
record miden cosas distintas y nadie se entera.

### 9 · Migración de datos, acotada y verificable

Las filas ya escritas en prod son de UNA sola versión del código (`emision.py` nació el
2026-09-04, commit `4f7bc0f3`; hoy es 2026-09-05) y ninguna está puntuada. Sus dos
productores conocidos —`bridge_imae_pib.*` y `bvar_minnesota.*`— emiten Δlog en % sobre
`PIB_CODE`. La migración pone `measure='dlog_pct'` y normaliza
`target_series 'pib_real' → PIB_CODE` **solo para esos `model_id`**. Cualquier otra fila
queda con `measure` NULL y la lista de §6 la muestra.

No es fabricar track record: es corregir un rótulo cuyo contenido es verificable leyendo el
único commit que lo escribió. Lo contrario —dejarlas inservibles— tira historial REAL y
ganado, en un ledger que necesita 12 observaciones para anclar y tiene 1.

## Tests — primero contra el código VIEJO

Regla de la casa que ya me falló: escribo la fixture que hace PASAR, no la que hace FALLAR.
Cada test se corre contra el código actual y se muestra el fallo ANTES de escribir el
arreglo.

1. `test_medida.py` — realización de cada medida y **cada motivo de negativa**, incluyendo
   el hueco de calendario (que es donde «la anterior disponible» mentiría).
2. `test_ledger.py` — puntuar una fila `dlog_pct` da la TASA observada, no el nivel
   (**falla hoy: 132,75**); una fila sin medida no se puntúa; `no_puntuables` reporta la
   serie inexistente.
3. `test_emision_se_puede_puntuar.py` (nuevo) — el que caza los DOS a la vez: emitir con el
   bloque real de juguete → llega el observado → puntuar → el error es del orden del modelo,
   no del nivel del índice. **Falla hoy por A (0 puntuados) y por B (error ~130).**
4. `test_desempeno.py` (nuevo) — la sección no dice «todavía no cerraron» cuando la causa es
   que no pueden cerrar.
5. Un test de que `bloque` resuelve `pib_real` al MISMO código que usa el nowcast: si
   divergen, el ledger puntúa contra otra serie.

## Los tres gates

`pytest modules/ shared/ -q` · `ruff check modules/ shared/ app/` ·
`mypy shared/ modules/ app/ --no-incremental | mypy-baseline filter` (exit code del FILTRO).

## Fuera de alcance

La discrepancia de unidades de la lectura sectorial (`_payload` pasa `punto` como `g_pib`) va
por otra rama y no se toca acá.
