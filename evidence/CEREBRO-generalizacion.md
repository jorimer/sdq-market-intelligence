# Generalización del Cerebro de Insights a todos los ejes

> El piloto cerró en `banking_score` (ver `PILOTO-banking-cerebro.md`). Acá se replica
> el patrón al resto de los ejes, **paridad total** (voz decision-grade + multi-audiencia
> + guardrail determinista + juez LLM).

## Fundación compartida (una vez)

- **`shared/narrative/derived.py` → `derived_figures(score, subcomponents, trend?, peers?)`**:
  precompute canónico de cifras derivadas, movido desde banking. Cada eje emite el contexto
  en la forma canónica (`score_global`, `sub_componentes[{componente,score,peso}]`,
  `tendencia_score?`, `pares?`, `cifras_derivadas`) y el detector determinista
  (`numeric_guard.deterministic_unsupported`) funciona SIN cambios. Solo emite lo que el
  dato del eje soporta.
- **Frontend genérico**: `shared/ui/AudienceTabs.tsx` + `shared/lib/useAudiencePref.ts`
  (selector + hook persistido) + slot `actions` en `AiInsightCard`. Reusables por eje.

## Receta por eje (repetible)

1. `cerebro.py`: `AXIS_DOCTRINE["<eje>"]` + `AUDIENCE_FRAMES["<eje>"][audiencias]`.
2. `claude_engine.py`: `THIN_TEMPLATES["<template>"]` (tarea liviana + disciplina de
   derivadas/superlativos).
3. `<eje>/ai_context.py`: emitir la forma canónica + `cifras_derivadas` (vía `derived_figures`).
4. Router: el insight pasa `axis="<eje>"` + Query `audience`.
5. Frontend: `AudienceTabs` + `useAudiencePref` cableados al fetcher + `depsKey`; i18n es/en/fr.
6. Verificar post-deploy: sensor (voz cerebro + orientación por audiencia + detector + a/b=0).

## Estado por eje

| Eje | Audiencias | Estado |
|---|---|---|
| banking_score | comite_credito·entidad·inversionista·supervisor | ✅ piloto (PRs #256–#267) |
| **sector_intel** | inversionista·empresa·financiador·formulador_politica | ✅ **#268, verificado en prod** |
| macro_political_risk | — | pendiente |
| trade_intel | — | pendiente |
| social_dev | — | pendiente |
| esg_climate | — | pendiente |
| macro_monitor | — | pendiente (call-site sync) |
| deal_scoring | — | pendiente (extraer builder) |

## sector_intel — verificación en prod (#268)

Sensor: 4 sectores × 4 audiencias (`scripts/sensor_sector_prod.py`, dump
`sensor_sector_prod.json`). Resultado:
- **Voz cerebro activa**: Sonnet, prosa decision-grade (~2.0k chars), no descripción.
- **Orientación por audiencia genuina**: mismos hechos (p. ej. agropecuario IAI 43.92,
  banda Media), distinto "y por tanto" por audiencia.
- **Guardrail activo server-side** (logs): atrapó un error de dirección en 1ª pasada
  ("17.02% supera el 17%, no está por debajo"), regeneró una vez, marcó el residual.
- **Anti-alucinación**: tipo (a) cifra inventada = 0, tipo (b) período = 0 (el eje no tiene
  serie). 1/16 tipo (c): suma de subconjunto rúbrica "29.86" (real 28.86) — mismo residual
  relacional aceptado en el piloto (no precalculable todo subconjunto). Procedencia
  real/rúbrica respetada.
