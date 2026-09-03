# TODO — Sprint vigente · SDQ·MIP

> v2 · 2026-06-12 · Reemplaza el plan por fases v1 (2026-06-06, quedó stale: varios ejes
> ya pasaron de "SPEC.md" a live). El plan rector es **`docs/PLAN_MAESTRO_DESARROLLO.md`**;
> este archivo es solo la ejecución fina del sprint actual. Marcar `[x]` al avanzar.
> Regla Plan First: confirmar este desglose con el dueño antes de implementar.
> **Desglose paso-a-paso por tarea (T1–T5): `tasks/PLAN_FINO_SPRINT.md`.**

---

## 🔴 PROPUESTO (pendiente aprobación) — Perfil SDQ + Fix 0 del ISF
> Spec: `docs/SPEC_PERFIL_SDQ_TAXONOMIA.md` (v1.3). Desglose fino:
> **`tasks/PLAN_PERFIL_SDQ.md`**. Verificación previa hecha 2026-08-07 contra el Excel
> crudo del SIS: bug de doble conteo CONFIRMADO (siniestros = 19% mediana de
> `gastos_totales`, 47% máx.), reaseguro y desglose por ramo CONFIRMADOS como
> disponibles en la fuente. **Corrección al spec §5.2**: el expense ratio no puede ser
> `gastos_totales − siniestros` (la sección 5 incluye cesión de reaseguro y reservas).
> Nada implementado todavía.

---

## ✅ COMPLETADO — Cerebro de Insights (7 ejes, MULTI-AUDIENCIA)
> Spec: `Spec_Implementacion_Cerebro_Piloto_BankingScore_v0.1.md` + arquitectura.
> Evidencia: piloto en `evidence/PILOTO-banking-cerebro.md`; generalización + receta en
> `evidence/CEREBRO-generalizacion.md`. Memoria viva: [[cerebro-insights-pilot]].

**Piloto banking — CERRADO (PRs #256–#267):** núcleo+doctrina+4 frames (`cerebro.py`),
motor con ruta `axis=` no-rotura + `THIN_TEMPLATES` (`claude_engine.py`), 3 call-sites
cableados, selector frontend (Fase 4), sensores en prod. **No-negociable anti-alucinación
CERRADO**: tipo (a) cifra inventada = 0 y tipo (b) período equivocado = 0 (vía PREVENCIÓN
—inyección de `cifras_derivadas`— + DETECTOR DETERMINISTA `numeric_guard.deterministic_unsupported`
+ juez LLM). Tipo (c) relacional/superlativo (números base correctos) ACEPTADO como residual
inherente (no converge por inyección+regex; semántico).

**Generalización — COMPLETA 7/7 (PRs #268–#276):**
- [x] Fundación compartida: `shared/narrative/derived.py` (precompute canónico, banking
  byte-idéntico) + frontend genérico `shared/ui/AudienceTabs.tsx` + `shared/lib/useAudiencePref.ts`
  + slot `actions` en `AiInsightCard`.
- [x] `sector_intel` #268 (verificado prod) · `macro_political_risk` #270 (dirección invertida)
  · `trade_intel` #271 (sin canónico → juez LLM) · `social_dev` #272 · `esg_climate` #273
  · `macro_monitor` #274 (coyuntural, 3 superficies, sync) · `deal_scoring` #275 (rúbrica anclada).
- [x] Cada eje: AXIS_DOCTRINE + AUDIENCE_FRAMES (3-4 audiencias) + thin template + contexto
  canónico + Query `audience` en API + selector frontend + i18n es/en/fr.
- [x] Verificación prod (smoke `scripts/smoke_cerebro_axes.py` #276): voz Sonnet + orientación
  por audiencia distinta en trade/social/esg/macro; logs muestran la ruta cerebro activa.

Pendiente opcional (no bloqueante): el detector determinista solo aplica a ejes con
sub-componentes ponderados (banking/sector/IRMP/social/ESG/deal); comercio y macro usan solo
el juez LLM (no hay descomposición ponderada que guardar). Cross-eje (tools/compare,
market-brief) NO se generalizan.

---

## Principios durables (no cambian)
- **Anti-Frankenstein:** índices en `shared/indices/`, fuentes en `shared/data/` con linaje; módulos se comunican solo por `shared.events.event_bus`. Dato faltante = `null`, nunca interpolar sin disclosure.
- **Mono-tenant.** Conectores `mode = live | fixture` (misma interfaz; live donde hay API).
- **Cinco gates por eje + Gate F transversal** (ver plan §2): A integridad · B prueba · C score · D insight IA · E backtest · **F operabilidad (UI + monitoreo + schedule)**.
- **Operabilidad por defecto:** toda operación recurrente nace con UI. Un endpoint suelto sin UI **no está hecho** (plan §7).

## Orden de fuentes (confirmado)
BCRD ✅ → WGI/Eje 4 ✅ → **ONE/Eje 3 (en curso)** → DGA → DGII (diferido, licencia).

---

## ESTADO (actualizado 2026-06-16)
- **Sprint T1–T5 + T4B: CERRADO.** Ejes 1 (Banca), 2 (Macro) y 4 (IRMP) cerrados a profundidad. Detalle histórico abajo (sección "SPRINT T1–T5").
- **Eje 4 (IRMP): CERRADO** por los 6 gates; metodología validada en panel amplio de 24 países (Gini gobernanza +0.21, IC [0.06, 0.36], monótona). PRs #158–#171. Memoria `eje4-cierre-plan`.
- **Eje 3 (`sector_intel`): EN CURSO.** Espina sectorial = **BCRD valor agregado por sector** (decisión del dueño 2026-06-16), NO la ONE (delgada → enriquecimiento). **T-E3-1 (Gate A) ✅ en prod (PR #172).** Siguiente: T-E3-2. Ver sección "Eje 3" abajo.

## CALIDAD DE INSIGHTS — Cerebro (Gate D, transversal)
> Eleva la narrativa IA de "economista promedio" a juicio decision-grade. Núcleo reutilizable
> (identidad + estándar epistémico + Barra de Insight) + doctrina/audiencia/templates por eje.
> Specs: `../Arquitectura_del_Cerebro_SDQMIP_v0.1.md` + `../Spec_Implementacion_Cerebro_Piloto_BankingScore_v0.1.md`.
> **Plan fino paso-a-paso: `tasks/PLAN_CEREBRO_PILOTO_BANKING.md`.**
- [x] **Piloto `banking_score`** ✅ MULTI-AUDIENCIA (4 frames). Cerebro + ruta `axis=` no-rotura + 3 call-sites + selector frontend + sensores en prod. No-negociable anti-alucinación CERRADO (a/b=0; tipo c residual aceptado). PRs #256–#267.
- [x] **Generalización** ✅ COMPLETA 7/7 (contrato spec §8): sector·IRMP·comercio·social·ESG·macro·deal con doctrina+audiencias+thin+contexto canónico+selector frontend. Fundación `shared/narrative/derived.py`. PRs #268–#276. Ver `evidence/CEREBRO-generalizacion.md`.

## HOUSEKEEPING UI (pre-go-live) — 4 secciones del menú incompletas
> Los 7 ejes están cerrados A–F. Antes del endurecimiento de seguridad, completar las 4 superficies del menú que aún eran placeholder/parciales. Una a la vez (plan fino → confirmación → implementar → verificar prod → reviewer → merge `--no-ff`).
- [x] **#1 · Metodología** (`/methodology`) ✅ **en prod (PR #223).** De solo-pesos a documento vivo de doctrina: marco de gates A–F, doctrina anti-fabricación, fuentes reales por eje (badges), **digest de validación que tira en vivo de los 6 backtests** (significancia honesta: 5 ejes Significativo, Sectorial nulo honesto, Macro n/a monitor), pesos por índice, marco SCQA. Sin backend nuevo. Verificado en prod con cuenta E2E. Reviewer APTO sin blockers.
- [x] **#2 · Comparador** (`/compare`) ✅ **en prod (PR #226).** Comparador unificado cross-eje: selector de dominio (Sectorial · Regulatorio · Social · ESG) → 2–4 ítems lado a lado por score + desglose por dimensión + insight IA comparativo. 1 adapter por dominio (`{load, score}`), tira de endpoints existentes vía el client; `bandFor`/`riskBandFor` correctos; ítem sin score → «Sin score» (anti-fabricación). Backend transversal `POST /tools/compare-insight` (`shared/tools`) + template `cross_compare`. Banca conserva su comparador dedicado (link). Verificado en prod E2E (Uruguay vs Chile → insight Claude real). Reviewer APTO sin blockers.
- [x] **#3 · Market Brief** (`/tools/market-brief`) ✅ **en prod (PR #228).** Síntesis ejecutiva cross-eje de RD generada con Claude. **Decisión de arquitectura (la mejor, no la fácil): server-side como Operación agendable** (`app/market_brief.py`) — ensambla el snapshot de los 7 ejes vía el getter de servicio público de cada módulo, genera el brief (template `market_brief`) y cachea en AppSetting; registrada como Operación → **agendable (Gate F)**, brief recurrente headless. GET `/tools/market-brief` (shared/tools, solo lee KV). `sector_intel.get_latest_scores` (bulk, una query). Front `MarketBriefPage`: tiles de pulso por eje + brief Markdown + Regenerar (admin) con polling. Verificado en prod: **7/7 ejes con dato, brief real claude-sonnet-4-6**, operación completa sin errores. Reviewer APTO (aplicado finding tono ESG).
- [ ] **#4 · Deal Scoring** (`/tools/deal-scoring`) — **FASE 1 EN PROD (PR #225).** IP recuperado (spec XGBoost). **Análisis profundo de 2 backups (OneDrive 37 + LaCie 32 carpetas, ~5,300 docs + email, workflows multi-agente, 2026-06-21):** ~176 oportunidades → **set maestro de ~29 labels validados con evidencia, balanceados (~19 closed / ~10 lost)** en 2 poblaciones (A: deals SDQ; B: real-estate dev CBS). **Dueño: modelar A+B con `deal_type` feature.** Set maestro persistido (`docs/Modelos Propietarios/deal_labels_master.*`, gitignoreado). 100 abiertos = pipeline de recuperación. **Graduación por curva de aprendizaje + IC de AUC en CV, NO "200" arbitrario** (sin sustento; el proto muestra AUC inestable a N=200). Ver [[deal-scoring-ip-and-data]].
  - [x] **G3·a — scaffold del registro** ✅: `HistoricalDeal`, migración `f8b3d1a6c904`, seed anonimizado, backfill, tests.
  - [x] **G3·b — migración en prod** ✅ (PR #225 mergeado, tabla `historical_deals` creada en prod). Pendiente: **cargar el set maestro validado** al registro (necesita endpoint admin de import — Fase 2).
  - [x] **G3·c — rúbrica anclada a los 7 ejes (Fase 1)** ✅ **en prod.** Índice 0-100 explicable, NO probabilidad/modelo entrenado (badge "rúbrica declarada"). `modules/deal_scoring/scoring/rubric.py` (pura) + `app/deal_scoring_api.py` (composición, lee anchors vía getters públicos) + template `deal_outlook`. `market_validation`←IAI, `regulatory_readiness`←IRMP, `climate`←IRC. Front `DealScoringPage`. Verificado prod (anclas IRMP DO 38.3 + IRC DOM 35.6 + IAI 37.5, narrativa claude-sonnet-4-6). Reviewer APTO (fix clamp 0-100). Tests 10/10.
  - [x] **G3·c-bis — Fase 2 (registro + cosecha + curva)** ✅ **en prod (PR #231).** `modules/deal_scoring/api/router.py`: import CSV admin (upsert, sin versionar), cosecha (`POST /deals`), `GET /deals`, `GET /learning-curve`. `validation/learning_curve.py`: LogisticRegression + StratifiedKFold CV + IC bootstrap; **graduación por IC inferior del AUC > 0.65, NO por N**. `DealType += advisory` + migración `d5a1c0b2e9f7` (corrida en prod). Front: "Estado del modelo" + "Guardar al registro" + "Importar CSV". Verificado prod. Tests 14/14.
  - [x] **G3·c-tris — Fase 2.5: gate de graduación libre de fuga** ✅ **en prod (PR #233).** Backfillear los 36 labels retrospectivos inflaba el AUC 0.27→0.96 y graduaba el modelo falsamente (**label leakage**). Fix: columna `retrospective` (migración `b6c4e1f2a3d8` marca pre-existentes como retrospectivas; `import`→retrospectivo, `save_deal`→ex-ante); la curva **gradúa SOLO sobre labels ex-ante**; retrospectivos → `retrospective_diagnostic` marcado "no gradúa". UI: tile "Ex-ante (gradúan)" + panel diagnóstico. Reviewer APTO, 16/16. **134 deals + backfill 4 señales (juicio AI-native, aprobado por dueño) cargados a prod.** Verificado: `n_ex_ante=0, status=rubrica`, diagnóstico 0.962 aislado.
  - [ ] **PENDIENTE (próxima sesión):** (1) ✅ CSV subido. (2) ✅ Backfill 4 señales (retrospectivo). (3) Resolver los 98 "open" a closed/lost (input dueño + email; siguen siendo retrospectivos). (4) **Cosecha going-forward**: scorear deals NUEVOS antes del outcome = únicos ex-ante que gradúan. (5) **G3·d — XGBoost** cuando la curva ex-ante gane el umbral de IC.

## SPRINT T1–T5 (CERRADO) — objetivo original
Cerrar Eje 2 (`macro_monitor`) a profundidad y arrancar Eje 4 (WGI) por Gate A, sobre una base de operabilidad y componentes de IA compartidos que sirvan a todos los ejes. **Resultado: cumplido** (memorias `cierre-banca-tres-puntos`, `eje4-cierre-plan`). El desglose T1–T5/T4B de abajo queda como registro histórico.

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

### T4B · Hardening de Macro (Eje 2) — cierre honesto de Gate D *(corre TRAS T4, ANTES de T5)*

> Decisión del dueño 2026-06-15 (ver `docs/DIAGNOSTICO_MACRO_Y_HARDENING_2026-06-15.md`).
> No es alcance nuevo: es la deuda de Gate C/D que dejó "Insuficiente" + fecha futura.
> Cierra Eje 2 a profundidad antes de abrir Eje 4 (WGI), respetando el orden de fuentes.
> Causa raíz confirmada en código (no inferida).

- [ ] **Punto 1 — fix de fecha futura [bajo].** Subir `POST /data/prune-future` a UI (parte de T2) o correrlo; asegurar que el snapshot del período no incluya períodos futuros. Causa: data futura filtrándose → resumen IA fechado "Diciembre 2026" con filtro en Q1.
- [ ] **Punto 2 — ventana de momentum [bajo-medio].** Alimentar a `compute_series_momentum` la serie histórica completa (no solo el período seleccionado), para que `trend`/`acceleration` se computen sobre ≥3 obs donde existan. Causa: `momentum.py` devuelve `insuficiente` con `len(clean)<2`; el `service` pasa solo el período → 1 punto/serie. Curar la tabla a ~25-30 series cabecera; colapsar/separar las de <2 obs reales.
- [ ] **Punto 3 — reordenar el héroe [bajo-medio].** Subir "Lectura de coyuntura (IA)" (SCQA) a primer plano; degradar la tabla de 292 a drill-down/anexo. Quitar la lectura "2 de 292" de la cabecera.
- [ ] **Sensor:** snapshot sin períodos futuros; tabla cabecera sin muro de "Insuficiente" (cada fila dice algo); narrativa SCQA como elemento principal; navegador claro/oscuro; consola limpia; reviewer subagent sobre el diff.

### T5 · WGI Gate A — arranque Eje 4 (plan §3/§4)
- [ ] `shared/data/wgi_client` live (World Bank API), hereda de `base_client`.
- [ ] Checklist de integridad (plan §4): unidades, matching, linaje, idempotencia por período, rezago declarado.
- [ ] Poblar `macro_political_risk` con dato WGI real (hoy lo referencia sin cablear).
- [ ] Sync de WGI entra a la Consola de Operación (T2) desde el día 1.
- [ ] **Sensor:** sync de un período completo, `errors: []`, un país verificado a mano contra el portal del Banco Mundial.

---

## Eje 3 · `sector_intel` (sectorial) — EN CURSO

> Decisión del dueño 2026-06-16: la espina sectorial = **BCRD valor agregado por sector** (PIB por sectores de origen, 17 sectores = 100% de la economía), NO los 3 anclas finos ni la ONE (que publica poco → queda como **enriquecimiento**). Anti-Frankenstein: reusa la fuente BCRD ya ingerida. Memoria `eje3-sector-intel`.

- [x] **T-E3-1 · Gate A — conector live BCRD valor agregado por sector.** ✅ CERRADO EN PROD (PR #172, `5c126ba`). `shared/data/bcrd_sectors.py` (parser determinista **fail-closed** anti-doble-conteo; `sector_size`=share del VAB, `sector_growth`=real interanual). `bcrd_sectores_sync` → `si_variables` idempotente. Operación `bcrd-sectores-sync` en la Consola (Gate F). Sensor prod: synced 272, 17 sectores, 2018-2025, `errors:[]`; Σ 2024 = 100% exacto. Suite 646 verde, reviewer subagent APTO.
- [x] **T-E3-2 · Contrato macro→sectorial** ✅ (punto 5 del `docs/DIAGNOSTICO_MACRO_Y_HARDENING_2026-06-15.md`). `shared/contracts/macro_sector.py` (tipos `MacroFactor`/`MacroSectorContract`) + `shared/doctrine/macro_sector.yaml` (7 factores: inflación, actividad, TPM, FX, reservas, deuda, remesas → dirección/magnitud + sectores/agentes impactados) + productor `modules/macro_monitor/macro_context.py` (dato real BCRD; faltante → n/d, nunca fabricado) + `GET /macro-monitor/macro-context` + se agrega a `macro.updated`. Consumidor: §2 "Contexto macro" (tab en la página sectorial, resalta el sector seleccionado). Verificado navegador claro/oscuro; reviewer APTO.
- [x] **T-E3-3 · Gate B/C — cablear IAI/SGPS a dato real (single-source)** ✅. `assemble_iai_dataset` (patrón IRMP): **sector** (size/growth) ← `si_variables` (BCRD real); **macro** ← contrato T-E3-2 derivado **por-sector** (`macro_exposure`, en `shared/contracts`); **negocios/talento/regulatoria** ← rúbrica declarada neutral 50 (uniforme — overrides parciales distorsionan el ranking min-max). Operación `sector-snapshot` (Consola) + `GET /dataset` + frontend single-source (sin `SAMPLE_SECTORS`) con **badge real-vs-rúbrica por dimensión**. Contrato persistido a `AppSetting` compartido (cross-módulo sin import). Hallazgo del motor: solo `sector`+`macro` discriminan (las económica-wide normalizan a 50 constante); honestidad declarada en la UI. Verificado navegador claro/oscuro; reviewer APTO. Suben a real: regulatoria←WGI, negocios/talento←estudios ONE.
- [ ] **T-E3-4 · Gate D — insight IA por sector** (template `sector_outlook`, patrón compartido `shared/ui`).
- [ ] **T-E3-5 · Gate E — backtest sectorial** honesto.
- [ ] **Enriquecimiento ONE/WGI** (llegada de turistas, generación de energía, gobernanza) sobre la base BCRD.
- [ ] **ONE como fuente rica (decisión dueño 2026-06-16) — EN CURSO via Eje 6.** La ONE publica datasets estructurados (datos.gob.do CSV) + **estudios/encuestas en PDF** (Censo 2022, ENHOGAR, ENAE, Boletín Pobreza, Anuario Sociodemográfico, Compendio Vitales). Inventario detallado hecho (2026-06-17). Patrón: CSV→índice (como BCRD sectores); PDF→digest IA (como [[bcrd-publications]]).

## Eje 6 · `social_dev` (Social/ONE) — EN CURSO

> Apertura del eje Social con dato real de la ONE, reemplazando el fixture `SAMPLE_REGIONS` (5 regiones inventadas) por las **10 regiones de desarrollo** reales. Decisión dueño 2026-06-17 (Fase 1: lo estructurado/rápido). Inventario IDM→fuente: solo `poverty_rate` es ONE estructurado por región; salud=WDI nacional, inclusión/informalidad=BCRD, educación=Censo/ENHOGAR PDF (extracción diferida). Mosaico honesto como el IAI.

- [x] **T-Social-1 · Gate A — conector ONE pobreza** ✅. `shared/data/one_client.py` live (CSV `descargas.one.gob.do`, pobreza general+extrema por las 10 regiones, 2000-2024, matching acento/alias-tolerante incl. Ozama) → `one_social_sync` → `sd_indicators` (theme/entity_key=región). Operación `one-social-sync` en la Consola. Sensor live: 500 records, Enriquillo 31% (más pobre) / Valdesia 11%. Reviewer APTO.
- [x] **T-Social-2 · Gate B/C — IDM sobre dato real single-source + backfill + purga** ✅. `assemble_idm_dataset` (pobreza ONE por región real + WDI salud nacional real + rúbrica declarada neutral para ingreso/educación/inclusión, badge real-vs-rúbrica), las 10 regiones como peer set; `backfill_idm_scores` (todos los años con pobreza, 2000-2024) + purga del cruft `SAMPLE_REGIONS`; operación `idm-snapshot`; `GET /dataset`; frontend single-source (sin POST de fixture). Sensor: Valdesia 56 (menor pobreza) arriba, Enriquillo 44 abajo. Reviewer APTO. Salud WDI añadida al `one-social-sync`.
- [ ] **T-Social-3+ (Fase 2/3):** extracción AI-native de Censo 2022/ENHOGAR (educación/salud por región) + estudios ONE como publicaciones (digest IA).

## Proceso (recordatorio CLAUDE.md)
- Plan First confirmado antes de implementar cada T.
- Reviewer subagent antes de cerrar cada PR no trivial (diff + este todo + CLAUDE.md).
- `ruff check` sobre todo el changeset (incl. tests) + CI verde + merge `--no-ff`.
- Tras cualquier corrección del dueño: actualizar `tasks/lessons.md` (síntoma, causa raíz, regla, disparador).

## Pre-go-live (en curso)
- [x] **RBAC + administración de usuarios** ✅ **en prod (#235 backend, #236 frontend).** Rol jerárquico super_admin/admin/analyst/viewer + tier free/pro/enterprise (monetización declarada) + CRUD gateado con barandas anti-escalada/anti-lockout + página Administración→Usuarios. Ver [[rbac-user-admin]].
- [ ] **Crear super_admin real:** el dueño setea `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` en Railway → bootstrap idempotente lo crea en el deploy.
- [ ] **Endurecimiento de seguridad:** desactivar cuenta E2E (`scripts/seed_e2e_user.py --deactivate`) una vez exista el super_admin real + revisar exposición del repo público (secretos/datos versionados).
- [~] **Idioma EN/ES/FR (i18n) — por fases.** [x] **Fase 1** (toggle + marco) ✅ #238. [x] **Fase 2** (narrativas IA por idioma) ✅ #240. [~] **Fase 3** (barrido por eje, cada uno 1 PR): [x] ESG #242 · Regulatorio #244 · Sectorial #245 · Social #246 · Comercio #248 · Macro #249 · **Financiero 3/4** (#250 layout+Dashboard · #251 Scoring+Rankings · #252 Scenarios+Compare+Fideicomisos). **PENDIENTE:** Financiero sub-PR 4 (Reports/Model/Validation + drawers EntityInsightDrawer/IndicatorDetailDrawer + PeerBar/TrendChart) · **Plataforma** (Overview/Comparador/MarketBrief/DealScoring/Metodología/Config/UsersAdmin) · **sección Datos** (6 páginas + OperationsConsole). Residual backend: insights persistidos (ej. social) no honran X-Lang. Ver [[i18n-multilang]].

## Deuda registrada (no en este sprint)
- Deal Scoring huérfano → módulo formal. · DGII bloqueado por licencia.
- **Macro punto 4 — capa de traducción [medio]** → diferido a **sprint de diferenciación** (decisión dueño 2026-06-15). Por señal activa / clúster acelerando, una línea de implicación por agente (empleado / PyME / gran empresa), usando el framework del PDF de niveles. Extiende `ai_context.py` + template. Ver `docs/DIAGNOSTICO_MACRO_Y_HARDENING_2026-06-15.md` §3 punto 4.
- **Macro punto 5 — contrato macro→sectorial [medio]** → **documentado hoy, se construye al abrir Eje 3 (ONE)**, no antes (decisión dueño 2026-06-15). Objeto estructurado por período (5-8 factores macro: dirección + magnitud + sectores/agentes impactados) que vive en `shared/` y alimenta la §2 del informe sectorial. **Requisito de diseño para Eje 3:** la §2 "Contexto macro" del sectorial consume este contrato, no re-deriva macro a mano. Spec en `docs/DIAGNOSTICO_MACRO_Y_HARDENING_2026-06-15.md` §3-4 punto 5.

---

## TAREA — Corregir inferencia del Gate E sectorial (IC apilado → IC-mean con t)
> Plan fino (Plan First). Origen: `tasks/TASK_gate_e_ic_inference_fix.md`. Sin migraciones, sin tocar ingesta, sin subir señal.
> **Decisión verificada:** `scipy>=1.12` YA está en `requirements.txt` (línea 10) → uso `scipy.stats.t.ppf` para el cuantil t (lo presente, impacto mínimo; no implemento t a mano).

### 1. `shared/validation/metrics.py` — `mean_ic_with_t(yearly_ics, alpha=0.05)`
- [ ] Función pura, sin DB. Input: lista de ICs anuales (ya filtrados no-None). `k = len`.
  - `k < 2` → `None` (n insuficiente para inferencia).
  - `mean = Σ/k`; `sd` muestral (ddof=1) = `sqrt(Σ(x-mean)²/(k-1))`; `se = sd/sqrt(k)`.
  - `sd == 0` → `t_stat = None`, `ci_lo = ci_hi = mean` (CI degenerado, con disclosure) — no crashea.
  - si no: `t_stat = mean/se`; `tcrit = scipy.stats.t.ppf(1-alpha/2, k-1)` (import lazy dentro); `ci = mean ± tcrit·se`.
  - Devuelve `{mean_ic, n_years, sd, t_stat, ci_lo, ci_hi}` (redondeados). **t de Student df=k-1, NO normal** (n chico es el punto).

### 2. `modules/sector_intel/validation/report.py` — IC-mean como titular
- [ ] Tras `per_year`: `yearly = [p["spearman"] for p in per_year if p["spearman"] is not None]` → `ic = mean_ic_with_t(yearly)`.
- [ ] **Titular nuevo** en el dict: `mean_yearly_ic`, `n_years`, `ic_t_stat`, `ic_ci = [ci_lo, ci_hi]` (None-safe si `ic is None`).
- [ ] **Degradar el pooled:** renombrar `spearman`→`spearman_pooled`, `spearman_ci`→`spearman_pooled_ci`, con nota `"pooled (sin clustering — sobrestima la precisión)"`. Sigue visible, NO titular.
- [ ] `_quintile_spread` → **dentro de cada año y promediado**: nuevo `_quintile_spread_by_year(by_year, k=5)` (por año: ordena las ~10 ramas, top vs bottom k-tile del outcome; promedia los spreads sobre años; salta años con <k ramas). Mismo sesgo de clustering, menor magnitud.
- [ ] **Intacto:** `_partial_spearman` por `sector_growth_T` (`spearman_partial_growth`/`_n`) y `by_year`.
- [ ] Disclaimer: titular = IC-mean con t sobre n años; el pooled es secundario y por qué; dejar explícito que la resolución es **10 ramas, no 17** (manuf/ZF/minería colapsan en "Industrias" del lado del outcome — limitación de resolución, no se resuelve aquí).

### 3. Frontend — `api.ts` + `components/ValidationTab.tsx`
- [ ] `api.ts` `SectorGateEReport`: +`mean_yearly_ic`, `n_years`, `ic_t_stat`, `ic_ci`; renombrar `spearman`→`spearman_pooled`, `spearman_ci`→`spearman_pooled_ci` (opcionales). Mantener `by_year`, `quintile_spread`, partial.
- [ ] `ValidationTab.tsx`: titular = StatTiles `IC medio anual` (`mean_yearly_ic`) + `IC 95% (t · n años)` (`ic_ci`) + `n años` (`n_years`); el `ρ pooled` pasa a tile/nota secundaria etiquetada "apilado, sobrestima precisión". `ciExcludesZero` ahora sobre `ic_ci`.
- [ ] Badge: cuando el `ic_ci` cruza cero → **"Inconclusivo por potencia (n insuficiente)"** (no "No significativo"); si lo excluye → "Significativo". + línea de contexto: "con n por año ≈10, el IC mínimo detectable es alto; validación direccional, no confirmatoria."

### 4. Tests
- [ ] `shared/validation/tests/__init__.py` + `test_metrics.py`: `mean_ic_with_t` con ICs anuales conocidos → mean/t/CI esperados; `k<2`→None; `sd=0`→`t_stat None` sin crash. (+ smoke de `spearman`/`spearman_bootstrap_ci` para mantener cobertura del archivo ≥80%.)
- [ ] `test_validation.py`: el reporte expone `mean_yearly_ic` (titular) y `spearman_pooled` (secundario, etiquetado); señal fuerte sembrada en **≥2 años** → el IC-mean la detecta (CI excluye 0); ruido → CI cruza 0, se reporta tal cual. **Ajustar** `test_gate_e_report_recovers_monotonic_signal` para sembrar ≥2 años (hoy siembra 1 → `mean_ic_with_t` daría None).

### 5. Sensores (correr y reportar; no cerrar en rojo)
```
ruff check shared/validation modules/sector_intel/validation
pytest shared/validation/tests/ modules/sector_intel/tests/test_validation.py -v
pytest --cov=shared/validation --cov=modules/sector_intel/validation --cov-report=term-missing \
       shared/validation/tests modules/sector_intel/tests/test_validation.py   # ≥80% en lo tocado
```
> Nota: el comando de cobertura de la tarea apunta `modules/sector_intel/validation` como path de TEST, pero los tests viven en `modules/sector_intel/tests/` → incluyo `test_validation.py` para que `report.py` quede cubierto de verdad.

### Cierre
- [ ] Reviewer subagent (diff + tarea + CLAUDE.md + lessons): titular = IC-mean con t, pooled secundario y etiquetado, parcial `sector_growth_T` intacto, strings en español.
- [ ] Verificar E2E en prod: tab "Validación" muestra el titular nuevo + badge "Inconclusivo por potencia".
- [ ] Entrada en `tasks/lessons.md` (síntoma/causa/regla/disparador).

---

## ✅ EJECUTADA 2026-09-03 — Fase 0 (T-PS-0): corrida en seco de la ingesta canónica BCRD
> **Informe: `tasks/INFORME_FASE0_PERSISTENCIA_BCRD.md`.** 26 archivos, 0 fallidos, 75,2 s,
> US$0,096. Artefacto `/tmp/fase0_bcrd_would_write.json`. Base del dueño intacta (md5).
> Spec: `docs/SPEC_PERSISTENCIA_SERIES_BCRD.md` §3.1.

- [x] **E1 — 600 series nuevas, 55.759 obs, CERO colisiones** y cero `None` que pisen un
      no-nulo. Las 7 series vivas están en otro espacio de nombres y no se cruzan.
- [x] **E2 — `pib_real` = 77 trimestres ≥ 60: el BVAR de T-MP-3 PROCEDE.** 2007-Q1→2026-Q1,
      sin huecos ni nulos. `ipc_general` 511 desde 1984; índice del IMAE 235.
- [x] **E3 — trampas 1 y 2 CONFIRMADAS; trampa 3 REFUTADA.** `ingest_canonical` ingiere
      archivos completos, así que `excel_series_suffix` NO gobierna la ingesta y el índice
      del IMAE ya se ingiere. Y el sufijo que declara la entrada `imae` no resuelve a
      ninguna serie: es la única de 33 con el puente roto.
- [x] **E4 — 17 de 50 entradas sin `excel_series_suffix`**, todas con archivo que sí produce
      series. El prefijo del código NO es el nombre del archivo (`default_prefix` slugifica).
- [x] **E5 — informe entregado** con recomendación explícita.
- [x] **Hallazgo nuevo:** 29.427 duplicados intra-lote con valores distintos, resueltos por
      «último gana» en silencio. 176 series, 4 archivos, ninguno de la vía de proyección.

---

## ✅ HECHA 2026-09-03 — T-PS-3-acotado: `persist=True` en 4 archivos · commit `eab91d0`
> Autorizada por el dueño tras el informe de fase 0. Decisiones tomadas: el guard de nulos
> va en este PR (no en T-PS-1), y el alcance es **cablear + verificar en dev**, sin desplegar.

- [x] **1. Lista blanca declarada** `canonical.PERSISTIBLES_VERIFICADOS`: los 4 archivos,
      con el motivo de cada exclusión y qué falta para levantarla. Transitoria por diseño.
- [x] **2. `ingest_canonical(solo_archivos=...)`** acota lo que se ESCRIBE, no lo que se
      lee: los 26 se siguen reportando. Default `None` = comportamiento histórico.
- [x] **3. `operations.py` pasa la lista blanca** a `macro-canonical-sync`.
- [x] **4. Guard de nulos §2.2.1** en la rama de actualización de `_upsert_records`.
- [x] **S1/S2 — tests con dientes**, corridos contra el código VIEJO primero: el del guard
      falló con `None == 3.14`; los 4 del alcance fallaron con la firma vieja.
- [x] **S3 — VERDE.** Dos corridas: 6.390 filas · 34 series · 5.881 persistidas cada vez.
      **0 valores cambiados, 0 no-nulos perdidos, 0 claves que aparezcan o desaparezcan.**
      Las 7 series preexistentes: 0 cambios. Hallazgo: la base dev está una migración
      atrás (`mm_series.nature`), y ese fallo se reporta como CONTADOR (`persisted: 0`),
      no como error — quien despliegue tiene que mirar `persisted`, no el estado.
- [x] **S4 — los tres VERDES.** `pytest` 7.434 pasados / 0 fallidos (exit 0) · `ruff` All
      checks passed · `mypy | mypy-baseline filter` **exit code 0**. En la primera pasada
      falló `test_directorio_sqlite.py`: lo causé yo, el script descartable construía un
      engine sin `ensure_sqlite_directory`. Corregido en el script — el guard tenía razón
      y eximirlo habría sido apagar el instrumento.

### Fuera de alcance, declarado
- `frequency` no se propaga acá (T-PS-1). Las 5.881 filas entran con NULL; el backfill
  futuro pasa de 509 a 6.390 filas, no a las 56.268 del canónico completo.
- No se despliega a producción. En prod la base no está vacía y el diff de la fase 0 fue
  contra dev.
- T-PS-2 sigue pendiente, ahora con **tres** trabajos: `pib_sectores_origen`, `imae_indice`
  y **corregir el sufijo roto de la entrada `imae`**.

---

## ✅ HECHA 2026-09-03 — T-PS-1: `frequency` en `_upsert_records` + backfill
> El paso 3 de T-PS-1 (guard de nulos §2.2.1) **ya se hizo** en `eab91d0`.
> Queda la propagación de `frequency` y la migración de backfill.

### Lo que la investigación cambió respecto del plan escrito

- **C6 se queda corta: no son dos vocabularios, son TRES en el mismo campo.**
  `inference.py:509` escribe `frequency="trimestral"` mientras sus hermanas de `:489` y
  `:525` escriben `"quarterly"` y `"annual"` — tres líneas de distancia, misma función. El
  caché de layouts ya tiene los cuatro valores conviviendo: `'quarterly'`, `'annual'`,
  `None` y `'trimestral'`. **Es un bug puntual y entra en este PR.**
- **El vocabulario NO es una preferencia: lo decide un contrato vivo.** `service.py:1169`
  sirve `frequency` por la Data API que consume PMS, hoy derivándolo con `_infer_frequency`,
  que devuelve **inglés**. Además lo escriben en inglés otros siete sitios
  (`insurance_intel` ×5, `pension_intel` ×2) y lo declara el comentario de `models.py:40`.
  Poblar la columna en español cambiaría `quarterly` → `trimestral` en una respuesta que
  hoy ya se sirve. **Va en inglés**, y lo español del canónico se traduce al escribir.
- **`Record` no lleva `frequency`** (`base_client.py:35-48`), así que el escalón 2 de la
  cascada necesita un parámetro nuevo en `_upsert_records` — que tiene **6 sitios de
  llamada**.
- **`spec.frequency` viene `None` en 2 de los 4 archivos encendidos** (`imae_2018.xlsx` e
  `ipc_base_2019-2020.xls`). El escalón 2 no está disponible la mitad de las veces.
- **`mm_series` NO tiene columna `note`.** El §3.2 del spec pide que lo inferido quede
  «marcado en `note`»: **no es implementable como está escrito**. Y sin marca, un valor
  inferido es indistinguible de uno declarado — que es exactamente lo que la doctrina de la
  casa prohíbe.

### Propuesta de diseño (invierte la cascada del spec §3.2, y por qué)

El spec ordena: canónico → spec de extracción → inferencia. Propongo: **el formato del
período manda, y la declaración del canónico es la AUTORIDAD CONTRA LA QUE SE VERIFICA.**

- El período (`2026-Q1`, `2026-07`) **no es una inferencia**: lo fija el parser al
  normalizar y determina la cadencia sin ambigüedad, fila por fila. Cobertura 100%.
- La declaración del canónico es por SERIE, pero un archivo produce muchas series
  (`imae_2018.xlsx` produce 12): aplicarle a las 12 la frecuencia de la entrada canónica es
  una suposición que hoy sale bien **por casualidad** — en los 4 archivos encendidos todas
  las series comparten cadencia, y eso no es una regla.
- Donde declarado y derivado **discrepan**, eso es un defecto que se SURFACEA (es la
  aserción 5 de §4: «ninguna serie trimestral tiene períodos con formato mensual»), no algo
  que se resuelva en silencio eligiendo uno.

Así no hace falta la columna `note`: no se escribe nada inferido-y-sin-marca, porque lo que
se escribe es derivado de dato real, y lo declarado se usa para detectar el error.

### Pasos atómicos

- [x] **1.** `inference.py:509` corregido. Test ESTRUCTURAL con `ast`
      (`test_vocabulario_de_frecuencia.py`) porque el defecto vivía en UNA rama de tres.
- [x] **2.** Hecho. El helper se promovió a `shared/data/series_cadence.py` —hermano de
      `series_nature.py`— en vez de escribir una tercera copia del que ya duplicaban
      `insurance_intel` y `pension_intel`.
- [x] **3.** `_discrepancias_de_cadencia` en `ingest_canonical`, que devuelve
      `cadence_mismatches` y avisa por log. En la corrida real: **0 discrepancias**.
- [x] **4.** `a4c7e1b9d302_backfill_mm_series_frequency.py`, data-only. Verificada sobre
      copia de dev: **509 → 0 NULL** (16 quarterly + 493 monthly), 0 valores alterados.

### Sensores

- [x] **S1 — VERDE, con dientes probados.** Contra el código viejo, `frequency` salía
      `{None}` en las tres filas: la aserción del test nuevo no pasaba.
- [x] **S2 — VERDE, y es el sensor que decidió el vocabulario.** `canonical_series_for_api`
      corrida contra las dos bases: **7 series, 0 cambios de valor** en `frequency`.
- [x] **S3 — VERDE.** Incluye el caso de las 17 entradas sin puente: no se pueden
      verificar y, sobre todo, no producen falso positivo.
- [x] **S4 — VERDE.** Y la corrida completa sobre la base encendida: **6.390 filas, 0 con
      `frequency` NULL, 0 fuera del vocabulario**, idempotente en valor Y en cadencia.
- [x] **S5.** `ruff` verde · `mypy` **exit 0** (con +1 línea de baseline, el mismo patrón
      que sus 5 vecinas de esta función: `row.nature = nat` es una de ellas) · `pytest` abajo.

---

## ✅ HECHA 2026-09-03 — T-PS-2: series faltantes en el canónico
> Tres trabajos. Los dos del IMAE son directos y con evidencia. El tercero **no es el que
> el spec describe**: el archivo que nombra está congelado desde 2019.

### Trabajo 1 · el sufijo roto de la entrada `imae` — RESUELTO CON DATO

La entrada declara `excel_series_suffix="serie_original_variacion_porcentual_interanual"` y
**ninguna** de las 12 series del archivo termina así: es la única de 33 entradas con puente
que no resuelve. Cuál es la correcta se COMPUTÓ, no se eligió por parecido de nombre: contra
la YoY calculada del índice original, sobre 223 períodos comparables,

| candidata | error medio |
|---|---:|
| **`variacion_porcentual_interanual`** | **0,00000 pp** |
| `interanual` | 0,31017 pp |
| `variacion_porcentual_acumulada` | 1,87588 pp |
| `interanual_acumulada` | 1,89979 pp |

- [x] **1.** Hecho. Test con fixture real: los 4 casos fallaban antes.

### Trabajo 2 · `imae_indice`

- [x] **2.** Hecho. **34 entradas con puente, 0 sin resolver** (antes: 1).
      El dato **ya está persistido** (235 obs, 2007-01→2026-07, sin huecos ni nulos): la
      ingesta es por ARCHIVO y el sufijo no la gobierna. Esto es DECLARACIÓN, no un cambio de
      datos — y es lo que permite que el test de §4 lo vigile y que `tpm_modeling` deje de
      consumir un `series_code` que ningún registro declara.

### Trabajo 3 · el PIB sectorial: **el spec nombra el archivo equivocado**

`PIB_sectores_origen.xls` (§3.3 del spec) está **congelado: `last-modified` 2019-02-23**.
Sus dos hojas son «Trim Acum 91-14» — llega a 2014, en base vieja — y sus 132 series MEZCLAN
períodos anuales y trimestrales dentro de la misma serie (`1991` → `2009-Q1`). Es la trampa 1
otra vez: el BCRD migró a un archivo base 2018 y el viejo quedó quieto.

El vigente es **`pib_origen_2018.xlsx`**, `last-modified` **2026-06-29**: cuatro hojas
(nominal y volumen encadenado, trimestral y trimestral acumulado), **2018-Q1 → 2025-Q4**.

**Pero tampoco está listo, por otro motivo.** De sus 98 series trimestrales de volumen
encadenado, cada sector aparece TRES veces y dos llevan el número de fila en el nombre. Qué
es cada una se computó contra el dato:

| serie | qué es | evidencia |
|---|---|---|
| `agropecuario` | índice de volumen (nivel) | base 2018=100 |
| `agropecuario_r46` | **tasa de crecimiento interanual** | error 0,00000 pp vs la YoY del nivel |
| `agropecuario_r83` | **incidencia** (contribución al crecimiento) | valores de orden 0,2 |

El contenido es correcto; **el nombre no dice cuál de las tres es**. Y el guard de la
frontera de escritura solo veta coordenadas de COLUMNA (`_c\d+$`, `service.py:57`): las de
FILA pasan. Serían ~196 series persistidas con un nombre que no dice qué miden — la doctrina
del sujeto, incumplida en la puerta que existe para eso.

Dato para decidir: **hoy hay CERO series `_rNN` en las 600 del canónico completo**, así que
extender el guard no vetaría nada de lo que ya existe.

- [x] **3a.** Corregido en el anexo III del informe, con `last-modified` de los dos archivos.
- [x] **3b.** Hecha, en `yellow` y FUERA de `PERSISTIBLES_VERIFICADOS`. Declarando
      en `homogenization` y `robustness` que dos de cada tres series están sin nombrar.
      **NO entra en `PERSISTIBLES_VERIFICADOS`**: el registro declara qué es citable; la
      escritura espera al nombrado.
- [x] **3c.** Extendido a `_[cr]\d+$`. No vetó nada existente (había 0 códigos `_rNN`).

### Sensores
- [x] **S1 — VERDE con dientes.** Los 4 fallaban antes: «ninguna de las 14 series termina
      así» y «el registro no declara `imae_indice`».
- [x] **S2 — VERDE.** Barrido sobre las 600 series: 34 con puente, 0 sin resolver. Más dos
      guards nuevos: lo habilitado para escribir debe declararse `green`, y el registro no
      puede apuntar a un archivo congelado.
- [x] **S3 — VERDE.** 6.390 filas, 0 valores cambiados, 0 cadencias cambiadas, 0
      discrepancias. `omitidos` pasó de 22 a 23: el archivo nuevo se lee y NO se escribe.
- [x] **S4.** `ruff` verde · `mypy` **exit 0** (sin sumar baseline: anoté la función en vez
      de aceptar la nota) · `pytest` abajo.

### Hallazgo que T-PS-2 destapa y NO resuelve
El nombrado era necesario pero **no suficiente**. Con los nombres arreglados,
`pib_origen_2018.xlsx` sigue sin poder persistirse: sus dos hojas **acumuladas** mezclan
períodos anuales y trimestrales dentro de la misma serie y producen **1.660 duplicados con
valores distintos** en 159 series. Las dos hojas trimestrales —`PIB$_Trim` y `PIBK_Trim`,
justo las que T-MP necesita— extraen limpias: 162 series, 2018-Q1→2025-Q4, cero conflictos.

Como la ingesta es por ARCHIVO y no por hoja, el libro entero queda fuera. Para habilitarlo
hacen falta **una de dos**: arreglar el parseo de las acumuladas, o que el alcance de
escritura pueda declararse por HOJA y no solo por archivo.
