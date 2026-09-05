# Modelo de valuación por TIPO de entidad — plan

## Lo que se encontró pidiendo el informe de punta a punta

BHD, cierre 2025, datos reales: **P/B implícito 1,40× a 12,23×**. El panel de ocho
transacciones dice que lo que se paga es **0,77×–2,73×**. El 12,23× no es un valor, es un
modelo roto.

Causa: `g = b × ROE = 0,60 × 22,57 % = 13,54 %` contra `Ke = 14,28 %` — el denominador de la
perpetuidad queda en 0,74 pp. El guard existente solo atrapa `g ≥ Ke`, o sea el caso que **no
converge**; no atrapa el que converge y es imposible. El PIB nominal dominicano crece 9,03 %
de largo plazo: una entidad que crece 13,54 % para siempre termina siendo más grande que la
economía.

## Lo que se midió (SIMBAD, cierres 2019-2025, 145 entidad-año)

### Dispersión de ROE (p75 − p25, pp) — la evidencia del riesgo relativo

| año | banca múltiple | ahorro y crédito | asociaciones | corp. crédito |
|---|---:|---:|---:|---:|
| 2020 | 15,3 | 8,4 | 2,0 | 8,6 |
| 2021 | 23,6 | 7,3 | 2,0 | 3,9 |
| 2022 | 12,7 | 13,8 | 4,0 | 7,6 |
| 2023 | 21,2 | 6,2 | 3,5 | 6,5 |
| 2024 | 17,6 | 11,8 | 3,4 | 0,7 |
| 2025 | 19,3 | 6,3 | 2,4 | 5,2 |

**Lo que la evidencia SÍ sostiene:** las asociaciones son las menos dispersas los **seis de
seis** años, y la banca múltiple la más dispersa **cinco de seis**.

**Lo que NO sostiene:** un orden fino de cuatro. Los dos del medio se cruzan, y las
corporaciones de crédito son **tres entidades** — su dispersión es ruido, no medición.

→ La beta se abre en **TRES** grupos, no cuatro, y las corporaciones comparten el de ahorro
y crédito **por falta de muestra**, declarado.

### Retención implícita `b = ΔPatrimonio / Utilidad`

| tipo | n | b mediano |
|---|---:|---:|
| banca múltiple | 54 | **0,75** |
| bancos de ahorro y crédito | 51 | **0,74** |
| asociaciones de ahorros y préstamos | 25 | **0,99** |
| corporaciones de crédito | 15 | **0,76** |

El 0,99 de las asociaciones no es un artefacto: **son mutuales, no tienen accionistas a
quienes pagar dividendos**, así que retienen todo. Es la diferencia por tipo mejor sostenida
de todas, y hoy el modelo usa un 0,60 igual para las cuatro — una rúbrica que el dato
desmiente.

## Qué se cambia

1. **Tope de crecimiento terminal.** `g = min(b × ROE, crecimiento nominal de largo plazo)`,
   con el tope COMPUTADO de nuestra propia serie de PIB nominal, no escrito a mano. Cuando el
   tope muerde, se declara — es un supuesto que cambia el valor y no puede viajar callado.
2. **Retención por tipo**, medida. Reemplaza el 0,60 de rúbrica.
3. **Beta por tipo**, en tres grupos. El ORDEN está medido; la MAGNITUD del salto es rúbrica
   y se declara como tal.

## Qué NO se cambia, y por qué

* **Las asociaciones se valúan sin trato especial** (decisión del dueño). Que sean mutuales
  entra por la retención medida, que es dato, y no por un caveat aparte.
* **La beta no se desapalanca.** Sigue valiendo el motivo original: en un banco los depósitos
  son materia prima.
* **`Ke` sigue siendo un rango.** Abrir la beta por tipo no lo vuelve un punto.
