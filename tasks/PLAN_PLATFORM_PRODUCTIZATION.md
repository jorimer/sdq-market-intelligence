# PLAN — Productización de plataforma (10 sectores × 3 niveles) + Monitor de Readiness

> v0.1 · 2026-06-23 · Desglose por fases del spec **`docs/SPEC_PLATFORM_PRODUCTIZATION.md`**.
> Estilo casa (ver `tasks/PLAN_FINO_SPRINT.md`). Marcar `[x]` al avanzar.
> Regla Plan First: confirmar este desglose con el dueño antes de implementar.
> **No toca `tasks/todo.md`** (sprint Gate E vigente). Enlace sugerido en todo.md:
> `> Productización plataforma: tasks/PLAN_PLATFORM_PRODUCTIZATION.md`.

---

## Principio anti-Frankenstein

Un framework en `shared/products/` + un contrato uniforme de sector + el monitor. Se construye "todo":
los 10 sectores se cablean end-to-end (P4), ninguno queda a medias. El monitor no decide qué se
cablea (todo se cablea); gobierna la **activación de acceso público** al cruzar el umbral de readiness.
Orden: P0 → P1 → P2 → P3 → P4 (los 10 sectores) → P5.

---

## P0 · Framework sector-agnóstico en `shared/products/` + Banca como referencia

### Pre-requisitos de lectura
- [ ] `docs/SPEC_TIER_PRODUCTIZATION_BANKING.md` (detalle del sector de referencia).
- [ ] `reports/pdf_generator.py`, `scoring/weights.py`, `scoring/rating_scale.py`,
  `reports/narrative.py`, `shared/narrative/claude_engine.py`.
- [ ] Cómo se promovió el Cerebro a `shared/` (`shared/narrative`, `shared/ui`) — es el molde.

### Pasos atómicos
- [ ] **1.** Crear `shared/products/tiers.py` (`ProductTier`, `TierLevelSpec`), `manifest.py`
  (`SectorProductManifest`), `assembler.py` (`assemble_product_report` genérico).
- [ ] **2.** Definir el `Protocol` `SectorProduct` (contrato del spec §1.1).
- [ ] **3.** Refactorizar `banking_score` para **implementar el contrato** y consumir el framework
  compartido (extensión no-rotura de `generate_pdf_report` con `sections/tier/sample`). Banca = sector 1.
- [ ] **4.** Implementar los 3 niveles de Banca vía manifiesto (Pulse anonimizado, Insight nombrado,
  Deep Dive con escenarios+recomendación) — según el spec de Banca (G1-G6 de ese doc).
- [ ] **5.** Fixtures `Banco Demo, S.A.` + script de muestras (3 PDFs).

### Archivos tocados
`shared/products/{tiers,manifest,assembler}.py` (nuevos) · `modules/banking_score/...` (implementa
contrato + manifiesto) · `reports/pdf_generator.py` (no-rotura) · `tests/...` · `scripts/generate_tier_samples.py`.

### Sensor de cierre
- [ ] Banca activable a Insight; 3 muestras OK; reportes existentes sin regresión. `pytest` ≥80% en
  `shared/products`. **Reviewer subagent**.

---

## P1 · Monitor de Readiness — backend

### Pasos atómicos
- [ ] **1.** `shared/products/readiness.py`: rúbrica G1-G5 (pesos del spec §3.1), cálculo desde las
  señales del contrato (`data_signals`, `has_engine`, narrativa, manifiesto, `validation_state`).
- [ ] **2.** `shared/products/models.py`: `ProductReadiness`, `ProductActivation` + migración Alembic
  (registrar en `env.py`). Linaje: cada score apunta a su señal.
- [ ] **3.** `shared/products/activation.py`: gate `readiness ≥ ACTIVATION_THRESHOLD[tier]`.
- [ ] **4.** `shared/products/registry.py`: `PRODUCT_REGISTRY` con los 10 sectores × 3 niveles.
- [ ] **5.** API `/api/v1/products`: `readiness`, `readiness/{sector}`, `activate`, `deactivate`,
  `readiness/recompute`. Errores en español. Recompute estilo consola de operación (estado en DB).
- [ ] **6.** Job de recálculo (reusar scheduler in-app existente; cadencia a definir — spec §7).

### Sensor de cierre
- [ ] Readiness calculado desde señales reales (no hardcode); activación rechazada bajo umbral (test).
  `pytest` ≥80%. `alembic upgrade head` OK. **Reviewer subagent** (API + modelo).

---

## P2 · Monitor de Readiness — dashboard (frontend `platform`)

### Pre-requisitos de lectura
- [ ] `modules/platform/pages/ConfiguracionPage.tsx`, `components/SeriesMaintenanceSection.tsx`,
  `DataSourcesSection.tsx` (patrones de consola/estado). `shared/ui/` (primitives, estados).

### Pasos atómicos
- [ ] **1.** Página "Monitor de Productos": grilla sectores × niveles, semáforo por readiness, %,
  desglose G1-G5 al expandir.
- [ ] **2.** Toggle de activación por celda (deshabilitado si < umbral, tooltip del gate faltante).
- [ ] **3.** Botón recalcular; estados carga/vacío/error; claro/oscuro; i18n.
- [ ] **4.** Ruta en `App.tsx` + entrada de navegación (rol admin).

### Sensor de cierre
- [ ] Un humano no-técnico ve readiness y activa/desactiva cada producto desde la UI. `tsc` + `build`
  OK, consola limpia, claro y oscuro. **Reviewer subagent**.

---

## P3 · Receta de onboarding de sector (plantilla repetible)

### Pasos atómicos
- [ ] **1.** Documentar en `docs/RECETA_ONBOARDING_SECTOR.md` los pasos para llevar un sector de
  Roadmap a activable: (a) adapter de fuente → (b) motor de índice vía `shared/indices` → (c)
  contexto de narrativa + templates → (d) `SectorProductManifest` → (e) señales de readiness → (f)
  fixtures de muestra.
- [ ] **2.** Validar la receta cableando **el siguiente sector más maduro** end-to-end (Macro &
  Country Risk: `macro_monitor` + `macro_political_risk` ya en desarrollo).
- [ ] **3.** Confirmar criterio: onboarding = implementar contrato + manifiesto + señales, **sin
  tocar** `shared/products` ni el motor genérico (test que lo verifique).

### Sensor de cierre
- [ ] Macro aparece en el monitor con readiness real; al cruzar umbral, activable. La receta queda
  validada como repetible. **Reviewer subagent**.

---

## P4 · Cablear los sectores restantes (TODOS — no opcional)

> Todos los sectores se cablean end-to-end (ingesta → motor → narrativa → reporte). Ninguno queda
> como scaffold. Cada sector = una tarea con la misma receta de P3. El monitor NO decide qué se
> cablea (todo se cablea); solo gobierna la **activación de acceso público** al cruzar umbral.
> La secuencia abajo es orden de ejecución por madurez de data, no una lista de candidatos.

- [ ] **S2 · Macro & Country Risk** — `macro_monitor`+`macro_political_risk` · BCRD, DIGEPRES, WGI/WDI, GDELT *(piloto de receta en P3)*.
- [ ] **S3 · Trade & Logistics** — `trade_intel` · DGA, BCRD.
- [ ] **S4 · Tourism** — BCRD turismo, ASONAHORES, MITUR.
- [ ] **S5 · Free Zones & Manufacturing** — CNZFE, ONE, datos.gob.do *(evaluar módulo propio)*.
- [ ] **S6 · Energy** — SIE, CNE, Organismo Coordinador *(evaluar módulo propio)*.
- [ ] **S7 · Telecom** — INDOTEL (trimestral, datos abiertos) *(evaluar módulo propio)*.
- [ ] **S8 · Construction & Real Estate** — ONE, ADOCEM, BCRD *(se cablea con data disponible; G1 puede quedar bajo umbral de publicación)*.
- [ ] **S9 · Agribusiness** — Min. Agricultura, BAGRÍCOLA, ONE *(se cablea con data disponible; G1 puede quedar bajo umbral de publicación)*.
- [ ] **S10 · ESG & Climate** — `esg_climate` · ONE, Medio Ambiente, IPCC, mix SIE *(comprador naciente)*.

Por cada Sx (checklist uniforme):
- [ ] Adapter de fuente + ingesta (G1) · [ ] Motor de índice (G2) · [ ] Narrativa + guard (G3) ·
  [ ] Manifiesto de 3 niveles (G4) · [ ] Señales de readiness + validación (G5) · [ ] Fixtures muestra ·
  [ ] Sensor de anonimización Pulse · [ ] Reviewer subagent · [ ] Aparece y se activa desde el monitor.

### Sensor de cierre (por sector)
- [ ] El sector queda **cableado y operativo internamente** (ingesta → motor → reporte), reporta
  readiness real, muestras OK, guard limpio, sin tocar el framework. Si cruza umbral, queda activable
  para el público desde el dashboard; si no, queda cableado pero no publicado.

---

## P5 · Cierre global

### Pasos atómicos
- [ ] **1.** Cobertura ≥80% en `shared/products/*` y en cada contrato de sector implementado.
- [ ] **2.** Correr TODOS los sensores del spec §5; reportar output.
- [ ] **3.** Reviewer subagent final sobre el diff agregado.
- [ ] **4.** Actualizar `tasks/lessons.md` (síntoma/causa/regla/disparador) por cada hallazgo.

### Sensor de cierre (global)
- [ ] `pytest shared/products modules/ -v` verde (≥80% en lo nuevo) · `ruff` · `alembic upgrade head`
  · dashboard operativo · guard limpio · reviewer sin críticos.
- [ ] Pregunta de staff engineer: ¿agregar el sector #11 es correr la receta (contrato + manifiesto +
  señales) sin tocar `shared/products` ni el motor? Si no, no está cerrado.

---

## Mapa de archivos nuevos (núcleo)

```
shared/products/tiers.py · manifest.py · assembler.py · registry.py · readiness.py · activation.py · models.py
modules/<sector>/...      # cada sector implementa el Protocol SectorProduct + su manifiesto
api/.../router_products.py            # /api/v1/products (readiness + activación)
frontend/src/modules/platform/pages/ProductMonitorPage.tsx
docs/RECETA_ONBOARDING_SECTOR.md
scripts/generate_tier_samples.py
infrastructure/alembic/.../<rev>_product_readiness_activation.py
```
