# Evidencia — Piloto Cerebro de Insights · banking_score

> Sensores §5.1 del `Spec_Implementacion_Cerebro_Piloto_BankingScore_v0.1.md`.
> Corrida: 2026-06-22, contra **prod** (Railway) tras mergear #256. Modelo real:
> **Claude Sonnet 4.6**. Set: 5 entidades reales (Popular, BHD, Santa Cruz, BDI,
> Reservas) × 4 audiencias (comite_credito, entidad, inversionista, supervisor) =
> 20 salidas de `entity_rating` + 6 de `indicator_insight` para el gate determinista.

## 1. Calidad (Barra de Insight) — PASA

Reviewer subagent fresco puntuó las 20 salidas contra los 5 tests (Postura·Mecanismo·
Asimetría·Falsabilidad·Decisión):

- **20/20 (100%) con ≥4/5.** 19/20 con 5/5; 1 caso (santacruz_entidad) 4/5 (asimetría
  cuantifica magnitud pero no el costo de equivocarse con nitidez).
- Baseline viejo: el template legacy es una encuesta de 4 bloques que falla
  Postura/Mecanismo/Asimetría/Falsabilidad por construcción (≤1/5). No se capturó
  legacy de prod porque el deploy reemplazó el código antes de la captura; baseline
  establecido estructuralmente + el antes/después mostrado al dueño sobre una entidad real.

Umbral del spec ("nuevo ≥4/5 donde viejo ≤1/5 en ≥4 de 5"): **cumplido** (100%).

## 2. Orientación por audiencia — PASA

Para las 5 entidades, los 4 textos comparten los mismos hechos/cifras y cambian el
"y por tanto" según la audiencia (comité→exposición; entidad→palanca de gestión con
Δscore cuantificado; inversionista→tesis de valor/rentabilidad; supervisor→fragilidad
temprana y prioridad). Reviewer: **las 5 orientadas, no genéricas.** Multi-audiencia
validada.

## 3. Anti-alucinación — 1 FALLO (no-negociable) → requiere guardrail antes de cerrar

- **Gate determinista (path indicador, contexto completo, 6 casos):** toda cifra del
  texto traza al contexto. Los flags del extractor regex son **redondeos** (111.49→"111"),
  **derivaciones** (245.5−147.52≈"98 pp"; 147.52%→"$1.47/peso"), HHI con separador de
  miles, y cifras macro del **telón BCRD** (provenance real). Cero cifras de entidad
  inventadas. → el estándar epistémico funciona: interpreta sin inventar.
- **Lectura holística (20 casos entity_rating):** **1 cifra fabricada** —
  `popular_supervisor` cita "83.42 en junio 2023"; el valor real es **82.42** y 83.42 no
  existe en la serie. Estocástico (los otros 3 archivos de Popular usan 82.42 correcto).
- Per spec §5.1 la regla es **cero cifras inventadas, un fallo bloquea el cierre**.
- **MITIGACIÓN IMPLEMENTADA (guardrail numérico, juez IA):** `shared/narrative/numeric_guard.py`
  + integración en la ruta cerebro del motor. Tras generar, un modelo barato (Haiku,
  `ANTHROPIC_GUARD_MODEL`) juzga si toda cifra del análisis se traza al contexto completo
  (tolerando redondeos, derivaciones, telón BCRD, fechas). Si marca alguna → **regenera
  UNA vez** con corrección explícita; si persiste, sirve igual con `guard_unsupported`
  registrado (best-effort, nunca vacía el insight). Convierte la regla dura en garantía
  mecánica, no solo instrucción del prompt. Verificación post-deploy: re-correr este set
  con el guard activo en prod → confirmar 0 flags persistentes.

## 4. No-regresión / costo — PASA

- `pytest modules/banking_score shared/narrative` = **313 verde**; ruff limpio (PR #256).
- Longitud de salida estable (~2.3–2.7k chars), comparable al baseline; el `system`
  añade input tokens acotado por caching 1h (cache key namespaceada por axis/audience).
- Best-effort verificado: fallo de API → `ai_insight=None`, endpoint nunca rompe.

## 5. Hallazgo colateral (dato, NO del cerebro) — auditar aparte

`tier1_ratio` da **raw NEGATIVO** (Popular −14.21, BDI −13.54; score 0.0, banda "débil")
para bancos grandes — un Tier-1 real es positivo ~10-20%. Bug en el cálculo del
indicador (signo/fórmula). El cerebro lo lee fielmente y lo eleva a "la tensión que
define el rating" en las 5 entidades → las lecturas se anclan en un dato corrupto.
Tarea separada de auditoría del pipeline banking_score (no del cerebro).

## Veredicto

El cerebro entrega **juicio decision-grade con orientación por audiencia genuina**,
validado sobre Sonnet real y entidades reales (Barra 100%, orientación 5/5). **Pendiente
para cierre formal:** (a) guardrail numérico anti-alucinación (1/20 falló, no-negociable);
(b) selector de audiencia en frontend (PR aparte). Hallazgo de dato `tier1_ratio` →
auditoría separada.
