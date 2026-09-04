# T-MP-5 · Procedencia y reporte — plan

## Lo que el plan decía y NO es cierto

El plan dice «`products.py`, `variable_signals()` **(EDIT)**». Comprobado en el código:

| lo que decía el plan | lo medido |
|---|---|
| hay un `modules/macro_monitor/products.py` | **no existe**. El producto del eje es `MacroProduct`, y vive en **`app/products_macro.py`** (787 líneas) |
| `variable_signals()` se EDITA | **no existe** en `MacroProduct` — `'variable_signals' in type(p).__dict__` da `False`. Hay que CREARLO |

Verificado instanciando el registro con `app.main` importado: 17 ejes implementados, `macro`
entre ellos, resuelto a `app/products_macro.py`.

## Y un hallazgo que el plan no anticipaba

`MacroProduct` **ya tiene superficie de pronósticos**: `canonical_forecasts()` y
`forecast_observations()`, hoy cableadas al ledger de TPM (`tpm_modeling/ledger.py`) y
sirviendo por el Data API. El ledger nuevo (`mm_forecast_log`) tiene que entrar por ahí
también, o las proyecciones macro existirán en la base y **no** en la superficie que el
cliente consulta. Es exactamente el patrón de «un tipo nuevo se registra en TODAS sus
superficies, o desaparece».

## Lo que YA está construido y dormido

Todo el aguas-abajo del BLOQUE PP está hecho y con test: el pasaje del registro propaga la
meta, `Evidence` la toma, el orquestador escribe en la `SubQuestion`, el gate de admisión
decide, la prosa de procedencia la narra y `coverage_projected` la publica. Lo vigila
`shared/research/tests/test_cableado_de_proyeccion.py`, en sus tres puntos.

**Lo único que falta es el ORIGEN**: ningún producto emite hoy una señal `PROJECTED`.

## Pasos

- [ ] **1.** `forecasting/procedencia.py`: `ProjectionMeta` construido **leyendo del ledger**
      —`track_record()` ya devuelve `n_oos`, `rmse`, `interval_coverage` y `overlapping`—,
      nunca al revés. Es el `[Lock]` de §3.6.2.
- [ ] **2.** `MacroProduct.variable_signals()` NUEVO: las variables macro reales, y las
      proyectadas con `state=PROJECTED` + meta completa. Una proyección sin fila en el
      ledger no se emite.
- [ ] **3.** `coverage_real` del eje macro **no cambia** — medido antes y después, no
      supuesto.
- [ ] **4.** Las proyecciones macro entran a `canonical_forecasts()`/`forecast_observations()`
      junto a las de TPM.
- [ ] **5.** Secciones de reporte de §5, con **«Desempeño de nuestras proyecciones
      anteriores» en el CUERPO**.
- [ ] **6.** SKU y tarifa vía `shared/billing/skus.py` y `tariffs.py`. **Sin precio
      hardcodeado.**
- [ ] **7.** `ESTADO_BACKTEST` de clase: ya existe en `MacroProduct` y declara el motor
      `macro_political_risk`. Hay que revisar si añadir el motor de proyección **cambia lo
      que el eje puede afirmar**, y cruzarlo contra `shared.validation.frescura.MOTORES` —
      un producto no puede reclamar un motor que nadie registró.

## Sensor
- [ ] Gate de honestidad deja pasar una pregunta prospectiva real (extremo a extremo).
- [ ] Una proyección sin backtest en el ledger **no** ancla.
- [ ] `coverage_real` del eje macro idéntico antes y después.
