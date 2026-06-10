# Handoff — SDQ·MIP (2026-06-10, sesión 5)

## Estado al cierre: Eje 1 (banking_score) con metodología sólida + drill-down e IA en toda la app

### 1) Metodología del rating — credibilidad cerrada (PRs #74–#81)
- **Calidad de cartera (fase 2)**: 5 de 6 indicadores antes N/D ahora con dato real del SIB
  (castigos ← `indicadores/morosidad-estresada`; exposición inmobiliaria ← `indicadores/riesgo-credito`;
  HHI sectorial ← `carteras/creditos`; HHI ingresos ← árbol nivel-4 de `estados/resultados/eif`;
  migración ← cartera-A del período previo). **Top-10 concentración** sigue N/D (no publicado) — *pendiente: investigar más*.
- **Eficiencia arreglada (bug, no calibración)**: `utilidad_neta` leía una hoja de gasto por substring;
  ahora lee el subtotal correcto (cascada TODOS) + ROA/ROE **anualizados** desde YTD. ROE Banreservas 16.7% (antes −2%).
- **Diversificación recalibrada**: curva HHI ingresos 100@3000→0@9000 (antes 66% de bancos en score 0).
- **Hardening del backfill**: paginación sin truncar (#77), anti-storm Celery (visibility 6h + dedup, #75/#78),
  heartbeat por trimestre. El backfill SIB tarda ~3h (cubo de carteras pesado) y corre **trimestral**.

### 2) Drill-down + insights de IA en toda la app (PRs #82–#88) — VERIFICADO EN PROD
La IA narrativa (`shared/narrative/claude_engine.py`, framework SCQA) **ya existía** con 6 templates
pero estaba "encerrada" en los PDF. Se surfacó in-app con un patrón reutilizable:
- **Patrón**: carga en **dos fases** (data instantánea con `?with_ai=false`, IA en background con `with_ai=true`,
  estado "Generando…") + renderer de **Markdown** (`shared/ui/Markdown.tsx`) + IA **best-effort** (nunca rompe la página).
- **Por indicador** (Scoring): `GET /{bank}/indicator/{key}` → valor/interpretación + tendencia (21 trim.) + pares + insight IA.
  Componente: `IndicatorDetailDrawer`.
- **Por entidad** (Rankings + Top entidades del Dashboard, clickeables): `GET /{bank}/insight` → rating global +
  5 sub-componentes (cada uno con impulsor/lastre que bajan al indicador) + tendencia + pares + IA "fundamento del rating".
  Componente: `EntityInsightDrawer`.
- **Tarjetas contextuales** (`AiInsightCard`): `POST /insight/compare` (Comparar), `GET /insight/sector` (Dashboard),
  `POST /insight/scenario` (Escenarios). **Ojo rutas**: van bajo `/insight/*` para no chocar con `/{bank_id}/insight`.

### 3) Config de IA — clave + modelo (parte de #83/#88)
- `settings` lee `ANTHROPIC_MODEL` (antes leía `CLAUDE_MODEL` → el env configurado se ignoraba) + `extra="ignore"`.
- En Railway: `ANTHROPIC_API_KEY` (válida, la seteó el usuario) + `ANTHROPIC_MODEL=claude-sonnet-4-6` (lo seteó el agente).
- Esto **también reactivó las narrativas de IA en los PDF de reportes**, que caían al placeholder por el mismo motivo.

### Pendientes vivos (para la próxima sesión)
1. **Concentración top-10**: investigar más en el SIB (¿SIMBAD? endpoints no probados). Hoy N/D.
2. **Castigos como "costo de crédito"**: revisar si redefinir el indicador (hoy usa castigos reales).
3. **Verificar Comparar/Escenarios** en navegador (endpoints OK; falta demo visual end-to-end).
4. **Calibrar cambiarias** (float de remesas), **optimizar velocidad del backfill** (~3h).
5. **Seguridad pre-go-live**: desactivar `claude@sdqconsulting.com.do`, crear admin real (secretos del usuario).
6. **Otros ejes (2–7)**: conectores live BCRD/ONE/DGA/WGI (hoy en fixture) + Fase 7 transversal. El patrón de
   drill-down/IA del Eje 1 es replicable a los demás ejes.

### Cómo operar (prod)
- Login E2E: `claude@sdqconsulting.com.do` / `Claude1234`. Base: `sdq-market-intelligence-production.up.railway.app`.
- Re-score sin re-ingesta: `POST /api/v1/banking-score/data/rescore?only_sib=true`. Backfill: `POST .../data/sib-backfill?force=true` (¡fuera de ventana de deploy! dedup de 15 min).
- Tests: `/opt/anaconda3/bin/python -m pytest modules/banking_score/ -q` (~285). Lint: `ruff check` (corré sobre TODO el changeset, incl. tests).
- Frontend lo sirve el mismo app (FastAPI SPAStaticFiles sobre `frontend/dist`); build en el Dockerfile.

---

# Handoff — SDQ·MIP (2026-06-10, sesión 4 cont.)

## Eficiencia arreglada — utilidad_neta + anualización ROA/ROE (PR #80)

**Bug encontrado (creíamos que era "calibración"):** `utilidad_neta` se extraía con un
match por substring de "Resultado antes del impuesto" que devolvía la **primera** fila
con ese `conceptoNivel2` — una **hoja de gasto** ("Otros gastos" = −403M), no el
resultado. → ROA/ROE **negativos** para TODOS los bancos (Banreservas ROE −2%).

**Fix:** leer el subtotal de la cascada TODOS (`conceptoNivel2="Resultado antes del
impuesto"` AND `conceptoNivel3="TODOS"`) + anualizar ROA/ROE por mes del período YTD
(×12/M). Re-ingesta hecha. **Verificado en prod (2025-12, anualizado):**
- Banreservas ROE 16.7% / ROA 1.48% · ADEMI 14.1% / 1.81% · Popular 7.6% / 1.40% ·
  APAP 2.84% / 0.54% — positivos y realistas en BM, BAC y AAyP.

**`#3 "último trimestre cerrado" quedó MOOT:** la distorsión del período latest (Banreservas
"en pérdida" en 2026-03) era el mismo bug de la hoja, no un preliminar genuino. Tras el
fix, 2026-03 muestra un Q1 sensato (ROA 0.68%). No se necesitó lógica de "último completo".

**Diagnóstico `sib-page-test` ahora soporta `entidad=` y volcado de filas (`grep`)** —
útil para inspeccionar el árbol de UN banco (PRs #76, #79).

### Pendientes vivos
- **Concentración top-10**: investigar más (no hay fuente pública obvia; los 4 endpoints
  de indicadores + variantes de carteras dieron 404 o sin deudor).
- ~~**Recalibrar diversificación**~~ ✅ HECHO (PR #81): curva lineal 100@3000 → 0@9000.
  Antes 27/41 bancos en score 0; ahora rango 7.6–94, mediana 55, 0 pegados. Solo
  rescore (sin re-ingesta). Verificado en prod.
- **Otras calibraciones/alcance**: umbrales cambiarias; velocidad backfill (~3h);
  seguridad pre-go-live (admin real); otros ejes (conectores live BCRD/ONE/DGA/WGI).

---

# Handoff — SDQ·MIP (2026-06-09, sesión 4)

## Fase 2: indicadores de calidad de cartera (PRs #74, #75)

**Objetivo:** poblar los 6 indicadores de calidad antes N/D con dato real del SIB.

### Logrado y desplegado (#74, ya activo en prod)
Investigación a fondo del SIB descubrió endpoints que el ETL nunca tocó (los slugs
usan **guion**): `indicadores/morosidad-estresada` (trae `castigos`+`carteraTotal`),
`indicadores/riesgo-credito` (deuda por `tipoCartera`, incl. Hipotecarios), y el
árbol de 7 niveles de `estados/resultados/eif`. **4 de 5 indicadores verificados en
prod** (Banreservas 2026-03, SDQ-A+):
- **castigos** (`castigos_pct` = castigos/carteraTotal) ✅
- **exposición inmobiliaria** (`exposicion_re_pct` = deuda hipotecaria/total) ✅
- **HHI sectorial** (`carteras/creditos`, deuda por sectorEconomico, agregado
  período-por-período) ✅
- **migración** (cartera-A del período previo) ✅
- **HHI ingresos** ✅ (Banreservas raw 5054, ADEMI 6254). El parser `_income_hhi_raw`
  era correcto (verificado con el diagnóstico `grep`: convención TODOS-en-cascada,
  el subtotal nivel4 es la fila `conceptoNivel5="TODOS"`). La causa de que saliera
  N/D era **truncamiento silencioso de la paginación**: el fetch de income (89k filas)
  daba 504 a mitad y `_get` cortaba devolviendo lo obtenido (40k) → se perdían las
  filas nivel4 de ingresos. **Fix #77**: reintentar la página fallida 3× antes de
  truncar + loguear fuerte si trunca. Re-corrida → income completo (89254 vs 40000) →
  HHI ingresos puebla. **5/5 indicadores nuevos verificados en prod (2026-03).**
- **concentración top-10**: N/D definitivo — no se publica en la API pública (probados
  los 4 endpoints de indicadores + variantes de carteras, todos 404 o sin deudor).

### Cierre fase 2 — PRs #74–#78 (todo en main y desplegado)
- #74 ETL + 4 indicadores · #75 heartbeat por trimestre + anti-storm (visibility 6h +
  dedup) · #76 diagnóstico raw-rows/grep · #77 paginación sin truncar (arregla HHI
  ingresos) · #78 ventana de dedup 15 min.
- **Re-backfill final 2026-06-09 ~02:00 UTC: completed, errors:[], 1698 ratings, 5/5.**
- Refinamiento futuro (no bug): **diversificación puntúa bajo** — HHI ingresos >5000 en
  casi todos los bancos (la banca DR es intensiva en margen de interés) → score 0. La
  curva (umbral 3000–5000) quizá deba recalibrarse para el contexto DR; el dato es real.

### ⚠️ Pendiente de cierre (#75 — bloqueado por incidente de Railway 2026-06-09 ~20:30 UTC)
El backfill de carteras es **mucho más pesado de lo estimado** (~113k filas/trimestre
para BM, ~3h total). En la 1ra corrida real surgieron dos problemas operativos que
**#75 arregla** (rama mergeada a main, pero su deploy quedó atascado por un incidente
de Railway — *image registry lento*, no nuestro código):
1. **Heartbeat congelado** por-tipo → la UI marcaba "(interrumpido)" en falso. Fix:
   callback `on_progress` por trimestre en `_compute_carteras_hhi`/`sib_sync`.
2. **Tormenta de re-entregas Celery**: `task_acks_late` + `visibility_timeout` default
   de Redis (1h) < duración del job (3h) → el job se re-entrega y re-ejecuta en bucle.
   Fix: `broker_transport_options visibility_timeout=6h` + guard de dedup en
   `run_backfill` (omite duplicado si un backfill terminó dentro de 4h).

**Al reanudar:** (a) confirmar que #75 promovió (deployment SUCCESS) y que el backfill
runaway del contenedor viejo se detuvo (`sync-status is_running=false`); (b) arreglar
`_income_hhi_raw` para HHI ingresos y re-correr el backfill (force=true) fuera de
ventana de deploy; (c) verificar los 5 indicadores. Data actual ya correcta (1698
ratings, 4/5 indicadores).

---

# Handoff — SDQ·MIP (2026-06-09, sesión 3)

## Estado al cierre de la sesión 3

**Universo SIB completo calificado y desplegado en prod.** 86 entidades, ratings
en escala SDQ, ranking creíble y discriminante (verificado en trimestre cerrado
2025-12).

### Logrado en la sesión 3 (PRs #58–#72)
- **Cambiarias (EIC) completas**: ETL + scoring propio + UI (42 agentes de
  cambio/remesas). PRs #61–#64.
- **Modelo de bancos (EIF) rediseñado honesto**:
  - **Integridad** (#66): indicador sin dato = N/D (no "perfecto"); subcomponentes
    se reponderan. Acabó con el ~45% fabricado.
  - **Mapeo correcto** (#69): matcher acento-insensible — los nombres del SIB
    llevan acentos (`Índice`, `Crédito`) y no matcheaban.
  - **Nombres de balance** (#70): el SIB renombró el plan de cuentas
    (`Efectivo y equivalentes`, `Depósitos del público`).
  - **Consistencia de unidades** (#71): el balance está en **pesos**, indicadores/
    solvencia en **millones**. Se guardan los **ratios % del SIB** en campos nuevos
    (`*_pct`, migración `c2f5a1b3e4d6`) y el motor los prefiere; los absolutos
    salen todos del balance.
  - **Jerarquía del balance** (#72): cada `conceptoNivel2` trae un subtotal
    `conceptoNivel3=TODOS` + hijos → no sumar todo (doble conteo inflaba activos).
- **Fiduciarias**: el SIB **no** publica sus estados vía API (solo EIF/EIC).
  Diferido. Ver `docs/PROPUESTA_CAMBIARIAS_FIDUCIARIAS.md`.

### Pendientes / refinamientos (no bugs)
1. **Calibrar ROA/ROE a base anual**: la utilidad del SIB es trimestral (YTD) y la
   curva de score espera ~anual → eficiencia puntúa bajo. Anualizar por mes del
   período o ajustar la curva.
2. **`carteras/creditos` (fase 2)**: dataset granular a nivel préstamo
   (`deudaVencida`, provisión, `clasificacionEntidad` A–E, `sectorEconomico`,
   `tipoCartera`). Permitiría poblar los 6 indicadores hoy N/D: concentración,
   HHI sectorial, exposición inmobiliaria, castigos, migración. Es ingesta pesada.
3. **"Último período" debería preferir el último trimestre CERRADO** por entidad:
   el SIB publica el trimestre en curso preliminar (Q1-2026 mostró pérdida en
   Banreservas, BHD=0), que distorsiona la vista "latest".
4. **Velocidad del backfill** (~40 min) y **calibración de umbrales de cambiarias**
   (los grandes de remesas penalizados por float).

---

# Handoff de sesión — SDQ·MIP (2026-06-08, sesión 2)

Trabajo de **cerrar el pipeline crediticio + extender al universo SIB**.
Rama: `main`. Prod: Railway (`sdq-market-intelligence-production.up.railway.app`),
auto-deploy en push a `main`.

## Estado actual (verificado en prod — 2026-06-08 fin de sesión)

- **Entidades:** 86 (44 de crédito + **42 cambiarias** nuevas)
- **Registros:** 1698 · **Ratings calculados:** 1698 (todos los registros calificados)
- **Rango temporal:** 2021-03-31 → **2026-03-31** (el trimestre en curso ya NO se ingiere)
- **Último sync:** `completed`, `errors: []`, `alerts: []` (alerta de no catalogadas apagada)
- **Backfill:** worker Celery in-container. ⚠️ **NO disparar backfill mientras hay un
  deploy en curso** — el rollout reinicia el worker y la corrida se interrumpe.
  Esperar a que el deploy esté estable (health 200 sostenido) antes de `force=true`.
- **Intérprete dev:** `/opt/anaconda3/bin/python` (3.13) para tests/ruff; el del
  sistema (3.9) rompe por sintaxis `str | None`.

### Completado en esta sesión (PRs #58–#64)

- ✅ **#58 Scoring automático post-sync** — el backfill recalcula ratings al
  terminar; `POST /data/rescore` recalcula sin re-ingesta. Cerró el hueco 834 datos
  vs 70 ratings. Servicio reusable `scoring/batch.py`.
- ✅ **#59 Excluir trimestre no cerrado** — el SIB devolvía el trimestre en curso
  (parcial) y el ranking salía todo SDQ-D; ahora se omite `period_end > hoy` y se
  purga (`POST /data/prune-future`).
- ✅ **#60 Catalogar las 6 entidades** — ATLANTICO/COFACI/OPTIMA (activas, BAyC),
  EMPIRE/ACTIVO/REIDCO (salieron; inactivas pero conservan su histórico). `active`
  flag en `_match_or_create_bank`.
- ✅ **#61 Diagnóstico de conceptos EIC** (sib-page-test dump).
- ✅ **#62 + #64 Submodelo Cambiarias** — ETL EIC (`_extract_eic_bulk`) + scoring
  propio (`scoring/cambiaria.py`): 42 agentes de cambio/remesas ingeridos y
  calificados (rango 29.5–82.1, mediana 70, 7 tiers). Auto-registro genérico vía
  `_entity_meta`. Fix #64: usar el código de tipo consultado (ARC/AC), no el campo
  `tipoEntidad` del SIB (que trae el nombre completo).
- ✅ **#63 UI cambiarias** — el dashboard muestra el submodelo (no "en construcción").
- ✅ **Fiduciarias** — investigado: la API del SIB **solo** expone EIF y EIC; no hay
  endpoint de fiduciarias (ver `docs/PROPUESTA_CAMBIARIAS_FIDUCIARIAS.md`). Diferido.

### Pendiente / próximos pasos

- **Calibrar umbrales de cambiarias** (refinamiento): los grandes de remesas
  (CaribeExpress, CibaoExpress, MoneyCorps) salen SDQ-D porque el modelo penaliza
  apalancamiento, y su "pasivo" es float de remesas en tránsito, no deuda riesgosa.
  Revisar con criterio de dominio si el float debe tratarse distinto.
- **Optimizar velocidad del backfill** (BM tarda ~8 min/tipo; full ~40 min).
- **Seguridad pre-go-live**: desactivar `claude@sdqconsulting.com.do`, crear admin real.

---

## Plan de próxima sesión (prioridad optimizada)

Objetivo: **cerrar el pipeline crediticio end-to-end** (datos SIB → ratings reales)
antes de extender a cambiarias/fiduciarias. La seguridad de admin queda para el
cierre del desarrollo.

### P0 — Cerrar el pipeline crediticio

| # | Tarea | Notas |
|---|-------|-------|
| 1 | **Catalogar 6 entidades no mapeadas** | Silencia la alerta persistente en prod. Propuesta por defecto (confirmar al inicio): `ACTIVO`, `OPTIMA`, `REIDCO` → `is_active=False` (defunct ~2022); investigar `ATLANTICO`, `COFACI`, `EMPIRE` en catálogo SIB y decidir si catalogar o marcar inactivas. |
| 2 | **Scoring automático post-sync** | Hueco crítico: 834 `banking_data` vs 70 `ratings`. Al terminar backfill, recalcular ratings para períodos con `source=sib_api` (incremental, fase visible en estado de sync — mismo patrón DB que `sib_sync_status`). Existe `POST /run-all?period_end=` pero no se dispara hoy. |

### P1 — Operación y extensión de alcance

| # | Tarea | Notas |
|---|-------|-------|
| 3 | **Scheduler in-app de chequeo SIB** | Chequeo periódico sin worker Celery separado (`railway add` da Unauthorized por CLI). Avisar de períodos nuevos. Base: auto-registro + detección de entidad nueva (PR #53). |
| 4 | **Submodelos cambiarias y fiduciarias** | Scope acordado en `banking_score/SPEC.md` §2 (después de tipos crediticios). Endpoints EIC (no EIF); indicadores propios. **Primero:** propuesta metodológica (pedido del usuario). **Luego:** ETL + pesos + UI (hoy "Submodelo en construcción" en Dashboard). Candidatos API: `EIC`, `AC`, `ARC`, `FID`, `FI`, `EF` (ver `GET /data/sib-explore`). |

### P3 — Solo si hay evidencia (no abrir la sesión con esto)

| # | Tarea | Disparador |
|---|-------|------------|
| 5 | **Diagnóstico OOM** | Sync interrumpido o logs Railway con kill/OOM. Hipótesis: 2 uvicorn workers + celery + listas grandes con `registros=5000`. Opciones: bajar `--workers`, streaming sin acumular en memoria, subir plan. |
| 6 | **Concurrencia paralela por `tipoEntidad`** | Full backfills frecuentes. Pasar `tipos` por parámetro (no mutar `_discovered_tipo_codes`, no thread-safe). Estimaría ~6 min vs ~20-25 min actual. |

### Al cierre del desarrollo (no ahora)

| # | Tarea | Notas |
|---|-------|-------|
| 7 | **Seguridad pre-go-live** | Desactivar cuenta de prueba `claude@sdqconsulting.com.do` y crear admin real (`scripts/prod_seed.py` con `ADMIN_EMAIL`/`ADMIN_PASSWORD`). Requiere input del usuario (secretos). |

### Fuera de scope de esta sesión

- Conectores live BCRD / ONE / DGA / WGI (ejes 2–7 siguen en fixture)
- i18n EN, Deal Scoring, Market Brief, Comparador cross-eje
- Fase 7 transversal (RAG, narrativa SCQA, reportes PDF cross-eje)

---

## Trabajo hecho en sesión SIB (PRs #34–#57 mergeados a main)

- #34 Config cifrada (shared/settings) + pantalla Configuración (claves API por sector).
- #35 Port del ETL real del SIB. #36 backfill + estado + UI. #37 prueba de conexión
  distingue proxy vs clave. #38 resolver SIB por sector (no por id mágico).
- #39 menú **Datos por sector** + sub-nav de banca. #40 pre-llenado de fuentes + fix
  de foco en inputs. #43 Corporaciones de crédito (tipo CC). #44 estado de sync en DB
  (visible entre workers). #45 progreso en vivo en la UI. #47 backfill incremental +
  Celery. #48/#49/#50 worker Celery in-container. #52 page size 5000 (≈20× más rápido,
  sin truncar) + heartbeat. #53 auto-registro de entidades + alerta de no-catalogadas.
- #54 catálogo (BLH/ALAVER/Maguana/Mocana/Peravia). #55 enum banktype en Postgres.
- #56 errores legibles. #57 limpiar alerts viejos.
- Repo original de referencia (NO reinventar): `/Users/ricardomercado/Developer/financial-analysis-agent`.

## Cómo verificar / operar (prod)

```
BASE=https://sdq-market-intelligence-production.up.railway.app
TOKEN=$(curl -s -X POST $BASE/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"claude@sdqconsulting.com.do","password":"Claude1234"}' | jq -r .access_token)
curl -s $BASE/api/v1/banking-score/data/overview -H "Authorization: Bearer $TOKEN"      # entidades/registros/sib_records/ratings
curl -s $BASE/api/v1/banking-score/data/sync-status -H "Authorization: Bearer $TOKEN"   # is_running/phase/alerts/result
curl -s -X POST "$BASE/api/v1/banking-score/data/sib-backfill?force=true" -H "Authorization: Bearer $TOKEN"  # disparar
railway logs -s sdq-market-intelligence | grep -viE httpx | grep -iE "celery@|Task banking|extrayendo|escrito|backfill"
```

Tests: `pytest modules/ shared/ -q` (≈342). Lint: `ruff check`. Diagnóstico SIB:
`GET /data/sib-explore` y `/data/sib-page-test` (admin, include_in_schema=False).

## Reglas del usuario (memoria) — respetar

- Usuario **no técnico**: ejecuto YO todo lo técnico (incl. Railway CLI); no le paso
  pasos de dashboard salvo lo que SOLO él puede (login/secretos).
- **Investigar a fondo** antes de concluir; **proponer plan** antes de fixes de prod.
- **Revisar TODO el spec/scope** de un módulo antes de implementar; **proponer
  proactivamente** los huecos que detecte.
- Jobs en background: **mostrar progreso** + estado compartido entre workers.
- Errores user-facing **en español legible**, nunca excepción cruda.
- Mergear ramas listas a main (PR, CI verde, merge --no-ff).