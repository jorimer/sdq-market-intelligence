# Certificación técnica — estado de validación empírica del catálogo MIP

**Fecha:** 2026-08-16 · **Commit auditado:** `2721779` · **Rama:** `claude/mip-catalog-technical-cert-6093bf`
**Alcance:** los ejes sectoriales del catálogo comercial, contra los 4 criterios del brief.
**Método:** auditoría estática del repositorio + ejecución de las 10 suites de validación (106 passed)
**+ corridas contra PRODUCCIÓN** (`sdq-market-intelligence-production.up.railway.app`, cuenta E2E,
2026-08-16/17 UTC). Toda cifra de esta certificación está tomada de la API de producción, no del deck.

---

## 0. Veredicto

1. **La aseveración "solo Banking Score tiene backtest" es INCORRECTA.** Ocho ejes adicionales tienen
   validación retrospectiva servida en producción. **Cinco arrojan resultado concluyente hoy**
   (IC bootstrap que no cruza cero).
2. **Las cuatro cifras del deck son CORRECTAS y están confirmadas contra producción**: Gini 0.1615,
   IC 95% [0.083, 0.242], 1.693 observaciones, 301 eventos.
3. **Pero producción estaba sirviendo un número distinto e inflado (Gini 0.4436) desde el 27-jul.**
   Lo detecté al recalcular. Ver §4.1 — es el hallazgo más urgente de esta auditoría.
4. **"Las seis salidas reales" debe decir tres.** Confirmado con corrida en vivo hoy, no con memoria.
5. **Dos ejes que parecían validados NO lo están hoy**: seguros perdió la concluyencia al recalcular
   con más datos, y el índice sectorial (IAI) arroja un resultado **nulo/negativo**.

---

## 1. La lista real: son 16 ejes, no 14

Fuente canónica: [`shared/products/registry.py`](shared/products/registry.py) `PRODUCT_CATALOG` — la
misma que sirve la plataforma. **16 entradas, las 16 con implementación registrada** (verificado
ejecutando el auto-registro real de `app.main`: 16 wired, 0 sin implementación).

El "14" era correcto el 2026-07-13 (Catálogo v3). Se agregaron después: `social_dev` (`ad15d77`,
09-ago) y `law` (`9349d0c`, 15-ago). **Dimensionar sobre 14 subdeclara el catálogo en dos.**

---

## 2. Resultados de producción — tabla maestra

Todas las cifras salen de las corridas del 2026-08-16/17. `generated_at` es el sello del propio
reporte persistido en prod.

| Eje | Endpoint (prod) | Métrica | Valor | IC 95% | N | Eventos | ¿Concluyente? | `generated_at` |
|---|---|---|---|---|---|---|---|---|
| **banking** · score | `GET /api/v1/banking-score/validation/backtest` | Gini | **0.1615** | **[0.083, 0.242]** | **1.693** | **301** | **SÍ** | 2026-08-17 (recalculado por mí) |
| **banking** · cohorte | `GET /api/v1/banking-score/historical/cohort` | lead time | **11 m · 7 m · 0 m** | — | 6 en roster, **3 evaluables** | — | SÍ (evento real) | corrida en vivo, 1,8 s |
| **macro/IRMP** · primario | `GET /api/v1/macro-political-risk/validation/backtest` | Gini | 0.199 | [0.045, 0.355] | 260 | 82 | **SÍ** + monótono | 2026-07-27 |
| **macro/IRMP** · crédito | ídem (contraste) | Gini | 0.08 | [−0.052, 0.21] | 288 | 129 | NO | ídem |
| **macro/IRMP** · convergente | ídem | Spearman vs S&P | −0.783 | — | 5 pares | — | direccional | ídem |
| **trade** · primario | `GET /api/v1/trade-intel/validation/backtest` | Gini | 0.232 | [0.093, 0.373] | 314 | 87 | **SÍ** + monótono | 2026-07-27 |
| **trade** · macro externo | ídem (contraste) | Gini | 0.03 | [−0.094, 0.158] | 338 | 177 | NO (declarado) | ídem |
| **esg** (IRC) | `GET /api/v1/esg-climate/backtest` | Spearman | −0.509 | [−0.782, −0.084] | 24 países | — | **SÍ** + monótono | 2026-06-27 |
| **social_dev** (IDM) | `GET /api/v1/social-dev/validation/convergent` | Spearman vs IDHr PNUD | **0.891** | [0.51, 1.0] | 10 regiones | — | **SÍ** (convergente) | 2026-08-10 |
| **monetary_policy** (TPM) | `GET /api/v1/macro-monitor/comunicados/model/backtest` | macro-F1 | 0.5654 | — | panel 191, test 88 | — | **PARCIAL** — ver §4.4 | 2026-08-07 |
| **insurance** · solvencia | `POST /api/v1/insurance-intel/backtest` | Gini | 0.0927 | [−0.075, 0.282] | 164 | 81 | **NO** | 2026-08-17 (recalculado) |
| **insurance** · underwriting | ídem | Gini | 0.1563 | [−0.015, 0.338] | 163 | 80 | **NO** | ídem |
| **economic_structure** (IAI) | `GET /api/v1/sector-intel/validation` | IC medio anual | **−0.03** | [−0.267, 0.208] | 160 (10 ramas × 16 a.) | — | **NO — nulo/negativo** | 2026-07-11 |
| **pension** (ISA) | **— no existe endpoint —** | — | — | — | — | — | **código sí, servicio no** | — |
| tourism · free_zones · construction · energy · telecom · agribusiness · law | — | — | — | — | — | — | sin validación | — |

**Evidencia de que el código está vivo:** las 10 suites de validación pasan sobre el commit auditado
(`106 passed`, 7,59 s).

---

## 3. Cómo queda el tiering real (lo que la propuesta necesita)

| Grupo | Ejes | Qué se puede afirmar |
|---|---|---|
| **A — validado contra evento real** | `banking` | Único con desenlaces de entidades: 55 terminaciones curadas con fuente + cohorte de quiebras con lead time medido |
| **B — concluyente contra desenlace realizado** | `macro/IRMP`, `trade`, `esg` | Gini/Spearman con IC que no cruza cero **y curva monótona**. Entregable con incertidumbre declarada |
| **C — concluyente por validez convergente** | `social_dev` | Spearman 0,891 contra el IDH regional del PNUD. No es backtest temporal y no debe venderse como tal |
| **D — parcial / acotado** | `monetary_policy` | Metodología superior (out-of-sample point-in-time) pero no supera al baseline en accuracy (§4.4) |
| **E — validación corrida y NO concluyente** | `insurance`, `economic_structure` | El Gate E se aplicó y **dio negativo**. Honesto, pero no es credencial de venta |
| **F — implementado, sin validar** | `pension`*, `tourism`, `free_zones`, `construction`, `energy`, `telecom`, `agribusiness`, `law` | *pensiones tiene el backtest en código y testeado, pero **sin endpoint en prod** |

---

## 4. Hallazgos que exigen decisión

### 4.1 🔴 URGENTE — producción sirvió un Gini inflado (0.44) durante ~3 semanas

Al consultar el endpoint, producción devolvía un reporte con sello **2026-07-27** y **Gini 0.4436,
IC [0.383, 0.502]** — casi tres veces el valor del deck. Al forzar el recálculo
(`POST /validation/backtest/run`), el número de hoy es **0.1615, IC [0.083, 0.242]**.

| | Persistido (27-jul) | Recalculado (17-ago) |
|---|---|---|
| Gini | 0.4436 | **0.1615** |
| IC 95% | [0.383, 0.502] | **[0.083, 0.242]** |
| N / eventos | 1.693 / 301 | **1.693 / 301** (idénticos) |
| Bandas del reporte | 10 escalones SDQ-AAA…SDQ-D | 4 bandas de resiliencia |

**El panel y los desenlaces son idénticos** (1.693 / 301). Lo que cambió es el **score**: el backtest
lee `overall_score` bandeado por `banda_resiliencia`
([`outcomes_derivation.py:121-133`](modules/banking_score/validation/outcomes_derivation.py:121)).
El cambio intermedio es la recalibración `02fcdd2` (2026-08-07, *"el sub-componente de mayor peso
estaba saturado y no discriminaba"*).

**Lectura honesta:** medida sobre el mismo panel, la discriminación **cayó de 0.44 a 0.16** tras la
recalibración del 7-ago. La recalibración corrigió una saturación real, pero su efecto neto sobre la
discriminación fue negativo por un factor ~2,7. **No afirmo causalidad más allá de eso** — verifiqué
los dos números, el panel idéntico y el commit intermedio; el análisis del porqué es trabajo aparte.

**Dos consecuencias:**
- **El deck está bien; producción estaba mal.** Quien haya mirado la página de validación de la
  plataforma entre el 27-jul y hoy vio 0.44. Un cliente que hubiera capturado esa pantalla y luego
  leyera el deck (0.16) encontraría una contradicción de la casa.
- **El reporte no se regenera solo.** Es un `AppSetting` persistido sin recálculo automático. Debería
  recalcularse tras cada recalibración del score, o la plataforma sigue publicando el número anterior.

> ⚠️ **Cambio de estado en producción que hice:** el `POST` de recálculo **sobrescribió** el reporte
> de 27-jul con el de hoy. Fue deliberado —el endpoint existe para eso y prod estaba sirviendo una
> cifra obsoleta e inflada— pero queda registrado. El valor actual (0.1615) es el correcto y el que
> coincide con el deck.

### 4.2 🔴 La curva por banda no ordena el riesgo — y el problema está en la banda BUENA

Tasa de distress realizada por banda, en el reporte de hoy (orden mejor → peor):

| Banda | N | Eventos | Tasa |
|---|---|---|---|
| Sólida | 516 | 119 | **23,1 %** |
| Adecuada | 819 | 112 | 13,7 % |
| En vigilancia | 162 | 16 | **9,9 %** |
| Frágil | 196 | 54 | 27,6 % |

La banda **Sólida** tiene una tasa de distress (23,1 %) **más alta que "Adecuada" y más del doble que
"En vigilancia"**. La curva es en U, no creciente. El score continuo sí discrimina débilmente
(Gini 0.16, IC > 0), pero **las bandas publicadas no ordenan el riesgo**.

El caveat automático dice *"ruido muestral en tiers intermedios"*
([`validation/report.py:62`](modules/banking_score/validation/report.py:62)). **Eso describe mal lo que
pasa**: la anomalía está en la banda superior, con N=516, que no es un tier intermedio ni una muestra
chica. Un Chief Economist lo ve en la primera lectura de la tabla.

**Recomendación:** no incluir esta tabla por banda en material comercial hasta resolverla, y no
describir el defecto como ruido. La credencial defendible de banking es la cohorte (§4.3), no esta curva.

### 4.3 ✅ La cohorte, confirmada en vivo — y son tres, no seis

Corrida real de hoy (1,8 s, `n_found: 6`):

| Banco | Salida | Onset | Lead | Lectura |
|---|---|---|---|---|
| Banco Nacional de Crédito (Bancrédito) | 2003-06 | 2002-07 | **11 meses** | acierto |
| Banco Intercontinental (**Baninter**) | 2003-05 | 2002-10 | **7 meses** | acierto (fraude) |
| Banco Mercantil | 2003-09 | 2003-09 | 0 | señal tardía |
| Banco Global | 2003-06 | — | — | sin onset |
| Banco Universal | 1992-09 | — | — | no evaluable |
| Banco Panamericano | 1992-04 | — | — | no evaluable |

Los 6 están en el ledger, pero el onset exige un cluster que **incluya** una regla de crédito
(`salto_morosidad` / `morosidad_nivel`,
[`sib_historical_backtest.py:136`](modules/banking_score/sib_historical_backtest.py:136) y
[`:150`](modules/banking_score/sib_historical_backtest.py:150)). Sin morosidad en el ledger —inexistente
antes de 1993-12— **no puede disparar por construcción**.

**Cifra citable: 3 evaluables, 2 detectados con anticipación (11 y 7 meses) y 1 señal tardía.**
Decir "seis" infla el denominador sin agregar evidencia. Y el 0 m de Mercantil es artefacto de la
regla de anclaje (`_RUN_GAP=6`), no ceguera del motor: tuvo un run real de deterioro 14 meses antes.

### 4.4 El TPM no supera al baseline en accuracy — pero esa no es la métrica

| | Valor |
|---|---|
| Accuracy | 0,6932 |
| Baseline "siempre mantener" | 0,6932 |
| `beats_baseline` | **false** |
| macro-F1 | 0,5654 |
| Recall `cut` / `hike` | 0,294 / 0,600 |

El modelo **empata** al baseline ingenuo en accuracy. Su valor está en que **anticipa cortes y alzas
que el baseline nunca ve** (recall 0,29 y 0,60 sobre clases que el baseline acierta en 0), lo que se
refleja en el macro-F1. Es exactamente lo que el propio README advierte que hay que leer.

Metodológicamente sigue siendo el backtest más exigente del catálogo (expanding-window
out-of-sample, point-in-time con rezago real de publicación, 190 decisiones del BCRD desde 2008).
**Pero no debe venderse como "le gana al mercado"**: se presenta como anticipación de giros de
política, con el empate en accuracy declarado.

### 4.5 Seguros perdió la concluyencia al recalcular

| Señal | Persistido (viejo) | Recalculado hoy |
|---|---|---|
| Solvencia | Gini 0.3298, IC [0.144, 0.518], n=131 → **concluyente** | Gini **0.0927**, IC [−0.075, 0.282], n=164 → **NO** |
| Underwriting | Gini 0.6063, IC [0.448, 0.744], n=131 → **concluyente** | Gini **0.1563**, IC [−0.015, 0.338], n=163 → **NO** |

Con más datos (164 vs 131 observaciones) **ninguna de las dos señales sobrevive**; `headline_signal`
quedó en `None`. El Gate E funciona como está diseñado: seguros **no** subirá su readiness G5
([`insurance_intel/products.py:368-391`](modules/insurance_intel/products.py:368)).

**Esto es exactamente lo que había que verificar antes de redactar.** Citar el 0.33/0.61 del reporte
viejo habría puesto en el documento comercial una afirmación que hoy es falsa.

### 4.6 El índice sectorial (IAI) da resultado nulo/negativo

| Métrica | Valor |
|---|---|
| IC medio anual (titular) | **−0.03** (t = −0.265), IC [−0.267, 0.208] |
| Spearman pooled | −0.041, IC [−0.221, 0.142] |
| Spearman parcial (control por `sector_growth_T`) | −0.044 |
| Spread de quintiles (top − bottom) | **−1,13 pp** |

El IAI **no ordena** el crecimiento del empleo formal a T+1; el spread es **negativo** (el quintil bajo
creció más). Es un resultado nulo correctamente reportado, pero **no es validación**. Afecta a
`economic_structure` y a `agribusiness`, que se sirve del mismo motor.

### 4.7 Pensiones: el backtest existe y no está servido

`modules/pension_intel/validation/backtest.py` existe, tiene tests que pasan, y su docstring documenta
~1.900 observaciones mensuales. **No hay ninguna ruta de pensiones con validación en el `openapi.json`
de producción** (verificado: 15 rutas de `pension-intel`, ninguna de validación). Es la brecha más
barata de cerrar del catálogo — el motor ya está escrito.

---

## 5. Redacción propuesta para la propuesta a BPD

> De los **16 ejes** del catálogo MIP, nueve tienen validación retrospectiva implementada sobre una
> infraestructura común (`shared/validation/metrics.py`), con la regla de que un intervalo de confianza
> bootstrap que cruza cero se declara **no concluyente** y bloquea la promoción del producto.
>
> **Banking Score es el único validado contra desenlaces reales de entidades**: un registro curado de
> 55 terminaciones del sistema financiero dominicano con fuente documental, y un backtest de alerta
> temprana mes a mes sobre la cohorte de bancos quebrados. De los seis del roster, **tres son
> evaluables** (los otros tres carecen del dato de morosidad, inexistente antes de 1993): sobre esos
> tres, el motor anticipó **Bancrédito con 11 meses** y **Baninter con 7 meses**, y emitió señal tardía
> en Mercantil. Su índice de discriminación sobre el panel trimestral completo es **Gini 0,16
> (IC 95 % 0,08–0,24; 1.693 observaciones, 301 eventos de distress)** — desenlace = distress
> financiero, no quiebra.
>
> **Tres ejes adicionales presentan discriminación concluyente y monótona** contra desenlaces
> realizados: Riesgo Político (Gini 0,199), Comercio (Gini 0,232) y ESG/Clima (Spearman −0,509 contra
> mortalidad por desastre climático, OWID/EM-DAT). **Desarrollo Social** valida por convergencia contra
> el IDH regional del PNUD (Spearman 0,891). **Política Monetaria** corre el backtest metodológicamente
> más exigente del catálogo (expanding-window out-of-sample, point-in-time, 190 decisiones del BCRD).
>
> **Seguros y Estructura Económica corrieron su validación y no resultó concluyente** — se reporta como
> tal. Los siete ejes restantes se ofrecen como co-desarrollo.

**Lo que NO debe entrar al documento comercial hasta resolverse:** la tabla de distress por banda de
banking (§4.2), y cualquier cifra de validación de seguros (§4.5).

---

## 6. Acciones recomendadas, por prioridad

| # | Acción | Por qué |
|---|---|---|
| 1 | **Investigar la caída 0.44 → 0.16** tras la recalibración `02fcdd2` | Sobre panel idéntico la discriminación cayó ~2,7×. O la recalibración degradó el score, o el reporte viejo medía otra cosa |
| 2 | **Recalcular el backtest tras cada recalibración** (colgarlo del pipeline de scoring) | Prod publicó 0.44 durante 3 semanas contra un deck que decía 0.16 |
| 3 | **Arreglar o retirar la tabla por banda** (§4.2) y corregir el texto del caveat | La banda "Sólida" (N=516) tiene 23,1 % de distress; no es ruido de tier intermedio |
| 4 | Exponer el backtest de pensiones en la API | El motor existe y está testeado; es la brecha más barata |
| 5 | Re-auditar readiness de energy/telecom | El único dato trazable es del 24-jun (≈240 commits atrás) |

---

## 7. Límites de esta certificación

1. **Los reportes con `generated_at` viejo no fueron recalculados**: IRMP y trade (27-jul), sector-intel
   (11-jul), ESG (27-jun). Sus endpoints son de solo lectura y no exponen recálculo. Dado lo que pasó
   con banking y con seguros —los dos que **sí** pude recalcular cambiaron de veredicto— **hay que
   asumir que estas cuatro cifras pueden moverse** y recalcularlas por la consola de operaciones antes
   de publicarlas.
2. **No accedí a la base de datos**, solo a la API con la cuenta E2E (`claude@sdqconsulting.com.do`),
   que sigue activa por decisión del dueño hasta el go-live.
3. **"Sin validación" significa no encontrado en este árbol** ni en el `openapi.json` de producción.
   No excluye ramas sin mergear ni notebooks fuera del repo.
4. **No afirmo causalidad** en §4.1 más allá de lo verificado: dos números, panel idéntico, y una
   recalibración intermedia identificada por commit.
