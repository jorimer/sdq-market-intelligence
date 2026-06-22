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
BCRD ✅ → WGI/Eje 4 ✅ → **ONE/Eje 3 (en curso)** → DGA → DGII (diferido, licencia).

---

## ESTADO (actualizado 2026-06-16)
- **Sprint T1–T5 + T4B: CERRADO.** Ejes 1 (Banca), 2 (Macro) y 4 (IRMP) cerrados a profundidad. Detalle histórico abajo (sección "SPRINT T1–T5").
- **Eje 4 (IRMP): CERRADO** por los 6 gates; metodología validada en panel amplio de 24 países (Gini gobernanza +0.21, IC [0.06, 0.36], monótona). PRs #158–#171. Memoria `eje4-cierre-plan`.
- **Eje 3 (`sector_intel`): EN CURSO.** Espina sectorial = **BCRD valor agregado por sector** (decisión del dueño 2026-06-16), NO la ONE (delgada → enriquecimiento). **T-E3-1 (Gate A) ✅ en prod (PR #172).** Siguiente: T-E3-2. Ver sección "Eje 3" abajo.

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
