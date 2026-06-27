# Plan de integración — Pensiones (SIPEN) · Módulo `pension_intel`

> Decisión del dueño (2026-06-27): **módulo completo** (cara sistema nacional + scoring de AFP/fondos)
> **y productizado** (Pulse / Insight / Deep Dive). Doctrina: excelencia, no la solución fácil.
> Fixture-first (el portal SIPEN bloquea bots: 403/473), dato real por canal, sin seed sintético.

## 0. Por qué un módulo y no un "eje" más

Los datos de SIPEN tienen **dos naturalezas** y el diseño las separa:

- **Sistema/nacional** (serie temporal, molde `MacroSeries`): afiliados, cotizantes, densidad de
  cotización, cobertura, salario promedio cotizable, fondo de pensiones total, rentabilidad del sistema.
- **Entidad** (estados financieros + rating, molde `banking_score`): las AFP (~5-6) y los fondos que
  administran — patrimonio, valor cuota, rentabilidad real/nominal, composición de cartera, solvencia,
  capital pagado, accionistas.

→ `modules/pension_intel/` con **dos caras**: *pulse nacional* + *scoring de AFP/fondos*.

## 1. Fuentes (cuatro canales, naturalezas distintas)

| Canal | Contenido | Formato | Frecuencia | Ingesta |
|-------|-----------|---------|-----------|---------|
| **A — CKAN datos.gob.do** (org SIPEN) | Afiliados 2003–2025, cotizantes, distribución por AFP/sexo, salario mínimo cotizable | CSV/JSON vía API CKAN | Mensual | API CKAN (reusar evaluación `datos-gobdo-ckan`) |
| **B — Estadística Previsional** (sipen.gob.do) | Valor cuota, rentabilidad real/nominal, patrimonio, composición de cartera — por fondo/AFP | XLSX (links con hash de fecha) | Mensual/trim. | Descarga XLSX + parser tabular |
| **C — Boletines Trimestrales** (No. 90 = Q4-2025) | Narrativa + tablas: rentabilidad del sistema, afiliación, traspasos, pensiones otorgadas | PDF | Trimestral | Digest IA (patrón `bcrd-publications`) |
| **D — Estados financieros + accionistas/capital** | Balance/resultados por AFP y por fondo; solvencia, capital pagado, accionistas | PDF/XLSX | Trim./anual | Parser estados financieros (molde estados banca) |

Derivados (tablero/mapa interactivo) NO se raspan: se reconstruyen desde A/B/D y se narran con IA.

## 2. Superficie de integración (10 puntos, molde verificado en código)

1. **Conector** `shared/data/sipen_client.py` → `FixtureBackedClient`, contrato `Record`+`Lineage`,
   gate `license_ok=True`. Fixture en `shared/data/fixtures/sipen.json`. `_fetch_live` por canal (Fase live).
2. **Modelos** `modules/pension_intel/models/models.py`:
   - `PensionSeries` (sistema; `series_code` namespaced `sipen.afiliados.total`, molde `MacroSeries`).
   - `PensionEntity` + `PensionFinancials` + `RatingResult` + `RatingAction` (entidad; molde `banking_score`).
   - `PensionSnapshot` (índice agregado de salud del sistema por período).
3. **ETL** `modules/pension_intel/sipen_sync.py` con `set_phase` (progreso UI). Persiste series + financials,
   recalcula snapshot/scoring. `only_latest` para refresh rápido.
4. **Operación** `modules/pension_intel/operations.py`:
   `register_operation(Operation("sipen-sync", "Sincronizar pensiones (SIPEN)", …, default_interval_hours=2160))`.
   Auto-agendada y cubierta por `data-freshness-audit` (ver `ops-auto-schedule-freshness`).
5. **Migración** Alembic (`alembic revision --autogenerate`) + import de modelos en `infrastructure/alembic/env.py`.
6. **Routers** `modules/pension_intel/api/` (`router.py` sistema, `router_entity.py` scoring, `router_data.py`
   sync/upload, `router_reports.py` PDF) → montados en `app/main.py` con prefijo `/api/v1/pension-intel`.
7. **Scoring** `modules/pension_intel/scoring/` (engine determinista + `weights.py` + `rating_scale.py`
   reusando la escala SDQ de 10 tramos; sub-componentes propios de pensiones: solvencia, rentabilidad
   ajustada por riesgo, eficiencia de gestión, calidad de cartera, cobertura).
8. **Insight IA / Cerebro** `shared/narrative/cerebro.py`: `AXIS_DOCTRINE["pension_intel"]` +
   `AUDIENCE_FRAMES` (afiliado, regulador, inversionista). `ai_context.py` por cara. Narrar con Claude real.
9. **Productización** `modules/pension_intel/products.py` implementando `SectorProduct`
   (Pulse=sistema anonimizado · Insight=AFP nombrada · Deep Dive), auto-registro `register_product(...)`.
   RBAC/tiers/suscripción salen gratis de `shared/products/access.py` (`can_access`).
10. **Frontend** `frontend/src/modules/pension-intel/`:
    - Página panel sistema (gauges, series, `AiInsightCard`).
    - Ranking + detalle de AFP (drill-down, `EntityInsightDrawer`, descarga PDF).
    - Página "Datos" (`/datos/pensiones`) con sync status + upload.
    - Rutas en `App.tsx`; entrada en `frontend/src/shared/layout/nav.ts` (grupo "Datos" y grupo de módulo).
    - i18n ES/EN/FR en `frontend/src/shared/i18n/*`.
    - Dominio "Pensiones" en `ComparadorPage` + alimentar `MarketBrief`.

Guards anti-Frankenstein: sin imports cruzados de módulos desde `shared/products`; sin colores/strings
hardcodeados; toda operación registrada; producto implementando el `Protocol`.

## 3. Fases de ejecución

- **F0 — Esqueleto + conector + fixtures** (CKAN afiliados/cotizantes + XLSX rentabilidad/patrimonio +
  1 boletín PDF). Modelos `PensionSeries`/`PensionEntity`/`PensionFinancials` + migración. Sync básica.
- **F1 — Cara sistema**: snapshot nacional + panel + insight IA + sección Datos + operación agendada.
- **F2 — Cara entidad (scoring AFP)**: engine + pesos + escala 10 tramos + ranking + detalle + reportes PDF
  + insight por entidad. Estados financieros (canal D).
- **F3 — Productización**: `SectorProduct` 3 niveles + muestra watermarked + gating tier/suscripción.
- **F4 — Transversal**: Comparador (dominio Pensiones) + Market Brief + i18n EN/FR completo + backtest/validación
  de la metodología de scoring (molde Gate E) antes de declararla.

## 4. Verificación / cierre

- Tests ≥80% en lógica de scoring (doctrina del repo).
- Parity SQLite↔Postgres (VARCHAR/enums) antes de prod (ver `dev-prod-sqlite-postgres-parity`).
- Verificación E2E en navegador local con dato real (receta `local-e2e-browser-verification`).
- Cada PR pequeño y mergeado a `main` con `--no-ff` (política `merge-ready-branches-to-main`).
- "¿Mejor o más fácil?" en cada decisión y al cerrar (`best-vs-easiest-before-closing`).

## 5. Decisiones abiertas (no bloquean F0–F1)

- Granularidad entidad: ¿AFP solamente, o AFP **y** los fondos individuales que administra cada una?
- Live vs fixture en prod: SIPEN bloquea bots → evaluar IPs estáticas Railway en allowlist (como BCRD) o
  mantener fixture versionado + refresh manual/operación. Decisión al llegar a "live".
- Backtest de scoring de AFP: contra qué outcome se valida (insolvencia/intervención/rentabilidad relativa).
