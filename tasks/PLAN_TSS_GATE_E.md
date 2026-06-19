# Plan de ingeniería — Outcome de empleo formal (TSS) + Gate E sectorial

> **Para:** Claude Code. **Autor:** asesoría de datos, 2026-06-19.
> **Origen:** [`docs/sectorial-gate-e-fuentes-hallazgos.md`](../docs/sectorial-gate-e-fuentes-hallazgos.md)
> (investigación de fuentes) y [`docs/sectorial-gate-e-data-spec.md`](../docs/sectorial-gate-e-data-spec.md).
> **Proceso:** aplica las reglas de `~/.claude/CLAUDE.md` (Plan First — este es el
> plan, confírmalo antes de codear; Verify Done con Sensors; Reviewer Subagent
> antes de cerrar; causa raíz; impacto mínimo; actualizar `tasks/lessons.md` tras
> cualquier corrección). Respeta `CLAUDE.md` del repo (módulos independientes,
> `event_bus`, identificadores Python en inglés, strings UI/errores en español,
> tests ≥80% en lógica de scoring, migraciones Alembic).

---

## 0. BLUF — qué se construye y por qué así

Se cablea el **primer outcome real del Gate E sectorial: empleo formal cotizante
por sector (TSS)**, y de paso se vuelven reales dos variables del IAI hoy en
rúbrica (`operating_cost`, `labor_availability`) con la misma extracción. Luego se
añade el **harness de backtest** (`modules/sector_intel/validation/`) que `sector_intel`
todavía no tiene, espejo del de `trade_intel`/`macro_political_risk`.

**Decisiones que este plan asume explícitas (cámbialas si discrepas):**

1. **Outcome primario = empleo formal TSS** (no IED). Cubre ~12-13 sectores vs ~8 de
   IED y es trimestral. IED (BCRD) entra como **outcome secundario de contraste**
   en una fase posterior, no en este PR.
2. **Resolución real, no forzar 17.** El Gate E corre sobre los sectores con dato
   real; los no cubiertos se marcan `out_of_validation`, no se imputan. (Validar
   contra dato imputado = validar contra ruido — lección §0.2 invertida.)
3. **Crosswalk con disclosure.** El mapeo TSS-CIIU → 17 slugs vive como tabla
   declarada y versionada en el conector, con nota por celda ambigua. Maximizar
   cobertura aceptando proxies declarados (decisión del dueño 2026-06-19).
4. **El dato sectorial de TSS vive en PDF (boletines trimestrales), no en CSV.** El
   CSV abierto de `datos.gob.do` solo trae total por tipo de empleador. La
   extracción por rama es la pieza ETL real de este plan.

**Métrica del Gate E (explicable, no caja negra):** como el outcome es continuo
(crecimiento del empleo sectorial), la validación es **IC de rango (Spearman)** entre
`IAI_T` y `Δempleo_{T+1}` agrupado por año (cross-section de sectores), más spread
por quintil y test de signo. NO es AUC binaria (eso es para shocks; aquí el desenlace
es magnitud). Panel ~8 años × ~12 sectores ≈ 80-100 obs → validación **direccional**,
se reporta con su n y su intervalo, sin sobre-afirmar.

---

## 1. Alcance / No-alcance

**En alcance (este plan):**
- Conector `shared/data/tss_client.py` (live boletines + fixture), patrón `BCRDSectorsClient`.
- Crosswalk declarado TSS-CIIU → 17 slugs.
- Sync `tss-empleo-sync` → upsert a `si_variables` (`formal_employment`, `operating_cost`, `labor_availability`).
- Wiring en `assemble_iai_dataset`: sacar `operating_cost` + `labor_availability` de rúbrica a dato real con fallback declarado.
- Harness `modules/sector_intel/validation/` (historical, outcomes, report) + operación `sector-gate-e`.
- API `GET /api/v1/sector-intel/validation` + badge real-vs-rúbrica actualizado.
- Tests + sensores + fixtures.

**Fuera de alcance (PR posteriores, anotar en `tasks/todo.md`):**
- IED como segundo outcome (BCRD `inversion_ext_sector_6.xls`).
- `skills_index` desde Censo 2022 (REDATAM).
- `ease_of_business` (no tiene fuente sectorial; queda rúbrica/proxy).
- Exportaciones como outcome (solo 4 sectores transables).
- Tarifas SIE (PDF escaneado, requiere OCR).

---

## 2. Arquitectura — archivos a crear/tocar

```
shared/data/
  tss_client.py            [NUEVO]  conector boletines TSS (live+fixture), patrón BCRDSectorsClient
  sector_crosswalk.py      [NUEVO]  crosswalk declarado CIIU/TSS → 17 slugs (single source of truth)
  fixtures/
    tss_employment.json    [NUEVO]  panel histórico comprometido (point-in-time, reproducible)
  tests/
    test_tss_client.py     [NUEVO]
    test_sector_crosswalk.py [NUEVO]

modules/sector_intel/
  sectors_sync.py          [EDITAR] + tss_empleo_sync()  (espejo de bcrd_sectores_sync)
  service.py               [EDITAR] sacar operating_cost+labor_availability de IAI_RUBRIC_VARS → live
  operations.py            [EDITAR] registrar tss-empleo-sync y sector-gate-e
  api/router.py            [EDITAR] GET /validation
  validation/              [NUEVO PAQUETE]
    __init__.py
    historical.py          panel IAI_T por (sector, período) — reusa el scorer puro
    outcomes.py            Δempleo_{T+1} por (sector, año); drop sin lookahead; nunca fabricar
    report.py              IC Spearman pooled + por año + spread por quintil + n
  tests/
    test_validation.py     [NUEVO]
    test_tss_empleo_sync.py [NUEVO]
    test_assemble_iai.py   [EDITAR] cubrir las 2 vars nuevas live
```

Sin nuevas tablas: `formal_employment`, `operating_cost`, `labor_availability` son
filas nuevas en `si_variables` (columna `variable`). El reporte Gate E se persiste
como `AppSetting` (patrón WGI), no tabla nueva → **0 migraciones Alembic** salvo que
`SectorVariable` necesite un índice (no lo necesita).

---

## 3. Fase 1 — Conector TSS + crosswalk

### 3.1 `shared/data/sector_crosswalk.py` (primero, es la base)

Tabla declarada CIIU/TSS → slug, con tipo de mapeo y nota. Es la fuente de verdad del
crosswalk para TODAS las fuentes laborales (TSS, ENCFT, Censo). Estructura:

```python
# (slug_destino, etiqueta_origen_normalizada, tipo, nota)
# tipo ∈ {"direct", "crosswalk", "proxy"} — para el badge de procedencia.
CIIU_TO_SLUG: list[CrosswalkRow] = [
    ("agropecuario", "agricultura y ganaderia", "direct", None),
    ("mineria", "explotacion de minas y canteras", "direct", None),
    ("manufactura_local", "industrias manufactureras", "crosswalk",
        "TSS no separa zonas francas; restar empleo_ZF (CNZFE) en fase posterior"),
    ("construccion", "construccion", "direct", None),
    ("energia", "electricidad gas y agua", "direct", None),
    ("comercio", "comercio al por mayor y menor", "direct", None),
    ("turismo", "hoteles bares y restaurantes", "direct", None),
    ("transporte", "transporte y almacenamiento", "direct", None),
    ("comunicaciones", "informacion y comunicaciones", "direct", None),
    ("financiero", "intermediacion financiera y seguros", "direct", None),
    ("inmobiliario", "actividades inmobiliarias", "proxy",
        "puede venir agrupado en 'otros servicios' en TSS; declarar"),
    ("ensenanza", "ensenanza", "direct", None),
    ("salud", "salud y asistencia social", "direct", None),
    ("administracion_publica", "administracion publica y defensa", "direct", None),
    ("servicios_profesionales", "actividades profesionales cientificas y tecnicas",
        "proxy", "puede venir en 'otros servicios'; declarar"),
    ("otros_servicios", "otras actividades de servicios", "direct", None),
    # zonas_francas: SIN fuente directa en TSS → queda fuera de cobertura TSS;
    #   se resuelve con CNZFE en fase posterior. NO imputar.
]
```

Normaliza las etiquetas con la **misma** función `_norm` de `bcrd_sectors.py` (acentos/case/espacios)
— extraerla a `shared/data/_text.py` para no duplicar (causa raíz, no copiar-pegar).
Expón `map_label(raw_label) -> tuple[slug|None, tipo, nota]` y
`coverage() -> dict` (cuántos de los 17 cubre el crosswalk, qué tipo). **`zonas_francas`
debe quedar `None` deliberadamente** y un test lo afirma.

> ⚠️ Las etiquetas exactas de la TSS hay que verificarlas contra un boletín real
> (ver 3.2). Esta tabla es el punto de partida; ajústala a la nomenclatura literal
> que imprima el PDF. Lección 2026-06-07 (verificar el VALOR real del campo, no asumirlo).

### 3.2 `shared/data/tss_client.py`

Patrón **idéntico** a `bcrd_sectors.py`: subclase de `FixtureBackedClient`, funciones
puras `parse_*`/`build_*_records`, modos live/fixture, guardas fail-closed.

```python
class TSSEmpleoClient(FixtureBackedClient):
    source = "TSS"
    license = "datos públicos TSS/SDSS — uso con cita"
    license_ok = True
    fixture_file = "tss_employment.json"
    live_phase = "Fase 4 (Eje 3 · empleo formal)"
```

**Live path (la pieza ETL real):**
1. Descubrir los boletines trimestrales en `tss.gob.do/transparencia/` (la página de
   PDFs no resolvió por fetch simple en la investigación — el `_fetch_live` debe
   enumerar los enlaces PDF, no asumir un patrón de URL fijo). Reusar
   `shared/data/bcrd_excel/download.py` si sirve para HTTP+cache; si no, `httpx`.
2. Extraer del PDF la tabla "cotizantes/empleos por actividad económica" y el
   "salario promedio cotizable por actividad". Usar extracción AI-native de tabla
   (lección §0.3: no cientos de parsers a mano — un extractor que infiere la tabla),
   p. ej. `pdfplumber` para tablas + verificación. **No** OCR (el boletín TSS es
   texto, no escaneado, a diferencia del pliego SIE).
3. Mapear cada rama vía `sector_crosswalk.map_label`. Rama sin slug → se registra en
   `errors[]` con disclosure, **no** se fuerza.
4. Emitir `Record` por (slug, período, variable):
   - `formal_employment` (conteo de cotizantes) — para el outcome y `labor_availability`.
   - `operating_cost` (salario promedio cotizable RD$) — nivel; el index engine lo
     **invierte** y normaliza (la var ya está declarada "invertida" en el spec).
   - `labor_availability` = `formal_employment` normalizado (o su share); decisión de
     scoring, documentar en doctrina.
   `Record(series=var, period="YYYY-Qn", value=..., lineage=Lineage(source="TSS", ...),
   unit=..., dimension=slug)`.

**Guardas fail-closed (lecciones 2026-06-16):**
- Si el crosswalk deja >N ramas sin mapear (cambio de nomenclatura TSS) → `raise TSSEmpleoError`,
  no persistir un panel parcial silencioso.
- **Verificar contra magnitud real conocida** (lección 2026-06-16, anti-bloques-apilados):
  el total de cotizantes sumado debe acercarse al total nacional publicado por la TSS
  (~2.3-2.5 MM 2025). Si Σ ramas se desvía >tolerancia del total del boletín → raise.
- Revisión por morosidad: la TSS revisa al alza los trimestres recientes. El conector
  marca `published_at` (Last-Modified) y el outcome usa solo trimestres **consolidados**
  (rezago ≥1 trim) para evitar look-ahead.

**Fixture (`fixtures/tss_employment.json`):** panel histórico comprometido, shape
`{"<slug>": {"<variable>": {"<período>": value}}}` (igual que `bcrd_sectors.json`). Es
el panel **point-in-time reproducible** que lee el Gate E (espejo de `comtrade_panel.json`).

---

## 4. Fase 2 — Wiring de variables reales en el IAI

En `modules/sector_intel/service.py`:

```python
# ANTES
IAI_RUBRIC_VARS = ("ease_of_business", "operating_cost", "labor_availability",
                   "skills_index", "regulatory_quality", "regulatory_volatility")
SECTOR_LIVE_VARS = ("sector_size", "sector_growth")

# DESPUÉS
IAI_RUBRIC_VARS = ("ease_of_business", "skills_index",
                   "regulatory_quality", "regulatory_volatility")
SECTOR_LIVE_VARS = ("sector_size", "sector_growth",
                    "operating_cost", "labor_availability")   # ahora reales desde si_variables
```

`assemble_iai_dataset` ya itera `SECTOR_LIVE_VARS` leyendo `si_variables` y solo
sobreescribe la rúbrica si el valor no es `None` (líneas 279-284). Mantiene el patrón:
**sector con dato TSS → live; sector sin dato (p. ej. zonas_francas) → rúbrica declarada,
`smap[var]="rubric"`**. Esto preserva "dato faltante = rúbrica declarada, nunca fabricado"
y mantiene honesto el badge. No reescribir el loop — solo mover las dos vars de tupla.

`regulatory_quality` ya sale de `IAI_RUBRIC_VARS` por el override WGI (líneas 276-278);
déjalo igual.

Actualizar `test_assemble_iai.py`: afirmar que con dato TSS sembrado,
`sources[slug]["operating_cost"] == "live"` y que un sector sin dato (zonas_francas)
queda `"rubric"`.

---

## 5. Fase 3 — Harness Gate E (`modules/sector_intel/validation/`)

Espejo de `modules/trade_intel/validation/`. Tres módulos puros (unit-testables sin DB
donde se pueda):

### 5.1 `historical.py`
```python
def build_iai_panel(db) -> list[dict]:
    """Una fila por (sector, período): {sector, period, iai_score, band}.
    Lee SectorScore persistido por backfill_sector_scores (ya point-in-time:
    sector dim real por período, rúbrica declarada en el resto). NO recomputa con
    dato futuro."""
```
Nota point-in-time: el IAI histórico ya usa rúbrica plana en las dims no-sourced y
dato real en la dim sector + (ahora) empleo/costo TSS del período. Es consistente.
Declarar en docstring que `macro_exposure` histórico es neutral (no hay contrato por
año pasado) — ya documentado en `service.py`.

### 5.2 `outcomes.py`
```python
EMP_GROWTH_MIN_OBS = ...   # umbral de cobertura por año
def employment_growth(tss_panel, sector, year) -> float | None:
    """Δ% empleo formal del sector de T a T+1 (consolidado). None si no hay lookahead."""
def label_panel_employment(panel, tss_panel) -> list[dict]:
    """Adjunta outcome continuo Δempleo_{T+1} por fila; descarta filas sin lookahead.
    Marca sectores fuera de cobertura TSS (p. ej. zonas_francas) como out_of_validation."""
```
Circularidad: el IAI ahora contiene `labor_availability_T` (empleo nivel T). El outcome
es **crecimiento T→T+1** (cambio, no nivel) — no es trivialmente circular, pero
**documentar el riesgo de inercia serial** y reportar también el IC controlando por
`sector_growth_T` (parcial), como honestidad metodológica.

### 5.3 `report.py`
```python
def gate_e_report(db) -> dict:
    """IC de rango (Spearman) IAI_T vs Δempleo_{T+1}:
       - pooled (todas las obs), - por año, - spread quintil sup vs inf,
       - n obs, n años, sectores cubiertos, test de signo.
    Devuelve dict explicable; nada de caja negra. Honesto si n es chico o IC ~0."""
```
Usar `scipy.stats.spearmanr` (ya en requirements? si no, implementar rango+Pearson a
mano — es trivial y evita dependencia; preferir esto, lección impacto-mínimo). Reportar
IC con su p-valor y n. **Si el IC no es significativo, decirlo** — un Gate E que falla
honesto es resultado válido, no se maquilla.

---

## 6. Fase 4 — Operación, API, badge

### 6.1 `sectors_sync.py` — `tss_empleo_sync(db, set_phase)`
Espejo exacto de `bcrd_sectores_sync` (líneas 59-115): `client = TSSEmpleoClient(mode="live")`,
`records = client.fetch()`, upsert idempotente a `SectorVariable` por
`(sector_code, period, variable)`, best-effort (no crashea la op, reporta `errors[]`).

### 6.2 `operations.py` — registrar dos operaciones
```python
register_operation(Operation(
    "tss-empleo-sync", "Sincronizar empleo formal (TSS · por sector)",
    "Extrae empleo formal cotizante y salario promedio por actividad económica de "
    "los boletines de la TSS, los mapea a los ~17 sectores (crosswalk declarado) y "
    "los persiste para el IAI (labor_availability, operating_cost) y el Gate E.",
    _run_tss_empleo_sync, default_interval_hours=2160))   # trimestral
register_operation(Operation(
    "sector-gate-e", "Backtest sectorial (Gate E · empleo formal)",
    "Valida que el IAI en T predice el crecimiento del empleo formal en T+1 por "
    "sector (IC de rango). Persiste el reporte y lo expone en Metodología.",
    _run_sector_gate_e, default_interval_hours=0))   # on-demand
```
`sector-gate-e` debe correr **después** de `tss-empleo-sync` + `sector-snapshot`
(dependencia de orden; documentar, igual que WGI "corre antes del backfill").

### 6.3 `api/router.py` — `GET /api/v1/sector-intel/validation`
Devuelve `gate_e_report(db)` (o el `AppSetting` persistido). Strings UI en español.
El frontend lo muestra en *Metodología → Validación* (badge: IC, n, sectores cubiertos,
y la lista honesta de sectores `out_of_validation`).

---

## 7. Tests + Sensores (Verify Done)

**Sensores a correr antes de cerrar (reporta output):**
```bash
ruff check modules/sector_intel shared/data
pytest shared/data/tests/test_tss_client.py shared/data/tests/test_sector_crosswalk.py -v
pytest modules/sector_intel/tests/ -v
pytest --cov=modules/sector_intel --cov=shared/data --cov-report=term-missing \
       modules/sector_intel shared/data    # ≥80% en scoring/validation
```

**Tests obligatorios:**
- `test_sector_crosswalk.py`: cobertura esperada de los 17; `zonas_francas` → `None`
  (afirmado); normalización tolerante a acentos/case (caso "Enseñanza" vs "ensenanza").
- `test_tss_client.py`: parseo de una tabla fixture → Records correctos; **guarda
  fail-closed** (Σ ramas desviada del total → raise); ramas sin mapear → `errors[]`,
  no fabrica; modo fixture reproducible.
- `test_assemble_iai.py`: las 2 vars nuevas son `"live"` con dato; `"rubric"` sin dato.
- `test_validation.py`: panel + outcome con lookahead conocido → IC esperado; filas
  sin lookahead se descartan; out_of_validation marcado; IC ~0 reportado honesto (no crash).
- `test_tss_empleo_sync.py`: upsert idempotente (correr 2× no duplica); best-effort
  (upstream falla → `errors[]`, no raise).

**Verificación contra realidad (no solo invariantes):** un test/manual que corra el
conector live contra UN boletín real y afirme que el total sumado ≈ total nacional TSS
publicado (lección 2026-06-16: un Σ=100% no prueba que los niveles lo sean).

**Reviewer Subagent** (regla de proceso): antes de marcar completo, despacha un revisor
fresco con el diff + este plan + `CLAUDE.md` + `tasks/lessons.md`; que verifique
fail-closed, idempotencia, no-fabricación, point-in-time del outcome, y strings en español.

---

## 8. Riesgos y fallbacks (honestidad de incertidumbre)

| Riesgo | Probabilidad | Mitigación / fallback |
|---|---|---|
| Boletines TSS por rama no tienen serie histórica larga (solo snapshots recientes) | media | **Fallback: ENCFT cuadros** (BCRD, descargables) para el outcome de empleo; cubre ~9 sectores con su propia agregación. El conector se diseña con interfaz común para intercambiar fuente. |
| Nomenclatura TSS difiere de la tabla del crosswalk | alta | Verificar contra boletín real ANTES de fijar la tabla (3.1); el crosswalk es editable y testeado. |
| `zonas_francas` sin dato TSS deprime su cobertura | cierta | Declarado out_of_validation; se resuelve con CNZFE en fase posterior. No imputar. |
| n del panel chico (~80 obs) → IC ruidoso | media | Reportar IC con n y p-valor; enmarcar como validación **direccional**, no confirmatoria. Sumar IED como 2º outcome sube la evidencia. |
| Revisión por morosidad TSS → look-ahead | media | Outcome usa solo trimestres consolidados (rezago ≥1 trim); `published_at` registrado. |
| `pdfplumber`/extracción de tabla no en requirements | baja | Añadir a `requirements.txt`; preferir librería ya presente si la hay. |

---

## 9. Secuencia de PRs (impacto mínimo, revisable)

1. **PR-1** `sector_crosswalk.py` + `_text.py` (extraer `_norm`) + tests. Sin efectos en runtime.
2. **PR-2** `tss_client.py` + fixture + tests (modo fixture; live detrás de flag).
3. **PR-3** `tss_empleo_sync` + operación `tss-empleo-sync` + verificación live contra boletín real.
4. **PR-4** wiring `service.py` (2 vars a live) + `test_assemble_iai`. Aquí el IAI ya discrimina.
5. **PR-5** `validation/` + `sector-gate-e` + `GET /validation` + badge UI.

Cada PR cierra con sus sensores en verde y un reviewer subagent. No desplegar a `main`
mientras corre un sync largo (lección 2026-06-07 jobs/restart).

---

## 10. Criterio de aceptación (Definition of Done)

- `tss-empleo-sync` puebla `si_variables` con `formal_employment`/`operating_cost`/
  `labor_availability` para ≥12 sectores, idempotente, con `published_at` y `license`.
- El badge real-vs-rúbrica muestra `operating_cost` y `labor_availability` como **live**
  en los sectores cubiertos (antes 100% rúbrica).
- `GET /api/v1/sector-intel/validation` devuelve un reporte Gate E con IC pooled, IC por
  año, spread por quintil, n, sectores cubiertos y lista `out_of_validation`.
- Σ ramas verificado contra total nacional TSS real (no solo invariante interno).
- Sensores en verde; cobertura ≥80% en `validation/` y `scoring/`; reviewer subagent sin críticos.
- `tasks/lessons.md` actualizado si hubo corrección; `tasks/todo.md` anota las fases
  fuera de alcance (IED, skills, ease_of_business).

---

## 11. Reglas del repo a no violar (resumen de `tasks/lessons.md`)

- Dato faltante = `None`/rúbrica declarada, **nunca interpolar ni fabricar**; el índice repondera.
- Guardas de integridad **fail-closed (raise)**, no warnings (jerarquías, sumas de partición).
- Verificar el **valor real** de un campo de fuente externa antes de mapear, no asumirlo.
- Verificar derivados contra una **magnitud del mundo real conocida**, no solo invariantes.
- Upserts **idempotentes** por clave única; nada de fixture/seed remanente en la DB.
- `period` ordenado por `_period_key` (no lexical); el anual `YYYY` gana al trimestral.
- Identificadores Python en inglés; strings UI/errores en español.
- "No se puede / N/D" debe ganar su barra de evidencia (§0.2 anti-falsa-imposibilidad).
