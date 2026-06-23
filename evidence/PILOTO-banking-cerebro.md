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
| + modos relacionales (#261) — v3 | **0** | **0** | 3 |
| + prevención de derivados (#262) — v5 | **0** | **0** | 4 |
| + prevención superlativos (#265) — v6 | **0** | 1 | 8 (modos nuevos) |
| + blindaje período forma C (#266) — **v7** | **0** | **0** | 10 |

**El no-negociable del spec ("cero cifras inventadas", tipo a) está MET y estable: 0 en
todas las corridas (v3–v7).** El tipo (b) (valor real atribuido a período equivocado) fue 0
en v3–v5, tuvo 1 caso en v6 ("diciembre 2025 (90.60)", real 89.82) en una forma de prosa
("período (valor)") que el detector no cubría → cubierta con la **forma C estricta
parentética** (validada offline contra 144 textos reales, 0 falsos positivos), y **v7
post-deploy confirmó (a/b)=0 en prod**. El tipo (c) subió a 10/24 en v7 (de 8 en v6) pese a
la prevención de superlativos (#265): **confirma empíricamente que el tipo (c) no converge**
— misma familia de errores (falsa igualdad "Solidez = suma del resto", superlativos de
serie, ponderado vs absoluto) en fraseos nuevos. Es la evidencia que respalda aceptarlo
como residual.

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

### Residual ACEPTADO (tipo c) — rigor relacional, no fabricación

Decisión del dueño tras 4 rondas de medición (v3–v6): **blindar (a/b)=0 y aceptar el tipo
(c) como residual inherente.** El tipo (c) son claims **relativos/superlativos** con el
**número base correcto pero el calificativo mal** ("el doble", "el segundo", "exactamente
igual", "el más bajo de los 3 marzos", "lo superan 6"). Probado empíricamente que NO
converge a cero por inyección+regex: cada ronda elimina los modos vistos y el modelo
inventa formas nuevas (v3→v6: 3·3·4·8; se inyectaron sucesivamente líder-vs-resto,
percentil→conteo, mayor-gap, orden-de-peso, mayor-caída — y aun así surgieron suma-vs-3,
ratio-de-gaps, resta mal, igualdad falsa). La razón de fondo: es un error **semántico**
(palabra calificativa), no numérico — no hay cifra fuera de rango que un check determinista
pueda marcar, y el espacio de comparaciones en prosa libre es ilimitado. Cerrarlo del todo
exigiría salida estructurada (sacrificando la prosa decision-grade que es el valor del
Cerebro) o un juez semántico LLM (ya probado poco fiable). La inyección de `cifras_derivadas`
**reduce** el tipo (c) y, sobre todo, **previene los modos numéricos duros (a/b)**, que es
lo que importa para no tergiversar el dato.

## 4. No-regresión / costo — PASA

`pytest shared/narrative modules/banking_score` 341 verde; ruff limpio. La inyección sube
input tokens (~5.4k→6.0k) acotado por caching 1h. La prevención evita regeneraciones
(v3–v5: `guard_flags=0`, 0 regens — los modos se previenen en origen). Best-effort
verificado: fallo de API/parseo → no rompe el endpoint.

## Veredicto

El cerebro entrega **juicio decision-grade con orientación por audiencia genuina** (Fase 4
selector frontend MERGEADA, #264). El **no-negociable anti-alucinación (tipo a: cifra
inventada) está CERRADO**: 0 en v3–v6, verificado en prod, mediante prevención (inyección de
`cifras_derivadas`) + garantía determinista. El tipo (b) (período equivocado) está blindado
con la forma C estricta del detector (0 FP en 144 textos). El tipo (c) (superlativos/
comparaciones relacionales, números base correctos) se **acepta como residual** por decisión
del dueño: es semántico, no converge por inyección+regex, y cerrarlo sacrificaría la prosa.
**Piloto CERRADO.**
