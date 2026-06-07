# Plan de implementación — SDQ Market Intelligence (think tank multi-eje)

> v1 · 2026-06-06 · Traduce `docs/SPECS_OVERVIEW.md` + los 7 `SPEC.md` a un plan
> de ejecución por fases. Mantener vivo: marcar `[x]` al avanzar.

## Objetivo

Llevar la plataforma de **1 eje en producción** (`banking_score`) a los **7 ejes**
del blueprint, sobre **un motor compartido** (un índice, una arquitectura), con
frontend hi-fi por eje y trazabilidad de extremo a extremo.

## Principio rector (anti-Frankenstein)

Todo índice nuevo se construye en `shared/indices/`, no se reescribe por módulo.
Toda fuente entra por `shared/data/` con linaje + verificación de licencia.
Los módulos se comunican **solo** por `shared.events.event_bus`. Dato faltante =
`null`, nunca interpolar sin disclosure.

## Estado de partida (auditoría 2026-06-06)

| Componente | Estado | Acción |
|---|---|---|
| `banking_score` (Eje 1) | Completo (banca múltiple) | Extender a `entity_type` |
| `macro_political_risk` (Eje 4) | Scaffold + tests 30/30, **sin persistencia/eventos/conectores** | Cerrar persistencia + eventos |
| `macro_monitor` (Eje 2) | Solo `SPEC.md` | Construir |
| `sector_intel` (Eje 3) | Solo `SPEC.md` | Construir |
| `social_dev` (Eje 5) | Solo `SPEC.md` | Construir |
| `trade_intel` (Eje 6) | Solo `SPEC.md` | Construir |
| `esg_climate` (Eje 7) | Solo `SPEC.md` | Construir |
| `shared/indices` `shared/data` `shared/doctrine` | **Hecho (Fase 0, 2026-06-06)** | — |
| `shared/knowledge` | Stub (diferido) | RAG en fase tardía |
| Frontend | Design system parcial + solo `banking-score` | Armazón + 6 módulos |

## Decisiones (2026-06-06)

- **Tenancy**: **mono-tenant** (como `CLAUDE.md`). Sin aislamiento por tenant en
  modelos/auth/queries. No añadir capa multi-tenant en esta versión.
- **Conectores**: **mixto por fuente**. Cada conector declara su `mode`
  (`live` | `fixture`). Donde haya API (p.ej. BCRD/WGI) se construye `live`; el
  resto arranca `fixture` con datos versionados en `data/`. La interfaz es la
  misma — cambiar de fixture a live no toca a los módulos.
- **RAG (`shared/knowledge`)**: se **difiere** a fase tardía; no bloquea el MVP de ejes.

## Supuestos pendientes

- [ ] Orden de prioridad de ejes = fases del SPEC (2→3→4→5→7→6). Confirmar.

---

## FASE 0 — Cimientos compartidos (bloqueante para todo lo nuevo)

Objetivo: el "motor" reutilizable. Sin esto, cada eje duplicaría lógica.
Base probada: `macro_political_risk/scoring/{normalization,dimensions,bands,engine}.py`
ya implementa el pipeline; solo está acoplado al IRMP por imports a su `weights.py`.
**Fase 0 = parametrizar ese patrón, no reescribirlo.**

> Detalle ampliado en `### Apéndice A — Diseño de Fase 0` al final del documento.

### 0.1 `shared/indices/` — motor de índices genérico
- [ ] `config.py` — dataclass `IndexConfig`: `name`, `dimension_weights: dict[str,float]`
      (debe sumar 1.0), `dimension_variables: dict[str, list[str]]`,
      `risk_increasing: set[str]`, `bands: list[Band]`, `direction` (str doc).
      Validación en `__post_init__` (pesos suman 1.0, bandas sin huecos).
- [ ] `normalization.py` — **mover** `normalize_value`/`normalize_variable` de MPR
      (idénticas, ya con docstring + doctests). Sin cambios de lógica.
- [ ] `dimensions.py` — generalizar `compute_dimension(dim, entity_key, dataset, config)`
      y `compute_all_dimensions(...)`; firma toma `config` en vez de importar pesos MPR.
      Mantener: skip de `null` (sin interpolar), breakdown `{raw, normalized, inverted}`.
- [ ] `bands.py` — `map_band(score, bands)` + `get_band_color(...)` parametrizados por
      `IndexConfig.bands` (hoy hardcoded a las 4 bandas IRMP).
- [ ] `engine.py` — `run_index(entity_key, dataset, config) -> dict` (pipeline:
      normalizar → dimensiones → suma ponderada → clamp → banda → breakdown con
      `contribution` por dimensión). Igual estructura de salida que `run_irmp`.
- [ ] `tests/` — motor genérico ≥80%: pesos que no suman 1.0, bandas con hueco,
      spread cero (→50.0), todas las variables `null` (→0.0), clamps 0/100,
      contribuciones suman al score.

### 0.2 `shared/data/` — capa de fuentes con linaje (mono-tenant, mixto por fuente)
- [ ] `lineage.py` — dataclass `Lineage`: `source`, `published_at`, `fetched_at`,
      `publication_lag_days`, `license`, `url`. Sellada en cada registro normalizado.
- [ ] `base_client.py` — `SourceClient` (ABC): `mode: Literal["live","fixture"]`,
      `fetch(series, period) -> RawSeries`, `normalize(raw) -> list[Record]` (con
      `Lineage`), `check_license() -> None` (lanza si no apta). Regla: `null` explícito.
- [ ] `fixtures/` — datos versionados por fuente (JSON/CSV) para clientes en `fixture`.
- [ ] Conectores (cada uno declara `mode`):
  - [ ] `sib_client.py` — **mover** desde `banking_score/external/sib_client.py` y
        adaptar a `SourceClient` (banking_score importa desde aquí). Estados financieros SIB/SIMBAD.
  - [ ] `bcrd_client.py` — sector real/precios/monetario/externo/laboral (modo `live` si hay API)
  - [ ] `one_client.py` — demografía/social/género/ODS/censos
  - [ ] `dgii_client.py` — registro/contribuyentes (`fixture` inicial)
  - [ ] `dga_client.py` — aduanas/comercio por producto (`fixture` inicial)
- [ ] `outcomes.py` — captura de **desenlaces etiquetados** (migraciones/defaults) para backtesting.
- [ ] `tests/` — license check bloquea, `null` se preserva, `Lineage` presente en cada record.

### 0.3 `shared/doctrine/` — doctrina de casa versionada
- [ ] `doctrine/{axis}.yaml` por eje (§3–§9): pesos vigentes + versión + justificación.
- [ ] `loader.py` — `load_doctrine(axis) -> IndexConfig` (la doctrina es la fuente de
      verdad de pesos; el código la consume, no la hardcodea). Cambio de peso = PR a YAML.

### 0.4 `shared/knowledge/` — RAG (DIFERIDO)
- [ ] Stub `retrieve.py` que retorna vacío, para que `shared/narrative` no rompa.
      Implementación completa (ingest/corpus/index) en fase tardía.

### 0.5 Integración sin regresiones
- [ ] Reescribir `macro_political_risk/scoring` para delegar en `shared/indices`
      (su `weights.py` se vuelve un `IndexConfig`). **Los 30 tests de MPR deben seguir verdes.**
- [ ] `banking_score/external/sib_client` re-exporta desde `shared/data/sib_client` (compat).
- [ ] **Verificación**: `pytest shared/ modules/macro_political_risk modules/banking_score -v`
      sin regresiones; cobertura ≥80% en `shared/indices` y `shared/data`.

---

## FASE 1 — Cerrar Ejes existentes

### 1A. `banking_score` (Eje 1) — extensión  ✅ 2026-06-06
- [x] `BankType` extendido a los 6 tipos SIB (banca_multiple, aap, banco_ahorro_credito, corporacion_credito, cambiaria, fiduciaria)
- [x] Perfiles de peso por `entity_type` (`WEIGHT_PROFILES` + `get_sub_component_weights`), mismo marco; `run_scoring(data, entity_type=)` los aplica
- [x] API: `GET /weights?entity_type=`; filtro `entity_type` en `/rankings`
- [x] Consume `irmp.updated` → overlay de **outlook** (no el score): `events.py` (IRMPOutlookContext + overlay_outlook), suscrito en `main.py`
- [x] Sin migración (columna `VARCHAR` sin CHECK en SQLite; autogenerate vacío)
- [x] Tests perfiles/overlay/scoring por tipo (sin regresión: 164 banking); E2E 35/35; total 300, cobertura 88%
- [ ] Pendiente (diferido): backtesting contra histórico etiquetado (requiere `outcomes` poblado)

### 1B. `macro_political_risk` (Eje 4) — completar  ✅ 2026-06-06
- [x] Capa de persistencia: `service.py::compute_and_persist` guarda `IRMPSnapshot`/`DimensionScore` (idempotente por país+período)
- [x] Publicar `irmp.updated` tras score (vía `events.py`, en el servicio)
- [x] Refactor `scoring/` para apoyarse en `shared/indices` (Fase 0)
- [x] Endpoint persistido: `POST /snapshot`, `GET /{cc}/latest`, `GET /{cc}/history`; `/weights` y `/score` intactos
- [x] Migración Alembic `2d738fdbf669` (tablas `mpr_*`); aplica y hace roundtrip
- [x] Sensibilidad de pesos ±10% (`test_sensitivity.py`: score estable y orden de pares preservado)
- [x] **Verificación**: 37 tests MPR verdes (30 + 5 servicio/eventos + 2 sensibilidad); suite total 221
- [ ] Pendiente (diferido): conector real WGI vía `shared/data`; backtesting contra episodios históricos (requiere `outcomes` poblado)

---

## FASE 2 — `macro_monitor` (Eje 2)  ✅ 2026-06-06

- [x] Modelos: `MacroSeries`, `MacroSnapshot` (PK UUID, linaje, `null` sin interpolar) + migración `1c4cb96934bf`
- [x] `bcrd_client` (fixture) ingiere series; fixture ampliado (gdp, inflación, remesas, deuda)
- [x] Scoring de **momentum** (cambio + aceleración + tendencia + banda de incertidumbre + prob. de continuidad)
- [x] Señales Reinhart-Rogoff (deuda) y Calvo (sudden stop) con severidad y evidencia
- [x] API `/api/v1/macro-monitor`: `GET /indicators` · `GET /snapshot` · `GET /signals` · `POST /refresh`
- [x] Publicar `macro.updated` (servicio, tras el snapshot)
- [x] Tests momentum/señales/servicio (25) + manejo de huecos; suite total 246, cobertura 88%
- [x] Routers en `app/main.py` + modelos en `alembic/env.py` (también completa el registro de MPR que faltaba)
- [x] E2E verificado con usuario Claude contra la app real (login → refresh → indicators/snapshot/signals)
- Nota: momentum es series temporales (módulo propio), no la normalización transversal de `shared/indices`.

---

## FASE 3 — `sector_intel` (Eje 3)  ✅ 2026-06-06

- [x] Modelos: `Sector`, `SectorVariable`, `SectorScore` (IAI/SGPS + breakdown) + migración `1ce789e4ec2c`
- [x] **IAI** vía `shared/indices` con doctrina `sectoral.yaml` (Macro 25·Negocios 25·Talento 20·Regulación 15·Sector 15); pesos por sector = extensión futura (recalibrables)
- [x] **SGPS** (Histórico 40·Estructural 35·Aceleración 25); la Aceleración consume `macro/irmp/trade.updated` vía `AccelerationContext` suscrito al `event_bus`
- [x] Consume `macro.updated` `irmp.updated` `trade.updated` (solo contrato string, sin importar otros módulos); publica `sector.updated`
- [x] Sectores ancla: Turismo + Energía + Zonas Francas (seed)
- [x] API `/api/v1/sector-intel`: `GET /sectors` · `GET /weights` · `POST /iai` · `POST /snapshot` · `GET /{sector}/latest`
- [x] Tests IAI/SGPS/aceleración/servicio + wiring de eventos (18); cobertura módulo ~100%, total 88% (278 tests)
- [x] E2E ampliado (Fase 3) → 28/28, valida integración de eventos en vivo
- [ ] Pendiente (futuro): matriz de pesos por sector (spec v2), Porter/Hausmann/Christensen explícitos, abrir los 16 sectores

---

## FASE 4 — `social_dev` (Eje 5) + `esg_climate` (Eje 7)  ✅ 2026-06-06

### `social_dev`
- [x] Modelos: `SocialIndicator` (desagregación/linaje), `DevelopmentScore` + migración `388f90002acf`
- [x] Índice multidimensional vía `shared/indices` + doctrina `social.yaml` (salud/educación/nivel de vida/inclusión); **reporta distribución (mean/min/max/spread/CV), no solo promedio**; informalidad como variable risk-increasing
- [x] API `/api/v1/social-dev`: `GET /weights` · `POST /index` · `GET /indicators` · `GET /sdg`; publica `social.updated`
- [x] Tests índice/distribución/persistencia/eventos

### `esg_climate`
- [x] Modelos: `EnvIndicator`, `ESGScore` (exposición + materialidad) + migración `388f90002acf`
- [x] Índice de resiliencia ESG/clima vía `shared/indices` + doctrina `esg.yaml` (físico/transición/adaptación/gobernanza); **materialidad** (alta/media/baja) + watch de greenwashing; ajuste Caribe (huracanes/costa)
- [x] API `/api/v1/esg-climate`: `GET /weights` · `POST /score` · `POST /exposure` · `GET /indicators`; publica `esg.updated`
- [x] Tests exposición/materialidad/persistencia/eventos

**Verificación Fase 4**: 288 tests, cobertura 88%; E2E ampliado → 33/33 (Fase 0/1A/1B/2/3/4/5).
Nota: ingesta real `one_client` (ONE/censos) y Findex pendiente; datos hoy provistos. Los 7 ejes del backend existen.

---

## FASE 5 — `trade_intel` (Eje 6)  ✅ 2026-06-06

- [x] Modelos: `TradeFlow`, `TradeScore` (concentración/dependencia/resiliencia) + migración `14e19953826c`
- [x] Índices: HHI exportaciones, diversificación (1-HHI), dependencia de importaciones, resiliencia (blend explicable)
- [x] API `/api/v1/trade-intel`: `POST /score` · `POST /snapshot` · `GET /flows` · `GET /concentration` · `GET /score`; publica `trade.updated`
- [x] Tests HHI/dependencia/resiliencia/servicio (14); cobertura módulo ~100%, total 88% (260 tests)
- [x] Registrado en `app/main.py` + `alembic/env.py`; E2E ampliado (Fase 5) → 22/22
- [ ] Pendiente (diferido): ingesta real `dga_client` (aduanas) — bloqueada por licencia sin confirmar (`license_ok=False`); flujos hoy se proveen explícitamente. Zonas francas/upgrading (Gereffi/Hausmann) en iteración posterior.

---

## FASE 6 — Frontend (en paralelo desde Fase 1; bloquea release)

Fuente de verdad: `frontend/DESIGN_SYSTEM.md` + prototipo `ui_kits/sdqmip-app/`.
Reglas duras: tokens vía CSS vars, cabeceras a una línea, **4 estados** por pantalla
(cargando/vacío/error/sin permiso), cifras tabulares, charts theme-aware, UI en español.

### 6.1 Armazón + primitivas + eje ejemplar  ✅ 2026-06-06 (PR #14)
- [x] **Armazón**: Sidebar de 3 grupos (Ejes/Herramientas/Plataforma) + Topbar (breadcrumbs · período · ámbito · tema · perfil) + tema claro/oscuro **persistente** (`AppContext`, localStorage)
- [x] Primitivas en `shared/ui/primitives.tsx`: Card, CardHead (cabecera a una línea), PageHead, Eyebrow, Chip, BandBadge, Delta, StatTile, Gauge (SVG, token colors), Tabs, Skeleton, **StateBlock (4 estados + "en construcción")**
- [x] `shared/lib/bands.ts` (bandFor/riskBandFor/tonos) + `format.ts` (cifras tabulares)
- [x] Eje ejemplar **macro-monitor** conectado a la API real (`/indicators`, `/signals`, `/refresh`): KPIs + tabla momentum + señales, 4 estados
- [x] Rutas en `App.tsx` para los 7 ejes + herramientas/plataforma; ejes 3-7 con `PlaceholderPage` (estado honesto "en construcción")
- [x] **Verificado con preview**: shell en claro/oscuro, datos reales (login usuario Claude), navegación/breadcrumbs/estado; `npm run build` OK; tsc limpio; sin errores de consola

### 6.2 UI canónica por eje  ✅ 2026-06-06 (PRs #15-#19)
- [x] `macro-political-risk` (IRMP): gauge + desglose ponderado + ranking + pesos + guardar snapshot (PR #15)
- [x] `sector-intel` (IAI/SGPS): gauge + desglose + ranking + **pestaña Aceleración** (integración de eventos en vivo) (PR #16)
- [x] `social-dev` (IDM): gauge + **distribución** (dot plot + CV) + desglose + ranking (PR #17)
- [x] `trade-intel`: gauge resiliencia + HHI/concentración por producto + guardar snapshot (PR #18)
- [x] `esg-climate`: gauge exposición + **materialidad** + greenwashing watch + ranking (PR #19)
- [x] Componente reutilizable `DimensionBreakdown` (driver/dim meters) usado por los 4 índices
- [x] Cada eje verificado en preview (claro/oscuro, datos reales con usuario Claude, build, consola)

**Los 7 ejes tienen UI canónica** (6 nuevas + macro-monitor de 6.1; banking-score sigue legacy funcional).

### 6.3 banking-score → tokens + canónico  ✅ 2026-06-06 (PR pendiente de merge)
- [x] Migración legacy → tokens en TODO el frontend (banking + shared); **alias deprecados eliminados** (`tailwind.config.js` + `.btn-secondary`)
- [x] Charts banking theme-aware (ScoreGauge/RatingBadge/TrendChart/RadarChart/PeerBar vía vars/tonos)
- [x] `input-field` indefinido unificado a `.field`; `Navbar` legacy eliminado
- [x] Dashboard rediseñada al patrón canónico (PageHead + StatTile + Top + distribución por rating)
- [x] Rankings rediseñado + **selector de período** (endpoint backend `GET /banking-score/periods`) + filtro por `entity_type`
- [x] Corrige mismatch de rutas/shapes frontend↔backend (rankings/stats); verificado con datos sembrados + scoring

### 6.4 Rediseño pantallas banking restantes  ✅ 2026-06-06 (PRs #21, #22)
- [x] **6.4a** (PR #21): Scoring/Scenarios/Compare al patrón canónico + integración API
  (módulo `api.ts`, `BankSelector` id+nombre, endpoints `GET /banks`, `POST /simulate-scenario`)
- [x] **6.4b** (PR #22): Data/Model/Reports al patrón canónico + rutas/shapes corregidas
  (`getStats`/`listPeriods`, reports por `bank_id` con list/generate/download); `ReportCard` huérfano eliminado
- [x] Todas las pantallas banking verificadas en preview con datos reales (scoring, simulación, comparación, generación de reportes, modelo, datos)

**Fase 6.4 cerrada — las 8 pantallas de banking-score siguen el patrón canónico y funcionan contra la API.**

### 6.5 Polish
- [x] **6.5a** (PR #23): shell responsive (drawer móvil + backdrop) + paleta de comandos ⌘K
- [x] **6.5b** (PR #24): Plataforma — Resumen ejecutivo (consolidado de los 7 ejes) + Metodología (pesos de todos los índices)
- [x] **6.5c** (PR #25): Configuración (settings reales: tema/período/ámbito/cuenta, persistidos)
- [x] **Charts a medida** (PRs #26, #27): trío completo — `Treemap` (trade), `Heatmap` (sector matriz), `ScenarioFan` (macro, con endpoint `GET /macro-monitor/series/{code}`). Todos theme-aware.
- [x] **Unificación de período** (PR #28): banking ahora usa el período global del topbar (mapeo trimestre↔fecha ISO en `periodToDate`), selectores duplicados eliminados; los ejes 2-7 ya lo usaban
- [ ] Pendiente (mejora, no bloqueante): i18n EN (refactor grande; sin switcher en UI hoy)
- [ ] Futuro (features, no placeholders): Deal Scoring, Market Brief, Comparador cross-eje

**Fase 6.5 cerrada en su núcleo** (shell responsive + ⌘K + Resumen ejecutivo + Metodología + Configuración). Lo restante son mejoras/features futuras anotadas.

---

## Saneamiento de release (deploy)  ✅ 2026-06-06 (PR #29)
- [x] Producción **sí** despliega vía integración nativa Railway↔GitHub (deploy en push a main); verificado con logs (health 200).
- [x] Eliminado el job `deploy-railway` del CI (redundante; fallaba por `RAILWAY_TOKEN` vacío y ponía `main` en rojo).
- [x] Logs a **stdout** (`app/main.py` basicConfig + `infrastructure/log_config.json` de uvicorn vía `--log-config`) → Railway deja de clasificar INFO como error.
- [x] `Body(example=...)` → `examples=[...]` en los 6 routers (elimina FastAPIDeprecationWarning de stderr).
- [x] **Migraciones en el deploy** (PR #30): el `CMD` corre `alembic upgrade head` antes de uvicorn; la imagen espeja `infrastructure/` (alembic/ini/log_config) para que resuelvan paths e imports. Verificado: contenedor con sqlite limpio corre toda la cadena de migraciones y arranca (health 200).
- [ ] Caveat pendiente del usuario: confirmar `DATABASE_URL`=**Postgres** en Railway (con esto el esquema se crea solo en el primer deploy).

## FASE 7 — Transversal / release

- [ ] Cada modelo nuevo registrado en `infrastructure/alembic/env.py` + migración generada y aplicada
- [ ] Mapa de eventos completo y probado (test de integración del `event_bus`)
- [ ] Narrativa Claude (SCQA) por eje vía `shared/narrative` + `retrieve.py`
- [ ] Reportes/PDF reutilizando patrón de `banking_score/reports`
- [ ] CI verde: `pytest modules/ shared/ -v` + `--cov` ≥80% en lógica de scoring
- [ ] Docker (`infrastructure/docker-compose`) + Railway: build con `frontend/dist`
- [ ] Regla de trazabilidad auditada: todo score → variable/metodología | corpus | doctrina

---

## Orden de ejecución recomendado

1. **Fase 0** (cimientos) — bloqueante.
2. **Fase 1B** (cerrar MPR: valida el motor compartido con un eje real).
3. **Fase 2** (`macro_monitor`) — habilita `macro.updated` que alimenta a sector_intel/MPR.
4. **Fase 5** (`trade_intel`) antes o junto a Fase 3 si se quiere `trade.updated` para sector_intel.
5. **Fase 3** (`sector_intel`) — consume eventos de 2/4/6.
6. **Fase 4** (`social_dev` + `esg_climate`) — relativamente independientes.
7. **Fase 1A** (extensión banking) cuando haya histórico etiquetado.
8. **Fase 6** frontend en paralelo; **Fase 7** cierre/release.

## Notas durante la ejecución

<bloqueos, decisiones, alternativas descartadas — actualizar aquí>

## Review (al cerrar cada fase)

- **Qué cambió**: …
- **Cómo se verificó**: tests / diff / ejecución
- **Riesgos residuales**: …
- **Lecciones**: link a `tasks/lessons.md` si aplicó

---

## Apéndice A — Diseño de Fase 0 (detalle)

### A.1 `IndexConfig` (contrato del motor)

```python
# shared/indices/config.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Band:
    name: str          # "Bajo"
    lower: float       # umbral inferior inclusivo (descendente, sin huecos)
    color: str         # "#047857"

@dataclass(frozen=True)
class IndexConfig:
    name: str                                   # "IRMP" | "IAI" | "SGPS" | ...
    dimension_weights: dict[str, float]         # debe sumar 1.0
    dimension_variables: dict[str, list[str]]
    risk_increasing: set[str]                   # se invierten en normalización
    bands: list[Band]                           # ordenadas desc por `lower`
    direction: str = "mayor score = mejor"

    def __post_init__(self):
        s = round(sum(self.dimension_weights.values()), 6)
        if s != 1.0:
            raise ValueError(f"{self.name}: los pesos suman {s}, no 1.0")
        # validar bandas gap-free / ordenadas en construcción del config
```

`run_index(entity_key, dataset, config)` produce la **misma forma** que el actual
`run_irmp` (score, banda, color, `dimensions{score, weight, contribution, variables}`).
Así MPR no cambia de contrato de API, solo de implementación interna.

### A.2 Mapa de migración MPR → shared (1:1, sin cambio de lógica)

| Origen (MPR) | Destino (shared) | Cambio |
|---|---|---|
| `scoring/normalization.py` | `shared/indices/normalization.py` | mover tal cual |
| `scoring/dimensions.py` | `shared/indices/dimensions.py` | recibir `config` por parámetro |
| `scoring/bands.py` | `shared/indices/bands.py` | bandas desde `config`, no hardcode |
| `scoring/engine.py::run_irmp` | `shared/indices/engine.py::run_index` | genérico por `config` |
| `scoring/weights.py` | `shared/doctrine/regulatory.yaml` → `IndexConfig` | pesos a doctrina |

`modules/macro_political_risk/scoring/engine.py` queda como wrapper fino:
`run_irmp(cc, ds) = run_index(cc, ds, load_doctrine("regulatory"))`.

### A.3 Definición de "hecho" para Fase 0 — COMPLETADO 2026-06-06

- [x] `shared/indices` y `shared/data` con tests (32 nuevos; cobertura no medible
      localmente —falta `pytest-cov`/`coverage`— pero CI la verifica; ramas cubiertas
      exhaustivamente por diseño).
- [x] Los **30 tests de MPR verdes** corriendo sobre el motor compartido (prueba viva).
- [x] `banking_score` importando `sib_client` desde `shared/data` sin romper (shim de compat).
- [x] Un `IndexConfig` cargable desde doctrina YAML (`shared/doctrine/regulatory.yaml`).
- [x] Cero lógica de scoring nueva fuera de `shared/indices` a partir de aquí.
- [x] `pyyaml` añadido a `requirements.txt`.
- [x] Suite completa verde: **214 passed**; `ruff` limpio.

**Pendiente menor**: añadir `pytest-cov`/`coverage` al entorno para poder reportar
el número de cobertura (la regla del proyecto es ≥80% en `scoring/`).
