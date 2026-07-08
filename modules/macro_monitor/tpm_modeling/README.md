# Modelo de predicción de la TPM (BCRD)

Modelo interpretable de la Tasa de Política Monetaria del Banco Central de la República
Dominicana. Dos componentes complementarios, ambos con **backtest time-series honesto**:

| Componente | Archivo | Rol |
|---|---|---|
| **Regla de reacción (tipo Taylor)** | `reaction_function.py` | Ancla interpretable: tasa **implícita** por OLS y **sesgo** (implícita − vigente). |
| **Clasificador (XGBoost)** | `classifier.py` | Predice el **sentido** de la próxima decisión: `hold` / `cut` / `hike`. |

El panel `dataset.py` es la base; `features.py` las transformaciones; `backtest.py` la
validación; `service.py` orquesta (entrena, persiste, sirve el forecast).

## Datos

- **Target:** 190 decisiones de TPM (2008→hoy) de la tabla `comunicado_tpm` (sentido +
  nivel resultante), derivadas de forma determinista de los comunicados del BCRD.
- **Features (BCRD, mensuales):** brecha de inflación (vs meta 4%), brecha de producto
  (HP-filter sobre el índice IMAE base 2018), tasa real, TPM rezagada, y momentum
  interanual de tipo de cambio, reservas y M1.

## Rigor (lo que hace creíble el resultado)

1. **Point-in-time:** para cada reunión se usa solo el dato *publicado* a esa fecha,
   respetando el rezago real de publicación de cada serie (`PUBLICATION_LAG_DAYS`). El
   HP-filter de la brecha de producto se recalcula sobre la historia truncada (one-sided),
   sin mirar hacia adelante.
2. **Backtest expanding-window out-of-sample**, nunca split aleatorio: se entrena con todo
   lo anterior y se predice la decisión siguiente.
3. **Desbalance explícito** (145 `hold` de 190): el clasificador usa pesos por clase y el
   reporte da **recall por clase y macro-F1 frente al baseline "siempre mantener"** (que ya
   acierta ~76% por el desbalance — la accuracy sola engaña).

## Cómo leer el backtest (honestidad tipo Fitch)

- **Clasificador:** el baseline "siempre mantener" gana en accuracy cruda por construcción;
  el valor del modelo está en el **macro-F1** y en el **recall de las clases minoritarias**
  (anticipa cortes y alzas que el baseline nunca ve).
- **Regla de Taylor:** ajusta bien el **nivel** (la TPM es muy persistente) pero **no
  cronometra la reunión inmediata**. Su **sesgo** anticipa la **dirección de la TPM a
  6–12 meses**, no la próxima decisión discreta — para eso está el clasificador.

## Limitaciones declaradas

- Sin *vintages*: se usa el valor final de cada serie con su rezago típico (no el dato
  exacto tal como se veía ese día). Resultados **direccionales**, no reconstrucción exacta.
- Sin tasa de la Reserva Federal ni riesgo país (EMBI): drivers externos ausentes del MVP.
- Panel corto y desbalanceado. **Análisis macro con incertidumbre, no consejo de inversión.**

## Uso

- Entrenar/re-entrenar: operación `tpm-model-train` (async; se dispara sola tras
  `bcrd-comunicados-sync`).
- Servir: `GET /api/v1/macro-monitor/comunicados/forecast` y `.../comunicados/model/backtest`.
- Persistencia: `AppSetting` `tpm_model` (regla + clasificador base64) y `tpm_backtest`.
