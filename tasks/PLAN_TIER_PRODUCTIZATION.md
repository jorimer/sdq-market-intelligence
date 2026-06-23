# PLAN — Productización por niveles (Pulse / Insight / Deep Dive) · `banking_score`

> v0.1 · 2026-06-23 · Desglose paso-a-paso (T1–T6) del spec **`docs/SPEC_TIER_PRODUCTIZATION_BANKING.md`**.
> Estilo casa (ver `tasks/PLAN_FINO_SPRINT.md`). Marcar `[x]` al avanzar.
> Regla Plan First: confirmar este desglose con el dueño antes de implementar.
> **No toca `tasks/todo.md`** (sprint Gate E vigente). Para enlazarlo, agregar a mano en todo.md:
> `> Tier productization: tasks/PLAN_TIER_PRODUCTIZATION.md`.

---

## Principio anti-Frankenstein

Un manifiesto declarativo (`product_tiers.py`) gobierna los 3 niveles sobre los **7 tipos de reporte
ya existentes**. No se crean generadores nuevos. Cada Tx es entregable, testeable y reversible.
Orden por dependencia: T1 → (T2 ∥ T3) → T4 → T5 → T6.

---

## T1 · Manifiesto de producto + enum (fundación, sin cambio de comportamiento)

### Pre-requisitos de lectura
- [ ] `reports/pdf_generator.py` — firma `generate_pdf_report(...)` y los 7 `REPORT_TYPES`; cómo
  consume `scoring_result` (`overall_score`, `rating_tier`, `sub_components`, `indicators`).
- [ ] `scoring/weights.py` (5 pilares + indicadores) y `scoring/rating_scale.py` (tiers, `TIER_COLORS`).
- [ ] `models/models.py` — `ReportType` enum y modelo `Report`.

### Pasos atómicos
- [ ] **1.** Crear `reports/product_tiers.py`: `ProductTier(Enum)` = `pulse|insight|deep_dive`,
  `TierManifest(dataclass frozen)`, y `TIER_MANIFESTS` con las 3 definiciones (campos del spec §3.1).
- [ ] **2.** Definir las listas de `sections` por nivel reutilizando claves de sección ya renderizadas
  por `pdf_generator` (cover, radar, sub_scores, indicators, narrative_*) + las nuevas claves
  (`peer_block`, `scenarios`, `recommendation`, `band_distribution`).
- [ ] **3.** Mapear `narrative_templates` por nivel a templates SCQA existentes; marcar los que faltan
  (`scenario_analysis`, `recommendation`) como TODO de T4.
- [ ] **4.** Test unitario del manifiesto: las 3 entradas existen, `base_report_type` ∈ 7 tipos,
  `granularity` ∈ {system, named_entity}, Pulse = system.

### Archivos tocados (esperado)
`reports/product_tiers.py` (nuevo) · `tests/test_product_tiers.py` (nuevo).

### Sensor de cierre
- [ ] `pytest modules/banking_score/tests/test_product_tiers.py -v` verde. `ruff` limpio.
- [ ] Cero cambios de comportamiento en reportes existentes (no se importó aún el manifiesto en runtime).

---

## T2 · Ensamblador + endpoint (Insight primero — reusa lo existente)

### Pre-requisitos de lectura
- [ ] `api/router_reports.py` — `generate_report` (L328+) y `download_report` (firma, validación,
  naming de archivo). Es el molde del nuevo endpoint.
- [ ] `reports/narrative.py` + `shared/narrative/claude_engine.py` — `narrative_engine.generate(...)`.

### Pasos atómicos
- [ ] **1.** Crear `reports/tier_assembler.py` con `assemble_tier_report(...)` (firma del spec §3.2).
- [ ] **2.** Extender `generate_pdf_report` de forma **no-rotura**: params opcionales `sections`,
  `tier`, `sample` (defaults = comportamiento actual). Si `sections` viene, filtra/ordena.
- [ ] **3.** Implementar el camino **Insight**: ensamblar narrativas (templates existentes) + delegar
  en `full_rating`/`scorecard` con las secciones del manifiesto. Incluir gancho de alertas
  (suscribirse a `rating.completed` ya emitido — no crear evento nuevo).
- [ ] **4.** Endpoint `POST /api/v1/banking-score/reports/product` (`tier`, `entity_id`, `period`,
  `sample`). Validar `tier`; errores en español. Reutilizar `download_report` para la descarga.
- [ ] **5.** Etiquetar `Report.product_tier` al persistir (columna nueva — migración en T2 o T5;
  si se difiere, dejar el campo nullable y TODO).

### Archivos tocados (esperado)
`reports/tier_assembler.py` (nuevo) · `reports/pdf_generator.py` (extensión no-rotura) ·
`api/router_reports.py` (endpoint) · `models/models.py` (+`product_tier`) · migración Alembic ·
`tests/test_tier_assembler.py` (nuevo).

### Sensor de cierre
- [ ] Generar un Insight de una entidad real existente: render correcto (rating, radar 5 pilares,
  indicadores, narrativa). `pytest` ≥80% en `tier_assembler`. `alembic upgrade head` OK.
- [ ] Reportes existentes siguen idénticos (regresión). **Reviewer subagent** (toca API + modelo).

---

## T3 · Pulse — agregado de sistema anonimizado (∥ con T2)

### Pre-requisitos de lectura
- [ ] `scoring/batch.py` — cómo se corre el scoring del sistema completo.
- [ ] `scoring/market_concentration.py` y `scoring/rating_scale.py` (bandas/tiers).
- [ ] `api/router_reports.py` — `generate_sector_outlook` / `generate_wire` (nivel sistema existente).

### Pasos atómicos
- [ ] **1.** Decidir el agrupamiento de bandas (3–4) con el dueño (decisión de doctrina, ver spec §7).
- [ ] **2.** Crear `scoring/system_aggregate.py`: `build_system_snapshot(period) -> dict` con
  `band_distribution`, `system_trends`, contexto macro-bancario — **sin** identificadores de entidad.
- [ ] **3.** Camino **Pulse** en `tier_assembler`: consume el snapshot, delega en `sector_outlook`/`wire`.
- [ ] **4.** **Sensor de anonimización**: test que falla si el PDF/estructura Pulse contiene cualquier
  nombre de entidad del catálogo de bancos.

### Archivos tocados (esperado)
`scoring/system_aggregate.py` (nuevo) · `reports/tier_assembler.py` (camino pulse) ·
`tests/test_system_aggregate.py`, `tests/test_pulse_anonymization.py` (nuevos).

### Sensor de cierre
- [ ] PDF Pulse a nivel sistema, en bandas, **cero nombres** (test verde). `pytest` ≥80%.

---

## T4 · Deep Dive — escenarios + recomendación (depende de T2)

### Pre-requisitos de lectura
- [ ] `shared/narrative/claude_engine.py` — estructura de `TEMPLATES` y guard `numeric_guard`.
- [ ] `scoring/entity_insight.py` — contexto de entidad disponible para los prompts.

### Pasos atómicos
- [ ] **1.** Templates SCQA nuevos `scenario_analysis` y `recommendation` (español, SCQA, con bloques
  fijos). La recomendación es **estructurada**: veredicto ∈ {aprobar, condicionar, declinar} +
  condiciones + umbrales de reevaluación.
- [ ] **2.** Builders `_build_scenarios()` y `_build_recommendation()` en `pdf_generator.py`, activos
  solo si `tier == deep_dive`. Sección de limitaciones reforzada.
- [ ] **3.** `_build_peer_block()` (G3) reutilizando `market_concentration` — para Insight y Deep Dive.
- [ ] **4.** Pasar las narrativas nuevas por la inyección `cifras_derivadas` + `numeric_guard`
  (no inventar cifras; mismo patrón anti-alucinación del Cerebro).

### Archivos tocados (esperado)
`shared/narrative/claude_engine.py` (+2 templates) · `reports/narrative.py` (wrapper) ·
`reports/pdf_generator.py` (+builders) · `tests/test_deep_dive_sections.py` (nuevo).

### Sensor de cierre
- [ ] Deep Dive = Insight + escenarios + recomendación estructurada + limitaciones. Guard:
  0 cifras inventadas, 0 período equivocado. `pytest` ≥80%. **Reviewer subagent**.

---

## T5 · Marca por nivel + fixtures de muestra (`Banco Demo, S.A.`)

### Pasos atómicos
- [ ] **1.** Marca/pie por nivel en `_build_cover_page`: Pulse "Vista abierta"; overlay rojo
  "MUESTRA — DATA ILUSTRATIVA" cuando `sample=True`.
- [ ] **2.** Fixture `tests/fixtures/banco_demo.py`: `scoring_result` sintético realista (KPIs del
  Anexo del catálogo). Marcar claramente como ilustrativo.
- [ ] **3.** Script/CLI `scripts/generate_tier_samples.py`: emite los 3 PDFs muestra (uno por nivel).
- [ ] **4.** Verificar que los 3 muestran las reglas de granularidad correctas (Pulse sin nombres,
  Insight/Deep Dive con `Banco Demo, S.A.`).

### Archivos tocados (esperado)
`reports/pdf_generator.py` (marca) · `tests/fixtures/banco_demo.py` · `scripts/generate_tier_samples.py`.

### Sensor de cierre
- [ ] 3 PDFs muestra generados e inspeccionados visualmente. Overlay de muestra presente.

---

## T6 · Cierre — cobertura, sensores, reviewer, lecciones

### Pasos atómicos
- [ ] **1.** Cobertura ≥80% en `product_tiers.py`, `tier_assembler.py`, `system_aggregate.py`.
- [ ] **2.** Correr TODOS los sensores del spec §6 y reportar output.
- [ ] **3.** **Reviewer subagent** fresco sobre el diff completo (pasarle spec + `CLAUDE.md`).
- [ ] **4.** Actualizar `tasks/lessons.md` (síntoma/causa/regla/disparador) con lo aprendido.
- [ ] **5.** Test "manifiesto-driven": quitar una sección del manifiesto cambia el PDF sin tocar
  el generador.

### Sensor de cierre (global)
- [ ] `pytest modules/banking_score shared/narrative -v` verde, cobertura ≥80% en lo nuevo.
- [ ] `ruff` limpio · `alembic upgrade head` OK · 3 muestras OK · guard limpio · reviewer sin críticos.
- [ ] Pregunta de staff engineer: ¿agregar un 4º nivel o un 2º sector es editar manifiesto + fixture,
  sin tocar el motor? Si no, no está cerrado.

---

## Resumen de archivos nuevos

```
modules/banking_score/reports/product_tiers.py        # manifiesto (T1)
modules/banking_score/reports/tier_assembler.py       # ensamblador (T2)
modules/banking_score/scoring/system_aggregate.py     # Pulse anonimizado (T3)
modules/banking_score/tests/test_product_tiers.py
modules/banking_score/tests/test_tier_assembler.py
modules/banking_score/tests/test_system_aggregate.py
modules/banking_score/tests/test_pulse_anonymization.py
modules/banking_score/tests/test_deep_dive_sections.py
modules/banking_score/tests/fixtures/banco_demo.py
scripts/generate_tier_samples.py
```

## Resumen de archivos extendidos (no-rotura)

```
modules/banking_score/reports/pdf_generator.py        # params sections/tier/sample + builders
modules/banking_score/reports/narrative.py            # wrappers de templates nuevos
modules/banking_score/api/router_reports.py           # POST /reports/product
modules/banking_score/models/models.py                # +product_tier en Report
shared/narrative/claude_engine.py                      # +templates scenario_analysis, recommendation
infrastructure/alembic/.../<rev>_product_tier.py      # migración
```
