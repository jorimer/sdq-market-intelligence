# Spec — `macro_political_risk` (Eje 4: Regulatorio & político)

> Estado: **scaffold construido** (engine, weights, normalization, bands, dimensions, models, API, tests 30/30)
> Fase: 2 · v1 2026-05-28 · Doctrina de Casa v1 §6

## 1. Propósito
Índice de Riesgo Macro-Político (IRMP): score 0–100 (**mayor = menor riesgo**) del entorno
macroeconómico y político-institucional como factor externo, explicable y determinista.

## 2. Fuentes (vía `shared/data`)
WGI (Banco Mundial), BCRD (macro/externo), agencias de rating soberano, análisis regulatorio
interno (RCI), módulo de monitoreo (eventos). Normativas y sanciones de la SIB.

## 3. Índice — dimensiones y pesos
Macro 30% · Externa 20% · Político-institucional 25% · Regulatoria 15% · Eventos 10%.
Cada dimensión = promedio de variables normalizadas (regional min-max; inversión para
risk-increasing). Bandas: Bajo ≥80 · Moderado ≥60 · Elevado ≥40 · Alto <40.

## 4. Modelo de datos
`Country`, `IRMPSnapshot` (score, banda, breakdown JSON), `DimensionScore`. PK UUID.

## 5. API — `/api/v1/macro-political-risk`
`GET /weights` (transparencia) · `POST /score` (country_code + dataset regional).

## 6. Eventos
- **Publica** `irmp.updated` → consumido por `banking_score` (overlay) y `sector_intel` (Acceleration Factors).

## 7. Doctrina codificada (§6)
Se puntúa **predictibilidad, no ideología**; discrecionalidad y volatilidad son los mayores
destructores de predictibilidad (RCI); evento = señal, no predicción; lo cualitativo va por
rúbrica con calibración inter-evaluador (Tetlock/Kahneman).

## 8. Criterios de aceptación
- Tests existentes (normalization, bands, dimensions, engine) ≥80%.
- Pendiente: backtesting del IRMP contra episodios conocidos; sensibilidad de pesos ±10%.

## 9. Pendientes de construcción
- Conectores reales (WGI/BCRD) en `shared/data`; persistencia (hoy el engine es DB-agnóstico); monitoreo regulatorio continuo.
