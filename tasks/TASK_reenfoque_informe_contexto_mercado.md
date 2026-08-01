# Tarea — Reenfoque narrativo del Informe de Contexto de Mercado (eje brand_intel, piloto McDonald's)

> **Para:** Claude Code. **Tipo:** rediseño de contenido narrativo (no de chrome/PDF, no de
> cálculo de cifras) + reestructuración de secciones.
> **Origen:** Ricardo revisó `SDQ-MIP_informe_explicativo_mcdonalds.pdf` (piloto real, Nov'25 +
> Mar'26) y objetó que el reporte es mecánico — repite ~46 veces el patrón «{proveedor}
> concluye: «X»» / «Lectura SDQ: Y», con frases de plantilla casi idénticas, tablas con
> columnas técnicas sin traducir (`Origen: solo_marca`, `Estado: Utilizable`), y tres
> secciones enteras que hoy son un placeholder de una frase ("Aún no hay pronósticos
> puntuados..."). Pide el registro Deep Dive que ya usan los otros 6 ejes: ejecutivo,
> sintético, que no le repita al lector lo que ya leyó en el informe del proveedor.
> **Proceso:** Plan First (este documento — confirmar con Ricardo antes de codear si algo no
> está claro), Verify Done con Sensors, Reviewer Subagent antes de cerrar, `tasks/lessons.md`
> al terminar. Antes de cerrar las secciones 3 y 4 de abajo, generar el informe de McDonald's
> real (Nov'25 + Mar'26, ya cargado en el tracker) con el pipeline viejo y el nuevo y mostrarle
> el diff a Ricardo — mismo criterio que ya aplicaron en `TASK_legibilidad_reportes_audiencia_mixta.md`
> para `market_brief`/`digest.py`: es contenido que ya está en manos de un cliente potencial
> (Ipsos/McDonald's), no un fix mecánico.

## Decisiones de Ricardo (ya cerradas, no reabrir)

1. **Motor narrativo: enrutar por `cerebro`, no reescribir plantillas a mano.** Nueva entrada
   en `AXIS_DOCTRINE`/`AUDIENCE_FRAMES` para `brand_intel`, igual que los otros 6 ejes. El LLM
   narra sobre datos YA calculados por `explain.py` — nunca decide causalidad, nunca inventa
   cifras. `explain.py` sigue siendo la única fuente de verdad del cruce macro↔métrica.
2. **Las secciones estructuralmente vacías con 2 olas** (pronóstico puntuado, ticket en pesos
   constantes cuando no hay serie, seguimiento de decisiones) **se comprimen a una nota dentro
   de Límites**, no quedan como secciones tituladas propias. Un reporte con 3 títulos de
   sección seguidos de "aún no hay X" se lee incompleto, no honesto.

## Contexto / causa raíz (verificado leyendo el código real, no una impresión del PDF)

**A. El patrón mecánico vive en dos archivos, es determinista a propósito, y esa parte del
diseño es correcta — el problema es que nunca pasa por el registro de voz del núcleo.**

- `modules/brand_intel/engines/explain.py` calcula, sin LLM, qué factor macro explica cada
  movimiento (`explain_conclusions()`). Su docstring lo declara explícito: *"Determinista a
  propósito... un modelo redactando causalidad libre es la manera más rápida de imprimir una
  explicación falsa con tono seguro."* — **esta garantía no se toca**. Pero la redacción de la
  lectura sale de un puñado de plantillas fijas: `_competitive_reading()` (líneas ~227-244)
  tiene exactamente **4 frases posibles** para TODAS las conclusiones de percepción
  (favorito, opinión, fidelidad, satisfacción, delivery, atributos) según dirección × postura
  del entorno — de ahí que el PDF repita casi textual "Indicador de percepción: el entorno
  económico no lo explica; el movimiento es dinámica competitiva entre marcas" ~20 veces.
  `_environment_reading()` (líneas ~155-225) tiene un poco más de variación pero el mismo
  problema de fondo: la prosa es plantilla, no síntesis.
- `modules/brand_intel/report_docs.py::narratives_and_tables()` es el punto ÚNICO donde ese
  output se convierte en el markdown que ve el cliente — ahí vive literalmente el f-string
  `f"**{proveedor} concluye:** «{e['claim']}»\n\n**Lectura SDQ:** {e.get('reading') or ''}"`
  aplicado en un loop sobre CADA conclusión (líneas ~100-112). Es el reemplazo directo del
  patrón que hoy se ve mecánico en el PDF.
- El resumen ejecutivo SÍ existe (`report.py::_executive()`, línea 97) pero es meta: cuenta
  cuántas conclusiones tuvieron capa explicativa ("8 conclusiones con porqué económico"), no
  sintetiza qué le pasó a la marca el trimestre. Por eso la sección 1 del PDF ("Las lecturas
  del trimestre") son dos bullets de conteo, no un resumen ejecutivo real.
- `modules/brand_intel/report_docs.py::SECTIONS` (líneas ~26-40) define el orden y título de
  las 13 secciones del documento — es la lista a reestructurar (ver Cambios §3).

**B. `brand_intel` nunca pasó por el motor compartido (`shared/narrative/cerebro.py`).**
Confirmado por grep: sin ocurrencias de `cerebro`, `claude_engine`, `axis=` en todo
`modules/brand_intel/`. No hay entrada `"brand_intel"` en `AXIS_DOCTRINE` (líneas 174-378) ni
en `AUDIENCE_FRAMES` (líneas 386+). Es el mismo patrón que ya diagnosticaron y corrigieron en
`TASK_legibilidad_reportes_audiencia_mixta.md` para `market_brief`/`digest.py`: una superficie
de reporte nueva que se construyó con su propia maquinaria en vez de heredar la doctrina y la
disciplina epistémica del núcleo. La regla que esa tarea dejó escrita en `lessons.md` —"toda
ruta de generación de narrativa nueva hereda EPISTEMIC_STANDARD por defecto"— aplica acá
directo.

**C. El chrome (portada, tipografía, paginación) NO se toca.** `report_docs.py::render()`
llama a `shared.products.render_product_pdf` — el renderizador único de la plataforma. El
rediseño es 100% de contenido narrativo y de qué secciones existen, cero de layout.

**D. Ya existe prueba interna de que estos datos funcionan en registro Deep Dive.**
`Alianzas/SDQ-Ipsos/capa3-analisis.md` y `producto-informe-contexto-mercado.md` (escritos a
mano por el equipo) demuestran el mismo contenido en prosa consultiva plena;
`Alianzas/SDQ-Ipsos/lamina-demo-mcdonalds.html` lo prueba visualmente. No hay que inventar el
tono desde cero — hay que hacer que el pipeline lo produzca solo.

## Cambios

Los diffs exactos NO vienen pre-escritos en este documento (a diferencia de
`TASK_legibilidad_reportes_audiencia_mixta.md`, que ya traía diffs verificados) — lo de abajo
es la especificación funcional. Investigar el código real al implementar; si algo difiere de
lo citado acá (líneas movieron desde esta redacción), adaptar manteniendo la intención y
avisar en el commit.

### 1. `shared/narrative/cerebro.py` — nueva doctrina de eje

Agregar `AXIS_DOCTRINE["brand_intel"]` siguiendo el mismo formato que `"insurance_intel"` o
`"banking"` (ver esas entradas como plantilla de tono/estructura). Debe cubrir, como mínimo:

- El rol del informe: SDQ NO repite lo que el tracker del proveedor (Ipsos u otro) ya mide con
  más autoridad — su aporte es el porqué económico (atribución categoría/marca, contexto
  macro) y la disciplina de qué movimiento alcanza para decidir (umbral de detección).
- Instrucción explícita de NO citar cada hallazgo del proveedor uno por uno: el lector ya leyó
  ese informe. Citar la fuente solo cuando la cifra específica sostiene el argumento.
- TRADUCE EL TECNICISMO (mismo bullet que ya generalizaron en el núcleo de `REGISTER_NEUTRO`
  en la tarea de legibilidad — heredado automático, no hace falta repetirlo acá, pero la
  doctrina de eje debe reforzarlo con el vocabulario propio: T2B, awareness espontáneo/TOM,
  índice de atributo por doble indexación, movimiento mínimo detectable).
- REGLA DURA reforzada para este eje específicamente: la narrativa NUNCA decide qué factor
  macro explica un movimiento — esa decisión ya la tomó `explain.py` de forma determinista y
  llega en el contexto como `entorno`/`explicadas`/`competitivas`/`sin_capa`. El LLM sintetiza
  y prioriza esa lectura ya hecha; no la recalcula ni la contradice.

Agregar también `AUDIENCE_FRAMES["brand_intel"]` con al menos un frame default orientado a
quien toma decisiones de producto/marketing/operación de la marca (p.ej. `"cliente_marca"`:
decide dónde poner presupuesto y foco operativo el próximo trimestre). Si el catálogo de
clientes de brand_intel va a incluir perfiles distintos (franquiciante vs. equipo de
marketing local), confirmar con Ricardo si hace falta más de un frame — no asumir.

### 2. `shared/narrative/claude_engine.py` — nuevo THIN_TEMPLATE

Agregar una entrada a `THIN_TEMPLATES` (ver `"research_answer"` como plantilla del patrón de
"REGLA DURA DE CIFRAS: usá SOLO los números servidos en el contexto") para la síntesis del
Informe de Contexto de Mercado. Debe producir, en una sola llamada o en llamadas separadas por
sección (a decidir en implementación, evaluando costo/latencia — ver Sensores), la prosa de:
resumen ejecutivo (síntesis real del trimestre, no meta-conteo), lectura del estudio
(consolidando `explicadas` + `competitivas` sin el patrón cita-por-cita), y "qué mover y qué
no" (fusión de agenda de vigilancia + filtro de señal, ver §3). REGLA DURA explícita en el
template: usar solo las cifras que ya vienen en `explanations`/`attribution`/`signal_filter`
del contexto — cero cifras nuevas, cero relaciones no dadas.

### 3. `modules/brand_intel/report_docs.py` — reestructurar `SECTIONS` y `narratives_and_tables()`

Nueva lista de secciones (reemplaza las 13 actuales):

```
executive            → "Resumen ejecutivo"            (nuevo: síntesis real, vía cerebro)
explanations         → "Lectura del trimestre"         (vía cerebro, sin cita 1:1)
priorities           → "Qué mover y qué no"             (fusión: vigilance_agenda + signal_filter)
ticket                → "El ticket en pesos constantes" (igual que hoy si hay serie; si no, una
                                                          línea, no título propio si queda vacío
                                                          en las próximas 1-2 olas — evaluar con
                                                          Ricardo si ya vale la pena tenerlo aparte)
attribution           → "¿La marca o el mercado?"        (igual que hoy — la tabla se queda, ya
                                                          es legible; se le puede sumar 1-2 frases
                                                          de síntesis vía cerebro si el volumen de
                                                          filas lo justifica)
methodology, sources, limits → igual que hoy
```

Sacan de ser secciones propias tituladas: `forecast_backtest`, `forecast_track_record`,
`scenarios`, `vigilance` (el panel de vigilancia SÍ puede quedar, ver nota abajo),
`decisions`. Su contenido honesto ("aún no hay pronósticos puntuados: el track record se
construye a partir de la próxima ola", "aún no hay decisiones registradas...") se mueve a
`_limits()` (`report.py`, línea 227) como uno o dos ítems más de la lista de límites
declarados — no desaparecen, solo dejan de ocupar un título de sección completo.

Nota sobre `vigilance` (panel de indicadores macro con fuerza `contextual`): evaluar si se
fusiona dentro de "Lectura del trimestre" (es literalmente el insumo que explain.py usa) en
vez de quedar como panel de tabla aparte — decisión de implementación, no bloqueante.

`Escenarios y lectura de la banda` (hoy sección `scenarios`): Ricardo no se pronunció
específicamente sobre esta tabla en la revisión — es sustantiva (no vacía) y distinta de las 3
secciones vacías que sí aprobó comprimir. Mantenerla, pero evaluar si es una tabla dentro de
"Qué mover y qué no" en vez de sección propia, dado que hoy son 13 secciones y varias son
livianas.

### 4. `modules/brand_intel/report.py` — construir el `context` para cerebro

En `build_report()` (línea 30) o en un paso nuevo antes del render, ensamblar el diccionario
que se le pasa a `narrative_engine.generate(context=..., template=..., axis="brand_intel",
audience=..., mode="detailed")` a partir de lo que YA calculan `svc.explanations_analysis`,
`svc.attribution_analysis`, `svc.signal_filter`, `svc.vigilance_analysis` — no recalcular nada,
solo servírselo al LLM en el `context` tal como hoy se le sirve a las plantillas mecánicas de
`report_docs.py`.

`_executive()` (línea 97) deja de construir el resumen ejecutivo por reglas fijas (conteo de
findings) y pasa a ser el `context` de entrada para la llamada de cerebro del resumen
ejecutivo — el `empty_reason` actual (cuando no hay insumos) se conserva como fallback si
`generate()` cae a la ruta legacy o si `xp.get("available")` es falso.

## Salvaguardas — no negociables

- `explain.py` sigue siendo la única fuente de causalidad y cifras. Cerebro narra, no decide.
  Si al implementar aparece la tentación de dejar que el LLM "mejore" o "amplíe" la lectura
  macro más allá de lo que `explain_conclusions()` ya determinó, es una señal de que el
  contexto que se le está pasando es insuficiente — corregir el contexto, no la regla.
- Revisar si `shared/narrative/numeric_guard.py` (el guardrail anti-alucinación de la ruta
  cerebro) necesita extenderse para verificar cifras de brand_intel (T2B, pp, base_n) o si ya
  cubre el patrón genéricamente — no asumir sin comprobar.
- No relajar `EPISTEMIC_STANDARD` ni su `REGLA DURA`/`REGLA DE JUICIO`. La instrucción de
  "traducir el tecnicismo" y "incertidumbre en prosa" ya están generalizadas en el núcleo
  (`REGISTER_NEUTRO`, tras `TASK_legibilidad_reportes_audiencia_mixta.md`) — se heredan solas,
  no hay que reescribirlas acá.
- No tocar `shared/products/render.py` ni `shared/products/report_sections.py` (metodología/
  fuentes/glosario auto-generados) — ya funcionan y ya los reutiliza brand_intel.
- No extender este cambio a otros ejes ni módulos — es un piloto acotado a `brand_intel`.

## Antes de cerrar

Generar el Informe de Contexto de Mercado de McDonald's real (los datos de Nov'25 + Mar'26 ya
cargados en `SDQ-MIP_plantilla_tracker_mcdonalds.xlsx`) con el pipeline viejo y con el nuevo, y
mostrarle a Ricardo el PDF completo antes/después — no un fragmento. Confirmar en esa revisión:
sin repetición mecánica de "concluye/Lectura SDQ", resumen ejecutivo que sí sintetiza el
trimestre, ninguna sección vacía con título propio, vocabulario técnico traducido antes de la
cifra, y que ninguna cifra del PDF nuevo difiera de las del PDF viejo (mismo dato, otra prosa).

## Sensores (correr y reportar output antes de cerrar)

```bash
ruff check shared/narrative modules/brand_intel
pytest shared/narrative/tests/ modules/brand_intel/tests/ -v \
    -k "cerebro or claude_engine or brand_intel or report_docs or explain"
python3 -m py_compile shared/narrative/cerebro.py shared/narrative/claude_engine.py \
    modules/brand_intel/report.py modules/brand_intel/report_docs.py \
    modules/brand_intel/engines/explain.py
```
Si no hay suite de tests para `modules/brand_intel/`, crear una nueva cubriendo al menos lo de
Tests obligatorios abajo.

## Tests obligatorios

- `AXIS_DOCTRINE["brand_intel"]` y `AUDIENCE_FRAMES["brand_intel"]` existen y `build_system("brand_intel", ...)` no lanza error.
- `THIN_TEMPLATES` trae la entrada nueva y `generate(..., axis="brand_intel")` no cae a la ruta
  legacy con un contexto de muestra válido (test de regresión directo — mockear
  `client.messages.create`).
- `report_docs.SECTIONS` refleja la lista nueva (7-9 secciones, no 13); ninguna de las 3
  antiguas vacías (`forecast_backtest`/`forecast_track_record`, `scenarios` si se decide
  fusionar, `decisions`) aparece como título de sección propio en la salida de
  `narratives_and_tables()`.
- Con un `payload` de muestra donde `explanations.available=False` (sin insumos), el reporte
  sigue generando sin excepción y cae al `empty_reason` explicativo — no debe quedar en blanco
  ni romper el render.
- E2E: generar el informe de McDonald's real (ver "Antes de cerrar") y confirmar visualmente
  ausencia del patrón `{proveedor} concluye` repetido más de 2-3 veces (uso puntual donde la
  cifra lo amerita es aceptable; el patrón sistemático no).
- Revisión manual (no automatizable): releer el resumen ejecutivo y "Lectura del trimestre"
  nuevos en voz alta — si repite información que el lector ya tiene del informe de Ipsos sin
  agregar la lectura SDQ, no está listo.

## Definition of Done

- El PDF de McDonald's (Nov'25 + Mar'26) ya no repite el patrón mecánico de cita 1:1; el
  resumen ejecutivo sintetiza el trimestre en vez de contar hallazgos; ninguna sección queda
  con título propio y contenido vacío (se movieron a Límites).
- Ricardo vio y aprobó el PDF completo antes/después.
- `explain.py` no cambió su lógica de atribución/causalidad — mismo output de cifras, solo
  cambió quién redacta la prosa a partir de ese output.
- Sensores en verde, reviewer subagent sin críticos.
- `tasks/lessons.md` actualizado: síntoma (tercera — cuarta, contando `digest.py` — superficie
  de reporte narrativo que se construyó sin pasar por `cerebro`), causa raíz (mismo patrón que
  `TASK_legibilidad_reportes_audiencia_mixta.md`: cada eje/producto nuevo arma su propia
  maquinaria de texto en vez de registrarse en `AXIS_DOCTRINE`), regla (todo módulo de
  `modules/` que genere narrativa reader-facing se registra en `AXIS_DOCTRINE` desde el
  primer commit, no como refactor posterior), disparador (agregar un módulo de sector/eje
  nuevo sin darle entrada en `AXIS_DOCTRINE`/`AUDIENCE_FRAMES`).

## NO hacer en esta tarea

- No tocar `shared/products/render.py` ni `report_sections.py`.
- No relajar `EPISTEMIC_STANDARD`.
- No extender el patrón a otros módulos de `modules/` fuera de `brand_intel`.
- No cerrar sin que Ricardo vea el PDF completo antes/después (no un extracto).
- No desplegar a Railway ni hacer commit sin que Ricardo revise el diff.
