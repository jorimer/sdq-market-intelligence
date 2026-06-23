# SPEC — Productización por niveles (Pulse / Insight / Deep Dive) sobre `banking_score`

> v0.1 · 2026-06-23 · Documento conceptual y de contratos. El plan ejecutable por fases vive en
> **`tasks/PLAN_TIER_PRODUCTIZATION.md`**. Fuente comercial: `Catalogo_SDQMIP_v2_Productos_Sectoriales.docx`
> (raíz del repo SDQMIP) — modelo de empaquetado de 3 niveles + matriz cross-sector.
> Regla Plan First: confirmar el desglose antes de implementar.

---

## 0. Resumen ejecutivo (BLUF)

El catálogo comercial define tres niveles de profundidad — **Pulse**, **Insight**, **Deep Dive** — que
hoy **no existen como producto** en el código, aunque **casi toda la maquinaria sí existe**. Este spec
NO crea generadores de reporte nuevos: crea una **capa de ensamblaje dirigida por un manifiesto**
(`product_tiers.py`) que mapea cada nivel comercial sobre los 7 tipos de reporte ya implementados en
`reports/pdf_generator.py`, rellena 3 huecos concretos (agregado anonimizado para Pulse, secciones de
escenarios+recomendación para Deep Dive, marca/marca de agua por nivel), y produce muestras reales
con un banco ficticio (`Banco Demo, S.A.`) para las reuniones de venta.

**Principio rector:** un manifiesto declarativo gobierna qué secciones, qué granularidad y qué
narrativa lleva cada nivel. Agregar/quitar una sección de un producto debe ser editar el manifiesto,
no tocar el generador. Esto preserva la doctrina de la casa: explicable, trazable, no caja negra.

**Alcance de esta entrega:** solo `banking_score` (eje Listo). El patrón queda generalizable a los
demás ejes después, igual que se generalizó el Cerebro de Insights (ver `tasks/todo.md`).

---

## 1. Contexto: qué ya existe (no reinventar)

Verificado en el repo (`modules/banking_score/`):

| Pieza | Ubicación | Qué aporta |
|---|---|---|
| Generador PDF, 7 tipos | `reports/pdf_generator.py` → `generate_pdf_report(report_type, bank_name, scoring_result, period, narratives, output_dir)` | `full_rating`, `scorecard`, `communique`, `datawatch`, `wire`, `sector_outlook`, `criteria`. Portada, radar, tabla de sub-scores, tabla de indicadores, secciones narrativas, disclaimer. |
| Escala de rating | `scoring/rating_scale.py` | 10 niveles `SDQ-AAA … SDQ-D`, `map_rating_tier()`, `TIER_COLORS`, índices ordinales. |
| Pilares y pesos | `scoring/weights.py` | 5 sub-componentes: `solidez (0.40)`, `calidad (0.30)`, `eficiencia (0.15)`, `liquidez (0.10)`, `diversificacion (0.05)`; perfiles por `entity_type`; listas de indicadores por pilar. |
| Narrativa SCQA | `shared/narrative/claude_engine.py` + wrapper `reports/narrative.py` | `narrative_engine.generate(context, template, mode, lang)`; guard anti-alucinación (`numeric_guard`, inyección `cifras_derivadas`). |
| API de reportes | `api/router_reports.py` (prefix `/api/v1/banking-score/reports`) | `generate_report` (genérico), `generate_communique/wire/datawatch/sector_outlook/criteria`, `download_report`, `list_reports`. |
| Modelos | `models/models.py` | `ReportType` enum, `Report`, `RatingAction`, enums de outlook/acción. |
| Insight de entidad | `scoring/entity_insight.py`, `scoring/indicator_detail.py` | Contexto y desgloses por entidad/indicador (Cerebro). |
| Agregación de sistema | `scoring/batch.py`, `scoring/market_concentration.py` | Scoring batch del sistema y concentración de mercado (insumo de Pulse y del bloque de pares). |

**Conclusión:** Insight ≈ ya existe (`full_rating` + `scorecard` por entidad nombrada). Pulse y Deep
Dive son ensamblajes + huecos puntuales. El trabajo es de **empaquetado y orquestación**, no de motor.

---

## 2. Mapeo nivel comercial → implementación

| Nivel | Granularidad | Mapea a (report types) | Secciones | Estado |
|---|---|---|---|---|
| **Pulse** | Sistema, **sin nombrar** (bandas) | `sector_outlook` / `wire` a nivel sistema | Distribución de ratings en bandas, tendencias del sistema, comentario macro-bancario | **Hueco G1** (agregado anonimizado) |
| **Insight** | Entidad **nombrada**, recurrente | `full_rating` + `scorecard` | Rating+outlook, radar 5 pilares + contribuciones, tabla de indicadores, **bloque de pares**, narrativa SCQA, gancho de alertas | Existe ~90% (huecos G3, packaging) |
| **Deep Dive** | Entidad/contraparte, a medida | `full_rating` **extendido** | Todo lo de Insight + **análisis de escenarios** + **recomendación explícita** (aprobar/condicionar/declinar) + limitaciones | **Hueco G2** |

Regla de granularidad (no negociable): **Pulse no puede emitir nombres de entidad**. La anonimización
se valida con un sensor automatizado (§6).

---

## 3. Arquitectura propuesta

### 3.1 Manifiesto de producto (config-as-code) — artefacto central nuevo

`modules/banking_score/reports/product_tiers.py`

```python
from enum import Enum
from dataclasses import dataclass, field

class ProductTier(str, Enum):
    pulse = "pulse"
    insight = "insight"
    deep_dive = "deep_dive"

@dataclass(frozen=True)
class TierManifest:
    tier: ProductTier
    base_report_type: str          # uno de los 7 tipos de pdf_generator
    granularity: str               # "system" | "named_entity"
    sections: list[str]            # claves de sección en orden de render
    narrative_templates: list[str] # templates SCQA a generar
    watermark: str | None          # p.ej. "VISTA ABIERTA", None, "MUESTRA — DATA ILUSTRATIVA"
    audience: str                  # metadato comercial
    cadence: str                   # "periodic" | "recurring" | "on_demand"

TIER_MANIFESTS: dict[ProductTier, TierManifest] = { ... }  # las 3 definiciones
```

El manifiesto es la **única fuente de verdad** de qué lleva cada producto. Cambiar el contenido de un
nivel = editar este archivo. Debe estar versionado y referenciado en la doctrina de la casa.

### 3.2 Ensamblador

`modules/banking_score/reports/tier_assembler.py`

```python
async def assemble_tier_report(
    tier: ProductTier,
    *,
    scoring_result: dict | None = None,   # requerido para insight/deep_dive
    system_snapshot: dict | None = None,  # requerido para pulse
    bank_name: str | None = None,
    period: str,
    lang: str = "es",
    sample: bool = False,                  # fuerza watermark de muestra
    output_dir: str | None = None,
) -> str:
    """Lee TIER_MANIFESTS[tier], construye el dict de narrativas (una llamada al
    narrative_engine por template), aplica reglas de granularidad y delega en
    pdf_generator.generate_pdf_report con report_type + secciones del manifiesto.
    Devuelve el path del PDF. NO duplica lógica de render."""
```

`generate_pdf_report` se extiende de forma **no-rotura** para aceptar:
- `sections: list[str] | None` — si viene, filtra/ordena las secciones (default = comportamiento actual).
- `tier: ProductTier | None` — para watermark y reglas de granularidad.
- `sample: bool` — overlay "MUESTRA — DATA ILUSTRATIVA".

### 3.3 Huecos a construir

- **G1 · Agregado de sistema anonimizado (Pulse).** `scoring/system_aggregate.py`: a partir de
  `batch.py`, produce `{band_distribution: {tier_band: count}, system_trends, macro_commentary_ctx}`
  **sin** identificadores de entidad. Banda = agrupación de tiers (p.ej. Fuerte/Adecuado/Vigilancia)
  para no exponer el rating individual. Pulse consume esto.
- **G2 · Secciones Deep Dive.** Templates SCQA nuevos `scenario_analysis` y `recommendation` en
  `shared/narrative` (o wrapper banking); builders `_build_scenarios()` y `_build_recommendation()` en
  `pdf_generator.py`, activados solo cuando `tier == deep_dive`. La recomendación es estructurada:
  veredicto ∈ {aprobar, condicionar, declinar} + condiciones + umbrales de reevaluación.
- **G3 · Bloque de pares.** `_build_peer_block()` reutilizando `market_concentration.py` / rankings;
  para Insight y Deep Dive.
- **G4 · Marca por nivel.** Pie/portada diferenciados: Pulse = "Vista abierta · SDQMIP"; muestra =
  overlay rojo. Reutiliza `_build_cover_page`.
- **G5 · Fixtures de muestra.** `Banco Demo, S.A.` — `scoring_result` sintético realista (alineado a
  los KPIs del Anexo del catálogo: Solvencia/CAR ~16.8%, morosidad ~1.9%, ROE ~19.4%, eficiencia ~56%,
  liquidez ~31%). Genera 3 PDFs muestra (uno por nivel) → reemplazan los Anexos ilustrativos del v1.
- **G6 · API.** `POST /api/v1/banking-score/reports/product` con `tier`, `entity_id|system`, `period`,
  `sample`. Reutiliza el plumbing de `generate_report`. Respuestas/errores en español.

### 3.4 Modelo de datos (mínimo)

- `ProductTier` enum (en `models.py` o importado de `product_tiers.py`).
- Columna `product_tier: str | None` en `Report` para etiquetar lo generado (filtrado/auditoría).
- Migración Alembic; registrar en `infrastructure/.../env.py`. **Sin** modelo de suscripción/billing.

---

## 4. Fuera de alcance (explícito)

- **Entitlements / billing / suscripciones / paywall.** Se etiqueta el tier en `Report`, nada más.
  El control de acceso comercial es Fase 2 (capa de distribución del Anexo B del catálogo).
- **Tienda self-serve, extractos de data, API pública, tier académico.** Anexo B → Fase 2/3.
- **Otros ejes** (macro, trade, etc.). Este spec es solo `banking_score`.
- **Pricing dinámico.** Los rangos son metadato comercial, no lógica de negocio.

---

## 5. Convenciones obligatorias (de `CLAUDE.md`)

Identificadores Python en inglés · strings UI/errores de API en español · independencia de módulo
(sin importar de otro módulo; contexto macro vía `event_bus` si se necesitara) · prefijo
`/api/v1/banking-score` · PK UUID · tests ≥80% en lógica de ensamblaje/manifiesto · migraciones
Alembic registradas en `env.py` · regla de trazabilidad: toda cifra de la narrativa rastrea a
metodología/data/doctrina o no se emite (guard existente).

---

## 6. Sensores y criterios de aceptación

**Sensores (correr antes de cerrar):**
- `pytest modules/banking_score -v` con cobertura ≥80% en `product_tiers.py`, `tier_assembler.py`,
  `system_aggregate.py`.
- `ruff check` limpio.
- `alembic -c infrastructure/alembic.ini upgrade head` OK (si hay migración).
- Generar los 3 PDFs muestra (`Banco Demo, S.A.`) e **inspección visual** de cada nivel.
- Guard anti-alucinación: las narrativas Deep Dive (escenarios/recomendación) pasan
  `numeric_guard.deterministic_unsupported` = 0 cifras inventadas, 0 período equivocado.
- **Reviewer subagent** sobre el diff (pasarle este spec + `CLAUDE.md`).

**Criterios de aceptación (por nivel):**
- **Pulse:** PDF a nivel sistema, distribución en bandas, **cero nombres de entidad** (sensor de
  anonimización automatizado), pie "Vista abierta".
- **Insight:** entidad nombrada; rating+outlook, radar de 5 pilares con contribuciones, tabla de
  indicadores, bloque de pares, narrativa SCQA.
- **Deep Dive:** todo lo de Insight + análisis de escenarios + recomendación estructurada
  (veredicto+condiciones+umbrales) + limitaciones; guard limpio.
- **Manifiesto-driven:** agregar/quitar una sección de cualquier nivel se logra editando
  `product_tiers.py`, sin tocar el generador (test que lo verifique).
- **Muestras:** 3 PDFs `Banco Demo, S.A.` generables por comando/fixture, con overlay de muestra.

---

## 7. Riesgos / decisiones abiertas

- **[Likely] Pulse — definición de "banda".** Hay que decidir el agrupamiento de los 10 tiers en
  bandas para anonimizar sin perder valor (propuesta: 3–4 bandas). Decisión de doctrina, no de código.
- **[Likely] Deep Dive vs. `deal_scoring`.** El Deep Dive de contraparte podría querer insumos de
  `deal_scoring`. Mantener independencia de módulo: si se necesita, vía `event_bus`, no import directo.
- **[Guessing] Reutilización de `sector_outlook` para Pulse.** Confirmar si `sector_outlook` ya
  produce a nivel sistema o si requiere el agregado anonimizado nuevo (G1). Probable que sí lo requiera.
