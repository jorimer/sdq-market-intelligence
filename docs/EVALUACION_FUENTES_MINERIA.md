# Evaluación de fuentes para MINERÍA — BCRD `pib_origen` y MEM Boletín Trimestral

**Estado: investigación de fuentes (Fase de propuesta → evaluación del flujo de Inteligencia
de Fuentes). NO se escribió código de integración ni se tocó el Data Registry. El gate humano
—la decisión de qué se integra primero— es del dueño.**

Evidencia recogida el 2026-07-15 contra los archivos reales del BCRD y del MEM (descargados y
extraídos, no solo navegados). Las cifras y estructuras de abajo son verificadas.

---

## 0. BLUF — recomendación de secuencia

| # | Fuente | Veredicto | Esfuerzo | Acción recomendada |
|---|---|---|---|---|
| **1** | **BCRD `pib_origen_2018.xlsx`** | El **dato** de minería YA está en la plataforma (leaf del conector), pero **el motor de research NO tiene eje de minería** | **Bajo-medio** (registrar el eje, no crear un conector) | **Integrar primero.** El trabajo real NO es un pull nuevo — es **promover minería de leaf-crudo a eje de primera clase** del motor (igual que se hizo con turismo/construcción/energía). Ver §1.5 |
| **2** | **MEM Boletín Estadístico Trimestral** | **DESCARTAR para minería** | n/a | **No integrar.** El boletín es Electricidad + Hidrocarburos; no contiene NINGUNA serie minera (producción/exportaciones/regalías/empleo) |
| — | Detalle físico de minería (oro/ferroníquel, exportaciones) | Fuera de estos dos candidatos | Medio-alto | Pointer para después: BCRD sector externo (exportaciones por producto) + reportes de Barrick Pueblo Viejo. Ver §4 |

**Síntesis:** la brecha de minería NO se cierra buscando una fuente nueva del MEM (callejón sin
salida verificado). Tampoco es exactamente "conectar `pib_origen`" — **ese dato ya está en la
plataforma**. Se cierra **registrando un eje de minería en el motor de research** que lea el dato de
minería que el conector `bcrd_sectors` ya extrae. Es un cambio de cableado en el motor, no un
conector nuevo. Ver §1.5 para la distinción exacta dato-vs-eje.

---

## 1. Candidato A — BCRD `pib_origen` (PIB por sectores de origen)

### 1.1 El conector YA EXISTE — minería ya es un sector-hoja cableado

Contrario a la premisa de "candidato pendiente para todas las brechas", el pull de `pib_origen`
**ya está en producción**. Vive en [`shared/data/bcrd_sectors.py`](../shared/data/bcrd_sectors.py)
y minería es una de las 17 actividades-hoja explícitamente cableadas:

```python
# shared/data/bcrd_sectors.py:69
("mineria", "Explotación de Minas y Canteras", "Minería y Canteras"),
```

El conector descarga dos archivos del CDN público del BCRD:

- `pib_origen_2018.xlsx` — serie vigente base 2018, trimestral (`PIB_ORIGEN_URL`, línea 44).
- `pib_origen_retro_2018_2007.xlsx` — retropolado oficial 2007→hoy, para historia (línea 57).

Está **consumido en vivo por tres módulos** (no es código muerto):
`modules/sector_intel/service.py`, `modules/construction_intel/service.py`,
`modules/macro_monitor/macro_context.py`. Es la espina dorsal sectorial del Eje 3.

### 1.2 Estructura real del archivo (verificada sobre el `.xlsx` descargado)

Descargué `pib_origen_2018.xlsx` (180 KB) del CDN y lo inspeccioné. Confirmado:

- **Título interno:** "PRODUCTO INTERNO BRUTO (PIB) — Trimestral 2018-2026".
- **Hojas:** `PIB$_Trim` (nominal, RD$ MM), `PIB$_Trim_Acum`, `PIBK_Trim` (índices de volumen
  encadenados base 2018 = real), `PIBK_Trim_Acum`.
- **Minería como rama propia:** sí — la etiqueta `Explotación de Minas y Canteras` aparece como fila
  independiente en tres representaciones dentro de `PIBK_Trim`:

| Representación | Fila | Unidad | Valor Q1-2026 (E-M 2026) |
|---|---|---|---|
| Índice de volumen encadenado | 14 | base 2018 = 100 | **71.96** |
| Crecimiento real interanual | 51 | % | **+7.71 %** |
| Incidencia en el crecimiento | 88 | puntos porcentuales | +0.111 pp |

- **Periodicidad:** **trimestral** (columnas E-M / A-J / J-S / O-D por año).
- **Último período disponible en la fuente:** **Q1-2026 (E-M 2026)** — el archivo está fresco.
- **Unidad para el "tamaño" del sector:** la hoja nominal `PIB$_Trim` en RD$ MM, de donde el
  conector deriva `sector_size = 100 · nominal_sector / Valor Agregado` (línea 273).

> **Lectura económica honesta:** el índice de volumen de minería en Q1-2026 es **71.96** (base
> 2018 = 100), es decir la producción minera real está **~28 % por debajo de su nivel de 2018**;
> el +7.71 % interanual es rebote sobre base baja, no expansión sobre máximos. Cualquier narrativa
> debe decir esto — no solo el signo del crecimiento.

### 1.3 Qué captura hoy el conector vs. qué deja fuera

El conector emite dos variables por sector: `sector_size` (% del VAB) y `sector_growth`
(crecimiento real interanual). **Pero las anualiza**: `_annual_by_sector` +
`_complete_year_columns` (línea 132) conservan solo los años con los 4 trimestres completos, así
que **el trimestre parcial en curso (Q1-2026) se descarta** de la salida en producción. Hoy, la
minería que ve el motor llega a 2025 (año completo), no a Q1-2026.

Lo que la fuente TRAE pero el conector NO expone hoy:
- La cadencia **trimestral** (la fuente la tiene; el conector la colapsa a anual).
- La **incidencia** (fila 88) — cuánto aportó minería al crecimiento del PIB, no solo su tasa.
- El trimestre más reciente (por el descarte del año parcial).

Lo que la fuente **NO contiene** (y por tanto `pib_origen` nunca cerrará): producción física por
mineral (oro, plata, ferroníquel), exportaciones mineras, regalías/impuestos, empleo minero. Es un
agregado de cuentas nacionales, no un dato físico del sector.

### 1.4 Qué haría falta técnicamente para profundizar (sin implementar)

1. Añadir a `bcrd_sectors.py` una ruta de extracción **trimestral** (paralela a `_annual_by_sector`)
   que conserve los trimestres y el año parcial, rotulando el trimestre parcial como preliminar.
2. Exponer la **incidencia** (fila de "puntos porcentuales") como tercera variable, o derivarla.
3. Decidir el contrato de salida: si el motor de research y los módulos del Eje 3 esperan anual, la
   ruta trimestral sería aditiva (nueva variable/frecuencia), no un reemplazo — cambio de bajo
   riesgo, sin migración de datos.

Estos tres son *enhancements de cadencia* — secundarios. El trabajo **primario** para que el motor
pueda responder sobre minería es otro, y es lo que explica §1.5.

### 1.5 Dato ≠ eje computado — por qué el informe dice "no hay eje de minería" (y tiene razón)

Hay que separar dos capas que se confunden fácil:

- **Capa de dato (existe):** `bcrd_sectors.py` extrae minería como leaf → `sector_size` + `sector_growth`.
  Ese dato alimenta el Eje 3 (`sector_intel`) y módulos como `construction_intel`.
- **Capa de eje del motor de research (NO existe para minería):** cuando le haces una pregunta libre,
  el motor solo convoca los **ejes registrados** en su catálogo
  ([`shared/products/registry.py`](../shared/products/registry.py) `PRODUCT_CATALOG`) + su summarizer
  ([`shared/research/data_pull.py`](../shared/research/data_pull.py) `_AXIS_SUMMARY`) + sus keywords de
  ruteo ([`shared/research/resolve.py`](../shared/research/resolve.py) `AXIS_KEYWORDS`).

**El catálogo tiene 14 ejes** — banking, macro, trade, tourism, free_zones, energy, telecom,
construction, agribusiness, esg, pension, insurance, monetary_policy, economic_structure — **y minería
no es ninguno.** Verificado: la cadena `mineria`/`mining`/`minas` **no aparece en NINGÚN archivo de
`shared/research/`**.

Lo revelador: turismo, construcción, energía y zonas francas salen del **mismo** partition de 17 hojas
de `bcrd_sectors` que minería — pero a ESOS se les registró un eje propio (CatalogEntry + summarizer +
keywords) y a minería no. Minería quedó como dato crudo que fluye a agregados, nunca elevado a eje
consultable.

**¿Y el eje `economic_structure`, que sí lee `bcrd_sectors`?** Solo expone el **principal motor**, el
**principal lastre** y el HHI de concentración (`_structure_summary`, línea 321). Nombra un sector solo
si es el mejor o el peor del período — no enumera los 17 ni entrega minería a pedido. Por eso minería
puede aparecer de refilón (si resulta ser el extremo) pero no es consultable como eje.

**Conclusión:** el informe es honesto y correcto. El gate de honestidad (Parte A, PR #533) se niega a
presentar minería como "inteligencia del sistema" porque, en efecto, **no hay un eje de minería
computado que el motor pueda convocar** — aunque el dato del BCRD exista físicamente en la plataforma.
Las cifras de §1.2 (índice 71.96, +7.71%) son reales, pero las leí YO abriendo el Excel directo; el
motor de research hoy no las alcanza como eje de minería.

### 1.6 Qué haría falta para que el motor SÍ responda sobre minería (sin implementar)

El trabajo primario NO es un conector nuevo (el dato ya está). Es **registrar el eje**, replicando el
patrón de turismo/construcción:

1. **`PRODUCT_CATALOG`** (`shared/products/registry.py`): añadir `CatalogEntry("mineria", "SDQ Mining
   Intelligence", ...)`.
2. **`_AXIS_SUMMARY`** (`shared/research/data_pull.py`): un summarizer de minería (probablemente
   reusando `_make_index_summary` como energía/telecom, o uno propio que exponga tamaño + crecimiento
   + incidencia).
3. **`AXIS_KEYWORDS`** (`shared/research/resolve.py`): keywords de ruteo (`minería`, `minas`, `oro`,
   `ferroníquel`, `Pueblo Viejo`, `Barrick`) para que el router semántico lo resuelva.
4. **Fuente del payload:** cablear el summarizer al dato que `bcrd_sectors` ya produce para la leaf
   `mineria` (o a un `mining_intel` mínimo si se quiere un módulo propio, como construcción).

Riesgo bajo, sin migración de datos, sin fuente externa nueva. La cadencia trimestral (§1.4) es un
extra opcional encima de esto.

---

## 2. Candidato B — MEM, Boletín Estadístico Trimestral

### 2.1 Hallazgo: el boletín NO trae minería

Localicé y descargué el boletín más reciente y verifiqué su contenido por extracción de texto (no
por el resumen de un buscador, que resultó engañoso — ver §2.3).

- **Enlace directo (más reciente):**
  `https://mem.gob.do/wp-content/uploads/2026/06/Boletin-Trimestre-Enero-Marzo-2026.pdf`
  ("Boletín Trimestre Enero–Marzo 2026", T1-2026, 20 páginas, 706 KB).
- **Índice real del boletín** (extraído del PDF):
  - **Electricidad** (págs. 6-11): generación neta por fuente, por tipo, renovable/no renovable,
    solar, y por provincia (en GWh).
  - **Hidrocarburos** (págs. 14-17): importación en el trimestre (US$ y %), por país de origen,
    precio FOB.
  - Fuentes/Metodología (18), Contacto (19).

**No existe una sección de Minería.** Ni producción por mineral, ni exportaciones, ni regalías, ni
empleo minero. El boletín es un producto de las direcciones de **Electricidad e Hidrocarburos** del
MEM, no de la Dirección de Minería.

### 2.2 Formato (por si se reconsiderara para electricidad/hidrocarburos)

- El boletín T1-2026 (producer "Pdftools SDK") extrae texto (~2.4k caracteres/página) pero con
  artefactos de glyph-id en los títulos (fuentes subseteadas) — las **tablas por provincia sí salen
  con cifras** (p.ej. "PUERTO PLATA 69.28 GWh").
- El boletín T2-2025 es un PDF **diseñado en Adobe Illustrator 29.7** — infografía; ahí las tablas
  tienden a ser gráficos vectoriales, menos extraíbles. El formato NO es estable entre trimestres.
- En ningún caso hay Excel/CSV ni API: es PDF de diseño. Extracción frágil aunque se quisiera.

### 2.3 Corrección de una pista falsa

Un resultado de búsqueda afirmaba que el boletín "incluye exportaciones trimestrales de oro y plata".
**Es falso, verificado.** Todos los hits de "plata" en el PDF son topónimos — **Puerto Plata** y
**Monte Plata** (provincias) — y las cifras adyacentes son GWh de generación eléctrica por provincia.
"Mineral" aparece en contexto de combustible térmico. No confundir el resumen del buscador con el
contenido real.

### 2.4 Veredicto B

**Descartar el Boletín Estadístico Trimestral del MEM como fuente de minería.** No aporta ninguna
serie del sector. (Sigue siendo un candidato válido si algún día se quiere un producto de
**electricidad** o **hidrocarburos**, pero eso es otra brecha.)

---

## 3. Verificación de los excluidos (C) — ¿cambió algo?

| Fuente | Estado previo (tu evaluación) | Verificación 2026-07-15 |
|---|---|---|
| `tablero-estadistico-minero/` | Power BI embebido, sin API ni descarga | **Sin cambios.** El HTML estático no expone botón de descarga ni endpoint; el dashboard carga por iframe/JS. No apto para pull automatizado. |
| `category/sector-electrico/` | Subsector eléctrico, no minería | **Confirmado.** El propio Boletín Trimestral (§2) es la evidencia: su contenido es 100 % electricidad + hidrocarburos. |
| `descargas-2/industria-extractiva/` | Solo informes de calidad de agua | No re-evaluado a fondo (tu premisa se mantiene); nada indica que haya cambiado. |

Ninguno cambió de estado. No hay acción sobre C.

---

## 4. Pointer — dónde vive de verdad el detalle físico de minería

Fuera del alcance de los dos candidatos que pediste evaluar, pero necesario para no dejar la
impresión de que "no hay data de minería en RD". Si más adelante se quiere un producto de minería
con producción/exportaciones (oro, ferroníquel), las fuentes reales son:

- **BCRD sector externo** — exportaciones por producto (incluye oro y ferroníquel en US$). Es la vía
  más limpia y probablemente ya parcialmente al alcance del conector BCRD existente.
- **Reportes de Barrick Pueblo Viejo** (mina dominante) — producción de onzas, guidance. Dato de
  empresa, no de gobierno; extracción manual/PDF.
- **DGA/DGII** — exportaciones y recaudación, para regalías.

Estas NO se evaluaron en detalle aquí (tu encargo fue A y B). Quedan como propuestas separadas para
el tablero de Inteligencia de Fuentes si el dueño quiere ir más allá de la contribución al PIB.

---

## 5. Resumen de decisión para el dueño

1. **Integrar A primero — pero el trabajo real es registrar el EJE, no un conector.** El dato de
   minería ya está en la plataforma (`bcrd_sectors`); lo que falta es promoverlo a eje de primera
   clase del motor de research (CatalogEntry + summarizer + keywords), como turismo/construcción/
   energía. Ver §1.5-§1.6. Bajo riesgo, sin fuente externa nueva, sin migración. La cadencia
   trimestral (§1.4) es un extra opcional encima.
2. **No integrar B** (MEM Boletín): verificado que no contiene minería.
3. **Diferir el detalle físico** (§4) a una propuesta aparte si se quiere un producto de minería más
   profundo que "aporte al PIB".

El código no se tocó. La decisión de secuencia y de si se abre §4 es del dueño.

---

## 6. Hallazgo colateral — `agribusiness` está registrado a medias (BUG en prod)

Al cruzar los 14 ejes del motor contra sus tres registros (CatalogEntry + summarizer + keywords)
apareció que **`agribusiness` es el único eje incompleto**: tiene `CatalogEntry`
(`shared/products/registry.py`) y summarizer (`_AXIS_SUMMARY`, `shared/research/data_pull.py`) pero
**le faltan las keywords de ruteo en `AXIS_KEYWORDS`** (`shared/research/resolve.py`). Los otros 13
ejes tienen los tres.

**Verificado en prod (2026-07-15), control simétrico:**

| Pregunta (misma forma) | gate | coverage | anchored | sources |
|---|---|---|---|---|
| "¿Qué situación tiene el sector **agropecuario** en RD?" | scoping | 0.0 | 0.0 | `[]` |
| "¿Qué situación tiene el sector **turismo** en RD?" (control) | report | 1.0 | 1.0 | BCRD turismo · ASONAHORES · MITUR |

La única diferencia estructural entre ambos ejes es que turismo tiene keywords y agropecuario no.
Resultado: una pregunta directa de agro **cae a scoping con cobertura 0** aunque el eje agribusiness
(IAI real) exista. Es exactamente el modo de falla que el propio código documenta para `insurance`
(`resolve.py:45-47`: "el eje primario no se detectaba y el gate caía a scoping"). Una pregunta
enmarcada en "crecimiento" sí da informe, pero vía `economic_structure`, no vía el eje agribusiness.

**Fix (bajo, aislado):** añadir a `AXIS_KEYWORDS` una entrada
`"agribusiness": ("agropecuario", "agroindustria", "agricola", "agro", "iai", ...)`. Una línea de
diccionario; sin datos ni fuentes nuevas. Debería ir con test de no-regresión (pregunta de agro →
gate report), igual que el fix de `insurance` del piloto.
