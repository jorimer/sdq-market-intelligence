# Auditoría de rúbrica de toda la app + plan de remediación

**Fecha:** 2026-07-10 · **Alcance:** todos los módulos de producto de SDQ·MIP · **Objetivo:**
determinar qué queda de "rúbrica" (valor de juicio tecleado a mano que alimenta un score
publicado, presentado como si fuera dato) y lanzar la investigación de fuentes confiables
para eliminarla.

**Método:** barrido exhaustivo de `modules/` + `shared/doctrine/` (3 auditorías paralelas +
revisión de las 5 doctrinas). Definición usada:
- **Tipo A — RÚBRICA DURA:** valor de juicio hardcodeado que SIEMPRE alimenta el score.
- **Tipo B — FALLBACK NEUTRAL:** default (típicamente 50 / neutral) usado SOLO cuando falta
  el dato real del período; el dato vivo lo sobreescribe.
- **Excluido:** pesos/bandas/umbrales de metodología, supuestos declarados documentados
  (meta de inflación), muestras sintéticas de demo, y fixtures de test.

---

## 1. Resumen ejecutivo

**La plataforma es, en su mayoría, honesta.** Tres hechos clave:

1. **Existe infraestructura de rotulado real-vs-rúbrica.** Cada `assemble_*_dataset` emite un
   mapa `sources` con `"live"|"rubric"` por variable → badge en UI + declaración en narrativa.
2. **8 de 13 módulos no tienen rúbrica dura:** los 6 ejes sectoriales (telecom, turismo,
   construcción, zonas francas, energía, comercio), `pension_intel` e `insurance_intel`.
   Diseño "never fabricate": la dimensión sin dato se **declara gap y se excluye** (peso
   renormalizado), nunca se rellena con un neutral.
3. **La rúbrica DURA está concentrada** en 3 focos: el **IRMP** (riesgo-país), dos inputs del
   **IAI sectorial**, y el **SGPS sectorial** — más `deal_scoring`, que es **IP intencional**.

**Dos brechas de honestidad** (rúbrica presentada como dato sin rotular):
- **SGPS histórico/estructural** (sector_intel) — rúbrica dura al 75% del peso del SGPS, **NO
  cubierta por el badge `sources`**. Prioridad de rotulado inmediato.
- `STATE_OWNED` (banking) — factual, rotulado solo parcialmente (menor).

---

## 2. Inventario consolidado

### 2.1 Rúbrica DURA (Tipo A) — sustituye dato de fuente, siempre activa

| # | Módulo · índice | Variable | Valor · ubicación | Alimenta (peso) | ¿Rotulada? |
|---|---|---|---|---|---|
| A1 | IRMP · riesgo-país | `electoral_uncertainty` | por país, `regulatory.yaml:97` | political (0.25) | Sí (doctrina + badge) |
| A2 | IRMP · riesgo-país | `policy_continuity` | por país, `regulatory.yaml:97` | political (0.25) | Sí |
| A3 | IRMP · riesgo-país | `discretion` | por país, `regulatory.yaml:97` | regulatory (0.15) | Sí |
| A4 | IRMP · riesgo-país | `contract_enforcement` | por país, `regulatory.yaml:97` | regulatory (0.15) | Sí |
| A5 | IRMP · riesgo-país | `news_sentiment`, `unrest_shocks`, `sanctions_signal` | por país, `regulatory.yaml:97` | events (0.10) | Sí |
| A6 | IAI · sectorial | `ease_of_business` | `50` fijo, `sectoral.yaml:62` + `service.py:462` | business (0.25) | Sí (badge) |
| A7 | IAI · sectorial | `skills_index` | `50` fijo, `sectoral.yaml:65` + `service.py:462` | talent (0.20) | Sí (badge) |
| A8 | SGPS · sectorial | `sgps_historical` | `50` fijo, `sectoral.yaml:68` + `service.py:496` | SGPS histórico (0.40) | **NO (brecha)** |
| A9 | SGPS · sectorial | `sgps_structural` | `50` fijo, `sectoral.yaml:69` + `service.py:497` | SGPS estructural (0.35) | **NO (brecha)** |
| A10 | banking · casas de cambio | `_diversificacion` (proxy) | ancla `0.5`, `cambiaria.py:82` | sub-score diversificación | Sí ("(proxy)") |
| A11 | banking · overlay soporte | `STATE_OWNED` | frozenset Banreservas, `support.py:31` | propensión de soporte (contexto, no muta SDQ) | Parcial |
| A12 | deal_scoring | `_STAGE_SCORE`, `_momentum_score` | `rubric.py:52,59` | stage (0.20) + momentum (0.08) | Sí (IP declarada) |

**Nota `regulatory_volatility_5y` (IRMP):** era rúbrica dura; **la Fase A (WGI 2025) ya la
mata** — se calcula de la desviación de la serie WGI de calidad regulatoria (real).

### 2.2 Fallback neutral (Tipo B) — solo si falta el dato real del período

| Módulo · índice | Variables | Fuente viva que las sobreescribe |
|---|---|---|
| ESG · IRC | `fossil_dependence`, `carbon_intensity` (0.5) | Ember (mix eléctrico/carbono) — ya cableada |
| Social · IDM | `income_per_capita`, `literacy_rate`, `schooling_years`, `financial_inclusion`, `informality_rate`, `secondary_coverage` (50) | ONE-ENCFT/ENHOGAR, WB Findex — ya cableadas |
| IAI · sectorial | `operating_cost`, `labor_availability`, `regulatory_quality`, `regulatory_volatility`, `macro_exposure` (50) | TSS, ENCFT, **WGI**, contrato macro→sectorial |
| banking · overlay | `sovereign_ratings.DO` (piso "BB") | store `AppSetting` vía `sovereign-ratings-sync` (Wikipedia) |
| banking/pension/insurance | guardas de escala degenerada → 50 / 0.5 | interno de normalización (panel plano); no es rúbrica de mercado |

### 2.3 Limpios — sin rúbrica

`telecom_intel`, `tourism_intel`, `construction_intel`, `free_zones_intel`, `energy_intel`,
`trade_intel`, `pension_intel`, `insurance_intel`. Motores puros sobre dato real; dimensión
sin dato → gap declarado y excluido.

---

## 3. Brechas de honestidad a cerrar YA (rotulado, no fuente)

| # | Qué | Acción | Esfuerzo |
|---|---|---|---|
| H1 | **SGPS histórico/estructural** es rúbrica dura pero el badge `sources` no lo cubre → se presenta como dato | Incluir `sgps_historical`/`sgps_structural` en el mapa `sources` como `"rubric"` + rótulo en el reporte SGPS | Bajo |
| H2 | `STATE_OWNED` rotulado solo en prosa | Marcarlo explícito como "dato de configuración declarado" en el overlay | Muy bajo |

Estas dos NO requieren buscar fuente — son de transparencia inmediata y deberían ir antes que
cualquier otra cosa (regla: mientras algo sea rúbrica, debe declararse como tal).

---

## 4. Plan de remediación por fuente (lanza la investigación)

Ordenado por prioridad (impacto sobre el producto × que la rúbrica NO esté ya en camino).

| Prioridad | Rúbrica(s) | Fuente(s) candidata(s) a investigar | Estado / bloqueo |
|---|---|---|---|
| **P0 (rotulado)** | H1 SGPS, H2 STATE_OWNED | — (transparencia) | Listo para hacer |
| **P1** | A6 `ease_of_business`, A7 `skills_index` (IAI) | Doing Business/B-READY (negocios); ENCFT-competencias / estudios ONE (talento) | Sin conector; investigar cobertura por-sector |
| **P1** | A8/A9 SGPS histórico/estructural | Serie histórica de crecimiento sectorial BCRD (histórico) + estructura insumo-producto ENAE-ONE (estructural) | BCRD histórico existe; ENAE parcial |
| **P2** | A1–A4 IRMP político/regulatorio | **V-Dem** (electoral, continuidad, discreción) · **WJP Rule of Law** / **B-READY** (contract_enforcement) | V-Dem: **verificar licencia comercial**. = Fases C/D del [[irmp-source-upgrade-workstream]] |
| **P2** | A5 IRMP eventos | **GDELT** (tono → news_sentiment; PROTEST → unrest; ECON_SANCTIONS) + listas **OFAC/UE/ONU** | Conector GDELT YA existe; = Fase B |
| **P3** | Cerrar gaps declarados (no rúbrica, pero suben cobertura) | pension: estados financieros AFP (`financials_sync`) → solvencia; insurance: BDFINAC 403/404 → capital mínimo ARS; ESG: completar panel Ember | Datos identificados; ingesta pendiente |
| **P3** | A10 `_diversificacion` (casas de cambio) | Desglose de ingresos por línea del feed EIC (si la Superintendencia lo publica) | Fuente incierta |
| **Fuera** | A12 deal_scoring stage/momentum | XGBoost sobre histórico de deals (cosecha en curso) — NO es fuente externa, es IP en maduración | Por diseño |

### Sinergia ya disponible (Fase A)
El **WGI 2025** que ya ingerimos (Fase A) puede alimentar la dimensión **regulatoria del IAI
sectorial** (`regulatory_quality`/`regulatory_volatility`, hoy fallback 50) con dato nacional
real — cierra fallback en `sector_intel` con una fuente **ya en casa**. Cablear como P1 barato.

---

## 5. Recomendación de secuencia

1. **P0 — rotulado (H1/H2):** cerrar las 2 brechas de honestidad. Rápido, y es lo que exige la
   regla de "no presentar rúbrica como dato". PR corto.
2. **Sinergia WGI→IAI:** cablear regulatoria del IAI al WGI-2025 ya ingerido. Barato, mata 2
   fallbacks con fuente en casa.
3. **Fases B/C/D del IRMP** (ya planificadas en [[irmp-source-upgrade-workstream]]): GDELT →
   V-Dem (tras licencia) → WJP/B-READY/sanciones. Cierran A1–A5.
4. **P1 SGPS + IAI negocios/talento:** investigar cobertura BCRD-histórico / ENAE / ONE / B-READY
   por-sector antes de cablear (riesgo: parcial distorsiona el min-max → política "todos o
   ninguno").
5. **P3 gaps de cobertura** (pension/insurance/ESG): no son rúbrica, pero elevan la riqueza del
   producto; ingesta incremental.

**Al completar 1–4:** la única "rúbrica" viva del sistema sería `deal_scoring` (IP intencional,
en cosecha) y los fallbacks neutrales que solo actúan ante ausencia de dato — todos rotulados.
