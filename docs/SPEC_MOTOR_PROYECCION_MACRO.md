# SPEC — Motor de proyección macroeconómica (nowcast + horizonte 4-8T)

> Versión v0.1 · 2026-09-03 · Documento de construcción.
> Etiquetas de confianza: **[Certain]** verificable contra código/doc citado ·
> **[Likely]** inferencia fuerte, no probada · **[Guessing]** supuesto a validar ·
> **[Lock]** decisión ya tomada por el dueño.

> **Disciplina de notación.** La escala SDQ-AAA…D está RETIRADA. El guard `ast` no cubre
> `.md`. Disciplina manual.

> **Depende de** `SPEC_PROCEDENCIA_PROYECCION` (vocabulario, bloqueante) y
> `SPEC_PERSISTENCIA_SERIES_BCRD` (datos, bloqueante).
> **Alimenta a** `SPEC_VALUADOR_ENTIDADES` (ROE proyectado).

---

## 0. Qué se construye (BLUF)

Una capa forward-looking dentro de `macro_monitor` — **no un eje nuevo** — con tres
motores y un ledger:

1. **Nowcast**: bridge equation IMAE mensual → PIB trimestral. Estima el trimestre en
   curso 45-60 días antes de la cifra oficial.
2. **Horizonte**: BVAR con priors tipo Minnesota, 4 a 8 trimestres, sobre el bloque
   PIB-inflación-TPM-tasas-tipo de cambio.
3. **Sectorial**: desagregación de la proyección agregada a los 17 sectores de valor
   agregado.
4. **Ledger de pronósticos**: cada proyección emitida se registra con su `as_of`, y se
   puntúa cuando llega el dato observado. **El track record es parte del producto, no un
   subproducto.**

**[Lock] Modelo de entrega: suscripción trimestral.** Calendario fijo de publicación, y
cada entrega incluye el error de las entregas anteriores.

### Lo que este producto NO hace

**[Lock]** No compite con el BCRD proyectando PIB anual. El BCRD tiene mejor información,
antes, y su propio modelo. La ventaja de SDQ es de oportunidad (nowcast antes de la
cifra), de granularidad (17 sectores, que el BCRD no proyecta públicamente) y de
verificabilidad (track record publicado, que nadie en el mercado local publica).

---

## 1. Principio rector

> El foso no es el modelo. Es el ledger.

Un informe de proyección sin error verificable es una opinión con gráficos, y el mercado
dominicano ya tiene varias. Cualquier casa puede publicar un número. Lo que no se copia
rápido es haber publicado el propio error durante seis trimestres seguidos.

Consecuencia de diseño: **el ledger se construye en la fase 1, no en la última.** Un
producto que sale sin ledger nunca lo retrofitea, porque hacerlo obligaría a admitir que
los primeros trimestres no se midieron.

---

## 2. Estado real (verificado contra código, 2026-09-03)

### 2.1 Lo que ya existe y se reutiliza

`modules/macro_monitor/tpm_modeling/` es el único motor de proyección de la plataforma, y
su arquitectura es reutilizable casi entera. **[Certain]**

| Pieza | Ruta | Qué aporta |
|---|---|---|
| Rezagos de publicación | `dataset.py:28-40` `PUBLICATION_LAG_DAYS` | inflación 15d, IMAE 45d, FX 1d, reservas 20d, M1 40d |
| Panel point-in-time | `dataset.py:155` `build_panel(db)` | El patrón que impide contaminar con información posterior |
| Fila del panel | `dataset.py:43-51` `PanelRow(as_of, action, tpm_level, tpm_prev, features)` | Estructura |
| Backtest | `backtest.py:51,128,164` `run_backtest(rows, min_train=MIN_TRAIN)` | Expanding-window one-step-ahead — **el patrón, no la constante: ver §2.2** |
| Filtro HP | `features.py:38` `hp_filter(y, lam=HP_LAMBDA_MONTHLY)` | Forma cerrada en numpy, one-sided, λ=129.600 mensual |
| Ledger | `tpm_forecast_log` | `as_of, model_version, predicted_action, status, realized_*, correct, brier, level_abs_error, scored_at` |

**[Certain]** `PUBLICATION_LAG_DAYS` con IMAE en 45 días es exactamente la ventana que
hace valioso el nowcast: el modelo sabe cuándo estuvo disponible cada dato.

**[Certain] Detalle que rompe si se copia mal:** las claves de `PUBLICATION_LAG_DAYS` no
son nombres cortos sino `series_code` completos — el del IMAE es
`bcrd.xls.imae_2018.serie_original_indice` (`dataset.py:30, 34-40`). Un
`PUBLICATION_LAG_DAYS["imae"]` es `KeyError`. Y ese `series_code` es el **índice**, que hoy
el registro canónico no declara: ver `SPEC_PERSISTENCIA_SERIES_BCRD` §2.4 trampa 3 y §3.4.

### 2.2 Lo que no sirve tal cual

- **[Certain]** `tpm_modeling` está acoplado a un target **discreto** (`comunicado_tpm`,
  acciones hold/cut/hike) y a features mensuales. El PIB es continuo y trimestral:
  requiere λ propio y rezagos propios.
- **[Certain] `MIN_TRAIN = 90` (`backtest.py:34`) es incompatible con datos trimestrales.**
  `run_backtest` exige `len(full) > min_train + 5` (`:164`); con ~76 trimestres devuelve
  `ok: False` siempre. Reutilizar `run_backtest` tal cual **no funciona**: se reimplementa
  el mismo patrón expanding-window con un `MIN_TRAIN` trimestral propio. **[Guessing]** ~40
  trimestres de entrenamiento mínimo, dejando ~36 para evaluación fuera de muestra.
- **[Certain]** `tpm_forecast_log` **no tiene UniqueConstraint**. Para un ledger que se
  puntúa contra realizado, eso permite duplicados silenciosos. El ledger nuevo lo lleva.
- **[Certain]** La tabla `comunicado_tpm` no existe en la base local inspeccionada, así
  que `tpm_modeling` puede estar sin panel en ese entorno. Verificar antes de apoyarse en
  su regla de reacción (§3.4).

### 2.3 La restricción de librería

**[Certain]** `statsmodels` **no está** en `requirements.txt` (`:8-12` tiene xgboost,
scikit-learn, scipy, pandas, numpy). El docstring de `features.py:5-6` lo documenta:
«El HP-filter se implementa con `scipy` (NO statsmodels, que no está en requirements)».

**[Lock] Decisión: NO se añade `statsmodels`, y el BVAR se implementa con dummy
observations sobre OLS.**

La primera versión de este spec ordenaba añadir `statsmodels` con el argumento de que un
BVAR a mano son cientos de líneas de álgebra no auditable. **El argumento era falso y la
premisa también.** `statsmodels` ofrece `VAR`, `VARMAX` y `VECM` — **no** ofrece BVAR con
prior Minnesota. Añadir la dependencia no habría resuelto nada.

El método correcto es el de Bañbura, Giannone & Reichlin (2010): el prior Minnesota se
implementa **añadiendo observaciones artificiales al dataset** y corriendo OLS sobre el
conjunto aumentado. Son del orden de 40 líneas, cada una inspeccionable, y el resultado se
verifica contra un caso conocido: con tightness → 0 el estimador debe converger al random
walk, y con tightness → ∞ al OLS sin restringir. **Ese es el test de la fase 3.**

### 2.3.1 Corrección econométrica sobre los hiperparámetros

La primera versión decía seleccionar `λ₁, λ₂, λ₃` por verosimilitud marginal. **Está mal
como estaba escrito**: la verosimilitud marginal en forma cerrada solo existe bajo el
prior natural-conjugado, y ese prior impone estructura Kronecker en la covarianza — lo que
**fuerza `λ₂ = 1`**, es decir, obliga a tratar igual los rezagos propios y los cruzados.
No se puede tener forma cerrada y `λ₂` libre a la vez.

**[Lock]** Se toma la rama conjugada: `λ₂ = 1` fijo, y se selecciona **`λ₁` (tightness
general) por verosimilitud marginal en forma cerrada**, con **`λ₃ = 2`** (decaimiento
cuadrático de rezagos, el valor convencional de la literatura Minnesota). La restricción se
declara en la metodología del reporte, no se esconde. Es una pérdida real de flexibilidad a
cambio de una selección de hiperparámetros que no contamina el backtest.

### 2.4 Los datos, tras el spec de persistencia

Contingente a `SPEC_PERSISTENCIA_SERIES_BCRD` §4.1 **[Guessing]**: `pib_real` ~76
trimestres (2007→2026 retropolado), `imae_indice` ~230 meses, `pib_sectores_origen` ~1.300
obs (17 sectores × 76 trimestres).

**[Lock] Tres gates de viabilidad, uno por motor.** No basta con mirar `pib_real`:

1. **Nowcast (§3.2).** Requiere `imae_indice` persistido — la serie que hoy el canónico no
   declara (`SPEC_PERSISTENCIA` §3.4). Sin ella el motor no arranca; no hay degradación
   posible, porque el índice YoY no sirve para agregar a trimestre.
2. **BVAR (§3.3).** Si `pib_real` sale con **menos de 60 observaciones trimestrales**, no
   procede como está especificado: se degrada a un VAR bivariado o a modelos univariados
   con indicadores adelantados, y se dice por qué. No se fuerza un modelo de 5 variables
   sobre 40 puntos.
3. **Sectorial (§3.5).** `pib_sectores_origen` está marcado `[Guessing]` en
   `SPEC_PERSISTENCIA` §3.3 y sujeto a verificación de cobertura y continuidad por sector.
   Cada sector se evalúa por separado: los que no pasen continuidad no se proyectan y se
   declaran brecha. **Si menos de 12 de los 17 pasan, la sección sectorial no se publica**
   — media desagregación es peor que ninguna, porque invita a leer los ausentes como
   irrelevantes en vez de como no medidos.

---

## 3. Diseño

### 3.1 Ubicación

```
modules/macro_monitor/forecasting/
├── __init__.py
├── nowcast.py          # bridge equation IMAE → PIB
├── bvar.py             # BVAR-Minnesota, horizonte 4-8T
├── sectoral.py         # desagregación a 17 sectores
├── ledger.py           # registro y puntuación de pronósticos
├── panel.py            # panel point-in-time (patrón de tpm_modeling/dataset.py)
├── models.py           # ORM del ledger
└── tests/
```

**[Lock]** Dentro de `macro_monitor`, no eje nuevo. `macro` ya está productizado
(`ESTADO.md`), tiene motor de frescura registrado, y la proyección es una capa sobre sus
mismas series. Un eje nuevo duplicaría la ingesta sin ganar nada.

### 3.2 Nowcast — bridge equation

**Por qué bridge y no MIDAS en v1.** Ambos resuelven mezcla de frecuencias. Bridge agrega
el indicador mensual a trimestral y corre una regresión simple; MIDAS pondera los meses
con una función paramétrica. Con ~76 trimestres, MIDAS gasta grados de libertad en
estimar la ponderación y gana poco. **[Likely]** Bridge primero, MIDAS como extensión
medida contra el bridge, no en lugar de él.

Especificación, en dos pasos explícitos:

**Paso 1 — completar el trimestre.** Si el trimestre tiene `m ∈ {1,2,3}` meses de IMAE
publicados, los `3−m` faltantes se imputan con un AR(p) univariado sobre el índice mensual
del IMAE, estimado con información disponible al `as_of`. Con `m = 3` este paso no corre.

**Paso 2 — agregar y regresar.** El índice mensual completo se agrega a trimestral
(promedio del trimestre), y:

```
Δlog(PIB_t) = α + β · Δlog(IMAE_trimestral_t) + γ · Δlog(PIB_{t-1}) + ε_t
```

**[Lock] Un solo regresor agregado, no tres coeficientes mensuales.** La versión anterior
escribía `Σ βᵢ · Δlog(IMAE_{t,i})`, que es un diseño distinto —MIDAS sin restricción— y
mezclado con el agregado no significa nada. Con ~76 trimestres, tres coeficientes mensuales
libres gastan grados de libertad sin ganancia demostrada. Bridge agregado en v1; MIDAS es
extensión medida contra este, no en lugar de este.

**[Lock] Tres variantes, tres backtests.** `m = 1`, `m = 2`, `m = 3` son tres modelos
distintos: difieren en cuánto imputa el paso 1. Un nowcast con un mes de información no
tiene el mismo error que con tres, y reportar un error promedio entre ellos es engañar.
Cada variante tiene su propio `model_id` (`bridge_imae_pib.m1.v1`, `.m2.v1`, `.m3.v1`) y su
propia fila de backtest.

`as_of` obligatorio, respetando el rezago de publicación del índice del IMAE (45 días,
`dataset.py:34-40`).

### 3.3 Horizonte — BVAR con priors Minnesota

Bloque de 5 variables **[Guessing]**, a confirmar con la data real:
PIB real, inflación interanual, TPM, tasa activa promedio, tipo de cambio.

**Por qué priors.** Con ~76 observaciones y 5 variables, un VAR sin restricciones estima
más parámetros de los que la data sostiene y ajusta ruido. El prior Minnesota encoge
hacia un random walk, que es la hipótesis nula honesta para series macro.

Hiperparámetros según §2.3.1: `λ₂ = 1` (impuesto por el prior conjugado), `λ₃` en su valor
convencional, y `λ₁` seleccionado por verosimilitud marginal en la ventana de
entrenamiento — **nunca mirando el error fuera de muestra**, que contaminaría el backtest.

Implementación por dummy observations sobre OLS (§2.3), sin dependencia nueva.

Salida: distribución predictiva → punto e intervalos al 80% y 90%, que alimentan
`ProjectionMeta.intervals` como `((0.80, lo, hi), (0.90, lo, hi))`.

### 3.4 Enganche con `tpm_modeling`

**[Lock]** La TPM del bloque no se asume: se toma de la regla de reacción ya estimada en
`tpm_modeling`. Cierra el bloque monetario endógenamente y evita la incoherencia de
proyectar inflación al alza con política monetaria constante.

Acoplamiento por lectura, dentro del mismo módulo — no cruza frontera de módulos, así que
no viola la regla de `CLAUDE.md`.

### 3.5 Sectorial

Proyección de los 17 sectores de `pib_sectores_origen`, con **restricción de agregación**:
la suma ponderada de los sectores debe reconciliar con el PIB agregado proyectado.

**[Guessing]** Método: proporciones con corrección de tendencia, o un factor model si la
correlación entre sectores lo justifica. Se decide con la data en mano, en la fase 3, y
se documenta la elección con su evidencia.

**[Lock]** Un sector cuya serie tenga huecos o cambio de base no se proyecta: se declara
brecha. 15 sectores proyectados honestamente valen más que 17 con dos inventados.

### 3.6 El ledger

```python
class ForecastLog(Base):
    __tablename__ = "mm_forecast_log"
    # UniqueConstraint("model_id", "target_series", "horizon", "as_of", "revision")

    model_id: str          # modelo + variante + versión en un solo id.
                           # "bridge_imae_pib.m2.v1" | "bvar_minnesota.v1"
                           # Sin model_version aparte: versionar dos veces admite contradicción
    target_series: str     # series_code de mm_series
    horizon: str           # "2026-Q4"
    as_of: str             # corte point-in-time de la información usada
    revision: int          # 0 = original; 1+ = correcciones posteriores (§3.6.1)
    point: float
    intervals: JSON        # [[level, lo, hi], ...] — mismos niveles que ProjectionMeta
    lo_80: float; hi_80: float   # denormalizados para consulta; derivados de intervals
    lo_90: float | None; hi_90: float | None
    status: str            # pending | scored   — SOLO ciclo de vida de puntuación
    superseded_by: int | None    # linaje: id de la revisión que la reemplaza (§3.6.1)
    # puntuación, al llegar el observado:
    realized: float | None
    realized_period_end: date | None
    abs_error: float | None
    sq_error: float | None
    interval_hit_80: bool | None   # ¿cayó el observado dentro del intervalo de 80%?
    interval_hit_90: bool | None   # ídem 90% — ambos niveles se puntúan
    scored_at: datetime | None
```

#### 3.6.1 Por qué `revision` está en la clave

**[Lock]** La clave de cuatro campos `(model_id, target_series, horizon, as_of)` era
incorrecta: hace **inalcanzable** el estado `superseded`. Si una corrección de un
pronóstico ya emitido no puede escribirse por colisión de clave, el único camino es
actualizar la fila original — que es exactamente reescribir la historia.

Con `revision` en la clave: la corrección entra como fila nueva, y **ambas quedan**.

**[Lock] `status` y linaje son dos ejes distintos, en dos columnas distintas.** Un primer
diseño ponía `superseded` como valor de `status` — y eso reabría el maquillaje por otra
puerta: el track record se computa sobre `revision = 0` en estado `scored`, así que marcar
la revisión 0 como `superseded` la sacaba del cómputo. Corregir un pronóstico habría
borrado el pronóstico original del historial, que es exactamente lo que `revision` viene a
impedir.

Por eso `status` es solo `pending | scored` —el ciclo de vida de la puntuación— y el
linaje vive en `superseded_by`. Una fila `revision = 0` se puntúa **siempre**, tenga o no
una revisión posterior. El track record se computa sobre `revision = 0` y `status =
scored`, sin mirar `superseded_by`: el pronóstico como se publicó, no como se corrigió
después.

Sin él, un rerun duplica pronósticos y el track record se puede maquillar sin querer, que
es peor que maquillarlo queriendo porque nadie lo nota. `tpm_forecast_log` no tiene
`UniqueConstraint` alguno **[Certain]**; este ledger no repite esa omisión.

**[Lock] La cobertura empírica de intervalos importa tanto como el error puntual.** Un
modelo cuyo intervalo del 80% acierta el 45% de las veces está mal calibrado aunque su
error medio sea bajo, y el lector que dimensiona riesgo con ese intervalo se equivoca. Por
eso se puntúan **los dos niveles**, 80 y 90, y ambas coberturas se publican junto al RMSE.

#### 3.6.2 Mapeo con `ProjectionMeta`

**[Lock]** El ledger es la fuente de verdad; `ProjectionMeta` se construye leyendo de él,
nunca al revés.

| `ProjectionMeta` | Ledger |
|---|---|
| `model_id` | `model_id` |
| `target_series` | `target_series` |
| `horizon` | `horizon` |
| `as_of` | `as_of` |
| `revision` | `revision` |
| `point` | `point` |
| `intervals` | `intervals` (misma estructura; `lo_80/hi_80/lo_90/hi_90` son denormalización de consulta) |
| `backtest_id` | `"{model_id}\|{target_series}\|{horizon}"` |
| `n_oos` | conteo de filas con `revision = 0` y `status = scored` bajo `backtest_id` |
| `oos_error` | RMSE/MAE sobre ese mismo conjunto |
| `n_oos_overlapping` | `True` si el horizonte supera el paso entre `as_of` consecutivos |

**[Lock]** `ProjectionMeta` lleva `revision`, igual que el ledger. Sin él la meta no
identifica una fila: la clave del ledger tiene cinco campos, y una meta de cuatro apunta a
un conjunto, no a un pronóstico.

**Cobertura empírica de intervalos.** El `[Lock]` de §3.6.1 exige publicarla, así que
necesita portador: `ProjectionMeta` lleva `interval_coverage`, una tupla
`((level, cobertura_observada, n), ...)` calculada sobre el mismo conjunto que `oos_error`.
Es lo que la prosa del reporte cita junto al RMSE — un intervalo del 80% que acierta el
45% de las veces se ve ahí y en ningún otro lado.

### 3.7 Puntuación automática

Operación en `operations.py` que, tras cada ingesta de macro, busca pronósticos `pending`
cuyo período ya tenga observado en `mm_series`, calcula errores y marca `scored`.

**[Lock]** Automática, no manual. Un proceso de puntuación que requiere que alguien se
acuerde deja de correr en el trimestre en que el resultado es malo.

---

## 4. Contrato de procedencia

Cada cifra proyectada viaja como `VariableSignal` con `state=PROJECTED` y
`ProjectionMeta` completo (`SPEC_PROCEDENCIA_PROYECCION` §3.2). `backtest_id` resuelve
contra `mm_forecast_log`.

`coverage_real` del eje macro **no cambia**. `coverage_projected` es campo aparte.

---

## 5. El producto comercial

**[Lock]** Suscripción trimestral, calendario fijo.

Anatomía por `REPORT_STANDARD`, con dos secciones propias:

| Sección | Contenido |
|---|---|
| Nowcast del trimestre en curso | Punto, intervalo, y qué meses de IMAE lo sostienen |
| Trayectoria 4-8T | PIB, inflación, TPM, tasas, FX con bandas |
| Lectura sectorial | Los 17 sectores; los que no se proyectan aparecen declarados |
| **Desempeño de nuestras proyecciones anteriores** | Error de cada pronóstico previo ya puntuado + cobertura empírica de intervalos |
| Metodología y fuentes | Auto-generada desde procedencia |

**[Lock]** La sección de desempeño va **en el cuerpo**, no en anexo. Es el argumento de
venta, no la letra chica.

**[Guessing]** Los primeros 4 trimestres esa sección va a incomodar. Es el costo de
entrada del foso: quien no lo paga no lo tiene.

Tier y precio: SKU vía `shared/billing/skus.py:45-53`, tarifa por
`create_tariff(...)` (`shared/billing/tariffs.py:81`). **No se hardcodea precio.**

---

## 6. Fases de build

| Fase | Alcance | Cierre |
|---|---|---|
| 0 | Los 3 gates de viabilidad de §2.4; verificar que `comunicado_tpm` exista | Conteos confirmados; sin dependencias nuevas que instalar |
| 1 | `panel.py` + `ledger.py` + ORM + migración + puntuación automática | Ledger escribe y puntúa con datos sintéticos; **UniqueConstraint de 5 campos probado, incluido el caso `superseded`** |
| 2 | `nowcast.py`, imputación AR + 3 variantes, backtest expanding-window con `MIN_TRAIN` trimestral propio | RMSE fuera de muestra por variante; `n_oos` y `n_oos_overlapping` declarados |
| 3 | `bvar.py` por dummy observations + enganche TPM | **Test de límites: tightness→0 converge a random walk, tightness→∞ a OLS sin restringir.** Backtest 1 a 8 pasos; cobertura empírica de intervalos 80 y 90 |
| 4 | `sectoral.py` con restricción de agregación | Reconciliación exacta; sectores no proyectables declarados |
| 5 | `variable_signals()` con `PROJECTED`; secciones de reporte; SKU | Gate de honestidad deja pasar la pregunta prospectiva |
| 6 | Operación programada + calendario de publicación | Corrida end-to-end de un trimestre completo |

Tres gates de CI íntegros. `mypy` sobre `shared/ modules/ app/`, mirando exit code.

---

## 7. Riesgos

| Riesgo | Severidad | Mitigación |
|---|---|---|
| `pib_real` con < 60 trimestres | Alta | Gate §2.4. Degradar el modelo y decirlo, no forzarlo. |
| El retropolado 2007 no es homogéneo con el tramo reciente | Alta | Test de quiebre estructural (Chow) en fase 2. Si hay quiebre, la muestra arranca después y se declara. |
| Sobreajuste por elegir hiperparámetros mirando el error OOS | Alta | Verosimilitud marginal en train. El OOS **solo** se mira al final. Revisión de PR explícita en este punto. |
| Backtest contaminado con información posterior | Alta | Panel point-in-time con `PUBLICATION_LAG_DAYS`, patrón ya probado en `tpm_modeling` |
| El BVAR a mano tiene un error de álgebra indetectable | Alta | Test de límites de la fase 3 (tightness→0 y →∞). Un error de implementación rompe al menos uno de los dos extremos. |
| `n_oos` cuenta ventanas solapadas como independientes | Media | `n_oos_overlapping` obligatorio en `ProjectionMeta` y declarado en la prosa del reporte |
| El primer año de track record es malo y daña la marca | Media | Es el costo de entrada, y se decidió pagarlo. Mitigación real: no prometer precisión que el backtest no sostiene. |
| El nowcast acierta menos que el consenso de mercado | Media | Publicar comparación contra un benchmark naive (random walk) desde el trimestre 1. Si no le gana al naive, el producto no sale. |

**[Lock]** Ese último es un gate de publicación, no un riesgo a monitorear: **un modelo
que no le gana consistentemente a un random walk fuera de muestra no se publica.**

---

## 8. Fuera de alcance v1

- **No** MIDAS ni coeficientes mensuales libres. Extensión medida contra el bridge
  agregado, después.
- **No** `statsmodels` ni ninguna dependencia nueva (§2.3).
- **No** modelos de factores dinámicos ni DSGE.
- **No** proyección de variables fiscales ni de balanza de pagos.
- **No** escenarios condicionales ("¿qué pasa si el turismo cae 10%?"). Es el candidato
  natural a tier alto por encargo, en otro spec.
- **No** ML para el punto central. Con ~76 observaciones no hay nada que aprender que un
  BVAR no capture mejor y de forma explicable.
- **No** proyección de los otros 16 ejes del catálogo.

---

## 9. Próximos pasos

1. Cerrar `SPEC_PROCEDENCIA_PROYECCION` y `SPEC_PERSISTENCIA_SERIES_BCRD`.
2. Fase 0 — y el número de `pib_real` decide si el §3.3 sigue como está escrito.
3. Fases 1-2 en una PR (ledger y nowcast juntos: el nowcast sin ledger no se mergea).
4. Definir el calendario de publicación con el dueño antes de la fase 6.

---

## 10. Referencias

- `docs/SPEC_PROCEDENCIA_PROYECCION.md`, `docs/SPEC_PERSISTENCIA_SERIES_BCRD.md`
- `docs/REPORT_STANDARD.md` — anatomía y tiers
- `modules/macro_monitor/tpm_modeling/README.md` — el patrón point-in-time
- `docs/SERIES_CANONICAS_BCRD.md`
