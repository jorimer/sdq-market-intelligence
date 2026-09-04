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

---

## ✅ HECHA 2026-09-03 — T-PS-2b: alcance de escritura POR HOJA
> Sale del hallazgo de T-PS-2: `pib_origen_2018.xlsx` tiene dos hojas limpias y dos rotas, y
> la ingesta es por ARCHIVO, así que el libro entero quedó fuera.

### Qué se habilitaría

| hoja | series | obs | estado |
|---|---:|---:|---|
| `PIB$_Trim` | 65 | 2.080 | limpia — 0 conflictos, 0 períodos mezclados |
| `PIBK_Trim` | 97 | 3.104 | limpia — 0 conflictos, 0 períodos mezclados |
| `PIB$_Trim_Acum` | 65 | 650 | **fuera** — 252 duplicados con valor distinto |
| `PIBK_Trim_Acum` | 98 | 3.136 | **fuera** — 1.408 duplicados con valor distinto |

`mm_series` pasaría de **6.390 a 11.574** filas (+162 series).

### Diseño

- **Una sola estructura, no dos.** `PERSISTIBLES_VERIFICADOS` pasa de lista a diccionario
  `{archivo: None | [hojas]}`: `None` = el archivo entero (lo de hoy), una lista = solo esas
  hojas. Dos estructuras paralelas —una de archivos y otra de hojas— se desincronizan, y ya
  hay lecciones en este repo sobre eso.
- **El filtro es por PREFIJO de código**, `bcrd.xls.<archivo>.<slug_de_hoja>.`, construido con
  el `_slug` del propio motor y no a mano. ⚠️ **El punto final no es cosmético**: `pib_trim`
  es prefijo de `pib_trim_acum`, y sin él habilitar la hoja limpia arrastraría la rota.
- **Solo aplica a libros multi-hoja.** En un libro de una sola hoja el motor NO pone segmento
  de hoja en el código (`bcrd.xls.<archivo>.<métrica>`), así que declarar hojas ahí no
  matchearía nada — eso tiene que fallar ruidosamente, no en silencio.
- Se sigue leyendo y reportando todo; lo acotado se declara en el resultado y en el log,
  ahora con el detalle de hoja.

### Pasos atómicos
- [x] **1.** Hecho: `{archivo: None | [hojas]}`, una sola estructura.
- [x] **2.** `solo_archivos` → `alcance`. No queda ninguna referencia al nombre viejo.
- [x] **3.** Con `_slug` y `default_prefix` del motor, no reconstruidos a mano.
- [x] **4.** Sigue pasando la constante.
- [x] **5.** `PIB$_Trim` y `PIBK_Trim` habilitadas.

### Sensores
- [x] **S1 — VERDE con dientes demostrados.** Un filtro sin el punto final devuelve
      `['pib_trim', 'pib_trim_acum']`; con el punto, solo `['pib_trim']`.
- [x] **S2 — VERDE.** El archivo queda `failed` con el motivo en el reporte, no en cero silencioso.
- [x] **S3 — VERDE.** 11.574 filas exactas. 162 series nuevas, **todas** `quarterly`
      2018-Q1→2025-Q4. **0 observaciones** de las dos acumuladas. **0 series con coordenada**
      (el guard vetó `salud_r69`, la única que el modelo no nombró). Idempotente: 0 cambios.
- [x] **S4.** `ruff` verde · `mypy` **exit 0** sin sumar baseline · `pytest` abajo.

### El guard de robustez pasa a ser por hoja (decisión del dueño)
`robustness` sigue describiendo el ARCHIVO. La regla ahora dice: un archivo habilitado
**entero** debe ser `green`; uno habilitado **por hojas** puede ser `yellow` —eso es
justamente lo que `yellow` significa— siempre que nombre cuáles, y una lista vacía se rechaza
porque sería habilitar nada pareciendo que se habilitó algo.

---

## ✅ HECHA 2026-09-03 — T-PS-2c: las hojas ACUMULADAS del PIB sectorial

### Causa raíz, verificada

Las hojas trimestrales rotulan sus columnas `E-M · A-J · J-S · O-D`; las acumuladas,
`E-M · E-J · E-S · E-D` (enero a marzo / junio / septiembre / diciembre). El mapa
`_QUARTERS` de `periods.py:59` tiene los cuatro primeros y **ninguno de los acumulados**:

```
parse_quarter('A-J') -> 2     parse_quarter('E-J') -> None
parse_quarter('J-S') -> 3     parse_quarter('E-S') -> None
parse_quarter('O-D') -> 4     parse_quarter('E-D') -> None
```

Sin trimestre, la columna cae al AÑO. Así que de cada año, `E-M` sale como `2018-Q1` y las
otras tres colapsan las tres en `2018` — y el dedupe «último gana» deja una arbitraria:

```
2018      103.871   ← E-J
2018      145.421   ← E-S     las tres compiten por la misma clave
2018      192.372   ← E-D
2018-Q1    52.442   ← E-M
```

Eso explica las tres cifras del anexo III de una sola vez: los 1.660 duplicados con valores
distintos, las 163 series que mezclan formas de período, y por qué la hoja acumulada tenía
10 observaciones por serie en vez de 32.

### El arreglo

- [x] **1.** Hecho. Y el calificador `_acumulado` viaja en el CÓDIGO, decidido por el
      encabezado del propio cuadro; el renombrado semántico ya no se lo lleva puesto (perdía
      96 de 163). Más nota metodológica por prefijo, que viaja al cliente por la Data API.
- [x] **2.** Las cuatro hojas habilitadas: **0 duplicados con valor distinto y 0 series con
      períodos mezclados** en las cuatro.

### ⚠️ La decisión que no puedo tomar yo
Con el arreglo, el valor de `pib_trim_acum.agropecuario` en `2019-Q2` es el **acumulado
enero-junio**, no el flujo del trimestre. Lo distingue el segmento de hoja del código
(`pib_trim_acum` frente a `pib_trim`) y nada más: mismo sujeto, misma unidad, mismo período.
Un consumidor que agrupe por el nombre de la serie sin mirar la hoja sumaría peras con
manzanas. Ver la pregunta al dueño.

### Sensores
- [x] **S1 — VERDE con dientes.** Antes: `E-J`/`E-S`/`E-D` → `None`.
- [x] **S2 — VERDE.** Y verificado contra el dato real: la suma de los 4 flujos de 2019
      da 197.776,4 y el acumulado de Q4 da 197.776,4 — diferencia 0,0000.
- [x] **S3 — VERDE.** Las 11.574 claves previas conservaron valor y cadencia; **0 cambios,
      0 desapariciones, 0 claves nuevas fuera del PIB por origen**.
- [x] **S4.** `ruff` verde · `mypy` **exit 0** · `pytest` abajo.

### Hallazgo mayor que esto destapó: la vista previa del modelo estaba TRUNCADA
Al abrir la hoja acumulada apareció que terminaba en **2020-Q2** y no en 2025-Q4. No era el
rótulo: su spec venía del MODELO con `value_col_end=11` sobre un cuadro de 34 columnas, y
re-inferir daba lo mismo. La vista previa muestra `PREVIEW_COLS = 12` y **no declaraba estar
cortada**: el modelo contestó el rango que veía.

No se arregla ensanchando la vista —21 de 27 planillas pasan de 12 columnas, una llega a 256—:
la vista ahora AVISA que está truncada y el pedido ofrece dejar el rango abierto, que el
extractor ya interpretaba como «hasta el final».

Al corregirlo apareció que las otras TRES hojas del mismo libro tenían el mismo defecto un
grado más suave: `cols=[1,33)` les comía el trimestre más reciente. Con los cuatro specs
re-inferidos, las cuatro hojas llegan a **2026-Q1**. `mm_series`: **11.574 → 17.115**.

---

## ✅ BARRIDO HECHO 2026-09-03 — specs cacheados que dejan dato sin leer

Sobre las **27 planillas canónicas / 46 hojas**, con el spec cacheado de cada una.

### Lo primero: el defecto del modelo está CERRADO
De las 46 hojas, **solo cuatro** tenían spec producido por el modelo — las cuatro de
`pib_origen_2018.xlsx` — y las cuatro ya leen hasta el final. Ninguna otra planilla del
canónico depende de una inferencia del modelo, así que la vista previa truncada no dejó más
daño en el corpus.

### Dos truncamientos REALES, los dos de la heurística

| archivo · hoja | lee | de | períodos que se pierden |
|---|---:|---:|---|
| `bpagos.xls` · balanza de pagos | <21 | 24 | **2011, 2012, 2013** |
| `lleg_total.xls` · «1993 - 2026» | <38 | 39 | **2026** |

Ninguno de los dos está en `PERSISTIBLES_VERIFICADOS`, así que **nada de lo persistido hoy
está afectado**. `bpagos` es la serie MBP5 histórica y descontinuada —su nota ya dice que se
use solo antes de 2010—, así que perder 2011-2013 es de bajo impacto. `lleg_total` pierde
**el año en curso**, que en una serie de llegadas turísticas es el dato que más se mira.

### Un falso positivo que conviene no olvidar
El primer barrido marcó `pib_gasto.xls` con «22 columnas con dato sin leer». Es correcto que
no las lea: de la columna 24 en adelante hay OTRO bloque, «Tasas de Crecimiento», con
encabezados `92/91`, `93/92`… La regla útil no es «hay números más allá» —en un cuadro de dos
bloques eso es lo normal— sino **«el encabezado declara un PERÍODO más allá del rango leído»**.
Con la regla afinada, `pib_gasto` sale limpio.

### La otra mitad del barrido: limpia
26 hojas `period_rows` —donde el spec LISTA sus columnas de valor, y truncar significa perder
SERIES enteras y no períodos— y **cero** columnas con dato sin declarar.

### Pendiente de decisión
- [x] **Guard puesto:** `inference.periodos_sin_leer` + `engine._avisar_si_trunca`. El aviso es
      de ARCHIVO (`ValidationReport.avisos`), pone el reporte en `ok=False` y viaja a
      `mm_excel_reports` con el detalle de qué períodos se perdieron. Probado en vivo forzando
      un rango corto sobre `bpagos`: el archivo queda marcado y nombra los 18 años perdidos.
- [x] **Arreglados los dos, y la causa era una sola.** `_axis_year` toleraba la nota al pie
      con barra («2008 3/») pero no los marcadores de PRELIMINAR del BCRD: `2011*`, `2013**`,
      `2021 (p)`. Esos años caían del eje temporal y el rango se cortaba en el último año
      «limpio». `bpagos` recupera 2011-2013 (54 obs cada uno) y `lleg_total` recupera 2026
      (574 obs).

### El mismo rótulo encadenaba los dos defectos del día
En `pib_origen_2018.xlsx` casi todos los años del encabezado están marcados `(p)`. Con
`_axis_year` sin arreglar, la heurística no encontraba eje temporal, devolvía confianza 0,0 y
el trabajo caía en el MODELO — que a su vez truncaba por su vista previa recortada. Un solo
rótulo no reconocido produjo los dos.

Con el arreglo, la heurística resuelve esas cuatro hojas por su cuenta y **su lectura es
idéntica a la del modelo**: mismas 2.145 y 3.234 observaciones, cero diferencias de clave y
cero de valor. Así que además de cerrar el truncamiento, el PIB sectorial deja de depender de
una inferencia paga.

**Alcance del barrido:** 27 planillas / 46 hojas. Solo 4 tenían spec del modelo. 26 hojas
`period_rows` sin columnas de dato sin declarar. `mm_series` sigue en **17.115** filas, con
cero regresión.

---

## ✅ HECHA 2026-09-04 — T-PS-2d: triaje de los archivos con «último gana» (LOS 4)

Re-medidos con el código de hoy (las cifras del anexo I se mantienen). **Tres causas
distintas**, ninguna es la misma:

### 1 · `TASA_DOLAR_REFERENCIA_MC.xlsx` — dos problemas, no uno

| hoja | obs | conflictos | qué pasa |
|---|---:|---:|---|
| `PromTrimestral` · `FPTrimestral` | 616 | **367** | el trimestre se rotula `Enero-Marzo`, `Abril-Junio`… y `_QUARTERS` solo tiene las formas ABREVIADAS (`ene-mar`). Sin trimestre, las 4 filas del año colapsan en el año. |
| `PromMensual` · `FPMensual` · `PromAnual` · `FPAnual` | 2.006 | **0** | ya están limpias |
| `Diaria` | 26.862 | **19.680** | es una serie **DIARIA** de verdad: columnas `Año \| Mes \| Día`. La identidad `(series_code, period)` no tiene día, así que los ~22 días hábiles de cada mes colapsan y sobrevive uno. |

Lo primero es una grafía faltante, del mismo tipo que los rótulos acumulados. Lo segundo es
una decisión de diseño.

### 2 · `piianual_6.xlsx` y `piianual.xls` — una dimensión que no es período

La fila bajo los años lleva `Saldo al inicio | Transacciones Netas | Variaciones de Tipo de
cambio | Variaciones de Precio | Otras Variaciones | Saldo al final`: **seis columnas por
año**, y ninguna es un subperíodo. El spec las ignora (`subperiod_header_row=None`) y las seis
caen en el mismo año — por eso `activos` en 2009 tiene cinco valores distintos (10.959,6 ·
−426,7 · −32,7 · 5,8 · 0,0). No son un conflicto: son **seis series distintas** aplastadas en
una. Bien leídas, el archivo multiplica por seis su información real.

### 3 · `lleg_total.xls` — el grupo no viaja con el número

En `year_blocks`, el encabezado tiene dos niveles: `Total | Tasa de Crecimiento | Dominicanos
| Tasa de Crecimiento`, y debajo `Mensual | Acumulado | Trimestral | Igual Mes…`. «Tasa de
Crecimiento › Igual Mes» aparece bajo *Total* y bajo *Dominicanos*: mismo código, datos
distintos. Es la doctrina del sujeto, en la orientación que todavía no la aplica —
`period_rows` ya tiene `_grupo_a_la_izquierda`, `year_blocks` no.

### Pasos
- [x] **1.** Hecho, más el caso `Año | Trimestre | valores` que la inferencia no contemplaba.
- [x] **2.** Habilitado con **las SIETE hojas**: la diaria también entró.
- [x] **3.** `YYYY-MM-DD` es la cuarta forma de período, con cadencia `daily`, orden
      cronológico e inferencia. `ExtractionSpec.day_col` se detecta por el encabezado y se
      confirma contra el contenido. 17.908 obs diarias, 0 conflictos.
- [x] **4a.** PII: `dimension_header_row` para los seis conceptos por año, y `_axis_year`
      dejó de tomar una FECHA por año —tomaba la fila de fechas de corte como fila de años y
      los flujos salían **corridos un año**—. Verificado con la identidad contable del propio
      cuadro: **cierra en 2.718 casos y falla en 0**. 130→780 y 96→576 series.
- [x] **4b.** `lleg_total`, con DOS defectos de la misma familia: el grupo repetido en
      `year_blocks` (`Tasa de Crecimiento` bajo *Total* y bajo *Dominicanos*) y **dos cuadros
      en la misma hoja** con el eje de años reiniciado —los años completos y el corte
      «enero-julio», con 2023-2025 en los dos y valores distintos—. De 4.555 conflictos a
      **0**; de 59 a 99 series. Habilitado por hoja.

### Sensores
- [x] Los cinco archivos de test nuevos, todos corridos contra el código viejo primero.
- [x] Las 7 hojas con 0 conflictos. Y las dos PII con 0.
- [x] **0 valores, 0 cadencias, 0 desapariciones.** `mm_series`: 17.115 → **51.687**.
- [x] `ruff` verde · `mypy` **exit 0** · `pytest` **7.548, exit 0**.

### Cierre del bloque: los cuatro archivos, cerrados
`mm_series` **509 → 73.472** filas y **7 → 1.828** series. Cero archivos con «último gana»,
cero series con coordenada, cero filas sin cadencia, cero archivos marcados por truncamiento.
Nueve archivos habilitados de 27; los 18 restantes siguen sin evaluar uno a uno.

---

## 🔵 EN CURSO — Los 18 archivos canónicos restantes
> Bloque siguiente al de «LOS 4». Nueve archivos habilitados de 27; estos son los otros 18.
> Instrumental ya construido: la corrida en seco, el barrido de specs cacheados, el guard de
> truncamiento (`periodos_sin_leer`), la medición de conflictos y el diagnóstico de cadencia.

### Los 18
`Costo_Canasta_quintiles_base_2019-2020.xlsx` · `Remesas_6.xlsx` · `Serie_TPM.xlsx` ·
`agregados_monetarios.xlsx` · `base_monetaria.xlsx` · `bpagos.xls` · `bpagos_6.xls` ·
`ipc_base_2019-2020_serie_referencial.xlsx` · `ipc_grupos_base_2019-2020.xls` ·
`ipc_quintiles_base_2019-2020.xls` · `ipc_regiones_base_2019-2020.xls` ·
`ipc_subyacente_base_2019-2020.xlsx` · `pib_gasto.xls` · `reservas_internacionales.xlsx` ·
`taap_activad.xlsx` · `taap_pasivad.xlsx` · `tasa_desocupacion.xls` · `tasa_ocupacion.xls`

### Criterio de habilitación (el mismo que se aplicó a los 9)
Un archivo (o una hoja) entra a `PERSISTIBLES_VERIFICADOS` solo si, medido:
1. **0 duplicados `(serie, período)` con valores en conflicto** — si los hay, el upsert
   resolvería por orden de lectura y el dato publicado sería arbitrario.
2. **0 series con formas de período mezcladas** — anual y trimestral en la misma serie
   significa que el eje temporal se leyó mal.
3. **0 códigos nombrados por coordenada** (`_c\d+` / `_r\d+`): el sujeto no viaja con el número.
4. **0 avisos de truncamiento** (`periodos_sin_leer`) y ninguna columna con dato fuera de la
   lista de series del spec.
5. **0 discrepancias de cadencia** contra lo que declara el registro canónico.
6. Y una **verificación de sentido** propia del archivo cuando la hay (identidad contable,
   YoY reconstruido, suma de partes), no solo ausencia de conflictos.

### Un séptimo criterio, que salió del triaje
**Densidad: filas contra claves distintas.** `taap_pasivad.xlsx` emitía 29.325 filas para
1.610 observaciones reales (×18,21) y todas las de más eran NULAS, así que ninguno de los
seis criterios lo veía. Un cuadro mal leído puede no producir un solo conflicto.

Y una corrección al instrumento antes que a los archivos: la primera medición contaba como
conflicto cualquier duplicado, y la mayoría eran valor contra NULO —que el upsert ya
protege—. Separadas las dos cosas, de 6 archivos «en falla» quedaron 3.

### Pasos
- [x] **1.** Triaje de los 18 con los seis criterios más la densidad.
- [x] **2.** Habilitados los 27 archivos del registro: 18 nuevos, todos verificados.
- [x] **3.** Ocho defectos del nombrado y de la unidad, cada uno con su test corrido antes
      contra el código viejo. El peor: el IMAE, encendido desde el primer bloque, tenía dos
      series que no se persistían nunca y siete que no decían de qué cuadro eran.
- [x] **4.** Corrida completa: **73.472 → 101.251** filas, **1.828 → 2.103** series, **0
      valores cambiados** en lo que ya existía, 1.125 correcciones de metadato, idempotente.
      Gates: pytest 7.631 exit 0 · ruff verde · mypy exit 0.
- [x] **5.** Anexo IX en el informe y entrada en `lessons.md`.

### Lo que queda declarado
249 series huérfanas por renombrado (248 reaparecen con su nombre bueno; la otra era una
columna fantasma con un solo valor real) — limpiadas en dev, **hay que repetirlo en prod**.
`pib_nominal_gasto` sigue sin puente. Producción y T-PS-4, sin empezar.


---

## ✅ COMPLETADO — T-PS-4 + la cura durable del arrastre

### La sincronización poda lo que ella misma dejó de escribir
`ingest_canonical(..., podar=True)`, encendido en la operación mensual. Cuatro frenos, y cada
uno tapa una forma concreta de destruir dato publicado: apagado por defecto · un archivo que
FALLÓ no autoriza a borrar sus series · una lectura que no produjo nada, tampoco · y un TOPE
proporcional que frena y REPORTA si la poda se llevaría más de la mitad de un archivo, porque
un renombrado de esa escala es un evento humano y no algo que una tarea mensual decida sola.
Siete tests, todos corridos antes contra el código viejo.

### T-PS-4 · las siete aserciones de §4
`modules/macro_monitor/tests/test_persistencia_canonica.py`, **137 casos**. El contrato se
congela en un MANIFIESTO comiteado —generado de una corrida real— porque CI no tiene el
corpus y un test que se conforme con una base vacía pasa siempre. `min_obs` es un
**trinquete**: `scripts/generar_manifiesto_canonico.py` se niega a bajarlo, porque regenerar
sería el gesto que borra la evidencia del defecto que el manifiesto existe para detectar.

Dientes probados rompiendo el contrato de a una cosa: detecta las seis (entrada sin serie,
renombrado, hueco, cadencia contradictoria, períodos mezclados, `pib_real` por debajo de 60).

### Lo que encontró en su primera corrida
**Dos huecos en la Tasa de Política Monetaria.** El BCRD rotula «Feb1» y «Mar2» —la llamada a
nota pegada al mes, sin espacio ni barra— y esas dos filas se descartaban en silencio.
No eran meses cualesquiera: **febrero de 2013 y marzo de 2020**, los dos en que el BCRD movió
la tasa (0,05 → 0,0425; y 0,045 → 0,035 al empezar la pandemia). Justo lo que un modelo con
rezagos necesita y lo que un ojo no echa de menos. Recuperadas: 101.251 → 101.257 filas, 0
valores cambiados.

Tres puentes canónicos nuevos donde no había decisión de analista que tomar (`remesas` —el
archivo produce UNA serie—, `tpm`, `ipc_subyacente`): las excepciones sin puente bajan de 18 a
**15**, cada una con su motivo escrito y verificado por un test que rechaza los genéricos.

---

## 🔵 PROPUESTO — BLOQUE PP · Procedencia de proyección
> Spec: `docs/SPEC_PROCEDENCIA_PROYECCION.md` (traído al repo hoy; vivía sin commitear en el
> checkout principal, igual que el de persistencia). Gate previo **CERRADO**: asimetría sí,
> `MIN_OOS = 12`, `N ≥ 8`.

### Qué se construye
Un cuarto estado, `PROJECTED`, entre «tengo el dato» y «declaro la brecha». Hoy
`is_forward_looking` ya detecta lo prospectivo y `_forward_gaps` lo declara brecha: falta la
vía legítima al otro lado del `if`. Una proyección ancla **solo si trae backtest**; si no,
se degrada a `GAP` **con el motivo escrito**, para que el informe diga por qué no se estimó.

### Verificación previa, hecha antes de planear
A diferencia del spec de persistencia —cuyos números de línea habían corrido ~30—, **este
spec está verificado contra el código y sus anclas son exactas**: `_evidence_state` :47,
`SubQuestion` :64, `anchored` :78, `VariableSignal` :66, `state_counts` :148, `_real_credit`
:155, `by_state` :173, `registry_passages` :36, `orchestrator` :110 y `_forward_gaps` :114,
`provenance_paragraph` :140, la ruta `quality` :479. Las trece coinciden.

Una corrección al plan igual: `by_state` (`signals.py:173`) **hoy inicializa tres claves y
acumula con `.get(k, 0)`**, así que no explota con una cuarta; el cambio es de consistencia
de reporte, no un arreglo de bug. El plan ya lo dice y se confirma.

### Pasos
- [x] **T-PP-1 · Vocabulario.** `PROJECTED`, alias, `ProjectionMeta` frozen (16 campos, §3.2),
      `projection` en `VariableSignal`. `normalize_state` sigue mandando lo desconocido a
      `GAP`: una cadena no reconocida nunca escala a proyección.
- [x] **T-PP-2 · Cobertura y su asimetría.** `_projected_credit` con `real_fraction` (no
      `1.0` plano), `coverage_projected` como propiedad HERMANA. **El test que manda:**
      convertir una señal `GAP` en `PROJECTED` admisible y comprobar que `coverage_real`
      queda IDÉNTICO. Más el diff de `scripts/build_estado.py` sobre los 17 productos: si se
      movió un decimal, es un bug.
- [x] **T-PP-3 · Gate de admisión** (`shared/registry/projection.py`, nuevo). Las once
      condiciones de rechazo, una por test. `MIN_OOS = 12`.
- [x] **T-PP-4 · Anclaje condicionado.** `anchored` con **desempaquetado de la tupla** —una
      tupla no vacía es siempre truthy, y retornarla directo ancla TODA proyección, que es lo
      contrario de lo que el bloque existe para lograr—. Cableado en tres puntos, ninguno en
      `_evidence_state`.
- [x] **T-PP-5 · Prosa.** El error va en la MISMA frase que la proyección, nunca en
      limitaciones al final.
- [x] **T-PP-6 · Cerebro y API.** Cuarto párrafo del `EPISTEMIC_STANDARD` en el núcleo (es
      regla de la casa, no de macro) y `quality` aditivo. Grepear `by_state` en `frontend/`.

### Cómo lo voy a partir en PRs
1. **T-PP-1 + T-PP-2 + T-PP-3** — vocabulario, cobertura y gate. Todo interno, sin cambiar
   comportamiento observable: el test de no-regresión de cobertura es el que lo cierra.
2. **T-PP-4** — el anclaje. Es el que cambia qué se publica, y va solo.
3. **T-PP-5 + T-PP-6** — prosa, Cerebro y API.

### Lo que NO se hace acá
Ningún modelo de proyección: eso es BLOQUE MP y depende de este. Sin `PROJECTED` no hay
dónde poner un pronóstico; con `PROJECTED` y sin motor, el gate simplemente degrada todo a
`GAP` — que es el comportamiento correcto y el de hoy.


### PR 1 del bloque PP — hecho
`PROJECTED` en el vocabulario, `ProjectionMeta` (16 campos), `coverage_projected` como
propiedad hermana y el gate de admisión con sus once condiciones de rechazo, una por test.

**El sensor que gobierna el bloque, con dientes.** La primera versión comparó los 17 ejes sin
base: los 17 salían «pendiente de cableado», sin señales, y la comparación era de ceros contra
ceros — un sensor que pasa sin mirar. Con la base de dev y los productos registrados
(`import app.main`, que es lo que los registra) el sensor mide de verdad:

| | |
|---|---:|
| ejes / variables | 17 / **134** |
| ejes cuya `coverage_real` se movió | **0** |
| media de cobertura, antes → después | 0,3609 → **0,3609** |
| `by_state`, antes | `{real: 62, rubric: 9, gap: 63}` |
| `by_state`, después | `{real: 62, rubric: 9, **projected: 0**, gap: 63}` |

**Dos correcciones al plan, con evidencia.** `scripts/build_estado.py`, que el plan nombra
como el sensor, **no existe** — la cobertura se computa en `shared/registry/service.py`, y de
ahí sale la medición de arriba. Y `shared/data_api` ya expone la cuarta clave como
consecuencia de `state_counts`: es aditivo (el frontend lee `.real`/`.rubric`/`.gap` por
nombre, no itera), pero adelanta parte de T-PP-6.

**Deuda declarada:** `fin_del_periodo` vive ahora en `shared/data/periodos.py`, y hay DOS
copias previas del mismo parse —`modules/macro_monitor/service.py` y
`modules/trade_intel/products.py`— escritas antes. No se unifican acá porque tocarlas es otro
cambio; queda anotado para que la próxima apunte a la de `shared/` y no escriba una cuarta.


### PR 2 del bloque PP — T-PP-4, el anclaje
El cableado en sus tres puntos: el pasaje del registro lleva la meta, `Evidence` la toma, y el
ORQUESTADOR —el único que puede escribir en la sub-pregunta— la asigna. `_evidence_state`
clasifica el estado (eso sí es suyo) pero no propaga la meta: recibe un `Dict` y devuelve un
`str`.

`anchored` desempaqueta la tupla. Y `_forward_gaps` consulta el gate antes de declarar
brecha: si la proyección pasa, no hay límite que declarar; si no pasa, la brecha **dice por
qué** — «no se estima» a secas deja al lector sin saber si es que no hay modelo o si el que
hay no está validado.

Un dato REAL siempre le gana a un pronóstico: la proyección es el último recurso antes de la
brecha, no una alternativa al dato.

**Un test mío nació ciego y lo cacé antes de commitear.** La pregunta de la fixture
—«¿Cuánto va a crecer el PIB en 2026?»— NO la reconoce `is_forward_looking`, así que los
cuatro casos pasaban sin ejercitar nada. Con una que sí reconoce («¿Cuál es la proyección
del PIB para 2026?»), dos fallaron contra el código viejo, que es lo que tenían que hacer.


### PR 3 del bloque PP — T-PP-5 y T-PP-6, y el bloque cierra
`projection_sentence` con sus cuatro elementos: error, calibración empírica del intervalo,
solapamiento CUANDO EXISTE —si no, la cláusula se omite; «no se solapan» es ruido— y corte
de información. El error va en la misma frase que la proyección, no en limitaciones al
final: enterrarlo en el apéndice es la práctica que la plataforma existe para no repetir.

Solo se narra lo que ANCLA: una proyección que el gate rechaza no se cuenta a medias.

El cuarto párrafo del `EPISTEMIC_STANDARD` va en el NÚCLEO, con un test que verifica que no
se coló en la doctrina de ningún eje — si viviera por eje, el primer eje nuevo que emita
proyecciones nacería sin la regla. Y `coverage_projected` en el bloque `quality` de la Data
API, al lado de la real y nunca sumada.

**BLOQUE PP cerrado.** Lo que sigue es MP, el motor, que tiene como precondición dura este
bloque y el de persistencia — los dos ya están.

---

## 🔵 PROPUESTO — BLOQUE MP · Motor de proyección macro
> Spec: `docs/SPEC_MOTOR_PROYECCION_MACRO.md` (traído al repo hoy; vivía sin commitear en el
> checkout principal, como los otros dos). Precondición dura: PS y PP completos — **los dos
> están**.

### T-MP-0 · Los tres gates de viabilidad — CORRIDO, los tres pasan

| gate | medido | veredicto |
|---|---|---|
| `imae_indice` persistido | 235 obs mensuales, 2007-01 → 2026-07, 0 nulas | **PASA** |
| `pib_real` ≥ 60 trimestres | **77**, 2007-Q1 → 2026-Q1, **0 huecos** | **PASA** — el BVAR procede |
| `pib_sectores_origen` ≥ 12 de 17 | **24 de 24** actividades, 0 huecos | **PASA** |

Y el cuarto punto ya estaba verificado: `comunicado_tpm` no existe, así que **T-MP-3 no puede
apoyarse en la regla de reacción** todavía.

**Sin dependencias nuevas.** El spec ya resolvió que `statsmodels` no aporta nada acá —no
ofrece BVAR con prior Minnesota— y que el prior se implementa con observaciones artificiales
sobre OLS, ~40 líneas auditables, verificables contra dos casos conocidos: con tightness → 0
converge al random walk, con tightness → ∞ al OLS sin restringir.

### ⚠️ Lo que la medición cambia respecto del spec
El cuadro por actividad arranca en **2018-Q1**: son **33 trimestres**, no ~76. El spec de
persistencia estimaba 2007→2026 en §4.1, y esa estimación era `[Guessing]`. Con `MIN_OOS = 12`
un backtest sectorial consume más de un tercio de la muestra.

La sección sectorial pasa el gate del plan, pero **lo que puede afirmar es más chico de lo que
el spec suponía**. Eso es una decisión de alcance y la dejo para el dueño, no la tomo yo:
publicar el sectorial con esa profundidad, o dejarlo fuera de la v1 y publicar solo nowcast y
horizonte, que sí tienen 77 y 235 observaciones detrás.

### Pasos propuestos, en el orden del spec
- [ ] **T-MP-1 · El ledger PRIMERO.** No se negocia (§1). `mm_forecast_log` con clave única de
      CINCO campos incluido `revision`; `status` solo `pending|scored` y el linaje en
      `superseded_by` aparte —poner `"superseded"` como status saca la revisión 0 del cómputo
      y borra el pronóstico original del historial, que es lo contrario de lo que `revision`
      viene a impedir—; puntuación AUTOMÁTICA, porque un proceso que depende de que alguien se
      acuerde deja de correr el trimestre en que el resultado es malo.
- [ ] **T-MP-2 · Nowcast** (bridge IMAE→PIB). El criterio de cierre del paquete pide que
      **le gane a un random walk fuera de muestra**; si no le gana, no se publica.
- [ ] **T-MP-3 · BVAR** con prior Minnesota por observaciones artificiales. Sin apoyo en la
      regla de reacción de TPM (no hay panel).
- [ ] **T-MP-4 · Sectorial** — sujeto a la decisión de alcance de arriba.
- [ ] **T-MP-5 · Procedencia**: cablear `ProjectionMeta` del motor al registro. Es lo que
      enciende el trabajo del BLOQUE PP: hasta que esto exista, ninguna señal llega proyectada.
- [ ] **T-MP-6 · Producto y calendario.**

### Cómo lo partiría
El ledger va solo en un PR (es esquema + migración + puntuación). Nowcast en otro, con su
backtest contra random walk como sensor. BVAR en un tercero, con los dos casos límite del
prior. Sectorial y cableado al final.
