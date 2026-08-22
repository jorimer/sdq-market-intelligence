# Estándar de Reporte SDQ·MIP — Market Intelligence Report (MIR)

> **Fuente de verdad** del contenido, formato, secciones y tono de TODO reporte de
> SDQ Market Intelligence — online (vista in-app), PDF y Word. Aplica a los 12 productos
> del catálogo y a todo lo que se construya en adelante. Referencias de calidad: reporte
> Accenture/Aspen "Global Opportunity Youth Network — Market Intelligence Report" y la guía
> de DataGreat sobre market intelligence reports. Decisión del dueño (2026-06-29): estándar
> completo (anatomía + DNA visual rico) con salida **PDF + Word + online**.

## 0. Por qué un estándar
Un MIR de clase mundial **investiga**, no resume: integra fuentes diversas en una narrativa
única orientada a una decisión. Nuestra ventaja estructural sobre el gold standard típico es
que ya rastreamos lo que otros fingen — **procedencia (lineage), cobertura honesta, fuentes
con fecha/licencia, versión de modelo, estado de validación** — así que las secciones más
respetadas y peor ejecutadas del mercado (Metodología, Fuentes, Limitaciones) las generamos
**automáticamente y con honestidad**.

## 1. Principios rectores
1. **Investigativo, no descriptivo.** El reporte CONCLUYE; explica el "y por tanto", no
   reexpone cifras.
2. **Anclado a evidencia real.** Toda afirmación cuantitativa sale del dato persistido; nada
   se inventa. Lo que no hay, se declara (no se rellena).
3. **Orientado a decisión.** Cada nivel cierra en una lectura accionable para su audiencia.
4. **Honesto con la procedencia.** Distingue dato real · rúbrica declarada · brecha. La
   cobertura y las limitaciones son explícitas — es un sello de calidad, no una disculpa.
5. **AI-native.** La narrativa la genera el Cerebro (system prompt por eje + frame por
   audiencia); Metodología/Fuentes/Limitaciones se derivan de la procedencia, no se redactan
   a mano.
6. **Excelencia sobre facilidad** ([[best-vs-easiest-before-closing]]): el reporte es la cara
   del producto; se construye al estándar, no al atajo.

## 2. Anatomía canónica
Una sola anatomía, escalada por tier (§3). Cada sección declara propósito, contenido, reglas
y **de dónde sale el dato** (para auto-generación).

| # | Sección | Propósito | Fuente del dato |
|---|---|---|---|
| 1 | **Portada** | Identidad + qué/quién/cuándo + veredicto headline | producto + tier |
| 2 | **Índice** (Deep) | Navegación | secciones presentes |
| 3 | **Resumen ejecutivo** | El VEREDICTO: tesis + cifra clave + lectura | narrativa Cerebro + score |
| 4 | **Contexto / panorama** | Encuadre del sector/mercado; "por qué importa" | ai_context + macro contrato |
| 5 | **Hallazgos y análisis** | El cuerpo: dimensiones, drivers/lastres, posición | snapshot + cifras_derivadas |
| 6 | **Recomendaciones** | Accionable, **priorizada** (Inmediato/Corto/Mediano) por audiencia | narrativa Cerebro (frame) |
| 7 | **Metodología y fuentes** | Cómo se mide, qué fuentes, cadencia, cobertura, versión | data_signals + lineage + validation_state |
| 8 | **Limitaciones y calidad de dato** | Cobertura honesta, brechas, sin-backtest | validation_state + coverage + doctrina del eje |
| 9 | **Glosario** (Deep) | Términos e índice | metodología del eje |
| 10 | **Fuentes / Referencias** | Citas con procedencia (fuente · licencia · fecha · URL) | lineage |

### Reglas por sección
- **Portada:** marca SDQ·MIP (símbolo Arco, tinta + acento), título del producto, sector/entidad,
  período, **banda/score headline** (p.ej. "ITT 93.0 · Fuerte"), fecha de generación,
  watermark por tier ("Vista abierta", "Suscripción", "On-demand"; muestra → "MUESTRA").
- **Resumen ejecutivo:** abre con un **pull-quote** de la cifra/insight clave (barra de
  acento). 1 frase de tesis + 3-5 hallazgos + cierre de lectura. En Pulse, ES el reporte.
  Regla de oro: que se pueda extraer la decisión en 30 segundos.
- **Hallazgos:** cada dimensión del índice con score/peso/aporte (de `cifras_derivadas`),
  drivers vs lastres, posición relativa/ranking cuando aplique. Visual: **callout de cifra**
  grande para el dato dominante, **pull-quote** para el insight, **tabla de dimensiones**,
  **gráficos** (barras de dimensión, línea de tendencia histórica del índice, ranking). No
  recalcular superlativos que no estén en el precompute.
- **Recomendaciones (Deep):** 3-6, **priorizadas** en Inmediato / Corto plazo / Mediano plazo,
  redactadas para la audiencia del nivel (inversionista/gobierno/empresa/multilateral). Cada
  una nombra la palanca y el "y por tanto".
- **Metodología y fuentes:** auto-generada (§7). Declara: qué mide el índice y sus dimensiones
  con pesos; fuentes reales con cadencia y fecha del último dato; **cobertura** (% del índice
  con dato real vs rúbrica vs brecha); versión del modelo; estado de validación (backtest sí/no).
- **Limitaciones:** auto + doctrina del eje. Nombra explícitamente brechas, supuestos de
  rúbrica, ausencia de backtest, agregación (nacional/anual), y lo que NO cubre.
- **Fuentes/Referencias:** lista con superíndice en el cuerpo → fuente · licencia · fecha de
  consulta · URL (de `lineage`). Toda cifra material citable.

## 3. Mapa por tier
| Sección | Pulse (abierto) | Insight (suscripción) | Deep Dive (on-demand) |
|---|:--:|:--:|:--:|
| Portada + banda headline | ✅ | ✅ | ✅ |
| Resumen ejecutivo (veredicto + pull-quote) | ✅ | ✅ | ✅ |
| Contexto / panorama | — | ✅ | ✅ |
| Hallazgos (dimensiones + callouts + gráficos) | — | ✅ | ✅ |
| Recomendaciones priorizadas | — | — | ✅ |
| Metodología y fuentes | mini (1 línea) | ✅ | ✅ |
| Limitaciones / calidad de dato | — | ✅ | ✅ |
| Índice + Glosario + Referencias citadas | — | — | ✅ |
| Extensión orientativa | 1-2 págs | 4-6 págs | 8-15 págs |

## 4. Tono y voz
Lo fija el **Cerebro** (`shared/narrative/cerebro.py`): identidad → doctrina del eje →
estándar epistémico → frame de audiencia. Consultivo-experto, investigativo, decisión-orientado,
SCQA donde aplique. Cifras tabulares. Español (UI), con i18n EN/FR para narrativa. Sin
adjetivos vacíos; cada párrafo mueve la decisión. Honestidad de procedencia siempre visible.

## 5. DNA visual / formato (marca SDQ·MIP)
- **Paleta y tipografía:** la MISMA de la app — dirección «Claro & Vivo», leída de
  `shared/brand/tokens.py` (espejo de `frontend/src/index.css`): tinta `--ink` (`#0A1A3A`),
  acento `--accent` (`#1E6FFF`) para rellenos y `--accent-ink` (`#1551C0`) para texto en
  acento (el acento puro da 4,40:1 sobre blanco y no pasa AA). El navy `#1A365D` y el signal
  red `#E11D48` de la paleta vieja se RETIRARON: el rojo sobrevive solo como `--alert`
  (`#C8392E`) y solo con significado —valor negativo, estampa de muestra—, nunca como
  decoración. Ningún renderizador declara un hex: lo vigila
  `shared/brand/tests/test_paleta_unica.py`. Tipografía: Plus Jakarta Sans
  (display) · Inter (cuerpo) · JetBrains Mono (cifras). Tokens, no hex sueltos.
- **Portada:** banda de marca + título + sujeto + período + banda/score + fecha + watermark.
- **Encabezado corrido** en cada página ("SDQ·MIP — {Producto} · {Sector/Entidad}") + **paginación**.
- **Numeración** de secciones (1, 2, 3…) y subsecciones (X.Y) en Deep Dive.
- **Pull-quote:** texto grande en acento con barra vertical, para la cifra/insight clave.
- **Callout de cifra:** número grande + etiqueta, estilo infografía.
- **Figuras numeradas con leyenda** ("Figura N: …").
- **Tablas:** cabecera navy, filas alternas, cifras `tabular-nums`.
- **Gráficos** (theme-aware, de `var(--c1..c6)`): barras de dimensión, línea de tendencia
  histórica del índice, ranking/posición. SVG propio o Recharts (online) / imagen (PDF/Word).
- **Watermark por tier** + estampa "MUESTRA — DATA ILUSTRATIVA" para muestras.
- **Disclaimer** SDQ Consulting al cierre.

## 6. Tipos de reporte (mapeo DataGreat → nuestros productos)
- **Geographic / Sector market** → la mayoría (free_zones, tourism, energy, telecom, trade,
  construction, agribusiness, esg, pension, economic_structure).
- **Competitive landscape** → banking (entidades), pension (AFP) en niveles nombrados.
- **Market trend / PESTEL** → macro (riesgo-país) y economic_structure (estructura + contribución).
Cada producto declara su tipo; la anatomía es común, el énfasis varía.

## 7. Auto-generación de Metodología, Fuentes y Limitaciones
Backbone AI-native: NO se redactan a mano. Se derivan del contrato `SectorProduct`:
- **Metodología** ← `product_manifest` (dimensiones/pesos) + `data_signals` (cobertura, cadencia,
  frescura, fuentes) + `validation_state` (score, backtest).
- **Fuentes/Referencias** ← `lineage` de cada conector (source, license, url, fetched_at,
  published_at).
- **Limitaciones** ← `validation_state.notes` + cobertura por procedencia + doctrina del eje
  (`cerebro.AXIS_DOCTRINE`).
Un producto sin estos signos honestos no publica (gate de readiness existente).

## 8. Salidas y paridad
- **Online (in-app):** la vista del reporte espeja la anatomía por tier (mismas secciones).
- **PDF:** motor de marca rico (portada, encabezado, pull-quotes, callouts, figuras, tablas,
  gráficos, citas, watermark).
- **Word (.docx):** misma anatomía, editable por el equipo/cliente; estilos de marca.
Las tres salidas se ensamblan desde **una sola estructura de contenido** (`ReportSpec`): el
producto produce el spec una vez; cada renderer (online/PDF/Word) lo pinta.

## 9. Checklist de cumplimiento
- [ ] El Resumen ejecutivo concluye (no describe) y abre con la cifra clave.
- [ ] Toda cifra material está anclada al dato real y, en Deep, citada.
- [ ] Metodología declara fuentes, cadencia, cobertura y versión.
- [ ] Limitaciones nombra brechas/rúbrica/backtest explícitamente.
- [ ] Recomendaciones (Deep) priorizadas y por audiencia.
- [ ] Marca: portada, encabezado corrido, paginación, watermark por tier.
- [ ] Paridad online ↔ PDF ↔ Word en secciones.
- [ ] Sin cifras inventadas; lo ausente se declara.

## 10. Plan de implementación (fases, PRs pequeños, CI verde, verificar en prod)
1. **Standard doc** (este archivo) — fuente de verdad. ✅
2. **`ReportSpec` (modelo de contenido):** estructura tipada de secciones/bloques (exec_summary,
   context, findings, recommendations, methodology, limitations, sources, glossary) que cada
   producto produce desde su snapshot + lineage + narrativas. Backbone único para las 3 salidas.
3. **Auto Metodología/Fuentes/Limitaciones** desde `data_signals`/`lineage`/`validation_state`,
   compartido en `shared/products`.
4. **Motor PDF rico** (portada, encabezado, pull-quotes, callouts, figuras, tablas, gráficos,
   citas, watermark) consumiendo `ReportSpec`.
5. **Motor Word (.docx)** consumiendo el mismo `ReportSpec`.
6. **Paridad online:** la vista in-app del reporte renderiza el `ReportSpec` por tier.
7. **Gráficos:** barras de dimensión + tendencia histórica del índice + ranking.
8. **Rollout** a los 12 productos + verificación en prod por tier.
Cada fase es uno o más PRs verdes, desplegados y verificados en prod.
