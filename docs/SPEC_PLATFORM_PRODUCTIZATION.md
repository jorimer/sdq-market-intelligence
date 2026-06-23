# SPEC — Productización de plataforma: 10 productos sectoriales + Monitor de Readiness

> v0.1 · 2026-06-23 · Spec maestro. Cubre TODOS los productos del catálogo, el framework que los
> unifica y el monitor que controla su activación. Plan ejecutable: **`tasks/PLAN_PLATFORM_PRODUCTIZATION.md`**.
> Detalle del sector de referencia (Banca): **`docs/SPEC_TIER_PRODUCTIZATION_BANKING.md`**.
> Fuente comercial: `Catalogo_SDQMIP_v2_Productos_Sectoriales.docx`. Plan rector: `docs/PLAN_MAESTRO_DESARROLLO.md`.
> Regla Plan First: confirmar el desglose antes de implementar.

---

## 0. Resumen ejecutivo (BLUF)

Se programa **todo el portafolio** del catálogo: 10 productos sectoriales, cada uno con 3 niveles
(Pulse / Insight / Deep Dive). **Todos los sectores se cablean** (ingesta de fuente → motor → reporte);
ninguno queda como scaffold opcional. Se construye:

1. **Un framework sector-agnóstico** (en `shared/`) que cualquier sector hereda vía manifiesto.
2. **Los 10 sectores cableados** end-to-end con su fuente autoritativa.
3. **Un Monitor que controla la activación de acceso público**: aunque un producto esté cableado y
   funcionando internamente, solo se expone al público/clientes cuando el dueño lo activa desde el
   monitor — y el monitor solo permite activar si el producto cruza el umbral de readiness (calidad).

El monitor NO decide qué se construye (todo se construye). Es el **gate de publicación**: separa "listo
internamente" de "disponible para el público", y protege la marca impidiendo exponer un producto cuyo
readiness (G1-G5) esté por debajo del umbral.

**Anti-Frankenstein:** un contrato uniforme de sector + una rúbrica de readiness garantizan que cada
sector cableado esté en un estado medible y completo, nunca en caos parcial.

---

## 1. Arquitectura

### 1.1 Framework de productización — promover a `shared/`

Hoy la lógica de niveles vive (por diseñarse) en `banking_score`. Se **promueve a `shared/products/`**
para que sea transversal, igual que se hizo con el Cerebro de Insights (`shared/narrative`, `shared/ui`).

```
shared/products/
├── tiers.py            # ProductTier(Enum): pulse|insight|deep_dive; TierLevelSpec base
├── manifest.py         # SectorProductManifest (dataclass): contrato declarativo por sector
├── assembler.py        # assemble_product_report(sector, tier, ...) genérico
├── registry.py         # PRODUCT_REGISTRY: catálogo en código de los 10 sectores × 3 niveles
├── readiness.py        # rúbrica G1-G5, cálculo de readiness por (sector, tier)
├── activation.py       # gate de activación (readiness ≥ umbral → activable)
└── models.py           # ProductReadiness, ProductActivation (DB)
```

Cada **sector** implementa un contrato uniforme (no importa de otros módulos; convención del repo):

```python
# Contrato que cada módulo de sector expone (Protocol)
class SectorProduct(Protocol):
    sector_key: str                       # "banking", "tourism", ...
    def data_signals(self) -> DataHealth   # frescura/cobertura de fuentes (alimenta G1)
    def has_engine(self) -> bool           # índice explicable operativo (G2)
    def scoring_snapshot(self, period, scope) -> dict      # named_entity
    def system_snapshot(self, period) -> dict              # agregado anonimizado (Pulse)
    def narrative_templates(self) -> list[str]             # G3
    def tier_manifest(self) -> SectorProductManifest       # G4
    def validation_state(self) -> ValidationState          # outcomes/QA + doctrina (G5)
```

### 1.2 Manifiesto por sector (config-as-code)

Cada sector declara, en su módulo, un `SectorProductManifest` con las 3 definiciones de nivel
(secciones, granularidad, templates, marca, cadencia, metadato de precio). El manifiesto es la única
fuente de verdad de qué lleva cada producto. Agregar un nivel o cambiar secciones = editar manifiesto.

### 1.3 Niveles (constantes en todos los sectores)

| Nivel | Granularidad | Secciones típicas | Cadencia |
|---|---|---|---|
| **Pulse** | Sistema, **sin nombrar** (bandas) | Distribución en bandas, tendencias, comentario | Periódico / abierto |
| **Insight** | Entidad/segmento **nombrado** | Score+outlook, radar de pilares, indicadores, pares, narrativa, alertas | Recurrente |
| **Deep Dive** | A medida | Insight + escenarios + recomendación + limitaciones | On-demand |

Regla no negociable: **Pulse nunca emite identificadores de entidad** (sensor de anonimización por sector).

---

## 2. Los 10 productos sectoriales

Cada uno mapea a módulo(s) existente(s) o nuevo, con su fuente autoritativa (el foso) y su madurez de
partida. La madurez final la mide el monitor, no esta tabla.

| # | Producto | Módulo(s) | Fuente autoritativa | Madurez inicial |
|---|---|---|---|---|
| 1 | SDQ Banking Intelligence | `banking_score` | SIB, fiduciaria, BCRD | **Listo** |
| 2 | SDQ Macro & Country Risk | `macro_monitor` + `macro_political_risk` | BCRD, DIGEPRES/Crédito Público, WGI/WDI, GDELT | En desarrollo |
| 3 | SDQ Trade & Logistics | `trade_intel` | DGA (aduanas), BCRD | En desarrollo |
| 4 | SDQ Tourism Intelligence | nuevo (o `sector_intel`) | BCRD turismo, ASONAHORES, MITUR | Roadmap |
| 5 | SDQ Free Zones & Manufacturing | nuevo (o `sector_intel`) | CNZFE, ONE, datos.gob.do | Roadmap |
| 6 | SDQ Energy Intelligence | nuevo | SIE, CNE, Organismo Coordinador | Roadmap |
| 7 | SDQ Telecom Intelligence | nuevo | INDOTEL (trimestral, datos abiertos) | Roadmap |
| 8 | SDQ Construction & Real Estate | nuevo (o `sector_intel`) | ONE, ADOCEM, BCRD | Roadmap (data parcial) |
| 9 | SDQ Agribusiness | nuevo (o `sector_intel`) | Min. Agricultura, BAGRÍCOLA, ONE | Roadmap (data fragmentada) |
| 10 | SDQ ESG & Climate | `esg_climate` | ONE, Medio Ambiente, IPCC, mix SIE | Roadmap (comprador naciente) |

> Sectores descartados del catálogo (Retail, Salud, Sector Público) **no** se programan; Sector Público
> se pliega en #2 (módulo fiscal). Ver Anexo del catálogo.

Decisión de implementación (a confirmar en P3): los sectores "nuevo (o `sector_intel`)" se montan como
**sub-ejes dentro de `sector_intel`** salvo que la complejidad de la fuente justifique módulo propio
(probable módulo propio para Energía, Telecom y Zonas Francas por la riqueza de su data regulatoria).

---

## 3. Monitor de activación pública (readiness gate)

> Rol: controlar qué productos —ya cableados— se exponen al público. No prioriza la construcción
> (todos se cablean). Mide readiness y bloquea la publicación de lo que no cruce el umbral de calidad.


### 3.1 Rúbrica (modelable, por sector × nivel)

| Gate | Mide | Señal técnica | Peso |
|---|---|---|---|
| **G1 Data** | Ingesta de fuente autoritativa operativa y fresca | `data_signals()` → cobertura % + antigüedad < umbral | 30% |
| **G2 Motor** | Índice explicable + scoring corriendo | `has_engine()` + último scoring OK | 25% |
| **G3 Narrativa** | SCQA operativa + guard anti-alucinación verde | templates presentes + guard 0 violaciones | 15% |
| **G4 Plantilla** | Reporte del nivel renderiza | manifiesto del nivel + smoke render OK | 15% |
| **G5 Validación** | Outcomes/QA + doctrina firmada | `validation_state()` aprobado | 15% |

`readiness(sector, tier) = Σ peso_i × score_i`, score_i ∈ [0,1]. Resultado 0–100%.

### 3.2 Gate de activación pública

```python
ACTIVATION_THRESHOLD = {"pulse": 0.75, "insight": 0.85, "deep_dive": 0.85}
# Un producto (sector, tier) puede EXPONERSE AL PÚBLICO solo si readiness ≥ umbral del tier.
# "Activar" = hacer disponible al público/cliente. El producto puede estar cableado y operativo
# internamente sin estar activado. El estado vive en ProductActivation (DB); el toggle del
# dashboard respeta el gate de readiness.
```

El umbral es más exigente para Insight/Deep Dive (nombrados, reputación) que para Pulse. La activación
es siempre **explícita y manual** (decisión del dueño), nunca automática al cruzar el umbral.

### 3.3 Persistencia

- `ProductReadiness` (DB): `sector_key, tier, g1..g5, readiness, computed_at`. Recalculado por job +
  on-demand. Linaje: cada score apunta a la señal que lo originó (trazabilidad).
- `ProductActivation` (DB): `sector_key, tier, is_active, activated_by, activated_at`. Toggle gated.

### 3.4 API (`/api/v1/products`)

- `GET /products/readiness` — matriz sector × nivel con readiness + desglose G1-G5.
- `GET /products/readiness/{sector}` — detalle de un sector.
- `POST /products/{sector}/{tier}/activate` — **expone al público** (rechaza si readiness < umbral; error en español).
- `POST /products/{sector}/{tier}/deactivate` — retira del acceso público (el producto sigue cableado).
- `POST /products/readiness/recompute` — recalcula (recurrente-humana, estilo consola de operación).

### 3.5 Dashboard (frontend `platform`)

Pantalla "Monitor de Productos": grilla **sectores (filas) × niveles (columnas)** con semáforo por
readiness (rojo/ámbar/verde), % y desglose G1-G5 al expandir, y **toggle de activación de acceso
público** por celda (deshabilitado si no cruza el umbral, con tooltip del gate faltante; un estado
visible distingue "cableado pero no publicado" de "publicado"). Claro/oscuro. Estados de carga/
vacío/error (doctrina UI). Reutiliza patrones de `ConfiguracionPage`/`SeriesMaintenanceSection`.

---

## 4. Convenciones obligatorias (de `CLAUDE.md`)

Identificadores Python en inglés · strings/errores de API en español · **independencia de módulo**
(sectores no se importan entre sí; lo transversal vive en `shared/`; contexto cruzado vía `event_bus`)
· prefijos `/api/v1/products` y `/api/v1/{sector}` · PK UUID · tests ≥80% en framework, readiness y
ensamblador · migraciones Alembic en `env.py` · regla de trazabilidad (toda cifra rastrea a
metodología/data/doctrina o no se emite) · anti-alucinación con `numeric_guard` + `cifras_derivadas`.

---

## 5. Sensores y criterios de aceptación

**Sensores:**
- `pytest shared/products modules/ -v`, cobertura ≥80% en `shared/products/*` y en el contrato de cada sector.
- `ruff check` limpio · `alembic upgrade head` OK.
- Smoke render de los 3 niveles para cada sector con `has_engine()=True`.
- Sensor de anonimización Pulse por sector (0 nombres).
- Guard anti-alucinación verde en narrativas nuevas.
- Dashboard: un humano no-técnico ve readiness y activa/desactiva cada producto desde la UI.
- **Reviewer subagent** en P0, P1, P3 y en el onboarding de cada sector (toca prod/contratos).

**Criterios de aceptación:**
- El framework en `shared/products/` gobierna los 3 niveles; `banking_score` lo consume sin regresión.
- El monitor calcula readiness por sector × nivel desde señales reales (no hardcode) y bloquea la
  **activación de acceso público** bajo umbral; la activación es manual/explícita.
- Los 10 sectores quedan cableados (ingesta → motor → reporte) e implementan el contrato `SectorProduct`.
- Onboarding de un sector = implementar el contrato + manifiesto + señales, **sin tocar** el framework
  ni el motor genérico (test que lo verifique).
- Banca publicable a nivel Insight con muestras reales (`Banco Demo, S.A.`).
- Cada sector aparece en el monitor con su readiness real, distinguiendo "cableado/no publicado" de
  "publicado".

---

## 6. Fuera de alcance

- Billing/suscripciones/paywall (solo se etiqueta `product_tier`; control comercial = Fase 2).
- Capa de distribución del Anexo B (tienda self-serve, extractos, API pública, tier académico) = Fase 2/3.
- Calidad/acceso de fuentes: todos los sectores se cablean con la data autoritativa disponible. Donde
  la fuente es fragmentada (Construcción, Agro), el sector se cablea igual con lo que haya y el monitor
  refleja G1 según cobertura real — eso puede dejar su readiness por debajo del umbral de publicación
  hasta ampliar la fuente. Nunca se inventa data para subir un gate.

---

## 7. Decisiones abiertas (de doctrina, no de código)

- **[Likely]** Bandas de anonimización por sector para Pulse (3–4 bandas). Por sector.
- **[Likely]** Qué sectores merecen módulo propio vs. sub-eje de `sector_intel` (probable propio:
  Energía, Telecom, Zonas Francas).
- **[Guessing]** Umbrales de activación (0.75/0.85) — calibrar tras el primer sector activado.
- **[Likely]** Cadencia del job de recálculo de readiness (¿diario? ¿por evento `*.updated`?).
