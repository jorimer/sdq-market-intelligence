# Evidencia — Piloto Cerebro de Insights · banking_score

> Sensores §5.1 del `Spec_Implementacion_Cerebro_Piloto_BankingScore_v0.1.md`.
> Corridas contra **prod** (Railway). Modelo de generación: **Claude Sonnet 4.6**;
> guardrail (juez LLM): Sonnet 4.6. Set del sensor: 6 entidades reales (Banco Popular
> Dominicano, BHD, Santa Cruz, BDI, Reservas, APAP) × 4 audiencias
> (comite_credito·entidad·inversionista·supervisor) = 24 salidas `entity_rating`.

## 0. Fix de dato tier1 — VERIFICADO EN PROD

`tier1_ratio`/solvencia llegaban NEGADOS del SIB (signo). Corregido (#257) y propagado:
Popular tier1 raw **+14.73 %, score 100** (antes −14, score 0); BDI **+13.87 %, score 100**.
Solidez de Popular = 100 y score global **88.96 (SDQ-AA)**. El cerebro ya no se ancla en un
dato corrupto. Ver [[cerebro-insights-pilot]].

## 1. Calidad (Barra de Insight) — PASA

20/20 (100 %) con ≥4/5 sobre Sonnet real (corrida inicial). Umbral del spec cumplido.

## 2. Orientación por audiencia — PASA

Las 4 audiencias comparten hechos/cifras y cambian el "y por tanto" (comité→exposición;
entidad→palanca con Δscore; inversionista→tesis de valor; supervisor→fragilidad temprana).
Reviewer: orientadas, no genéricas.

## 3. Anti-alucinación — NO-NEGOCIABLE (cifras inventadas) CERRADO

Trayectoria del guardrail, medida re-corriendo el sensor en prod tras cada deploy y
auditando cada cifra contra su contexto (subagente verificador + verificación manual):

| Versión del guard | (a) cifra inventada | (b) valor en período errado | (c) relacional/derivado mal calc. |
|---|---|---|---|
| Juez Haiku (#258) | 1/20 | — | — |
| Juez Sonnet, prompt endurecido (#259) | varias | 2 | 2 |
| Determinista + inyección (#260) | **0** | **0** | 3 |
| + modos relacionales (#261) | **0** | **0** | 6 (modos nuevos) |
| + prevención de derivados (#262) — **v5** | **0** | **0** | **4** |

**El no-negociable del spec ("cero cifras inventadas") está MET y estable:** tipo (a)
—cifra que no existe en la serie, el fallo original "83.42"— y tipo (b) —valor real
atribuido a un período equivocado— son **0** en v3, v4 y v5.

Hallazgo metodológico clave: **un juez LLM de una sola pasada (aun Sonnet, con ejemplos
explícitos) no recomputa de forma fiable** — en v2 marcó 0/24 dejando pasar 4 defectos.
La solución que cierra el no-negociable es **mecánica**, en dos capas:

1. **PREVENCIÓN (inyección).** `ai_context_entity` precalcula `cifras_derivadas` (aporte y
   gap al techo por componente, líder vs suma del resto, deltas vs mediana/p75, pares que
   lo superan, rango de 12T con períodos, variaciones del score, cortes de marzo). El thin
   template tiene una **regla dura**: prohibido calcular de memoria números derivados; usar
   solo lo servido; si no está precalculado, expresarlo en palabras sin número.
2. **GARANTÍA (detector determinista).** `numeric_guard.deterministic_unsupported` computa y
   verifica delta-vs-mediana (ligado a la base), rango/extremo de la ventana, valor↔período,
   aporte, dirección vs P75 y conteo bajo umbral. Corre junto al juez LLM (unión → regenera
   1 vez). Validado offline contra 96 textos reales: 0 falsos positivos.

### Residual conocido (tipo c) — calidad, no fabricación

v5 deja **4/24** claims **superlativos** errados ("el mayor gap / el más débil / la mayor
caída") — el modelo olvida **Diversificación** (peso 0.05) al rankear gaps, o no compara
contra toda la serie de caídas. **Todos los números base son correctos**; el error es la
comparación de superlativos. No es una cifra inventada ni mal atribuida → no viola el
no-negociable; es un ítem de rigor relacional. El espacio de estos claims en prosa libre es
ilimitado (cada re-run surge un fraseo nuevo): perseguirlos con regex es whack-a-mole. Fix
futuro barato y acotado: inyectar el **ranking de gaps** (componente de mayor gap) y la
**mayor caída Q1** en `cifras_derivadas` para que el modelo copie el superlativo correcto.

## 4. No-regresión / costo — PASA

`pytest shared/narrative modules/banking_score` 341 verde; ruff limpio. La inyección sube
input tokens (~5.4k→6.0k) acotado por caching 1h. La prevención evita regeneraciones
(v3–v5: `guard_flags=0`, 0 regens — los modos se previenen en origen). Best-effort
verificado: fallo de API/parseo → no rompe el endpoint.

## Veredicto

El cerebro entrega **juicio decision-grade con orientación por audiencia genuina**. El
**no-negociable anti-alucinación (cifras inventadas / mal atribuidas) está CERRADO** y
verificado en prod (v3/v4/v5 = 0), mediante prevención (inyección) + garantía determinista.
Residual de calidad acotado: 4/24 superlativos relacionales (números correctos), con fix
futuro barato identificado. Pendiente del piloto: **Fase 4 — selector de audiencia en
frontend**.
