# Receta de onboarding de un sector al framework de productos

> Validada cableando **Macro & Country Risk** (sector #2) en P3. Onboardear el sector
> #N = seguir estos pasos **sin tocar** `shared/products/{tiers,manifest,contract,assembler,
> readiness,registry,activation,service,render}.py`. Si necesitás modificar el framework,
> es una mejora del framework (como el renderer genérico o el fix de G4 en P3), no parte
> del onboarding — sepáralo y justifícalo.

## Qué es "cablear un sector"

Implementar el `Protocol` `SectorProduct` (ver `shared/products/contract.py`) para que el
**Monitor de Productos** lo muestre con readiness real y permita activarlo al cruzar umbral.
El framework orquesta (rúbrica, gate, registry, ensamblador, sensor de anonimización); el
sector solo aporta **datos + manifiesto + señales + narrativa + render**.

## Dónde vive el código del sector

- **Sector de un solo módulo** (banking, trade, esg…): en el propio módulo,
  `modules/<sector>/products.py`.
- **Sector que abarca varios módulos** (macro = `macro_monitor` + `macro_political_risk`):
  a **nivel app** (`app/products_<sector>.py`), componiendo vía los **getters de servicio
  públicos** de cada módulo (NUNCA importando un módulo desde otro; misma regla que
  `app/market_brief.py`).

## Pasos

1. **Fuente / datos.** Leé el dato real del sector por sus getters públicos (no tablas
   ajenas en crudo). Define un helper por fuente (p.ej. `_macro_factors(db)`,
   `_irmp(db)`) con `try/except` que devuelva vacío si la fuente no está (honesto).

2. **Manifiesto de 3 niveles** (`SectorProductManifest`). Declará Pulse (granularidad
   `system`, **sin nombrar** — el sensor de anonimización lo exige), Insight y Deep Dive
   (`named_entity`). Para sectores **nacionales** sin entidades (macro), la "entidad
   nombrada" es el país; el Pulse es el agregado nacional con `entity_roster=()`.
   Secciones + `narrative_templates` por nivel; `watermark` del Pulse = "Vista abierta…".

3. **Señales de readiness:**
   - `data_signals() -> DataHealth`: cobertura (frac. con dato) + frescura (días) +
     fuentes. **G1** sale de acá.
   - `has_engine() -> bool`: ¿índice/motor operativo? **G2**.
   - `validation_state() -> ValidationState`: outcomes/QA + doctrina firmada. **G5**.
   - G3 (narrativa) y G4 (plantilla) salen del manifiesto (templates y secciones
     declarados). No se inflan: si no hay dato, G1/G2/G5 bajan y el producto queda
     **cableado pero no publicable** hasta ampliar la fuente. **NUNCA inventar data.**

4. **Snapshot** (`snapshot(tier, period, scope) -> ProductSnapshot`): para `system`
   (Pulse) un payload agregado **sin identificadores** (el ensamblador corre
   `enforce_anonimizado` con el `entity_roster` que adjuntes); para nombrado, el payload
   de la entidad + `entity_name`.

5. **Narrativas** (`async narratives(tier, snapshot, lang)`): generá por sección con
   `narrative_engine.generate(context=..., template=..., axis="<eje>", audience=...)`.
   **Pasá siempre `axis`** para enrutar por el `numeric_guard` (anti-alucinación); el
   template debe estar en `THIN_TEMPLATES` y el axis en `AXIS_DOCTRINE`, si no NO hay
   guard (ver `tasks/lessons.md` 2026-06-23). Secciones estáticas (limitaciones) sin
   cifras → texto fijo.

6. **Render** (`async render(...) -> path`): usá el **renderer genérico**
   `shared/products/render.py::render_product_pdf` (portada + tablas + narrativas +
   marca), salvo que el sector tenga un generador rico propio (banking con su radar).
   Pasá `watermark` del nivel y `sample` para muestras.

7. **Auto-registro:** al final del módulo,
   `register_product("<sector>", lambda db: <Sector>Product(db))`. Cableá su import en
   `app/main.py` (junto a los otros). Para multi-módulo, usá `from app import products_<sector>`
   (NO `import app.products_<sector>`, que rebindea el nombre `app` = la instancia FastAPI).

8. **Tests + fixtures:** conformidad con el contrato (`isinstance(..., SectorProduct)`),
   manifiesto, readiness desde señales reales (probar que con DB vacía G1/G2 bajan = no
   hardcode), y render sintético de los 3 niveles. Sensor de anonimización si aplica.

## Criterio de cierre (staff)

El sector aparece en `/products` con readiness real; al cruzar umbral, activable. **Y el
diff NO toca ningún archivo de `shared/products/` del framework** (solo agrega el módulo
del sector + su línea de import). Si lo toca, no está cerrado como onboarding.
