# SPEC — Perfil SDQ: reemplazo de la notación de calificación por un sistema propio de dos ejes

> v1.3 · 2026-08-07 · Estado: **propuesto — pendiente aprobación de Ricardo antes de implementación.**
> Origen: auditoría del Deep Dive de Banco Popular Dominicano (yuxtaposición SDQ-AA+ vs. panel real
> S&P/Fitch/Moody's) + discusión de diseño con Ricardo Mercado (producto) y su hija Teresa Mercado
> (actuaria) sobre seguros/ISF. v1.1 extiende el rigor de seguros a pensiones y fiduciarias. v1.2
> cierra el naming de las bandas de Ejecución y la regla de N chico (§4.1, §4.2). **v1.3 incorpora el
> review actuarial completo de Teresa sobre seguros (§5) — incluye un bug confirmado en el ISF de
> producción (doble conteo de siniestros, §5.1) que es más urgente que el resto del roadmap de Perfil
> SDQ, y dos correcciones a conclusiones de la v1.2 sobre disponibilidad de datos (reaseguro y
> concentración por ramo, §5.5-§5.6) que resultaron estar mal calificadas — eran brechas de
> extractor, no de fuente.** Todo lo que Teresa señaló se incorpora — Ricardo lo validó explícitamente
> como mejora al producto, no solo al ejercicio de taxonomía.
> Regla Plan First: Claude Code confirma el desglose de implementación y re-verifica el estado actual
> del repo (los conteos de este documento tienen fecha de corte 2026-08-06) antes de tocar código.

---

## 0. Resumen ejecutivo (BLUF)

SDQ reemplaza la notación de calificación estilo agencia (`SDQ-AAA … SDQ-D`, 10 escalones) por un
sistema propietario de **dos ejes — Ejecución y Resiliencia — bajo el nombre "Perfil SDQ"**,
homologado en banca, seguros, pensiones y fiduciarias.

**Problema que resuelve:** la notación actual (a) usa la gramática de una calificadora de riesgo
regulada sin serlo, (b) aplica `SDQ-D` — la etiqueta más grave del vocabulario de agencia — a un
rango de 45 puntos que cubre entidades operando con normalidad, no en default, y (c) ya produjo una
yuxtaposición riesgosa real: el Deep Dive de Banco Popular muestra `SDQ-AA+` junto al panel real de
agencias (`BB`/`BB-`/`Ba3`) para el soberano, dos escalas distintas que un lector puede leer como
contradicción.

**Principio de diseño:** no se recalibra la metodología existente. Se reagrupan las dimensiones ya
ponderadas y calibradas de cada motor de scoring en dos familias — Ejecución (desempeño) y
Resiliencia (exposición al riesgo) — y se renormaliza el peso dentro de cada una. Es una capa de
agregación distinta sobre trabajo ya validado, no un rediseño metodológico.

**Alcance de esta entrega (v1.3 — los cuatro sectores tienen resolución completa; seguros tuvo una
revisión sustancial adicional tras review actuarial):**
- **Banca** (§3.1) — listo. Metodología 100% calibrada, sin dependencias de datos nuevas.
- **Seguros / ISF** (§5) — **contiene un bug de producción a corregir con prioridad** (doble conteo
  de siniestros, §5.1, independiente del resto de este spec) más un rediseño de Ejecución como
  combined ratio (§5.2), varios gates de datos (ingesta multi-año, extractor de reaseguro y de
  desglose por ramo) y dos correcciones a la v1.2 que resultaron sobre-afirmadas: reaseguro y
  concentración por ramo no estaban bloqueados por fuente, estaban bloqueados por una función de
  agregación del extractor (§5.5, §5.6).
- **Pensiones / ISA** (§6) — listo, con un gate de datos (cobertura real de solvencia) y una alerta
  de N chico (7 AFP).
- **Fiduciarias** (§7) — listo, sin gates de datos pendientes (mismo motor 100% calibrado que banca),
  con alerta de N muy chico (5 entidades).
- **Explícitamente fuera de alcance:** solo calce de duración en seguros — brecha de fuente probable,
  no de diseño (§5.10). Reaseguro y concentración por ramo ya no están fuera de alcance (§5.5, §5.6).

---

## 1. Contexto: qué ya existe (no reinventar)

Verificado en el repo (`sdq-market-intelligence/`, corte 2026-08-06):

| Pieza | Ubicación | Qué aporta |
|---|---|---|
| Escala de rating (banca) | `modules/banking_score/scoring/rating_scale.py` | Única fuente de verdad: `RATING_SCALE` (10 tuplas `tier, lo, hi`), `TIER_COLORS`, `RATING_TIER_TO_INDEX`/`INDEX_TO_RATING_TIER`. 11 módulos downstream importan de acá — no hay lógica de escala duplicada. |
| Pesos de banca | `modules/banking_score/scoring/weights.py` | 5 sub-componentes universales: `solidez (0.40)`, `calidad (0.30)`, `eficiencia (0.15)`, `liquidez (0.10)`, `diversificacion (0.05)`. Perfiles por `entity_type` en `WEIGHT_PROFILES` (incluye `fiduciaria`: 0.37/0.22/0.26/0.10/0.05). |
| Motor de fiduciarias | `modules/banking_score/scoring/fiduciaria.py`, `external/fiduciaria_pdf_client.py` | Reusa el motor de banca (mismos 5 sub-componentes) con indicadores propios para negocio fee-based. `FIDUCIARY_ENTITIES`: 5 entidades registradas (Reservas, BHD, Popular, La Nacional, FiduAPAP). Datos anuales (`period_type=annual`), estados auditados IFRS. |
| Fideicomisos Públicos | `modules/banking_score/scoring/fideicomiso.py`, `fiduciaria_sync.py` | Objeto **distinto** de fiduciarias: `Fideicomiso.fiduciaria_bank_id` es FK a la fiduciaria que lo administra (relación institución→vehículo, como banco→cartera). `HEALTH_BANDS`: Sólida(≥75)/Estable(≥50)/En vigilancia(≥30)/Frágil(<30) — drift de cortes vs. ISF/ISA. No es uno de los 4 sectores de este spec; no se fuerza alineación (ver §7.4). |
| ISF (seguros) | `modules/insurance_intel/scoring/isf.py` | 5 dimensiones: `solvencia (0.35)`, `siniestralidad (0.20)`, `liquidez (0.15)`, `escala (0.15)`, `resultado_tecnico (0.15)`. Bandas `_BANDS` = Sólida(≥75)/Adecuada(≥60)/En vigilancia(≥45)/Frágil(<45). Híbrido banda absoluta + peer min-max. **`resultado_tecnico` tiene un bug de doble conteo con `siniestralidad` — ver §5.1.** |
| Extractor de estados auditados (seguros) | `modules/insurance_intel/external/audited_excel_extractor.py` | Parsea `Estados-Financieros-Auditados-por-cia-<year>.xlsx` (catálogo regulatorio SIS, secciones 1-5). `gastos_totales = leaves_sum("5", ndig=6)` — suma TODO section 5, incluye siniestros (§5.1). `primas`/`siniestros` se extraen vía `children_sum_where` sobre leaves de 6 dígitos que casi con certeza son desglose por ramo, pero se colapsan a un total único (§5.6). No extrae cesión ni recuperables de reaseguro hoy — ausencia del parser, no confirmado como ausencia de la fuente (§5.5). |
| Roster seguros | `shared/data/sis_roster_client.py` | Verificado en vivo contra `sis.gob.do/companias-aseguradoras-y-reaseguradoras` (2026-08-06): 35 compañías autorizadas, 33 puntuadas hoy por el ISF. |
| ISA (pensiones) | `modules/pension_intel/scoring/isa.py` | 5 dimensiones: `solvencia (0.35, declared gap)`, `rentabilidad (0.25)`, `riesgo/volatilidad (0.15, real, NAV mensual)`, `escala (0.15)`, `costo (0.10)`. Mismas bandas y cortes que ISF. Docstring confirma que sigue **el precedente de Fideicomisos** ("fund-like entities get their own band scale, not a credit rating"). |
| Volatilidad NAV (pensiones) | `modules/pension_intel/nav_sync.py`, `scoring/isa.py` | NAV mensual encadenado desde Boletines Trimestrales SIPEN, ventana ≈10 trimestres (~30 observaciones). Mínimo exigido por el motor: `_VOL_MIN_RETURNS = 12`. Cobertura holgada — a diferencia de seguros, esta dimensión **ya existe y ya tiene profundidad suficiente**. |
| Solvencia AFP (pensiones) | `modules/pension_intel/financials_sync.py` | Dos vías de ingesta (manual + live SIPEN, decisión 2026-06-27): `patrimonio` + `activos_totales` por AFP → dimensión de solvencia del ISA. Camino ya construido; **estado real de cobertura en producción sin confirmar desde este entorno** (ver §6.2). |
| Roster pensiones | `shared/data/fixtures/sipen_entities.json` + Wikipedia (cruzado 2026-08-06) | 7 AFP: Popular, Crecer, Reservas, Siembra, Romana, JMMB-BDI, Atlántico. Wikipedia cita "en 2024 operaba 7 AFP en la República Dominicana" — coincide exactamente con el fixture. |
| ISARS (ARS, subvertical seguros) | `modules/insurance_intel/scoring/ars_rating.py` | Mismas bandas y cortes (75/60/45) — tercer motor con el patrón ya validado. No es uno de los 4 sectores core; queda igual sin cambios. |
| Almacenamiento histórico | `infrastructure/alembic/versions/dc1b15fd8ca1_add_banking_score_tables.py` | `rating_results.rating_tier` y `rating_actions.previous_tier/new_tier` son `VARCHAR(10)` planos — **no hay FK ni enum**. La migración de nomenclatura es un remapeo de datos (`UPDATE`), no una migración de esquema. |

**Alcance de referencias a la notación actual** (grep en `modules/ app/ frontend/ shared/ scripts/
clients/ infrastructure/ docs/`, excluyendo worktrees/`.venv`/caches, corte 2026-08-06):

| Patrón | Archivos | Ocurrencias |
|---|---|---|
| `rating_tier` | 53 | 132 |
| `RATING_SCALE` | 6 | 18 |
| `SDQ-(AAA\|AA+\|AA-\|AA\|A+\|A-\|A\|BBB+\|BBB\|D)` | 44 | 186 |

La mayoría de los 186 hits de notación de letras son strings de display en reportes/tests/docs, no
reimplementaciones de la escala — la lógica vive solo en `rating_scale.py`. **Claude Code debe
re-correr este grep antes de estimar esfuerzo real**, este conteo puede estar desactualizado.

---

## 2. Diseño: Perfil SDQ

### 2.1 Estructura

Cada entidad recibe **dos índices independientes, 0-100**, en vez de un solo símbolo fusionado:

- **Índice de Ejecución** — rentabilidad, eficiencia, disciplina operativa. Qué tan bien le va.
- **Índice de Resiliencia** — solvencia, liquidez, calidad de activos/cartera. Qué tan expuesta está.

Cada eje tiene su propia banda cualitativa. No hay fusión en un solo símbolo ordinal — es deliberado:
ninguna agencia de calificación separa desempeño de exposición de esta forma, así que la
no-comparabilidad es estructural, no solo de nomenclatura.

### 2.2 Nombre

**"Perfil SDQ"** — decidido con Ricardo tras descartar "Vector SDQ" (no resuena con el público) y
"Radar SDQ" (colisiona con el uso ya existente de "radar" como nombre del gráfico multi-pilar en
`reports/pdf_generator.py` y `shared/products/render.py`). "Pulso SDQ" también descartado por
colisión dura: `ProductTier.pulse` ya es un tier de producto shipeado en
`modules/esg_climate/products.py` ("Pulso de Resiliencia Climática").

Los nombres de los ejes reciclan vocabulario de marca ya aprobado en vez de inventar uno nuevo:
"Ejecución" viene de la tagline secundaria ("Estrategia que se ejecuta. No solo se presenta.");
"Resiliencia" viene de cómo `SDQ_brand-guidelines.md` §1 define "invencible" (combinar rigor con
velocidad, no blindaje pasivo).

Esto resuelve además el punto abierto de `SDQ_brand-guidelines.md` §14 ("Sub-marca para productos
tech... a validar") para el primer producto propietario nuevo — sirve de precedente para JurisAI/MIP/
eHipoteca.

### 2.3 Principio de agregación (no recalibrar)

Cada motor sectorial ya tiene dimensiones ponderadas y calibradas. Perfil SDQ **reagrupa esas mismas
dimensiones en dos familias y renormaliza el peso dentro de cada una** — no se tocan los pesos
relativos originales entre dimensiones, no se inventan pesos nuevos.

---

## 3. Mapeo de dimensiones por sector — resumen

### 3.1 Banca (`banca_multiple`)

| Eje | Sub-componente | Peso actual | Peso renormalizado dentro del eje |
|---|---|---|---|
| Resiliencia | Solidez Financiera | 40% | 47% (40/85) |
| Resiliencia | Calidad de Activos | 30% | 35% (30/85) |
| Resiliencia | Liquidez | 10% | 12% (10/85) |
| Resiliencia | Diversificación | 5% | 6% (5/85) |
| Ejecución | Eficiencia y Rentabilidad | 15% | 100% |

Resiliencia = 85% del peso actual, Ejecución = 15%. No es arbitrario: refleja que en banca regulada,
solvencia/calidad de cartera/liquidez estructuralmente importan más que rentabilidad pura para saber
si una entidad aguanta un shock — es, sin que se haya nombrado así, el mismo criterio de CAMELS que
usa el supervisor bancario.

### 3.2 Fiduciarias — ver resolución completa en §7

### 3.3 Seguros (ISF) — ver resolución completa en §5

### 3.4 Pensiones (ISA) — ver resolución completa en §6

---

## 4. Bandas por eje — regla general

| Eje | Bandas (0-100) | Estado |
|---|---|---|
| Resiliencia | Sólida (≥75) · Adecuada (≥60) · En vigilancia (≥45) · Frágil (<45) | Ya vigente — hereda ISF/ISA/ISARS sin cambios. Nombres **cerrados**, no se tocan. |
| Ejecución | **Sobresaliente** (≥75) · **Competitiva** (≥60) · **Rezagada** (≥45) · **Deficiente** (<45) | Nombres **cerrados** (v1.2, ver §4.1). Cortes numéricos siguen provisionales — por simetría con Resiliencia, no validados contra distribución real. Acción requerida antes de shippear: correr la distribución real de cada eje por sector y fijar cortes por percentil si la distribución no calza con 75/60/45. Precedente de falla a evitar: Gate E sectorial — bandas fijas sin validar contra distribución real terminaron comprimiendo casi todo el universo en una sola categoría. |

### 4.1 Naming de las bandas de Ejecución — decisión cerrada

**Sobresaliente / Competitiva / Rezagada / Deficiente.** Reemplaza el borrador de trabajo
("Alta/Media/Limitada/Débil") que nunca pasó por validación — quedó en el spec como placeholder de
diseño de cortes, no como naming aprobado.

Grep de colisión contra todo el vocabulario de bandas ya usado en el repo (`_BANDS`/`BANDS`/
`PULSE_BANDS`/`BAND_ORDER`, los 17 ejes de SDQMIP, corte 2026-08-06) — hallazgo relevante no
documentado hasta esta versión: **SDQMIP ya tiene dos familias de nomenclatura de banda en
producción**, no una:

1. `Fuerte / Adecuado / Vigilancia / Crítico` — nivel sistema/sector: `banking_score` (Pulse
   agregado), `construction_intel`, `free_zones_intel`, `tourism_intel`, `energy_intel`,
   `telecom_intel`.
2. `Sólida / Adecuada / En vigilancia / Frágil` — nivel entidad: `insurance_intel` (ISF/ISARS),
   `pension_intel` (ISA).
3. Variante suelta en `trade_intel`: `Fuerte / Sólido / Vigilar / Débil`.

Los nombres de Ejecución evitan deliberadamente las tres familias — no reusan `Fuerte`, `Adecuado`,
`Vigilancia`/`Vigilar`, `Crítico`, `Sólido`/`Sólida`, `Frágil`, `Débil`, ni las bandas de 3 niveles ya
usadas en `esg_climate` (`Alta/Moderada/Baja`) o las etiquetas de severidad de eventos en
`banking_score/events.py` (`Alto/Elevado/Bajo`). También se descartó `Insuficiente`: colisiona con el
string literal `"Datos insuficientes"` que ya usa el motor (`fideicomiso.py`, `isa.py`) para el estado
de "sin banda por cobertura mínima no alcanzada" — usarlo como banda real de Ejecución generaría
ambigüedad real entre "no se pudo calificar" y "calificado, bajo en Ejecución".

`Rezagada` tiene un precedente reforzante, no un choque: `pension_intel/early_warning.py` ya dispara
una alerta `"Rentabilidad rezagada"` cuando la rentabilidad de una AFP cae bajo el percentil 20 — el
mismo concepto (desempeño por debajo del panel), en el mismo sector. `Deficiente` hace eco deliberado
del precedente de FICO citado en la fase de diseño de este spec (bandas descriptivas
Deficiente/Regular/Bueno/Muy Bueno/Excepcional) — mismo espíritu, vocabulario propio.

Chequeado contra vocabulario bloqueado de `brand-kit/CLAUDE.md`: ninguna de las cuatro palabras
aparece en la lista bloqueada; registro consultivo-experto, sin admiraciones, sin clichés.

**Nota de consistencia (post-v1.3):** los nombres de banda estaban cerrados, pero su relación con la
taxonomía numérica no quedó explícita para seguros al momento de escribir la revisión actuarial —
seguros definía Ejecución sobre combined ratio (%, menos-es-mejor) mientras el resto de los sectores
usa un índice 0-100 (más-es-mejor) con los cortes de esta sección. Se cerró en §5.2 con una función
de conversión explícita — las cuatro bandas significan lo mismo (mismos cortes 0-100 de esta tabla)
en los cuatro sectores, sin excepción.

### 4.2 Regla de N chico — decisión cerrada

**4 bandas en los cuatro sectores, sin excepción — se prioriza la homologación por encima de ajustar
cardinalidad por sector.** Tener pensiones/fiduciarias en 3 bandas y banca/seguros en 4 rompería el
objetivo original de un lenguaje único entre sectores.

Para compensar la fragilidad estadística con N chico (5 fiduciarias, 7 AFP — ver §6.1, §7.1):
**regla de UI, no de cálculo** — cuando el universo puntuado de un sector tiene menos de 15
entidades, el reporte muestra siempre la posición relativa junto a la banda (ej. "Resiliencia:
Sólida — 2/5 fiduciarias"), nunca la banda categórica sola. El ISA ya calcula peer min-max
internamente (§1) — este requisito reusa ese cálculo para el display, no agrega un componente de
scoring nuevo. Aplica igual a los dos ejes.

---

## 5. Seguros (ISF) — resolución detallada (v1.3 — revisión sustancial tras review actuarial)

### 5.0 Origen de esta revisión

Feedback de Teresa Mercado (actuaria) sobre la v1.2 de este spec, incorporado 2026-08-07 (correo
"Nota Tecnica SDQ Perfil Seguros - Feedback de Hija aseguradora"). Cambia materialmente el diseño de
Ejecución, saca Escala de Resiliencia, agrega Reaseguro, y corrige dos conclusiones de la v1.2 que
resultaron ser más fuertes de lo que la evidencia sostenía (§5.5, §5.6). Ricardo confirmó: todo lo
que Teresa señaló se incorpora, no es opcional — mejora el ISF de producción, no solo este ejercicio.

### 5.1 Bug confirmado en el ISF de producción: doble conteo de siniestros

`modules/insurance_intel/scoring/isf.py`: `resultado_tecnico = (ingresos_totales - gastos_totales) /
primas_suscritas`. `gastos_totales` se calcula en `external/audited_excel_extractor.py` como
`leaves_sum("5", ndig=6)` — la suma de TODAS las cuentas de la sección 5 (GASTOS) del catálogo
regulatorio SIS, sección que estructuralmente incluye la línea de reclamaciones/siniestros como
gasto. `siniestros_pagados` se extrae aparte, de la misma fuente
(`children_sum_where("RECLAMACIONES PAGADAS POR SINIESTRO")`).

**El ISF que corre HOY en producción cuenta los siniestros dos veces**: directo en `siniestralidad`
(20%) y otra vez escondido dentro de `gastos_totales` en `resultado_tecnico` (15%). No es un defecto
que introduce Perfil SDQ — es un defecto preexistente que este ejercicio destapó. **Se corrige en el
motor actual, con prioridad sobre el resto del roadmap de Perfil SDQ** — impacta scores que ya se
están publicando, no solo el diseño de los dos ejes.

### 5.2 Rediseño de Ejecución: combined ratio, no resultado_tecnico

Reemplaza `resultado_tecnico` como única variable de Ejecución. Ejecución se construye como el
**combined ratio** — estándar de la industria, cualquier persona de seguros lo lee sin explicación —
con dos componentes mutuamente excluyentes:

- **Loss ratio** = siniestros / primas (ver §5.3 sobre base pagados vs. incurridos).
- **Expense ratio** = gastos de adquisición y operativos / primas — `gastos_totales` **menos** la
  porción de siniestros ya contada en el loss ratio. Requiere que el extractor separe, dentro de la
  sección 5, la sub-cuenta de reclamaciones (que ya aísla vía `children_sum_where`) del resto — es
  extender un patrón que el extractor ya usa, no data nueva.
- **Combined ratio = loss ratio + expense ratio**, ancla en **100% = breakeven técnico**. Reemplaza
  el corte "por simetría con Resiliencia" de la v1.2 con un ancla económica real, igual en espíritu a
  cómo ya se ancla solvencia en 1.0 = cumple (§1). Los puntos intermedios de banda (§5.9) siguen
  pendientes de calibrar contra distribución real — el ancla en 100% da un punto de referencia no
  arbitrario, no resuelve solo eso.

**Conversión a índice 0-100 (cierra un hueco de la v1.3 inicial, no estaba explícito):** el combined
ratio es un porcentaje donde *menos es mejor*, mientras que Ejecución en banca/pensiones/fiduciarias
(§3.1, §6.5, §7.3) es un promedio ponderado 0-100 donde *más es mejor*, con los cortes de banda de
§4 (≥75/≥60/≥45). Sin una conversión explícita, seguros quedaba en una escala paralela — rompía la
promesa central de Perfil SDQ de un lenguaje único entre sectores. Se resuelve con una función lineal
anclada en los tres cortes que §5.9 ya fijaba sobre combined ratio (90/100/110), que calzan
exactamente con los tres límites de banda de §4 (75/60/45):

```
score_ejecucion = clamp(60 − 1.5 × (combined_ratio − 100), 0, 100)
```

Breakeven (100%) cae en score 60 — el borde inferior de "Competitiva", consistente con que breakeven
es aceptable pero no sobresaliente. Con esto, seguros reporta Ejecución en la misma escala 0-100 y
usa las mismas bandas de §4 que los otros tres sectores; el combined ratio queda como la métrica
subyacente que alimenta el índice, no como una segunda escala visible en paralelo. La pendiente
(1.5) se deriva de los cortes ya elegidos, no es un número nuevo inventado — sigue siendo provisional
en el mismo sentido que todo lo demás en este spec: a validar contra la distribución real una vez
haya datos (§5.9).

Resuelve el doble conteo de raíz: loss ratio y expense ratio son mutuamente excluyentes por
construcción, a diferencia de siniestralidad y resultado_tecnico en el diseño de la v1.2.

### 5.3 Base de siniestros: pagados vs. incurridos

`siniestros_pagados` (base caja) es gameable: una aseguradora puede demorar el reconocimiento/pago de
reclamaciones para mostrar mejor loss ratio en el período — el riesgo de "maquillar subreservando"
que señaló Tere.

**Aproximación factible sin datos nuevos:** `reservas_tecnicas` ya se extrae por período
(`21xx + 22xx`, balance a fin de año). `financials_sync.py` ya descubre `{year: file_url}` para
múltiples años en la página de transparencia de SIS, no solo el más reciente. Con dos años
consecutivos:

```
siniestros_incurridos ≈ siniestros_pagados + (reservas_tecnicas_t − reservas_tecnicas_t-1)
```

**Limitación a documentar, no a esconder:** `reservas_tecnicas` tal como se extrae hoy mezcla
reservas de siniestros pendientes con reserva de riesgos en curso (prima no devengada) — la
aproximación sobreestima el ajuste si la prima no devengada se mueve por razones no relacionadas a
siniestros. Mejora recomendada: que el extractor aísle la sub-cuenta de reserva de siniestros
pendientes específicamente (mismo patrón `children_sum_where`, buscar descripción tipo
"RESERVA.*SINIESTRO"). Se puede lanzar con la aproximación agregada mientras se refina, declarando la
limitación en el reporte — mismo principio de transparencia que Tere ya validó en la v1.2.

**Prerequisito de ingesta:** `financials_sync.py` describe descubrir URLs por año, pero el comentario
del módulo dice "Discovers the **latest**" — Claude Code debe confirmar si ya se ingieren series
multi-año o si hay que extender la sincronización más allá del año más reciente.

### 5.4 Ventanas temporales distintas por eje

Los dos ejes no comparten el mismo corte temporal — el balance (Resiliencia) es una foto, se quiere
la más reciente; el underwriting (Ejecución) es un ciclo, se quiere promedio de 3-5 años para
absorber estacionalidad y catástrofes, y porque ayuda con el reserving.

- **Resiliencia** → último período disponible (como hoy).
- **Ejecución** → promedio del combined ratio sobre 3-5 años, no el último año aislado. Razón
  adicional: con un solo año, una catástrofe puntual reclasifica a una aseguradora bien manejada — no
  es un assessment justo.

No son dos problemas distintos del gate de nivel/volatilidad de §5.9 — es el mismo problema de
profundidad temporal visto desde dos ángulos (uno pide multi-año para el nivel promedio, el otro para
medir volatilidad). Un solo requerimiento de ingesta multi-año resuelve ambos.

### 5.5 Reaseguro en Resiliencia — corrección de la v1.2

**La v1.2 afirmó "confirmado en código, no es inferencia" que reaseguro estaba bloqueado por
disponibilidad de fuente. Esa afirmación fue más fuerte de lo que la evidencia sostenía — se corrige
acá.** Lo confirmado es que `audited_excel_extractor.py` no extrae hoy ninguna cuenta de cesión ni
recuperables — no hay ninguna línea para eso en el extractor. Eso no es lo mismo que "la fuente no lo
tiene". El catálogo de cuentas regulatorio dominicano (Ley 146-02) casi con certeza tiene cuentas
específicas de prima cedida y recuperables de reaseguradores — es estándar en cualquier catálogo de
seguros de la región. Nadie las codificó todavía en el parser. **Es una brecha de ingeniería, no de
fuente** — Claude Code debe confirmar contra el Excel crudo de SIS
(`Estados-Financieros-Auditados-por-cia-<year>.xlsx`) antes de asumir cualquiera de las dos versiones.

**Diseño de la dimensión:** entra a Resiliencia. Proxies: prima cedida / prima bruta, y recuperables
/ patrimonio. **No monótona** — cesión moderada es sana, casi cero es desprotección, casi total es
fronting (la aseguradora no retiene riesgo real). Requiere scoring en **U invertida**, no una banda
lineal como el resto del ISF — la peor puntuación está en ambos extremos, la mejor en una banda
intermedia. Los puntos exactos de esa banda ("sano" = qué % de cesión) son ilustrativos hasta
validarlos con benchmark de mercado reasegurador caribeño — no inventar precisión falsa acá tampoco.

**Esto resuelve Escala de forma más precisa que la v1.2:** lo que convierte tamaño en resiliencia
real no son los activos totales, es cuánto y cómo reasegura la aseguradora. Con reaseguro como
dimensión propia, **Escala sale de Resiliencia** — no como corrector residual condicional (v1.2
§5.2), sino reemplazada directamente por una señal más precisa del mismo fenómeno. Mismo patrón de
resolución que ya se aplicó en pensiones (§6.4): cuando existe una señal real y específica del
fenómeno que Escala intentaba proxear, Escala deja de hacer falta.

### 5.6 Dispersión de loss ratio entre ramos — segunda corrección de la v1.2

La v1.2 marcó "concentración por ramo" como bloqueada por fuente, citando que `sis_client.py` solo
trae primas por ramo a nivel de mercado agregado. Sigue siendo cierto para ESA fuente — pero no es la
única. `audited_excel_extractor.py` (el estado financiero por compañía que ya alimenta el resto del
ISF) lee primas y siniestros a nivel de **leaves de 6 dígitos bajo los sub-headers "PRIMAS SUSCRITAS"
y "RECLAMACIONES PAGADAS POR SINIESTRO"** (`children_sum_where`) — y esos leaves de 6 dígitos, por
estructura de catálogo regulatorio, son casi con certeza desglose por ramo. El extractor de hoy los
suma todos a un total único y descarta el desglose en el paso de agregación — **la granularidad por
ramo existe en lo que ya se está leyendo, se pierde después, en `leaves_sum`/`children_sum_where`.**

**Implicación:** concentración por ramo y dispersión de loss ratio entre ramos (idea de Tere: si el
pricing es bueno, el loss ratio debería ser parejo entre segmentos porque la prima sigue al riesgo;
mucha dispersión esconde cross-subsidy que el agregado no muestra — mide skill de pricing, más
difícil de maquillar que el margen agregado) **no están bloqueadas por fuente — están bloqueadas por
una función de agregación modificable.** Esfuerzo de extractor, no brecha de datos. Claude Code debe
confirmar la estructura exacta de los 6-digit leaves contra el Excel crudo antes de construir esto —
la hipótesis es razonable pero no está verificada contra el archivo real desde este entorno.

Dispersión de loss ratio entre ramos queda como candidato a extensión de Ejecución, no como parte del
mapeo mínimo de §5.9 — se evalúa una vez que el desglose por ramo esté disponible.

### 5.7 Pesos del ISF (35/20/15/15/15): transparencia sobre el origen

Sin justificación documentada más allá del código — vienen del commit original del ISF
(`921b9a1 feat(insurance): ISF sobre solvencia y liquidez REGULATORIAS`), juicio experto de quien lo
construyó. No hay backing adicional recuperable desde este entorno. **Acción:** el reporte (y
cualquier documentación de metodología visible al cliente) debe decir esto explícitamente — "pesos
por juicio experto, no derivados empíricamente" — en vez de dejarlo implícito. Mismo estándar de
transparencia ya aplicado a los cutoffs no validados de Ejecución.

### 5.8 Gate nuevo: peso × dispersión

La influencia real de una dimensión sobre el índice es peso × dispersión, no el peso nominal. Es
posible que Escala (transformación log, rango amplio) mueva el índice más que Solvencia pese a tener
menos peso nominal — no se puede saber sin datos reales. Con Escala saliendo de Resiliencia (§5.5)
este chequeo pasa a aplicar sobre solvencia/liquidez/reaseguro dentro de Resiliencia, y loss
ratio/expense ratio dentro de Ejecución.

**Test, no ejecutado desde este entorno** (no hay fixture con los estados financieros completos de
las 33 aseguradoras, solo fixture de solvencia/liquidez): sobre las aseguradoras cargadas, calcular
la desviación estándar de cada dimensión, multiplicar por su peso, ordenar. Correr antes de fijar los
pesos finales de cada eje.

### 5.9 Mapeo final (reemplaza la tabla de la v1.2)

| Eje | Dimensión | Ventana temporal | Estado |
|---|---|---|---|
| Ejecución | Loss ratio (nivel, base incurridos si §5.3 se resuelve) | Promedio 3-5 años | Gate: ingesta multi-año (§5.4) |
| Ejecución | Expense ratio | Promedio 3-5 años | Gate: extractor separa gastos de siniestros (§5.2) |
| Resiliencia | Solvencia | Último período | Vigente, sin cambios |
| Resiliencia | Liquidez | Último período | Vigente, sin cambios |
| Resiliencia | Loss ratio (volatilidad) | Ventana histórica multi-año | Gate de estabilidad de ranking (test de la v1.2, sigue vigente) |
| Resiliencia | Reaseguro (nuevo) | Último período | Gate: extractor + benchmark de banda sana (§5.5) |
| Fuera de ambos ejes | Escala | — | Sale de Resiliencia, reemplazada por Reaseguro (§5.5) |
| Candidato a extensión, no mínimo | Dispersión de loss ratio por ramo | Último período o promedio | Gate: extractor expone desglose por ramo (§5.6) |

**Bandas de Ejecución:** se aplican sobre `score_ejecucion` (§5.2), no sobre el combined ratio
directo — mismos cortes de §4 que banca/pensiones/fiduciarias (≥75/≥60/≥45). Expresado en combined
ratio, que es como lo va a pensar cualquier lector técnico, esos cortes equivalen a: Sobresaliente
(<90%) · Competitiva (90-100%) · Rezagada (100-110%) · Deficiente (>110%). El corte en 100% es el
único no arbitrario (breakeven); 90/110 son provisionales igual que el resto de los cortes de este
spec — y son los mismos números que fijan la pendiente de la conversión en §5.2, no un segundo
sistema de cortes independiente.

**N chico:** con 33 aseguradoras, la regla de §4.2 aplica igual (universo <15 → mostrar posición
relativa junto a la banda), aunque acá es menos urgente que en pensiones/fiduciarias. Las 4 bandas se
mantienen sin excepción — no se colapsan por sector (§4.2).

### 5.10 Fuera de alcance — actualizado

Solo **calce de duración** se mantiene como brecha probable de fuente — sin evidencia de que el
catálogo de cuentas extraído tenga desglose de duración de activos/pasivos técnicos, y pesa más en
vida/pensiones que en P&C. Reaseguro y concentración por ramo **salen de "fuera de alcance"** — pasan
a §5.5 y §5.6 como trabajo de extractor. Esta es la corrección más importante de esta revisión frente
a la v1.2: no eran brechas de datos, eran brechas de ingeniería que se leyeron como brechas de datos.

### 5.11 Antes de publicar: prueba de correlación entre ejes

Sin cambios respecto a la v1.2 — ver §8, aplica igual con el mapeo nuevo de §5.9. Una vez calculados
Ejecución y Resiliencia con datos reales sobre las 33 aseguradoras: correr la correlación entre
ambos. Si sale >0.7-0.8, el split no agrega poder discriminante real.

---

## 6. Pensiones (ISA) — resolución detallada

### 6.1 Roster verificado

7 AFP operando: Popular, Crecer, Reservas, Siembra, Romana, JMMB-BDI, Atlántico. Cruzado
2026-08-06 entre `shared/data/fixtures/sipen_entities.json` (fuente citada: Diario Financiero,
Diario Libre/ADAFP, Hoy/ADAFP) y Wikipedia ("en 2024 operaba 7 AFP en la República Dominicana").
**N más chico que seguros (33) — la alerta de banda de §6.6 es más urgente acá.**

### 6.2 Solvencia: gap declarado, con camino de ingesta ya construido

`solvencia (0.35)` es hoy un *declared gap* — sin estados financieros ingeridos, es la dimensión de
mayor peso de Resiliencia y no tiene dato. `modules/pension_intel/financials_sync.py` ya tiene dos
vías construidas (manual + live SIPEN, decisión 2026-06-27) para `patrimonio` + `activos_totales`
por AFP.

**Acción para Claude Code, no asunción de este spec:** confirmar en `pension_series` si ya hay
cobertura real de `patrimonio`/`activos_totales` por AFP antes de fijar el peso final de Resiliencia.
Si la cobertura sigue en 0: Resiliencia se publica temporalmente con 100% de peso en
riesgo/volatilidad (§6.3) — mismo patrón interino que seguros mientras no se cierre el gate de
volatilidad de siniestralidad (§5.9).

### 6.3 Riesgo/volatilidad: ya existe, ya tiene profundidad suficiente

A diferencia de seguros (donde el split nivel/volatilidad hay que construirlo desde cero), pensiones
**ya tiene** una dimensión de riesgo separada de rentabilidad: `_score_riesgo` en `scoring/isa.py`,
calculada sobre NAV mensual encadenado desde Boletines Trimestrales SIPEN
(`modules/pension_intel/nav_sync.py`), ventana ≈10 trimestres (~30 observaciones mensuales). El
mínimo que exige el propio motor es `_VOL_MIN_RETURNS = 12` — la cobertura real está holgadamente
por encima del mínimo. Esta dimensión no necesita un gate de habilitación: ya es estadísticamente
sólida.

### 6.4 Escala: resuelta, sin condición que evaluar

Como la volatilidad ya existe y ya tiene datos suficientes, Escala **no** necesita entrar a
Resiliencia como proxy de diversificación — sería el mismo doble conteo que en seguros se resolvió
reemplazando Escala por Reaseguro (§5.5). Acá no hay ni siquiera una dimensión sustituta que
construir: la señal real (riesgo/volatilidad) ya está. **Resolución: Escala queda fuera de
Resiliencia por defecto.**

Si hay argumento para meterla en Ejecución (mayor AUM podría reflejar éxito comercial/captación de
afiliados, no eficiencia de portafolio), es un argumento distinto — de crecimiento de negocio, no de
riesgo — y es una decisión de producto de Ricardo, no una inferencia técnica de este spec.

### 6.5 Mapeo final

| Eje | Dimensión | Peso actual | Peso renormalizado dentro del eje |
|---|---|---|---|
| Resiliencia | Solvencia (sujeto a §6.2) | 35% | 70% (35/50), si hay cobertura real |
| Resiliencia | Riesgo/volatilidad | 15% | 30% (15/50), o 100% mientras §6.2 no resuelva |
| Ejecución | Rentabilidad | 25% | 71% (25/35) |
| Ejecución | Costo (comisión/AUM, invertido) | 10% | 29% (10/35) |
| Sin asignar | Escala (AUM) | 15% | Fuera de ambos ejes por defecto — ver §6.4 |

### 6.6 Bandas — N chico, resuelto por la regla general de §4.2

Con 7 AFP, 4 bandas por eje son estadísticamente frágiles: es plausible que una banda quede vacía o
con una sola entidad, y que un solo punto de score mueva a una AFP de categoría sin que haya cambiado
nada material. **Resuelto en §4.2, no requiere una regla distinta para pensiones:** se mantienen las
4 bandas (mismo nombre en los 4 sectores), y el reporte de pensiones muestra siempre la posición
relativa entre las 7 AFP junto a la banda — el ISA ya calcula peer min-max, se reusa ese cálculo para
el display.

### 6.7 Antes de publicar: mismo gate de correlación que §5.5, ver §8.

---

## 7. Fiduciarias — resolución detallada

### 7.1 Roster verificado en código

`modules/banking_score/external/fiduciaria_pdf_client.py` → `FIDUCIARY_ENTITIES`: 5 entidades —
Fiduciaria Reservas, Fiduciaria BHD, Fiduciaria Popular, Fiduciaria La Nacional, FiduAPAP.
**N=5 — el universo más chico de los cuatro sectores.**

### 7.2 Motor: mismo de banca, sin gates de datos pendientes

`scoring/fiduciaria.py` reusa los 5 sub-componentes de banca (`weights.py`, perfil `fiduciaria`:
solidez 37% · calidad 22% · eficiencia 26% · liquidez 10% · diversificación 5%) con indicadores
propios para un negocio fee-based sin cartera de crédito. Datos **anuales** (`period_type=annual`),
de estados auditados IFRS por compañía — sin serie de alta frecuencia como el NAV de pensiones, así
que no aplica ninguna pregunta de nivel-vs-volatilidad acá: no hay una dimensión candidata a
dividirse. El mapeo de ejes es una reagregación directa, igual que banca.

*(Nota menor: el docstring de `fiduciaria.py` cita pesos v1 desactualizados — 35/20/25/10/10 — que
no coinciden con `weights.py` (37/22/26/10/5, calibración v1.1 2026-06-11). Usar siempre `weights.py`
como fuente de verdad; Claude Code debería actualizar el comentario al tocar el archivo.)*

### 7.3 Mapeo final (igual al ya presentado en §3.2 del spec original)

| Eje | Sub-componente | Peso actual | Peso renormalizado |
|---|---|---|---|
| Resiliencia | Solidez | 37% | 50% (37/74) |
| Resiliencia | Calidad | 22% | 30% (22/74) |
| Resiliencia | Liquidez | 10% | 14% (10/74) |
| Resiliencia | Diversificación | 5% | 7% (5/74) |
| Ejecución | Eficiencia | 26% | 100% |

### 7.4 Relación con Fideicomisos Públicos — resuelta

**No se alinean.** `Fideicomiso.fiduciaria_bank_id` (en `fiduciaria_sync.py`) confirma que una
fiduciaria administra N fideicomisos — es la relación institución→vehículo administrado, análoga a
banco→cartera de préstamos que origina. Son objetos distintos que miden cosas distintas: Perfil SDQ
en fiduciarias mide la solidez de la institución; el Índice de Salud de Fideicomisos Públicos mide la
salud del vehículo/fondo administrado. **No hay necesidad de forzar los cortes de Fideicomisos
(75/50/30, "Estable") a converger con los de Resiliencia (75/60/45)** — quedan como sistemas
separados por diseño, no por deuda técnica pendiente. Esto cierra la pregunta abierta en la v1.0 de
este spec.

### 7.5 Bandas — N chico, resuelto por la regla general de §4.2

Con solo 5 entidades, 4 bandas por eje casi garantizan categorías de 0-1 compañía — es el caso más
severo de los cuatro sectores. Misma resolución que pensiones (§6.6): se mantienen las 4 bandas, y el
reporte de fiduciarias muestra siempre la posición relativa entre las 5 junto a la banda.

### 7.6 Fase de implementación

Sin gates de datos pendientes (a diferencia de seguros y pensiones), fiduciarias puede implementarse
**en la misma fase que banca** (§9, Fase 1) — mismo motor, mismo rigor ya aplicado. El único trabajo
específico de fiduciarias es: cortes de Ejecución por percentil sobre su propia distribución (no la
de banca — son negocios estructuralmente distintos) y la decisión de bandas de §7.5.

---

## 8. Gate general: correlación entre ejes (aplica a los 4 sectores)

Antes de publicar Perfil SDQ en cualquier sector: con datos reales, correr la correlación entre
Ejecución y Resiliencia sobre el universo de esa sector. Si sale por encima de 0.7-0.8, el split no
está agregando poder discriminante real — es la misma información repartida en dos etiquetas, y el
argumento de "separar desempeño de exposición" se debilita frente a cualquier cliente técnico que
pida ver los números. Correr por separado en banca, seguros, pensiones y fiduciarias — no asumir que
el resultado en un sector se traslada a otro.

---

## 9. Migración de datos históricos

`rating_results.rating_tier` y `rating_actions.previous_tier/new_tier` son `VARCHAR(10)` sin FK — el
cambio es un `UPDATE` de remapeo, no una migración de esquema.

**Decisión pendiente de Ricardo, no técnica:** ¿el histórico de `rating_actions` (downgrades/upgrades
ya registrados bajo `SDQ-A…D`) se re-etiqueta retroactivamente al nuevo Perfil SDQ, o se documenta un
corte de fecha y el histórico pre-corte queda leído en notación vieja? Este spec no asume una
respuesta.

**Riesgo de cliente a resolver en la migración, no solo en el código:** cualquier documento ya
circulado bajo la notación vieja (el Deep Dive de Banco Popular es el caso conocido) debería recibir
una nota de reemplazo o reissue una vez Perfil SDQ esté publicado, para que no convivan dos
notaciones distintas frente al mismo cliente para el mismo período.

---

## 10. Plan de implementación por fases

0. **Fix del bug de doble conteo en el ISF de producción (§5.1) — prioridad sobre todo lo demás,
   fase independiente.** No es parte del rollout de Perfil SDQ, es una corrección a un score que ya
   se está publicando hoy. No esperar a las fases 1-3 para arrancarla.
1. **Motor — banca y fiduciarias juntas.** Extender el equivalente de `rating_scale.py` para
   computar Ejecución/Resiliencia por re-agregación de los sub-componentes ya existentes (§3.1, §7.3).
   Sin datos nuevos, sin recalibración en ninguno de los dos. Menor riesgo, mayor apalancamiento —
   desbloquea el patrón para seguros y pensiones.
2. **Seguros (ISF) — la fase con más superficie de esta entrega.** Implementar según §5:
   - 2a. Extractor: separar gastos de siniestros del resto de la sección 5 (§5.2); confirmar/extender
     ingesta multi-año (§5.3, §5.4); confirmar contra el Excel crudo si existen cuentas de cesión y
     recuperables de reaseguro (§5.5) y si los leaves de 6 dígitos de primas/siniestros son
     desglose por ramo (§5.6) — antes de escribir el resto del código de esta fase.
   - 2b. Ejecución como combined ratio (loss ratio + expense ratio, ancla 100%) sobre promedio 3-5
     años (§5.2, §5.4). Estado interino aceptable mientras la ingesta multi-año no esté lista: combined
     ratio del último año disponible, documentado como interino.
   - 2c. Reaseguro como nueva dimensión de Resiliencia con scoring en U invertida (§5.5); Escala sale
     de Resiliencia (reemplazada, no como corrector condicional).
   - 2d. Gate de estabilidad de ranking para volatilidad de loss ratio (heredado de la v1.2, §5.9);
     gate de peso × dispersión (§5.8); cortes de Ejecución por percentil sobre combined ratio (§5.9).
3. **Pensiones (ISA).** Implementar según §6: confirmar cobertura real de solvencia (§6.2, puede
   quedar en estado interino igual que seguros) + Escala fuera de Resiliencia por defecto (§6.4,
   resuelto) + cortes por percentil + regla de N chico ya cerrada (§6.6, §4.2).
4. **Migración de superficie.** Actualizar los ~44 archivos con notación de letras (reportes, tests,
   docs) y remapear el histórico según la decisión de §9.
5. **Reconciliación de Fideicomisos Públicos** (opcional, fuera de los 4 sectores core): **resuelto
   en §7.4 — no se alinea.** No requiere trabajo adicional salvo que Ricardo decida lo contrario.
6. **Reissue de documentos ya circulados** bajo notación vieja (Banco Popular Deep Dive) — coordinar
   con el dueño de la relación antes de publicar Perfil SDQ externamente.

---

## 11. Criterios de aceptación

- [ ] **Bug de doble conteo (§5.1) corregido en el ISF de producción**, verificado con al menos una
      aseguradora recalculada a mano para confirmar que `expense_ratio` ya no incluye siniestros.
- [ ] Combined ratio (loss ratio + expense ratio, ancla 100%) implementado como Ejecución en seguros
      (§5.2) — `resultado_tecnico` retirado del cálculo de Ejecución.
- [ ] Conversión combined ratio → `score_ejecucion` 0-100 implementada (§5.2, fórmula
      `60 − 1.5×(CR−100)` clamped) — seguros reporta Ejecución en la misma escala y con las mismas
      bandas de §4 que banca/pensiones/fiduciarias, no en combined ratio directo.
- [ ] Confirmado contra el Excel crudo de SIS (no asumido) si existen cuentas de cesión/recuperables
      de reaseguro (§5.5) y si los leaves de 6 dígitos de primas/siniestros son desglose por ramo
      (§5.6), antes de construir sobre esos supuestos.
- [ ] Reaseguro implementado como dimensión de Resiliencia con scoring en U invertida, si el gate de
      §5.5 se supera; si no, documentado como brecha de ingeniería pendiente, no de fuente.
- [ ] Ventanas temporales distintas por eje en seguros: Resiliencia con el último período, Ejecución
      con promedio 3-5 años (§5.4) — o estado interino documentado si la ingesta multi-año no está
      lista.
- [ ] Correlación Ejecución×Resiliencia < 0.7-0.8 por sector, verificada con datos reales, antes de
      publicar ese sector (§8).
- [ ] Gate de peso × dispersión (§5.8) corrido en seguros antes de fijar los pesos finales de cada eje.
- [ ] Cortes de Ejecución fijados por percentil de la distribución real, no por simetría — por sector
      (en seguros, el ancla en 100% de combined ratio ya da un punto de referencia no arbitrario;
      90/110 siguen siendo provisionales, §5.9).
- [ ] Gate de datos de volatilidad de siniestralidad (Resiliencia, seguros) superado con test de
      estabilidad de ranking antes de usarla; si no se supera, estado interino documentado.
- [ ] Escala en seguros resuelta según §5.5 (fuera de Resiliencia, reemplazada por reaseguro). Escala
      en pensiones resuelta según §6.4 (fuera de Resiliencia por defecto).
- [ ] Cobertura real de solvencia en pensiones confirmada en `pension_series` antes de fijar el peso
      final de Resiliencia (§6.2) — si no hay cobertura, publicar en estado interino.
- [ ] Calce de duración (seguros) documentado como brecha conocida de fuente — sin proxy forzado.
- [ ] Pesos del ISF (35/20/15/15/15) documentados explícitamente como juicio experto, no derivado
      empíricamente (§5.7), en cualquier superficie de metodología visible al cliente.
- [ ] Regla de N chico aplicada (§4.2): 4 bandas en los cuatro sectores, posición relativa visible
      en el display cuando el universo puntuado tiene menos de 15 entidades (seguros N=33 opcional
      por consistencia, pensiones N=7 y fiduciarias N=5 obligatorio).
- [ ] Naming de bandas de Ejecución implementado tal cual §4.1 (Sobresaliente/Competitiva/Rezagada/
      Deficiente) — sin variantes ni el borrador viejo (Alta/Media/Limitada/Débil).
- [ ] Decisión explícita de Ricardo sobre re-etiquetado retroactivo vs. corte de fecha para
      `rating_actions` antes de correr la migración de datos.
- [ ] Plan de reissue para documentos ya circulados bajo notación vieja, antes de publicar
      externamente.

---

## 12. Instrucción directa para Claude Code

> Arrancar por el **Fix 0** (§10.0): corregir el bug de doble conteo de siniestros en el ISF de
> producción (§5.1). Es independiente del resto de este spec y no debe esperar por las fases de
> Perfil SDQ — ya está afectando scores publicados.
>
> Después, implementar Perfil SDQ en los cuatro sectores en este orden: Fase 1 (motor de banca +
> fiduciarias, §10.1), Fase 2 (seguros/ISF, §5 y §10.2 — la fase con más superficie nueva de esta
> versión), Fase 3 (pensiones/ISA, §6 y §10.3).
>
> Antes de escribir código de la Fase 2: **confirmar contra el Excel crudo de SIS**
> (`Estados-Financieros-Auditados-por-cia-<year>.xlsx`), no asumir desde este spec, (a) si existen
> cuentas de cesión/recuperables de reaseguro (§5.5) y (b) si los leaves de 6 dígitos bajo "PRIMAS
> SUSCRITAS"/"RECLAMACIONES PAGADAS POR SINIESTRO" son desglose por ramo (§5.6). Ambas son hipótesis
> de este spec basadas en cómo está estructurado el catálogo regulatorio, no verificaciones directas
> contra el archivo — la v1.2 de este spec ya se equivocó una vez al sobre-afirmar una conclusión de
> disponibilidad de datos sin este chequeo; no repetir el error en sentido contrario asumiendo que
> ahora sí están disponibles sin confirmarlo.
>
> Antes de escribir código en general: (a) re-correr los greps de §1 para confirmar que el alcance no
> cambió desde 2026-08-07, (b) proponer el desglose de tareas en `tasks/todo.md` siguiendo la regla
> Plan First del repo, y (c) confirmar acceso a la base de producción para: el test de estabilidad de
> volatilidad de siniestralidad (§5.9), el gate de peso × dispersión (§5.8), la cobertura real de
> `patrimonio`/`activos_totales` por AFP (§6.2), y el cálculo de distribución real para los cortes
> por percentil de §4 en los cuatro sectores. Si no hay acceso, dejar estas piezas como tareas
> explícitas con el script listo pero sin ejecutar — no simular con datos de fixture ni asumir el
> resultado.
>
> Calce de duración (seguros) sigue fuera de alcance — documentar como brecha conocida de fuente si
> aparecen menciones sueltas en código o reportes (§5.10). Reaseguro y concentración por ramo **ya no
> están fuera de alcance** — ver §5.5 y §5.6.
>
> No forzar alineación entre fiduciarias y Fideicomisos Públicos — ya está resuelto que son sistemas
> separados (§7.4).
>
> La regla de N chico ya está cerrada (§4.2): 4 bandas en los cuatro sectores, con posición relativa
> siempre visible en el display cuando el universo puntuado tiene menos de 15 entidades (pensiones,
> fiduciarias, y seguros por consistencia). No hay decisión de producto pendiente acá.
>
> Los nombres de banda de Ejecución están cerrados (§4.1): Sobresaliente / Competitiva / Rezagada /
> Deficiente. En seguros, el corte en 100% de combined ratio (§5.9) es el único de los tres cortes
> con ancla económica real — no proponer alternativas de naming ni usar el borrador viejo
> (Alta/Media/Limitada/Débil) que pueda seguir apareciendo en el histórico de diseño.
>
> Pesos del ISF (35/20/15/15/15): documentar explícitamente como juicio experto en cualquier
> superficie de metodología visible al cliente (§5.7) — no dejarlo implícito.
>
> Dispatch de un reviewer subagent antes de cerrar cada fase, con este spec + `CLAUDE.md` del repo,
> dado que toca contratos públicos (API, modelos de reporte), un fix de producción con impacto en
> scores ya publicados, y una migración de datos históricos. Para el Fix 0 en particular: el reviewer
> debe confirmar específicamente que ningún score recalculado empeora silenciosamente sin que quede
> registrado como acción de rating explicable (mismo estándar de trazabilidad que ya rige el resto
> del motor).
