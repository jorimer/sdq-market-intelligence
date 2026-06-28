# Plan técnico — (b) Composición de cartera de inversiones de los fondos de pensiones

**Fecha:** 2026-06-28 · **Estado:** propuesta para aprobación (sin construir) · **Workstream:** `pension_intel` (SIPEN)
**Antecede:** (a.1) pulso CKAN live + (a.2) rentabilidad live, ambos en prod y verificados.

> Doctrina aplicada: investigar el dato real antes de construir · dato real sin seed sintético ·
> PRs pequeños con CI verde · "¿la mejor solución o la más fácil?" · módulos independientes (comunicación vía eventos).

---

## 1. Fuente del dato (CONFIRMADA por investigación)

**Boletín Trimestral SIPEN (PDF) → Cuadro 6.1 "Composición de la cartera de inversiones de los fondos de
pensiones por emisor (RD$)".**

- **Descubrimiento:** `https://sipen.gob.do/publicaciones/boletines-trimestrales` → link por
  `aria-label="Descargar documento Boletín Trimestral No. NN - <trimestre>"` (mismo patrón robusto que rentabilidad
  y estados financieros). Último: No.91 = Q1-2026 (`boletines-trimestrales_2026_05_1778598547.pdf`).
- **Legible (no escaneado):** pdfplumber extrae 169K chars de 72 pp. → **descarta OCR**.
- **Ubicación:** Cuadro 6.1 abarca **páginas 31-32** (tabla ancha partida horizontalmente).
- **`extract_tables()` da 0 tablas** (el PDF no tiene líneas de grilla — es texto posicionado).
  → la extracción NO puede asumir grilla.

### Estructura del Cuadro 6.1
- **Filas:** emisor, agrupado por **sub-sector económico** (cada grupo tiene su subtotal):
  - Ministerio de Hacienda — 56.04% / RD$728,220,623,962
  - Banco Central RD — 8.69% / RD$112,896,479,175
  - Bancos Múltiples — 6.77% (itemizados: Reservas, BHD, Popular, Santa Cruz, Promerica, Caribe, Lafise, Vimenca,
    BDI, Banesco, Qik, Scotia, ADEMI, López de Haro)
  - Asociaciones de Ahorros y Préstamos (APAP, Cibao, La Nacional, Bonao)
  - Bancos de Ahorro y Crédito (Caribe, Fondesa, Unión, Motor Crédito)
  - Empresas Privadas — 2.16% (Acero Estrella, César Iglesias, energía: ITABO, Dominican Power, Enadom, Gulfstream,
    Haina, Punta Cana-Macao; minería: Consorcio Minero; Ingeniería Estrella, Alpha Sociedad de Valores…)
- **Columnas:** por fondo — `Subtotal Fondos CCI` (el principal del sistema) + Complementarios (Romana/Alcanza/Prospera)
  en p31; más columnas de fondos + **TOTAL** en p32. Cada fondo trae `Monto` + `Porcentaje`.
- **Total CCI:** RD$1,299,519,710,008.94 (≈ RD$1.3 billones); total sistema ≈ RD$1.4-1.9 billones.
- **Cuadros vecinos (fase posterior, opcionales):** p37 tasa de interés promedio ponderada por instrumento;
  p38 inversiones en US$.

### Decisión de extracción — parser DETERMINÍSTICO posicional (RESUELTA 2026-06-28, la mejor por correctitud)
El texto plano mete **espacios espurios en los montos** ("8 7,956,707,912.06" = 87,956,707,912.06;
"3 2,027,246,695.76" = 32,027,246,695.76) porque pdfplumber separa un dígito por una micro-espacio. Un regex por
línea de texto es frágil (nombres con letras finales "S. A", dígitos partidos). **VERIFICADO con `extract_words`:**
las columnas están right-aligned en X fijos (emisor x1<~200; Monto CCI x1≈287; Pct CCI x≈300-315), así que un parser
posicional por **bandas de X** reconstruye cada monto uniendo las palabras de la banda (el dígito partido se re-une).
- **Elegido: parser determinístico** `parse_cartera_words(words) -> List[Holding]` (puro, offline, testeable con
  fixture real de coords commiteado), con **cuadre del TOTAL** (Σ montos == 1,299,519,710,008.94 ±0.5% → si no, falla
  cerrado, nunca persiste). Mejor que Claude para una tabla regulatoria de layout fijo: exacto, gratis, sin API key en CI.
- (Claude queda como molde de respaldo en `audited_pdf_extractor` si algún boletín cambia de layout radicalmente.)
- **Alcance PR1:** columna **"Subtotal Fondos CCI"** (el portafolio del sistema, ~RD$1.3B = ~90% del total) →
  `fund="cci"`. Las columnas por-fondo complementario (p31) y el gran TOTAL (p32) quedan para PR4.
- **Sub-sector:** lista curada de encabezados de grupo (`Bancos Múltiples`, `Asociaciones de Ahorros y Préstamos`,
  `Bancos de Ahorro y Crédito`, `Empresas Privadas`; Hacienda y BCRD son grupo propio sin hijos). Se trackea el grupo
  actual al recorrer filas; el header lleva `is_subtotal=True`, los hijos heredan su `sub_sector`.

---

## 2. Modelo de datos (nuevo)

`PensionSeries` (series×period×entity_slug) NO encaja: la cartera es `period × emisor × sub_sector × fondo × (monto, pct)`.
Tabla nueva, namespaced en el módulo:

```
PensionHolding(UUIDMixin, Base)               # tabla pension_holdings
  period           String(10)                  # "2026-Q1" (trimestral, del boletín)
  fund             String(40)                   # "cci" | "complementario_romana" | … | "total_sistema"
  sub_sector       String(120)                  # "Ministerio de Hacienda" | "Bancos Múltiples" | "Empresas Privadas" …
  issuer           String(200)                  # emisor tal cual ("Banco de Reservas de la República Dominicana")
  issuer_slug      String(80)                   # clave estable normalizada ("banco_de_reservas")
  amount           Float (nullable)             # RD$ (NULL = no presente, nunca interpolado)
  pct              Float (nullable)             # % del fondo
  is_subtotal      Boolean                      # fila de subtotal de sub-sector (no sumar con sus hijos)
  # cruces (resueltos en ingest, sin acceder a otras tablas — ver §5)
  bank_entity_slug String(40) (nullable)        # mapeo a banking_score, si el emisor es banco supervisado
  macro_class      String(20) (nullable)        # "deuda_publica" (Hacienda) | "bcrd" | None
  # lineaje
  source/published_at/license                   # "SIPEN", boletín No., uso con cita
UniqueConstraint(period, fund, issuer_slug)
Index(period, fund), Index(issuer_slug)
```

Migración Alembic nueva (id encadenado a la última de pension_intel).

---

## 3. Conector + operación

- `shared/data/sipen_client.py`:
  - `boletin_links(html) -> {label: url}` (reusa el patrón aria-label; ya probado).
  - `latest_boletin_url()` (network, best-effort) → PDF más reciente.
  - parser puro `parse_cartera_text(text) -> List[Holding]` (opción B: el prompt a Claude vive en el extractor;
    el parser puro valida/normaliza la salida y cuadra los totales).
- `modules/pension_intel/external/cartera_extractor.py`: reusa `audited_pdf_extractor` (PDF→texto→Claude→JSON)
  + `issuer_slug()` (normalización acento/caso) + validación de cuadre de totales (falla cerrado).
- `modules/pension_intel/cartera_sync.py`:
  - `ingest_cartera(db, content, filename)` — carga manual testeable (molde `ingest_financials`).
  - `sipen_cartera_sync(db)` — live: descubre boletín → extrae Cuadro 6.1 → persiste `pension_holdings`.
- Operación `sipen-cartera-sync` (trimestral, cada 2160h, auto-agendada — molde [[ops-auto-schedule-freshness]]).
- `conftest.py`: stub del fetch a `[]`/fixture para tests offline.

---

## 4. Endpoints (read-only, módulo Pensiones)

- `GET /api/v1/pension-intel/cartera?period=&fund=cci` → composición (sub-sector → emisores, monto, pct).
- `GET /api/v1/pension-intel/cartera/insight` → insight Cerebro (`pension_cartera`, doctrina + 4 audiencias).
- Snapshot extendido (opcional): headline con top concentraciones (Hacienda %, BCRD %, top banco).

## 4b. Frontend (Pensiones)
- Pestaña/sección "Cartera" en `PensionIntelPage`: treemap o barras apiladas por sub-sector + tabla de emisores +
  `AiInsightCard`. i18n ES/EN/FR. Selector de fondo (CCI por defecto) y de período.
- Sección Datos·Pensiones: bloque de carga manual de boletín (molde EF).

---

## 5. Cruces cross-módulo (la joya) — respetando independencia de módulos

**Restricción CLAUDE.md:** un módulo NO importa ni lee tablas de otro; se comunican por `shared.events.event_bus`.
El mapeo emisor→banco/macro se resuelve **dentro de `pension_intel`** con un **crosswalk de datos públicos**
(no leyendo tablas de banca/macro), y el dato se **publica por evento** para que Macro/Banca lo consuman.

### 5.1 Crosswalk (en pension_intel, dato público)
- `issuer_to_bank`: emisor SIPEN → `bank_entity_slug` de banking_score (Reservas, BHD, Popular, Santa Cruz, Promerica,
  Caribe, Lafise, Vimenca, BDI, Banesco, Qik, Scotia, ADEMI, López de Haro, APAP, Cibao, La Nacional…). Tabla de
  mapeo curada y commiteada (molde `sector_crosswalk`). Ojo bug histórico substring [[bonanza-bonao-api-defect]]:
  matching por nombre normalizado exacto, no substring.
- `issuer_to_macro`: Ministerio de Hacienda → `deuda_publica`; Banco Central → `bcrd`.

### DECISIÓN DE CRUCES (resuelta 2026-06-28, tras leer el patrón real del codebase)
El codebase tiene UN patrón canónico para cross-módulo: **productor `publish_X_updated(payload)` → consumidor
con un `Context` singleton (`on_X` cachea el último read) que ENRIQUECE su propia narrativa/outlook**, nunca el
score intrínseco ni persistiendo en otra tabla (precedente: `banking_score` consume `irmp.updated` como overlay de
outlook — `IRMPOutlookContext`; `sector_intel` consume macro/irmp/trade). Para DISPLAY de paneles que componen varios
módulos, el precedente es **leer la API** del módulo dueño (Market Brief / Comparador). Los dos NO compiten: evento =
capa narrativa; API = capa de display. **El dato de cartera VIVE solo en `pension_intel` (single source); NO se
duplica-persiste en tablas de macro/banca.**

- `pension_intel/events.py`: `publish_pension_cartera_updated(payload)` con
  `{period, public_debt_amount, bcrd_amount, system_total, by_bank: {bank_slug: amount}}`. Se emite tras `cartera_sync`.

### 5.2 PR2 — Macro/BCRD (evento → context narrativo)
- `macro_monitor` (o `macro_political_risk`) registra `PensionHoldingsContext` suscrito a `pension.cartera.updated`
  → su insight/narrativa menciona "los fondos de pensiones tienen RD$728B en deuda pública (X% del sistema), mayor
  inversor institucional / demanda de papel del gobierno". **Sin persistir MacroSeries** (enriquecimiento, no dato
  nuevo en macro). Ratio vs deuda pública total solo si el denominador existe; si no, None (honesto).

### 5.3 PR3 — Banca (evento → outlook context, molde IRMP)
- `banking_score` registra un context suscrito a `pension.cartera.updated` (cachea `by_bank`) → enriquece el
  **outlook/narrativa** de cada banco con "exposición de fondos de pensiones RD$X" (fondeo institucional/concentración).
  **Nunca el score intrínseco** — exactamente el precedente del overlay IRMP (`overlay_outlook`).
- Anti-doble-conteo: usar emisores individuales (`is_subtotal=False`), no los subtotales de grupo.

### 5.4 Display opcional
- Si un panel de Macro o Banca quiere RENDERIZAR las tenencias como visual, lee `GET /pension-intel/cartera` (precedente
  Market Brief/Comparador). El dato sigue siendo de `pension_intel`.

---

## 6. Dispositivos de honestidad (anti-alucinación)
- Validación de cuadre: Σ montos por fondo == TOTAL del cuadro (±0.5%) o falla cerrado (no persiste).
- `amount`/`pct` faltantes → NULL, nunca interpolado.
- Emisor sin mapeo a banco/macro → `bank_entity_slug`/`macro_class` NULL (se muestra en "Otros/Privado"), no se fuerza.
- Provenance estampado (boletín No., fecha de corte "Al 31 de marzo de 2026", uso con cita).
- Período trimestral explícito; el boletín va por trimestre (no mezclar con el pulso mensual).

---

## 7. Desglose en PRs (pequeños, CI verde, cada uno verificable en prod)

1. **PR1 — Pensiones (cartera):** modelo `PensionHolding` + migración + extractor AI-native + `cartera_sync` +
   operación + endpoints `/cartera` y `/cartera/insight` + pestaña frontend + i18n + tests (parser/cuadre offline).
   *Verificación prod:* correr `sipen-cartera-sync`, confirmar Hacienda 56% / BCRD 8.69% / total ~RD$1.3B.
2. **PR2 — Macro/BCRD:** evento `PensionCarteraUpdated` + suscripción en `macro_monitor` + serie tenencia deuda
   pública/BCRD + panel/insight.
3. **PR3 — Banca:** exposición pensión→banco por entidad (evento o API) + panel/insight + crosswalk emisor→banco.
4. **(Opcional) PR4:** cuadros vecinos — tasa por instrumento (p37) y/o inversiones en US$ (p38).

---

## 8. Riesgos / abiertos
- **Layout del boletín cambia entre trimestres** → la extracción AI-native + cuadre de totales lo absorbe; si cambia
  radicalmente, falla cerrado (no persiste basura).
- **Mapeo emisor→banco incompleto** (bancos pequeños/no supervisados) → quedan en "Otros", honesto.
- **Histórico:** el boletín da un trimestre por PDF; para serie histórica habría que ingerir varios boletines
  (No.84…No.91 disponibles) — diferible; PR1 arranca con el último corte.
- **Confirmar §5 (evento vs API)** antes de PR2/PR3.
