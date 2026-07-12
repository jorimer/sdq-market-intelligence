# SPEC — Motor de Research Custom sobre Corpus Curado SDQMIP

> Versión v0.1 · 2026-07-11 · Documento de construcción (no de validación de mercado).
> Etiquetas de confianza: **[Certain]** verificable contra código/doc citado ·
> **[Likely]** inferencia fuerte, no probada · **[Guessing]** supuesto a validar ·
> **[Lock]** decisión ya tomada por el dueño.

> **Estado de implementación (2026-07-11):** Fases 1, 3 y 4 **construidas y verificadas**
> (núcleo determinista, tests verdes). Data Registry en `shared/registry` (§3.1);
> retrieval real en `shared/knowledge` —reemplaza el stub del §2— (§3.2); orquestador +
> gate de honestidad en `shared/research` (§3.3/§3.4/§4), con el test round-trip de brecha
> del §4. Andamiaje de la Fase 2 (instrumento de piloto) y de la Fase 5 (export con la
> anatomía del REPORT_STANDARD) listo. Fases 2/5/6 requieren input del dueño (preguntas
> reales, medición de horas, decisión de tier) — ver `docs/MOTOR_RESEARCH_PILOTO.md`.
> Pendiente incremental: exponer `variable_signals` en los productos que aún degradan al
> fallback a-nivel-producto (banking, macro, trade, pension, insurance, monetary_policy);
> y enchufar el Cerebro para el pulido de prosa (alimentado solo de pasajes con procedencia).

## 0. Qué se construye

Un motor que toma una pregunta libre de un comprador (no un template de producto fijo)
y produce un reporte con la misma anatomía y el mismo estándar de honestidad de
procedencia que el resto del catálogo SDQMIP ([[REPORT_STANDARD]]): toda afirmación
material ancla a dato real, rúbrica declarada o brecha declarada — nunca se rellena
con conocimiento paramétrico del modelo disfrazado de dato.

**[Lock]** No es un producto de mercado nuevo a tarifar de cero. Es un motor de
producción para el SKU que ya existe y ya está tarifado — DD Full / Deep Dive
(US$7,000–25,000+/encargo, hoy 2-4 semanas, [[SDQMIP_Productos_Comercializables_Discusion_v0.2]]).
Si funciona, comprime el tiempo de producción de ese SKU sin tocar el precio, y abre
la puerta a un tier más rápido/barato entre DD Express y DD Full una vez medido el
ahorro real de horas (§7). No se decide ese tier en este documento.

## 1. Principio rector

El mismo de todo SDQMIP, aplicado a un caso más difícil. En un producto fijo (Banking
Score, IRMP, sectoriales), el sistema sabe de antemano qué dimensiones existen y cuáles
tienen dato real vs. rúbrica vs. brecha — el `sources` map se declara al construir el
producto, no al responder. En una pregunta libre, el sistema tiene que **descubrir en
tiempo de consulta** si tiene evidencia real para cada sub-afirmación, y declarar la
brecha si no la tiene — sin que el modelo la rellene con una respuesta plausible. Esa
es la regla dura de todo este spec (§4). Romperla no es un bug menor: es el colapso del
único diferencial de SDQ frente a un research genérico de IA (que sí rellena huecos con
conocimiento general, sin avisar) y frente a Analytica (que no hace scoring trazable
en absoluto, [[competidor-analytica]]).

## 2. Estado real de la infraestructura (verificado contra código, 2026-07-11)

No asumir sobre lo que existe — esta tabla corrige una sobreestimación previa en la
conversación con el dueño.

| Capa | Estado | Evidencia |
|---|---|---|
| Doctrina "nunca fabricar" + etiquetado live/rúbrica por variable | **[Certain] Construido y vivo** | `assemble_*_dataset` emite mapa `sources` "live"\|"rubric" por variable → badge UI + narrativa ([[RUBRIC_AUDIT_AND_REMEDIATION]]) |
| Motor de narrativa Cerebro (SCQA) por producto fijo | **[Certain] Construido y maduro** | `shared/narrative/`, usado en los 12 productos del catálogo |
| Lineage por conector (fuente/licencia/fecha) | **[Certain] Construido** | `shared/data/*_client.py` por fuente (SIB, BCRD, ONE, DGA…) |
| `ReportSpec` unificado + auto-generación de Metodología/Fuentes/Limitaciones | **[Certain] Solo especificado, no implementado** | `REPORT_STANDARD.md` §10: únicamente el paso 1 ("Standard doc") está marcado ✅; pasos 2-8 (el `ReportSpec`, el motor PDF/Word, la paridad online) no lo están |
| `/api/v1/tools/compare-insight` | **[Certain] Construido y vivo** | `shared/tools/router.py` — compara 2-4 elementos, pero solo scores YA calculados que ya existen en la base. No busca nada nuevo. |
| `/api/v1/tools/market-brief` | **[Certain] Construido y vivo** | Síntesis cross-eje, pero **cacheada y programada** (Operación de consola), no on-demand por pregunta |
| `shared/knowledge/retrieve.py` (RAG retrieval) | **[Certain] Stub, cero lógica** | El archivo literal: recibe una consulta, devuelve `[]` siempre. Docstring: "Real implementation... is deferred." |
| `shared/knowledge/ingest.py`, `corpus/`, `index/` | **[Certain] No existen como archivos** | Estaban en el plan original (`SPECS_OVERVIEW.md`, 2026-05-28) junto a `retrieve.py`; de los 7 ejes planeados esa fecha, los 7 se construyeron — el pipeline RAG es la única pieza del plan original que sigue sin una línea de código 6 semanas después. Señal, no descuido: se ha priorizado sistemáticamente detrás de cobertura de ejes. |
| `shared/source_intel/` (agente de descubrimiento de fuentes) | **[Certain] Construido y vivo, pero es OTRA cosa** | Admin-only, propone FUENTES candidatas para cerrar brechas de cobertura (lado oferta), con conocimiento no verificado de Claude y gate humano antes de integrar. No contesta preguntas de cliente (lado demanda). |
| Aislamiento entre módulos (comunicación solo por `event_bus`) | **[Certain] Regla de arquitectura vigente** | `CLAUDE.md`: "Never import directly from another module" |

**Lectura:** lo que existe es la disciplina de dato (honestidad, lineage, nunca-fabricar)
y el motor de narrativa para templates fijos. Lo que este producto necesita —recuperación
sobre el corpus + orquestación cross-eje de una pregunta libre— no existe en ningún grado,
está diferido por diseño desde el blueprint original. El esfuerzo es "construir un
componente nuevo completo", no "cablear un lector sobre algo que ya funciona".

## 3. Arquitectura objetivo

Cuatro piezas nuevas, en orden de dependencia:

### 3.1 Catálogo de datos (Data Registry) — capa de LECTURA, no de escritura
Agrega `data_signals` + `lineage` + `validation_state` de los 13 módulos en un esquema
uniforme y consultable: qué mide cada eje, con qué peso, con qué fuente, con qué cadencia,
y su estado real/rúbrica/brecha vigente. **No viola el aislamiento entre módulos** — la
regla de `CLAUDE.md` es sobre acoplamiento de escritura/tablas, no sobre agregación de
lectura para un consumidor transversal (mismo patrón que ya usa `shared/tools` con los
scores ya calculados). Vive en `shared/`, expone un servicio de solo-lectura.

### 3.2 Retrieval real (implementar `shared/knowledge/retrieve.py`)
**[Guessing]** Alcance acotado — NO es "búsqueda vectorial sobre la web abierta", es
recuperación estructurada sobre (a) el Data Registry de 3.1 y (b) el corpus documental
propio ya de licencia clara (metodologías, doctrina versionada, boletines fuente ya
ingeridos). Cualquier fuente externa NUEVA que se necesite sigue pasando por el flujo
existente de `shared/source_intel` (propuesta → evaluación → gate humano → integración) —
este motor no scrapea en vivo dentro de la respuesta a un cliente.

### 3.3 Orquestador de pregunta libre (el "agente")
Recibe el prompt del comprador, lo descompone en sub-preguntas mapeadas a ejes/indicadores
del Data Registry, ejecuta 3.2 por sub-pregunta, y entrega al Cerebro **solo pasajes con
procedencia adjunta** (fuente, fecha, estado real/rúbrica/brecha). Regla dura: el Cerebro
nunca redacta una sub-afirmación sin evidencia adjunta de 3.2. Si el retrieval no
encuentra nada, esa sub-pregunta se marca BRECHA y se declara — no se completa con
conocimiento general del modelo. Esta es la traducción operativa del principio del §1.

### 3.4 Gate de publicación (paralelo al gate de readiness que ya existe para productos fijos)
Un reporte custom no sale al comprador si el % del cuerpo sin evidencia real supera un
umbral. **[Guessing]** Umbral inicial propuesto: 40% del cuerpo del informe sin ancla de
dato real o rúbrica declarada → el sistema entrega un "scoping report" (qué se puede y
no se puede contestar hoy, y qué fuente cerraría la brecha) en vez de un informe con
apariencia de completo. Esto es lo que impide el riesgo reputacional identificado antes:
fabricar por omisión en el momento en que el cliente más necesita ver honestidad.

La salida reutiliza la anatomía de `REPORT_STANDARD.md` (portada, resumen, hallazgos,
metodología/fuentes/limitaciones auto-generadas) — poblada dinámicamente por pregunta en
vez de por template fijo. Si el `ReportSpec` de la §10 de ese documento no está
implementado para cuando esto llegue a producción, es un prerrequisito compartido, no
trabajo duplicado.

## 4. Regla de honestidad para pregunta libre (el gate central del producto)

Toda sub-afirmación que el orquestador le pasa al Cerebro debe llevar una de tres
etiquetas, igual que hoy en los productos fijos pero decidida en tiempo de consulta:
**dato real** (con lineage), **rúbrica declarada** (con nota de qué es y por qué), o
**brecha** (declarada explícitamente, con la fuente candidata que la cerraría si existe
en el tablero de `source_intel`). El Cerebro no tiene permiso de sintetizar una cuarta
categoría silenciosa ("lo sé por conocimiento general"). Esto se prueba con un test de
round-trip: dada una pregunta con una brecha conocida a propósito, el reporte generado
debe declararla, no completarla — se sugiere como gate de CI antes de cualquier release
de esta pieza, en la línea de los tests round-trip que ya protegen las curvas de
sensibilidad en banking ([[DEEP_DIVE_FITCH_PARITY]] Fase 4, PR #407).

## 5. Fases de build

| Fase | Qué | Depende de | Esfuerzo relativo | Qué mide/desbloquea |
|---|---|---|---|---|
| 0 | Dado — doctrina, etiquetado, lineage, Cerebro | — | Ya existe | — |
| 1 | Data Registry (agregación de solo-lectura) | Fase 0 | Bajo-medio | Sirve YA para el piloto manual de la Fase 2 sin esperar 3-4 |
| 2 | Piloto manual (protocolo de 3-5 preguntas reales de los compradores identificados) | Fase 1 | Bajo (analista + Claude asistido, sin agente autónomo) | Cobertura real por pregunta (% real/rúbrica/brecha), horas ahorradas vs. proceso DD actual, y si el gate de honestidad sobrevive a preguntas libres. Esto es instrumentación de build, no validación de mercado. |
| 3 | Retrieval real (`shared/knowledge/retrieve.py` + `ingest.py`/`corpus/`/`index/`) | Fase 1, informa con Fase 2 | Alto — es la pieza que no existe en ningún grado | Habilita automatizar lo que la Fase 2 probó a mano |
| 4 | Orquestador de descomposición + gate de honestidad automatizado (§3.3, §3.4, §4) | Fase 3 | Alto | Producto funcional end-to-end |
| 5 | Integración a producción de DD Full/Deep Dive como motor de aceleración | Fase 4 | Medio | Horas-analista ahorradas por encargo, medido contra el proceso actual |
| 6 | Empaquetado comercial (tier nuevo entre DD Express y DD Full, si aplica) | Fase 5 con números reales | — | Se decide con datos de la Fase 5, no antes |

**[Likely]** La Fase 2 es la más barata y la más informativa: no requiere escribir el
motor de retrieval todavía, solo el Data Registry (Fase 1) y disciplina manual. Si la
cobertura real sobre preguntas reales resulta baja porque faltan fuentes (no porque
falte el motor), eso es un hallazgo que cambia la prioridad — se resuelve con
`source_intel` (ingesta), no con más ingeniería de orquestación.

## 6. Riesgos técnicos y mitigación

| Riesgo | Mitigación |
|---|---|
| Acoplamiento cross-módulo viola la regla de aislamiento de `CLAUDE.md` | Data Registry es capa de lectura agregada, no importa módulos entre sí ni toca sus tablas — mismo patrón que `shared/tools` ya usa hoy |
| El modelo rellena una brecha con conocimiento paramétrico en vez de declararla | Gate duro §4: el Cerebro solo redacta con pasaje-con-procedencia adjunto; test round-trip en CI |
| Costo de IA por pregunta libre no acotado (a diferencia de un template fijo con costo conocido) | Medir costo/pregunta en el piloto de Fase 2 antes de automatizar en Fase 3-4 |
| Fuentes nuevas que la pregunta requiere y no existen en el corpus | Siguen el flujo `source_intel` existente (propuesta → gate humano) — este motor no la resuelve en vivo dentro de una respuesta a cliente |
| Sobreventa al comprador antes de tener el Data Registry siquiera | No presentar este producto en las reuniones de descubrimiento de precio (protocolo v0.2 §7) hasta cerrar al menos la Fase 2 |

## 7. Fuera de alcance v1 (explícito, para evitar scope creep)

No se construye: motor de búsqueda sobre la web abierta; ingestión de fuentes externas
nuevas en tiempo real dentro de la respuesta al cliente (eso sigue el flujo
`source_intel`); un tier de precio nuevo (se decide en Fase 6, con datos de Fase 5);
reemplazo del `ReportSpec` de `REPORT_STANDARD.md` — este motor lo consume, no lo duplica.

## 8. Próximos pasos concretos

1. Construir el Data Registry (Fase 1).
2. Elegir las 3-5 preguntas reales del piloto (de los compradores ya identificados en
   [[SDQMIP_Productos_Comercializables_Discusion_v0.2]]) y correrlas manualmente (Fase 2).
3. Con los números de cobertura/horas de la Fase 2, decidir si se construye el retrieval
   real (Fase 3) o si primero hay que cerrar fuentes vía `source_intel`.
4. No comprometer fecha ni precio de este motor frente a compradores hasta cerrar el
   punto 3.
