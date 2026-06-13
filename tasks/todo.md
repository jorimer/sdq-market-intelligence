# TODO — Sprint vigente · SDQ·MIP

> v2 · 2026-06-12 · Reemplaza el plan por fases v1 (2026-06-06, quedó stale: varios ejes
> ya pasaron de "SPEC.md" a live). El plan rector es **`docs/PLAN_MAESTRO_DESARROLLO.md`**;
> este archivo es solo la ejecución fina del sprint actual. Marcar `[x]` al avanzar.
> Regla Plan First: confirmar este desglose con el dueño antes de implementar.
> **Desglose paso-a-paso por tarea (T1–T5): `tasks/PLAN_FINO_SPRINT.md`.**

## Principios durables (no cambian)
- **Anti-Frankenstein:** índices en `shared/indices/`, fuentes en `shared/data/` con linaje; módulos se comunican solo por `shared.events.event_bus`. Dato faltante = `null`, nunca interpolar sin disclosure.
- **Mono-tenant.** Conectores `mode = live | fixture` (misma interfaz; live donde hay API).
- **Cinco gates por eje + Gate F transversal** (ver plan §2): A integridad · B prueba · C score · D insight IA · E backtest · **F operabilidad (UI + monitoreo + schedule)**.
- **Operabilidad por defecto:** toda operación recurrente nace con UI. Un endpoint suelto sin UI **no está hecho** (plan §7).

## Orden de fuentes (confirmado)
BCRD (cerrar D+E) → **WGI (siguiente)** → ONE → DGA → DGII (diferido, licencia).

---

## SPRINT — objetivo
Cerrar Eje 2 (`macro_monitor`) a profundidad y arrancar Eje 4 (WGI) por Gate A, sobre una base de operabilidad y componentes de IA compartidos que sirvan a todos los ejes.

### T1 · Refactor compartido de componentes IA (plan §5.1) — *bloquea T3*

> **Plan fino CONFIRMADO** (2026-06-13, tras leer el código real). Ajusta el plan tentativo
> de `PLAN_FINO_SPRINT.md` en 3 puntos que el código contradice (ver "Hallazgos" abajo).
> Refactor PURO: comportamiento y render **idénticos**. Toca prod (Eje 1).

**Blast radius (consumidores, leído del código):**
- `AiInsightCard` → `ComparePage`, `ScenariosPage`, `DashboardPage` (3 páginas). Único acople: `import type { AiInsight } from "../api"`.
- `EntityInsightDrawer` → `RankingsPage`, `DashboardPage`.
- `IndicatorDetailDrawer` → `IndicatorTable` + **anidado dentro de `EntityInsightDrawer`**.

**Hallazgos que ajustan el plan tentativo:**
1. Los drawers NO usan el tipo nominal `AiInsight`; su `ai_insight` es un tipo anónimo inline estructuralmente idéntico. El tipo nominal lo usan solo `AiInsightCard` + los fetchers `getCompare/Sector/ScenarioInsight`. → re-export cubre a los fetchers; los drawers pueden re-tiparse al compartido sin cambio (idéntico estructuralmente).
2. El patrón de dos fases NO es uniforme: `IndicatorDetailDrawer` salta la fase 2 si `!latest.available`; `EntityInsightDrawer` siempre la corre. Ambos mergean **solo** `ai_insight`. → el hook necesita `shouldFetchAi?` y exponer `ai` por separado.
3. `Escape` en `EntityInsightDrawer` tiene semántica anidada (cierra el indicator drawer primero, no la entidad). → el Shell debe aceptar `onEscape?` (default `onClose`) o cerraría ambos a la vez (regresión).

**Decisión de alcance (qué se mueve y qué NO):**
- `AiInsightCard` → se mueve **entero** a `shared/ui/`.
- `EntityInsightDrawer` / `IndicatorDetailDrawer` → **se quedan en banking-score** (cuerpo de dominio: `RatingBadge`, `TrendChart`, `PeerRow`, sub-componentes). Solo se extrae el cascarón + hook + sección IA.

**Pasos atómicos (archivos exactos):** — ✅ implementados y verificados (2026-06-13)
- [x] **1. Tipo compartido.** Crear `shared/ui/insight-types.ts` con `export interface AiInsight { text; model_used; from_cache }`. En `banking-score/api.ts`: borrar la interfaz local y `export type { AiInsight } from "@/shared/ui/insight-types"` (re-export → fetchers y consumidores siguen importando desde `../api` sin ruptura).
- [x] **2. `AiInsightBody` (presentacional compartido)** en `shared/ui/AiInsightBody.tsx`: estados `loading` (skeleton + "Generando análisis de IA… (~10–15s)") / `error` (StateBlock) / `unavailable` (`!ai || model_used==="static_fallback"`, copy vía prop `unavailableHint`) / contenido (`<Markdown text={ai.text}/>` + footer "Generado por IA (model)…"). Props `{ loading; error?; ai: AiInsight|null; unavailableHint: string }`. Es el núcleo común de las 3 superficies (los copys de "no disponible" difieren → prop; `AiInsightCard` además tiene estado `error`, los drawers no → `error` opcional).
- [x] **3. Mover `AiInsightCard`** a `shared/ui/AiInsightCard.tsx`. Mantiene su fetch de una fase (efecto por `depsKey`); su cuerpo pasa a `<AiInsightBody/>`. Import de tipo → `./insight-types`. Actualizar los 3 imports en páginas: `"../components/AiInsightCard"` → `"@/shared/ui/AiInsightCard"`.
- [x] **4. `useTwoPhaseInsight` hook** en `shared/ui/useTwoPhaseInsight.ts`. Firma: `useTwoPhaseInsight<T>(fetchFn: (withAi:boolean)=>Promise<T>, depsKey: string, opts: { pickAi: (d:T)=>AiInsight|null; shouldFetchAi?: (d:T)=>boolean }) → { data: T|null; ai: AiInsight|null; loading; aiLoading; error }`. Reproduce exacto: fase1 `fetchFn(false)`→`data`,`loading=false`; si `shouldFetchAi(data)!==false` → `aiLoading=true`, `fetchFn(true)`→`ai=pickAi(full)`,`aiLoading=false`; cleanup con `active`; reset en cambio de `depsKey`.
- [x] **5. `InsightDrawerShell`** en `shared/ui/InsightDrawerShell.tsx`. Solo cascarón: `fixed inset-0 z-50 flex justify-end` + overlay (`bg-ink/40 backdrop-blur-sm`) + panel (`w-full max-w-lg h-full bg-surface border-l border-line shadow-pop overflow-y-auto`) + header sticky (eyebrow `text-xs text-muted truncate` + `h2` título + botón cerrar) + body wrapper `p-5 space-y-6`. Props `{ eyebrow?; title; onClose; onEscape?; children }`. `Escape`→`onEscape ?? onClose` (preserva semántica anidada).
- [x] **6. Refactor `IndicatorDetailDrawer`**: usar `InsightDrawerShell` + `useTwoPhaseInsight(getIndicatorDetail.bind(bankId,key), `${bankId}:${indicatorKey}`, { pickAi: d=>d.ai_insight, shouldFetchAi: d=>d.latest.available })` + `AiInsightBody` en la sección IA. Cuerpo (valor/score, tendencia, pares) sin tocar. `onEscape` = default (`onClose`).
- [x] **7. Refactor `EntityInsightDrawer`**: igual, con `useTwoPhaseInsight(getEntityInsight.bind(bankId), bankId, { pickAi: d=>d.ai_insight })` (sin `shouldFetchAi`). `onEscape={() => indicatorKey ? setIndicatorKey(null) : onClose()}`. El `IndicatorDetailDrawer` anidado se renderiza como hermano del Shell (fragment), igual que hoy.

**Archivos tocados (esperado):**
`shared/ui/`: + `insight-types.ts`, `AiInsightBody.tsx`, `AiInsightCard.tsx` (movido), `useTwoPhaseInsight.ts`, `InsightDrawerShell.tsx`.
`banking-score/`: `api.ts` (re-export), `components/EntityInsightDrawer.tsx`, `components/IndicatorDetailDrawer.tsx` (refactor), `components/AiInsightCard.tsx` (eliminado), `pages/{Compare,Scenarios,Dashboard}Page.tsx` (1 línea import c/u).

**Sensor de cierre (Gate D infra + §0.1) — NO se cierra sin esto:** — ✅ CERRADO 2026-06-13
- [x] `tsc --noEmit` sin errores + `npm run build` OK. (tsc exit 0; vite build ✓ en 2.42s)
- [x] Navegador **claro y oscuro** (E2E local: backend uvicorn + DB dev con 35 entidades/70 ratings, usuario E2E): Rankings→`EntityInsightDrawer` (score 94.8, SDQ-AA+, sub-comp/tendencia/pares, copy IA exacto); `IndicatorDetailDrawer` anidado (driver "Patrimonio/activos"); **`Escape` cierra solo el anidado** (2→1, entidad queda; 2º Escape 1→0); tema persistido `sdq_dark=1`; `AiInsightCard` Dashboard ("Panorama del sector (IA)", copy de tarjeta); Comparar/Escenarios montan sin crash. Render+comportamiento idénticos.
- [x] Consola del navegador limpia (sin errores en todo el recorrido).
- [x] **Reviewer subagent** (general-purpose, foco diff de comportamiento): **PASS** — 8/8 puntos OK contra HEAD, cero regresiones, solo nits cosméticos. Verificó Escape anidado, dos fases, merge `ai_insight`, copys por superficie carácter-por-carácter, stacking del anidado (fragment vs hijo), `scoreColor` muerto removido solo en Entity.

### T2 · Consola de Operación + retirar curl-only (plan §7.2)
- [ ] Diseñar la Consola de Operación extendiendo la página Datos/Configuración existente (no crear silo).
- [ ] Subir a UI con botón + progreso + estado en DB compartido + historial:
  - [ ] `POST /data/rescore`
  - [ ] `POST /data/recompute-carteras?period=`
  - [ ] `POST /data/fiduciaria-sync` (+ `fiduciaria-sync-status`)
  - [ ] `POST /data/prune-future`
- [ ] Scheduler in-app: cada operación declara cadencia sugerida; avisar de períodos nuevos.
- [ ] Auditoría por corrida (origen manual/schedule/API, usuario, timestamp, resultado).
- [ ] **Sensor:** un humano no-técnico dispara, monitorea y agenda cada una **desde la UI**, sin `curl` ni Railway CLI. Errores en español.

### T3 · Retrofit de IA en `macro_monitor` (plan §5.4/§5.5) — *depende de T1*
- [ ] Endpoint(s) con `?with_ai=bool` (dos fases) + helper best-effort (espejo de `_ai_insight`).
- [ ] `*_ai_context()` compacto por serie/snapshot (no volcar el objeto entero).
- [ ] Template: `trend_analysis` por serie + `executive_summary` para lectura de coyuntura.
- [ ] Frontend: dos `useEffect` (data instantánea → IA en background con "Generando…"), render `<Markdown/>`.
- [ ] **Sensor:** data al instante; IA carga después; al cortar API key cae a fallback sin romper; consola limpia; navegador claro/oscuro.

### T4 · Backtest MVP del Eje 1 (plan §6.4) — con UI (no solo endpoint)
- [ ] Módulo `modules/banking_score/validation/`: derivar desenlace blando ("¿deterioro material en 4T?") desde el histórico SIB.
- [ ] Disciplina point-in-time: sello de disponibilidad (no fin-de-período), cifra originalmente publicada (vía `lineage.py`).
- [ ] Métricas sobre el componente determinista (OOS gratis): **Gini/AR + curva de tasa-de-deterioro por tier SDQ** (verificar monotonicidad).
- [ ] Cablear a `shared/data/outcomes.py` (`LabeledOutcome`).
- [ ] Reporte de validación exportable **+ su página en UI** + refresh agendable (Gate F).
- [ ] Honestidad: intervalos por bootstrap; etiquetar "validación preliminar, no grado-Basilea".
- [ ] **Sensor:** curva monótona (SDQ-D peor) y Gini reportado con IC; reporte visible y regenerable desde UI.

### T5 · WGI Gate A — arranque Eje 4 (plan §3/§4)
- [ ] `shared/data/wgi_client` live (World Bank API), hereda de `base_client`.
- [ ] Checklist de integridad (plan §4): unidades, matching, linaje, idempotencia por período, rezago declarado.
- [ ] Poblar `macro_political_risk` con dato WGI real (hoy lo referencia sin cablear).
- [ ] Sync de WGI entra a la Consola de Operación (T2) desde el día 1.
- [ ] **Sensor:** sync de un período completo, `errors: []`, un país verificado a mano contra el portal del Banco Mundial.

---

## Proceso (recordatorio CLAUDE.md)
- Plan First confirmado antes de implementar cada T.
- Reviewer subagent antes de cerrar cada PR no trivial (diff + este todo + CLAUDE.md).
- `ruff check` sobre todo el changeset (incl. tests) + CI verde + merge `--no-ff`.
- Tras cualquier corrección del dueño: actualizar `tasks/lessons.md` (síntoma, causa raíz, regla, disparador).

## Deuda registrada (no en este sprint)
- Deal Scoring huérfano → módulo formal. · DGII bloqueado por licencia. · Seguridad pre-go-live (admin real, desactivar cuenta de prueba).
