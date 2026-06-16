# PLAN FINO — Sprint vigente (T1–T5)

> v1 · 2026-06-12 · Desglose ejecutable, paso a paso, de las tareas de `tasks/todo.md`.
> Gobernado por `docs/PLAN_MAESTRO_DESARROLLO.md` (gates + §0.1 Doctrina de calidad).
>
> **Cómo se ejecuta (no negociable, plan §0.1):** UNA tarea a la vez. Antes de implementar
> cada T, Claude Code confirma su plan fino con el dueño. Antes de cerrar: sensor mostrado +
> reviewer subagent en lo no trivial. Prohibido correr el lote de corrido.
>
> Las firmas/props citadas abajo fueron leídas del código al 2026-06-12. Si un archivo
> cambió, **releer antes de tocar** — no asumir.

---

## T1 · Promover componentes de IA a `shared/ui/`

**Objetivo:** que todo eje reutilice el patrón de insight sin duplicar. Hoy vive atrapado en `frontend/src/modules/banking-score/`.

**Decisión de diseño (leída del código, justifica el alcance):**
- `AiInsightCard.tsx` ya es **casi genérico**: props `{title, subtitle?, icon?, depsKey, fetcher}`. Su único acople es `import type { AiInsight } from "../api"`. → se promueve **entero**.
- `EntityInsightDrawer.tsx` / `IndicatorDetailDrawer.tsx` están **cargados de dominio bancario** (`RatingBadge`, `TrendChart`, `sub_components`, `peers`, `EntityInsight`, `getEntityInsight`). **NO se promueven enteros** — arrastrarían tipos bancarios a `shared/`. Solo se extrae el **cascarón genérico** + el **patrón de dos fases**.

### Pre-requisitos de lectura
- [ ] Releer `frontend/src/modules/banking-score/api.ts` (o `/api/`) para ubicar la definición del tipo `AiInsight` (campos usados: `text`, `model_used` con sentinel `"static_fallback"`, `from_cache`).
- [ ] Confirmar que `@/shared/ui/primitives` exporta `Card, CardHead, Skeleton, StateBlock` y `@/shared/ui/Markdown` exporta `Markdown` (ya compartidos — verificar imports vigentes).

### Pasos atómicos
- [ ] **1. Tipo compartido.** Mover `AiInsight` (y tipos satélite que use el card/drawer de IA) a `frontend/src/shared/ui/insight-types.ts` (o `shared/lib/`). Re-exportar desde `banking-score/api` para no romper a los demás consumidores del módulo (cambio sin ruptura).
- [ ] **2. Mover `AiInsightCard`.** A `frontend/src/shared/ui/AiInsightCard.tsx`. Ajustar el import de tipo a la nueva ubicación. Sin cambios de comportamiento.
- [ ] **3. Extraer `useTwoPhaseInsight` hook** a `shared/ui/` (o `shared/lib/`): encapsula el patrón leído en `EntityInsightDrawer` (cargar `fetcher(false)` → pintar → `fetcher(true)` en background con `aiLoading`; cleanup con `active`). Firma sugerida: `useTwoPhaseInsight<T>(fetchFn: (withAi: boolean) => Promise<T>, depsKey) → { data, loading, aiLoading, error }`.
- [ ] **4. Extraer `InsightDrawerShell`** a `shared/ui/`: solo el cascarón (overlay `fixed inset-0`, backdrop, panel `max-w-lg`, header sticky con título/subtítulo/botón cerrar, manejo de `Escape`). Props: `{title, subtitle?, onClose, children}`. El **cuerpo de dominio** (badge, sub-componentes, pares) se pasa como `children` y se queda en banking-score.
- [ ] **5. Refactorizar `EntityInsightDrawer` e `IndicatorDetailDrawer`** para consumir `InsightDrawerShell` + `useTwoPhaseInsight` + `AiInsightCard`/sección IA compartida. **Comportamiento idéntico** — esto es refactor puro, no rediseño.

### Archivos tocados (esperado)
`shared/ui/`: + `AiInsightCard.tsx`, `insight-types.ts`, `useTwoPhaseInsight.ts`, `InsightDrawerShell.tsx`.
`modules/banking-score/components/`: `EntityInsightDrawer.tsx`, `IndicatorDetailDrawer.tsx` (refactor).
`modules/banking-score/api`: re-export del tipo.

### Sensor de cierre (Gate D infra + §0.1)
- [ ] `tsc` sin errores + `npm run build` OK.
- [ ] Verificación en navegador **claro y oscuro**: Rankings → abrir `EntityInsightDrawer`; Scoring → abrir `IndicatorDetailDrawer`; drill driver/drag; tarjetas Comparar/Sector/Escenario. **Comportamiento y render idénticos a antes.**
- [ ] Consola limpia.
- [ ] **Reviewer subagent obligatorio** (toca prod): foco en *diff de comportamiento*, no solo de convenciones. Pasarle este plan + `CLAUDE.md`.

> ⚠️ T1 toca `banking-score`, único activo en prod. "Sin cambio de comportamiento" es donde se cuela la regresión silenciosa. No se cierra sin el reviewer + verificación visual completa.

---

## T2 · Consola de Operación + retirar curl-only (plan §7)

**Objetivo:** subir a la UI las operaciones recurrentes que hoy solo corren por `curl`, con progreso, estado en DB compartido, historial y schedule. Operable por humano no-técnico.

### Pre-requisitos de lectura
- [ ] Leer `modules/banking_score/api/router_data.py` para las firmas exactas de: `rescore` (L261), `prune-future` (L278), `fiduciaria-sync` (L587) + `fiduciaria-sync-status` (L607), `recompute-carteras` (L621). Anotar params (`period=`, `force=`, etc.).
- [ ] Leer cómo `sib-backfill` (L233) + `sync-status` (L295) exponen estado en DB y progreso (patrón `sib_sync_status`) — es el molde a copiar.
- [ ] Leer el frontend de referencia: `modules/banking-score/pages/DataPage.tsx`, `modules/platform/pages/ConfiguracionPage.tsx`, `modules/platform/components/SeriesMaintenanceSection.tsx`.

### Pasos atómicos
- [ ] **1. Clasificar** cada operación (plan §7.1): confirmar que las 4 son "recurrente-humana". `sib-page-test`/`sib-explore`/`fiduciaria-pdf-test` quedan como diagnóstico (sin UI).
- [ ] **2. Estado en DB** para `rescore`/`recompute`/`prune`/`fiduciaria-sync` si no lo tienen (espejo de `sib_sync_status`): `is_running`, `phase`, `progress`, `last_result`, `errors[]`, `updated_at`. Compartido entre workers.
- [ ] **3. Endpoints de estado** por operación (o uno unificado `/data/operations-status`).
- [ ] **4. UI — Consola de Operación**: extender la página Datos/Configuración (no crear silo). Por operación: botón disparar, estado en vivo, último resultado + timestamp, errores en español, próximo run agendado.
- [ ] **5. Historial/auditoría**: tabla `operation_runs` (operación, origen `manual|schedule|api`, usuario, inicio/fin, resultado). Mostrar las últimas N en la consola.
- [ ] **6. Scheduler in-app**: cadencia sugerida por operación; ejecutar sin worker Celery aparte; avisar de períodos nuevos. (Reusar/extender lo existente; no duplicar Celery.)

### Sensor de cierre (Gate F)
- [ ] Un humano no-técnico dispara, monitorea y agenda **cada** operación desde la UI, sin `curl` ni Railway CLI.
- [ ] Estado sobrevive a reinicio de worker (en DB, no en memoria).
- [ ] Tests backend de los endpoints de estado + `ruff` + CI verde. Reviewer subagent.

---

## T3 · Insight de IA en `macro_monitor` (plan §5.4/§5.5) — depende de T1

**Objetivo:** primer retrofit del patrón compartido sobre un módulo con datos reales (BCRD).

### Pre-requisitos de lectura
- [ ] Leer `modules/macro_monitor/api/router.py` (endpoints de serie/snapshot, L67–L120 aprox.) para saber dónde colgar `?with_ai=`.
- [ ] Releer `shared/narrative/claude_engine.py`: firma `narrative_engine.generate(context, template, mode)` y templates disponibles (`trend_analysis`, `executive_summary`).
- [ ] Releer el helper `_ai_insight` y `*_ai_context` en `modules/banking_score/api/router_scoring.py` (L49–L57, L135) como molde.

### Pasos atómicos
- [ ] **1. Backend**: en el endpoint de serie/snapshot, añadir `?with_ai: bool = True` (dos fases). Helper best-effort local (try/except, warning en español, `None` si falla — la IA jamás tumba el endpoint).
- [ ] **2. `macro_ai_context()`** compacto por serie/snapshot (valores recientes, momentum, no el objeto entero). Plan §5.2.
- [ ] **3. Templates**: `trend_analysis` por serie; `executive_summary` para lectura de coyuntura del snapshot.
- [ ] **4. Frontend**: en la página de macro, usar `useTwoPhaseInsight` + sección IA compartida (de T1). Render `<Markdown/>`. Placeholder "Generando…".
- [ ] **5. Degradación**: sin API key → fallback estático sin romper.

### Sensor de cierre (Gate D)
- [ ] Data al instante; IA en background; al cortar API key cae a fallback; consola limpia; navegador claro/oscuro.
- [ ] Tests del endpoint con `with_ai=false` (determinista) y best-effort. `ruff` + CI. Reviewer subagent.

---

## T4 · Backtest MVP del Eje 1 (plan §6.4) — con UI

**Objetivo:** validar que el score discrimina, con su reporte en UI y refresh agendable. Artefacto de venta de Confiabilidad.

### Pre-requisitos de lectura
- [ ] Leer modelos en DB: `banking_data`, `rating_results`, `rating_actions` (esquema) para saber qué hay para derivar desenlaces y scores históricos.
- [ ] Releer `shared/data/outcomes.py` (`LabeledOutcome`) y `shared/data/lineage.py`.

### Pasos atómicos
- [ ] **1. Módulo** `modules/banking_score/validation/`: `outcomes_derivation.py`, `metrics.py`, `report.py`.
- [ ] **2. Derivar desenlace blando** "¿deterioro material en 4T?" desde histórico SIB: downgrade ≥2 escalones SDQ / morosidad que duplica / ROA negativo sostenido 2+T / breach de solvencia 10%. Persistir como `LabeledOutcome` con `score_at_prediction`.
- [ ] **3. Point-in-time**: sello = fecha de disponibilidad (no fin-de-período); cifra originalmente publicada (vía `lineage`). Documentar el rezago asumido.
- [ ] **4. Métricas (componente determinista, OOS gratis)**: Gini/AR + curva de tasa-de-deterioro-realizado por tier SDQ (chequear monotonicidad). Intervalos por bootstrap.
- [ ] **5. Reporte** exportable + **página en UI** (no solo endpoint): curva por tier, Gini con IC, etiqueta "validación preliminar, no grado-Basilea".
- [ ] **6. Refresh agendable** vía Consola de Operación (T2) cuando entra período nuevo.

### Sensor de cierre (Gate E + F)
- [ ] Curva monótona (SDQ-D peor que SDQ-A) y Gini reportado con IC; si no es monótona, **no se cierra**: se investiga la causa (no se maquilla).
- [ ] Reporte visible y regenerable desde UI por humano no-técnico.
- [ ] Tests de `metrics.py` con datos sintéticos de Gini conocido. Reviewer subagent.

> Honestidad obligatoria (plan §6.5): con pocos eventos duros esto es direccional. No afirmar Gini alto desde 3 quiebras. Decirlo en el reporte.

---

## T5 · WGI Gate A — arranque Eje 4 (plan §3/§4)

**Objetivo:** conector live del Banco Mundial (WGI) e integridad de fuente; poblar `macro_political_risk` con dato real.

### Pre-requisitos de lectura
- [ ] Leer `shared/data/base_client.py` (interfaz `FixtureBackedClient` / `Record`) y un conector live de molde (`bcrd_api.py` / `bcrd_client.py`).
- [ ] Leer en `modules/macro_political_risk/` dónde se referencia WGI hoy (sin cablear) para saber qué espera el módulo.

### Pasos atómicos
- [ ] **1. `shared/data/wgi_client.py`** live (World Bank Indicators API), hereda de `base_client`, `mode = live|fixture`.
- [ ] **2. Checklist de integridad (plan §4)**: unidades por indicador, matching de países (ISO), linaje (origen/fecha/versión), idempotencia por período, rezago de publicación declarado, errores en español.
- [ ] **3. Cablear** `macro_political_risk` al dato WGI real (reemplazar la referencia no-cableada).
- [ ] **4. Operabilidad (Gate F)**: el sync de WGI entra a la Consola de Operación (T2) desde el día 1 — no nace como curl.
- [ ] **5. Tests**: parser WGI, idempotencia, fallback fixture.

### Sensor de cierre (Gate A + F)
- [ ] Sync de un período completo, `errors: []`; **un país verificado a mano** contra el portal del Banco Mundial.
- [ ] Sync disparable/monitoreable desde UI. `ruff` + CI verde. Reviewer subagent.

---

## Orden y dependencias
```
T1 ──► T3            (T3 usa los componentes compartidos de T1)
T2 ──► T4, T5        (backtest y WGI cuelgan su operación de la consola)
Secuencia sugerida:  T1 → T2 → T3 → T4 → T5
```
Confiabilidad sobre velocidad: si una T no cabe con calidad en su ventana, se parte en sub-tareas, no se recorta el sensor.
