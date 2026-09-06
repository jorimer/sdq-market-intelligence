# Lecciones aprendidas

> Bitácora de patrones de error y reglas para no repetirlos.
> Revisar al inicio de cada sesión. Agregar entrada después de cualquier corrección del usuario.

## Formato

Cada entrada sigue esta estructura:

```
### YYYY-MM-DD — <título corto>

- **Síntoma**: qué se observó (tests rojos, comportamiento incorrecto, comentario del usuario).
- **Causa raíz**: por qué pasó realmente (no el síntoma).
- **Regla**: qué hacer distinto la próxima vez. Concreta y verificable.
- **Disparador**: cuándo aplica esta regla (contexto en que se debe recordar).
```

---

## Entradas

### 2026-06-07 — Errores user-facing en español legible, nunca la excepción cruda

- **Síntoma**: el usuario vio en la UI un error crudo `(psycopg2.errors.InvalidTextRepresentation) invalid input value for enum banktype...` como JSON. Lo señaló dos veces: "este mensaje de error no debería ser en JSON, pues no le da información útil al usuario final".
- **Causa raíz**: el backend propagaba la excepción tal cual al estado de sync que la UI muestra; no había capa de traducción.
- **Regla**: todo mensaje que llegue al usuario va en español claro y accionable. La excepción/traceback/JSON técnico solo va a los logs. Usar el patrón `_friendly_error` en `modules/banking_score/sib_sync.py` para mapear excepciones a mensajes legibles.
- **Disparador**: cualquier error que pueda terminar en la UI (jobs en background, respuestas de API, estados de sync).

### 2026-06-07 — Revisar el SCOPE completo del spec antes de implementar

- **Síntoma**: se construyó la conexión SIB para banca, pero el spec ya incluía las demás entidades supervisadas (corporaciones de crédito, casas de cambio/cambiarias, fiduciarias) y la UI de carga existía sin estar enlazada en el menú. Generó retrabajo y sensación de "no está hecho".
- **Causa raíz**: se atacó la parte obvia del módulo sin leer a fondo todo el SPEC ni el prototipo de UI.
- **Regla**: al enfrentar un módulo nuevo, leer su `SPEC.md` entero + la UI/prototipo y listar TODO el alcance (tipos de entidad, pantallas, estados, fuentes) antes de codear. Combinar con la disciplina de investigar-antes-de-proponer.
- **Disparador**: inicio de trabajo sobre cualquier módulo o feature nuevo.

### 2026-06-07 — Proponer proactivamente los huecos/mejoras detectados

- **Síntoma**: la sincronización no daba de alta entidades nuevas; el usuario tuvo que preguntar "si aparecen entidades nuevas, ¿la sincronización no las añade?". Comentó: "este tipo de hallazgos podrías haberlo detectado como una mejora que propondrías".
- **Causa raíz**: detecté gaps al construir pero esperé a que el usuario los descubriera en vez de señalarlos.
- **Regla**: cuando detecte un hueco o mejora durante la construcción/revisión, señalarlo y proponer la mejora como parte del trabajo, sin esperar a que pregunten.
- **Disparador**: mientras implemento o reviso código y noto un caso no cubierto.

### 2026-06-07 — Jobs en background deben mostrar progreso y estado compartido entre workers

- **Síntoma**: el backfill "parecía muerto" — corría pero la UI no mostraba avance; el estado en memoria era invisible porque Railway corre 2 workers uvicorn.
- **Causa raíz**: el estado de sync vivía en memoria por proceso; cada worker veía un estado distinto y la UI a veces no lo veía.
- **Regla**: ningún job corre en silencio. Persistir estado/fase/conteos en DB (patrón `AppSetting sib_sync_status` en `sib_sync.py`), con heartbeat por update, y que la UI haga polling y muestre fase + conteos mientras `is_running`. Nunca estado solo-en-memoria si hay >1 worker.
- **Disparador**: cualquier proceso largo en background (sync, backfill, importación, reporte).

### 2026-06-07 — Usuario no técnico: ejecuto YO todo lo técnico (incl. Railway CLI)

- **Síntoma**: tendía a pasarle pasos técnicos al usuario; él recordó "favor revisar la regla con respecto a los temas técnicos y el operador".
- **Causa raíz**: asumí que tareas de infra/CLI (Railway) las haría el operador.
- **Regla**: ejecuto yo todos los pasos técnicos, incluido Railway CLI (variables, logs, deploys). Solo delego lo que SOLO el usuario puede o debe hacer: login/autenticación y entrada de secretos. Nunca creo cuentas ni autentico como el usuario.
- **Disparador**: cualquier tarea que requiera terminal, CLI, despliegue o configuración de infraestructura.

### 2026-06-07 — Portar del repo original probado, no reinventar

- **Síntoma**: empecé a reescribir el ETL del SIB cuando ya existía probado y optimizado en `financial-analysis-agent`.
- **Causa raíz**: no consulté primero la fuente de verdad existente.
- **Regla**: si existe una implementación probada en `/Users/ricardomercado/Developer/financial-analysis-agent`, portarla (verificar con diff/git log), no reinventarla.
- **Disparador**: al construir extracción/ETL/integración que el repo original ya pudo haber resuelto.

### 2026-06-07 — Las adiciones de valores a enum de Postgres requieren migración explícita

- **Síntoma**: insertar un banco `corporacion_credito` falló con `invalid input value for enum banktype`, aunque el enum en código ya tenía el valor.
- **Causa raíz**: Alembic autogenerate NO detecta valores nuevos de un enum; el tipo `banktype` en Postgres seguía con los valores originales.
- **Regla**: al agregar valores a un enum usado en Postgres, escribir migración manual con `ALTER TYPE ... ADD VALUE IF NOT EXISTS` dentro de `op.get_context().autocommit_block()`, no-op en SQLite. Ver `b7c1e9a2d3f4_add_banktype_enum_values.py`.
- **Disparador**: cualquier cambio que agregue valores a un `Enum` mapeado a Postgres.

### 2026-06-07 — Verificar el comportamiento real de una API antes de "optimizar" a ciegas

- **Síntoma**: la extracción era lenta (registros=100, ~30 min/tipo) y truncaba a 20k. Iba a asumir límites de la API.
- **Causa raíz**: no había confirmado qué parámetros honra la API del SIB antes de elegir tamaños de página.
- **Regla**: antes de optimizar paginación/tamaños, probar el comportamiento real con un diagnóstico (endpoint `sib-page-test`). Se comprobó que la API honra `registros` hasta ≥2000 → `PAGE_SIZE=5000`, ~20× más rápido y sin truncar.
- **Disparador**: al ajustar paginación, batching o rendimiento contra una API externa.

### 2026-06-07 — Jobs reanudables: upsert idempotente + acks_late, y evitar churn de deploys

- **Síntoma**: corridas largas de backfill se reinterrumpían por mis deploys seguidos; con `task_acks_late` se re-encolaban pero nunca cerraban una pasada limpia.
- **Causa raíz**: desplegar a `main` durante un job largo reinicia el contenedor/worker y reinicia el job.
- **Regla**: (a) diseñar jobs idempotentes — upsert por clave única `(bank_id, period_end)` para que reintentar no duplique; (b) usar `task_acks_late` para re-encolar al reinicio; (c) NO desplegar mientras corre un job largo en background — dejarlo converger primero.
- **Disparador**: jobs largos en background sobre datos persistentes, y decisiones de cuándo hacer push a `main`.

### 2026-06-07 — Investigar a fondo y proponer plan antes de tocar producción

- **Síntoma**: tendencia a aplicar fixes directos en prod ante un error.
- **Causa raíz**: saltar el diagnóstico por aparente obviedad.
- **Regla**: nada de guess; investigar a fondo, llegar a una conclusión y proponer un plan de acción para aprobación antes de aplicar fixes en producción.
- **Disparador**: cualquier incidente o cambio que afecte el entorno de producción.

### 2026-06-07 — Ingesta de datos organizada como menú "Datos" con submenús por sector

- **Síntoma**: la carga de datos no tenía un lugar claro en la navegación.
- **Causa raíz**: faltaba una estructura de navegación pensada para multi-fuente.
- **Regla**: exponer la ingesta de datos bajo un grupo de menú "Datos" con submenús por sector (multi-fuente), no enterrada en cada módulo. Ver `frontend/src/shared/layout/nav.ts`.
- **Disparador**: al añadir nuevas fuentes/sectores de datos a la plataforma.

### 2026-06-08 — Verificar la SEMÁNTICA real de un campo de API, no solo que exista

- **Síntoma**: el backfill de cambiarias (EIC) ingirió 0 de 41 entidades — todas fallaron "entidad no catalogada", pese a que la extracción EIC funcionó (logs: "6/36 cambiarias"). 40 min de corrida perdidos.
- **Causa raíz**: asumí que el campo `tipoEntidad` del SIB traía el CÓDIGO ("ARC"/"AC"); en realidad trae el NOMBRE completo ("AGENTES DE REMESAS Y CAMBIO"). Mi mapa `_TIPO_TO_BANKTYPE` no lo reconocía → `bank_type=None` → rechazo.
- **Regla**: antes de leer un campo de una API para mapear/decidir, verificar su VALOR real (no solo que el campo exista). Si conozco el parámetro con que consulté (p.ej. `tipoEntidad=ARC`), usar ESE valor conocido, no re-leerlo del registro de respuesta. Probar con un registro real (había evidencia: un log EIF mostraba `'tipoEntidad': 'BANCOS MÚLTIPLES'`).
- **Disparador**: al mapear/clasificar a partir de campos de una respuesta de API externa.

### 2026-06-08 — No disparar un job de prod mientras un deploy está en rollout

- **Síntoma**: el primer backfill se interrumpió ("(interrumpido)", resultado viejo) porque lo disparé ~90s tras el merge, con el deploy aún desplegándose; el worker viejo murió a mitad de extracción.
- **Causa raíz**: `health 200` NO garantiza que el rollout terminó (el contenedor viejo responde 200 durante el rollout).
- **Regla**: antes de disparar un job largo en prod tras un merge, esperar a que el deploy esté estable: ventana fija (~160s) + varios `health 200` consecutivos, y confirmar `is_running=false`. Mejor: no mergear/desplegar mientras un job largo corre.
- **Disparador**: disparar backfill/sync/import en prod justo después de un merge a `main`.

### 2026-06-09 — Datos de una API: verificar UNIDADES y JERARQUÍA, no solo el nombre

- **Síntoma**: el modelo de bancos daba disparates (ROA=418M, solvencia=0.0001, liquidez=−477) aunque cada campo "mapeaba".
- **Causa raíz**: (a) **unidades distintas por endpoint** — el balance del SIB viene en pesos, los indicadores/solvencia en millones; sumarlos/dividirlos entre sí rompe todo. (b) **jerarquía** — el balance trae un subtotal `conceptoNivel3=TODOS` por cada `conceptoNivel2` MÁS sus hijos; sumar todas las filas hace doble conteo e infla los activos.
- **Regla**: al consumir absolutos de varias fuentes, (1) confirmar la **unidad** de cada una con un dato real y normalizar; mejor aún, preferir los **ratios % ya calculados** (adimensionales) y calcular el resto desde UNA fuente consistente (el balance en pesos). (2) Para datos jerárquicos, leer solo el nivel de subtotal (`=TODOS`), nunca sumar subtotal + hijos.
- **Disparador**: ETL que combina balance + indicadores + solvencia, o cualquier fuente con árbol de conceptos.

### 2026-06-09 — Enumerar TODO el catálogo de endpoints/jerarquía antes de declarar un dato "no disponible"

- **Síntoma**: 3 indicadores de calidad (castigos, HHI ingresos, exposición inmobiliaria) se daban por "no publicados por el SIB". En realidad SÍ estaban: castigos en `indicadores/morosidad-estresada`, el desglose de ingresos en el árbol profundo (niveles 4-7) de `estados/resultados/eif`, y la exposición hipotecaria en `indicadores/riesgo-credito`.
- **Causa raíz**: (a) el ETL viejo solo probó 2 de los 4 endpoints de `indicadores/` y ninguno de los nuevos; (b) los slugs nuevos usan **guion** (`morosidad-estresada`, `riesgo-credito`) y los intentos sin guion daban 404 → se concluyó "no existe"; (c) se asumió que el estado de resultados era "limitado" porque solo se leyó hasta `conceptoNivel2`, cuando el árbol tiene 7 niveles con todas las fuentes de ingreso.
- **Regla**: antes de declarar un dato inexistente, (1) enumerar el catálogo COMPLETO de endpoints del portal del proveedor (no solo los que ya usás); (2) probar variantes de slug (con/sin guion, singular/plural) con el diagnóstico `sib-page-test`; (3) para endpoints jerárquicos, recorrer TODOS los niveles de concepto (revisar `dimensions`/`sample` del diagnóstico), no solo los primeros. Un 404 en un slug adivinado no prueba que el recurso no exista.
- **Disparador**: cuando un indicador queda N/D por "dato no disponible" en una API externa con catálogo amplio o estructura jerárquica.

### 2026-06-10 — Rutas literales de FastAPI no deben chocar con rutas `/{param}/...`

- **Síntoma**: `GET /sector/insight` devolvía 404 "Banco sector no encontrado"; la tarjeta de IA del Dashboard mostraba "Error al cargar".
- **Causa raíz**: la ruta parametrizada `GET /{bank_id}/insight` (registrada antes) matcheaba `/sector/insight` con `bank_id="sector"`. FastAPI resuelve por orden de registro y `/{bank_id}/insight` captura cualquier `/<X>/insight`.
- **Regla**: una ruta literal de dos segmentos cuyo 2º segmento coincide con el de una ruta `/{param}/<lit>` choca. Solución: agrupar las literales bajo un prefijo propio que NO coincida (ej. `/insight/sector` en vez de `/sector/insight`), o registrarlas antes de la parametrizada. Verificar con un GET real tras agregar endpoints nuevos cerca de rutas `/{id}/...`.
- **Disparador**: agregar endpoints con segmentos literales en un router que ya tiene rutas `/{id}/algo`.

### 2026-06-10 — En árbol jerárquico, leer el SUBTOTAL exacto, no un match por substring

- **Síntoma**: ROA/ROE salían negativos para todos los bancos (Banreservas ROE −2%, real +20%). `utilidad_neta = fv(inc, ["RESULTADO ANTES DEL IMPUESTO"])` devolvía −403M.
- **Causa raíz**: `_find_value_in_records` hace match por substring sobre cualquier `conceptoNivelN` y devuelve la PRIMERA fila. En el árbol del SIB, `conceptoNivel2="Resultado antes del impuesto"` lo tienen TODAS las filas operacionales (hojas incluidas); la primera era una hoja de gasto ("Otros gastos"), no el subtotal del resultado.
- **Regla**: para leer el valor de un nodo en un árbol jerárquico del SIB, apuntar a su fila de **subtotal** exacta vía la convención **TODOS-en-cascada** (el subtotal del nivel N es la fila donde nivel N+1 == "TODOS"), no un substring que cae en una hoja. Ej.: resultado antes de impuesto = `conceptoNivel2="Resultado antes del impuesto"` AND `conceptoNivel3="TODOS"`. Mismo patrón mordió en el HHI de ingresos. Verificar el valor contra un dato real conocido (Banreservas pre-tax ~24B/año, no −403M).
- **Disparador**: extraer un total/subtotal de un endpoint jerárquico (estados/resultados, situación) del SIB con `_find_value_in_records`/substring.

### 2026-06-11 — Un score bajo "raro" suele ser extracción incompleta, no calibración

- **Síntoma**: Fiduciaria Popular salía **SDQ-D** (el peor tier). La reacción instintiva fue "hay que calibrar los umbrales". Al inspeccionar los campos extraídos, `patrimonio_tecnico` y `utilidad_neta` estaban en **None** (su estado auditado etiqueta distinto que el de Reservas) → solidez/eficiencia colapsadas a ~0 → SDQ-D artificial. Tras robustecer el mapper, Popular pasó a **SDQ-BBB+** sin tocar un solo umbral.
- **Causa raíz**: con un parser por keywords sobre formatos heterogéneos, un dato faltante (None→0) se ve igual que un score genuinamente malo. La "anomalía de calibración" era un hueco de extracción.
- **Regla**: ante un score sospechosamente alto/bajo, **primero inspeccionar los campos crudos extraídos** (vía un diagnóstico que los devuelva), no los umbrales. Calibrar solo cuando los inputs estén completos y verificados. Robustez de mapper: claves alternativas + **identidad contable** (patrimonio = activos − pasivos), fallback al subtotal final (ignorando ceros), `abs()` en montos con signo. La calibración real (p. ej. un indicador que es ~0 para TODA una clase y no discrimina, como la diversificación en fiduciarias mono-línea) se decide DESPUÉS, con el dato completo y con criterio de dominio.
- **Disparador**: un rating/score que sorprende (un líder en el peor tier, o todos clavados en un valor), sobre datos de un ETL por parseo heterogéneo.

### 2026-06-10 — No hardcodear enumeraciones que el backend ya conoce (se desfasan en silencio)

- **Síntoma**: el selector de período del topbar tope **2025-Q2** y abría ahí por defecto, mientras prod tenía ratings hasta **2026-03-31**. Toda la app (período transversal) mostraba datos ~1 año viejos y los 3 trimestres más frescos ni se podían seleccionar. Nadie lo notó hasta verificar en navegador.
- **Causa raíz**: la lista `PERIODS` estaba hardcodeada en el front (`AppContext.tsx`) en vez de derivarse de los datos reales; ya existía `GET /banking-score/periods`. Una lista estática que depende de datos vivos se desfasa cada vez que entran datos nuevos.
- **Regla**: si el backend ya conoce el conjunto (períodos, tipos de entidad, sectores…), **derivarlo en runtime** (con fallback estático por si falla el fetch), nunca hardcodear. Default = el elemento más reciente/relevante, y reconciliar el valor persistido si ya no existe en la lista. Al bumpear el default, versionar la key de localStorage (`*_v2`) para no quedar pegado al viejo.
- **Disparador**: cualquier lista de opciones en UI (selectores, filtros, tabs) cuyo contenido válido dependa de datos que cambian con el tiempo.

### 2026-06-10 — Verificar end-to-end en navegador revela gaps que el endpoint OK esconde

- **Síntoma**: los endpoints de IA (`/insight/compare`, `/insight/scenario`) respondían 200 con narrativa correcta, pero en pantalla la tabla del insight Comparativo salía con **pipes Markdown crudos** (`| Componente | … |`) — el renderer `Markdown.tsx` era minimalista y no parseaba tablas GFM. El backend "verde" no lo delataba.
- **Causa raíz**: verificar solo el backend (curl) no prueba el render. El contrato de datos puede estar bien y la presentación rota.
- **Regla**: para features con salida visual, cerrar la verificación **en el navegador** (no solo curl), en claro y oscuro, mirando el render real. Lo que el usuario ve es la prueba, no el 200.
- **Disparador**: verificar cualquier feature que produzca contenido renderizado (Markdown, tablas, charts, PDF).

### 2026-06-11 — Al portar un módulo probado, no descartes la parte que vas a necesitar

- **Síntoma**: el sync de fiduciarias falló en 7 de 24 PDFs de entidad con "no se pudo
  extraer texto suficiente". Eran **escaneos imagen-only** (sin capa de texto OCR), a
  diferencia de otros del mismo portal que sí la traían (escáner PaperStream con OCR).
- **Causa raíz**: al portar el extractor del repo `financial-analysis-agent` dejé fuera su
  `OCRProcessor` (detect scanned → OCR vía tesseract) "para no arrastrar dependencias
  pesadas". Validé contra un PDF que SÍ tenía capa de texto y asumí que todos la tenían.
  La fuente es heterogénea: unos PDFs son digitales, otros escaneos-con-OCR, otros
  escaneos-imagen-puros.
- **Regla**: cuando portás un módulo probado, mapeá QUÉ resuelve cada parte antes de
  descartarla; la pieza que parece "extra" (OCR) suele cubrir un caso real del dataset.
  Si la dejás fuera, **probá contra muestras variadas** (no un solo archivo "bueno") y
  documentá el gap explícitamente. Para PDFs: detectar texto-extraíble vs imagen, y tener
  un camino OCR para los imagen-only (o declararlos N/D, nunca fabricar).
- **Disparador**: portar/adaptar un pipeline de ingesta o cualquier módulo del repo
  original; validar extracción sobre fuentes heterogéneas.

### 2026-06-11 — Índice compuesto: un solo eje disponible NO es un veredicto

- **Síntoma**: al ver los datos reales en prod, muchos fideicomisos salían "Sólida 100"
  calificados **solo por solvencia** (patrimonio/activos ≈100% en fondos tenedores), con
  liquidez y sostenibilidad en N/D. El ranking quedaba engañoso (fondos parados arriba).
- **Causa raíz**: `compute_health` promediaba las dimensiones disponibles sin mínimo; con
  una sola dimensión, el "promedio" era esa dimensión → veredicto fabricado desde un ratio.
- **Regla**: un índice compuesto sobre cobertura parcial debe exigir un **mínimo de ejes
  medidos** (aquí ≥2 de 3) para emitir banda; por debajo, "Datos insuficientes", no un
  número. Es el corolario de "dato faltante = N/D, nunca acreditar": tampoco se acredita un
  veredicto global desde una sola señal. Verificar con datos REALES revela esto; los tests
  sintéticos con todas las dimensiones presentes no.
- **Disparador**: cualquier índice/score compuesto que promedie sub-dimensiones con
  disponibilidad variable.

### 2026-06-09 — Cubo granular: consultar acotado (período por período) y agregar al vuelo

- **Síntoma**: `carteras/creditos` (cubo de préstamos) devolvía 504 y estaba deshabilitado; se creía que el endpoint estaba roto.
- **Causa raíz**: se consultaba el rango completo (5 años × todos los tipos) de una; el servidor no alcanza a materializar el cubo. Una consulta de **un trimestre / un tipo** responde en ~12s sin 504.
- **Regla**: para datasets granulares pesados, (1) consultar acotado (un período a la vez), paginando; (2) **agregar al vuelo** a la métrica final (p.ej. sumar `deuda` por `sectorEconomico` → HHI) y descartar las filas crudas — nunca acumular cientos de miles de filas en memoria ni en DB; (3) persistir solo el valor derivado por (entidad, período). Es el mismo principio que jobs en background con estado compartido.
- **Disparador**: ETL de un endpoint que devuelve datos a nivel transacción/préstamo/celda de cubo, o que da 504/timeout en consultas amplias.

### 2026-06-09 — Integridad: un indicador sin dato no debe puntuar "perfecto"

- **Síntoma**: calidad/liquidez/diversificación salían idénticas en TODOS los bancos (81.9 / 14.37 / 100) — ~45% del peso fabricado.
- **Causa raíz**: indicadores cuyos inputs no mapeaban computaban 0 → score perfecto (p. ej. morosidad sin datos = 0% = 100). El modelo "inventaba" dato faltante.
- **Regla**: un indicador sin su input es **N/D** (se excluye del promedio del subcomponente); un subcomponente sin indicadores disponibles es N/D y el score global **repondera** sobre lo medido. Nunca acreditar dato faltante. Cada número del rating debe ser trazable a dato real.
- **Disparador**: cualquier scoring/índice compuesto sobre datos externos con cobertura parcial.

### 2026-06-12 — META: "no se puede" es una afirmación que debe ganar su barra de evidencia (anti-falsa-imposibilidad)

- **Síntoma (patrón, no incidente único)**: corrección directa del dueño. Repetidamente se declaró un dato "no disponible / N/D / fuera de alcance" desde una investigación de **una sola capa, superficial** — y luego SÍ estaba. Casos verificados en este mismo archivo: indicadores "no publicados por el SIB" que estaban en slugs con guion / árboles nivel 4-7 (línea 123); concentración top-10 "N/D definitivo" ~4 sesiones cuando el dato estaba en el cubo `carteras/creditos` **que ya se streameaba** (mayores deudores); un 504 leído como "endpoint roto" cuando solo requería consulta acotada (línea 198).
- **Causa raíz**: el criterio "si el alcance no cabe con calidad, reduce el alcance" se aplicaba sin guarda. Reducir alcance por una imposibilidad **no probada** es una falla de calidad disfrazada de disciplina. Falta rigor de investigación, no falta de regla.
- **Regla**: un *"no se puede / N/D / no existe el dato / fuera de alcance por imposibilidad"* es una **AFIRMACIÓN con barra de evidencia**, simétrica a "dato faltante = N/D, nunca fabricar" → **dato alegado como inexistente = sospechoso, nunca asumir**. Antes de aceptarla, agotar: (1) catálogo/schema COMPLETO de la fuente (variantes de slug, jerarquías profundas, params no probados); (2) ¿está en algo que YA traés?; (3) consultas acotadas si la amplia da 504; (4) portales alternativos del mismo emisor. **Escalar, no decidir en silencio**: una imposibilidad se surfacea al dueño con el rastro de búsqueda (qué se probó, qué devolvió) — él tiene dominio que ha desbloqueado lo "imposible" (señaló el portal de supervisados; sugirió el ángulo del cubo). Distinguir reducción de alcance **por decisión** (legítima, con rationale) de **por imposibilidad alegada** (requiere barra + surface). Anti-patrón con nombre: **"falsa imposibilidad" / "N/D prematuro"** — es un bug, no un cierre aceptable.
- **Disparador**: cada vez que estés por escribir "no se puede", "no está disponible", "no lo expone la API", "queda N/D", o por recortar alcance alegando una limitación de la fuente. Antes de escribirlo: ¿agotaste la barra, o te quedaste en la primera capa? Codificado en `docs/PLAN_MAESTRO_DESARROLLO.md` §0.2.

### 2026-06-12 — META: ambición AI-native, no estimar como humano (memoria `feedback-ai-native-ambicion`)

- **Síntoma**: corrección del dueño. Al enmarcar el ETL de 700 Excel del BCRD como "cientos de parsers a mano = un programa de meses", sonó a humano poniendo trabas. El dueño espera **ideas que superen eso** y aprovechen lo que la IA hace y un humano no: analizar volúmenes enormes y heterogéneos e inferir estructura/relaciones a escala. Hermano gemelo de §0.2 ("falsa imposibilidad"): cierre prematuro, disfrazado de esfuerzo.
- **Causa raíz**: (a) se importó calibración humana de tiempo ("meses") — inexacta e irrelevante, Claude no trabaja a ritmo humano; (b) se trató el valor de la IA como "ejecutar trabajo manual más rápido" en vez de **volver tratable lo inviable**; (c) se usó el tamaño para acotar a un piloto en vez de diseñar la solución que colapsa el costo marginal por ítem.
- **Regla**: el valor de Claude NO es trabajo manual más rápido — es lo intratable hecho tratable. Ante volumen/heterogeneidad: **NO** defaultear a "es mucho, acotemos a un piloto"; primero la solución **AI-native** que colapsa el costo por ítem (parser auto-inferente, o Claude interpretando la estructura de cada archivo → config/series normalizadas a escala). Proponer además lo que la IA desbloquea más allá de cargar datos (relaciones entre series, quiebres estructurales, narrativa sobre el corpus, auto-reparación). **Acotar solo por correctitud/validación, nunca por esfuerzo.** Estimar magnitud es legítimo solo como insumo de priorización del dueño (PLAN §3), nunca como razón para rendirse, y debe ser investigada, no adivinada. Anti-patrón: **"falso sobre-esfuerzo" / "desistir por tamaño"**.
- **Disparador**: "esto tomaría meses", "son cientos de parsers a mano", "mejor un piloto acotado", "es demasiado para ahora". Antes: ¿traés trabas humanas? ¿cuál es la solución que colapsa el costo por ítem? ¿qué desbloquea la IA más allá de cargar el dato? Codificado en `docs/PLAN_MAESTRO_DESARROLLO.md` §0.3; memoria canónica `feedback-ai-native-ambicion`.

### 2026-06-13 — Recurrencia §0.2: un solo endpoint del SIB en 0 NO prueba "no publicado"

- **Síntoma**: durante un diagnóstico de cobertura de cambiarias, consulté `estados/resultados/eic` (P&L) para agentes de cambio (AC) en 2026-Q1, dio `count=0`, y concluí ante el dueño "el SIB no publicó AC 2026-Q1; el re-sync no recupera nada". El dueño lo refutó con una captura de **SIMBAD** mostrando AGC DAMOS al mes 3 de 2026. Al enumerar endpoints después, los datos del balance sí existen vía `estados/situacion/eic` para otros períodos, y SIMBAD (portal) muestra cosas que la API abierta aún no expone.
- **Causa raíz**: exactamente el anti-patrón ya codificado (§0.2 "falsa imposibilidad"): cerré "no hay dato" desde **una sola capa** (un endpoint del catálogo EIC: `resultados`, no `situacion`), sin enumerar el catálogo completo ni distinguir las superficies de origen (API abierta `apis.sb.gob.do/estadisticas/v2` vs portal **SIMBAD**).
- **Regla**: para EIC/SIB, "no hay dato para período X" exige **enumerar TODOS los endpoints relevantes** (`estados/situacion/eic` Y `estados/resultados/eic` Y `indicadores/financieros`), por **tipo** (ARC y AC se publican en cadencias distintas) y por **granularidad** (los AC se filan por mes en SIMBAD). Y antes de concluir, distinguir **API abierta ≠ SIMBAD**: el portal puede tener dato que la API aún no expone (rezago/superficie distinta) — preguntar al dueño cuál es la fuente canónica, no asumir. Un `count=0` en un endpoint es una señal, no un veredicto.
- **Disparador**: cualquier afirmación "el SIB no publicó / no hay dato / N/D" sobre cambiarias/fiduciarias o cualquier serie del SIB. Ver también [[local-e2e-browser-verification]] y la entrada META §0.2 de arriba.

### 2026-06-16 — Anti-doble-conteo en jerarquías: la garantía debe ser fail-closed (raise), no un warning

- **Síntoma**: en el conector BCRD de valor agregado por sector (Eje 3, T-E3-1), el docstring prometía que "Σ hojas == Valor Agregado evita el doble conteo", pero el código solo emitía `logger.warning` si la suma se desviaba. El reviewer subagent lo marcó NO APTO: en un sync best-effort en background, un padre ("Industrias"/"Servicios") colándose o una hoja renombrada degradaría los shares **sin frenar nada** y el warning se pierde en logs → dato distorsionado persistido en silencio. Es la lección SIB del subtotal `TODOS` + hijos, en forma de cuentas nacionales.
- **Causa raíz**: documentar una garantía que el código no da. Un guard de integridad que solo loguea no es un guard — es un comentario. En un job automático, "avisar" ≠ "proteger".
- **Regla**: toda invariante de integridad que protege contra fabricación/doble-conteo se implementa **fail-closed**: `raise` (que el runner captura y reporta como error visible en la Consola), nunca un warning silencioso. Validar contra **fuente externa** (el `Valor Agregado` que el BCRD publica como fila propia), no contra la auto-suma (validación circular). Doble defensa: (a) falta una hoja del partition → raise; (b) |Σ hojas − total publicado| > tolerancia → raise. Y el matching de etiquetas, acento/caso-insensible (NFKD+casefold) para tolerar renombres del proveedor. Si el docstring afirma "asserts/guarantees X", X debe ser un `raise`, no un `log`.
- **Disparador**: cualquier ingestión de una tabla jerárquica con subtotales (cuentas nacionales, planes de cuenta, cubos), o cualquier vez que escribas "esto asegura/garantiza" sobre datos en un job best-effort. ¿La garantía es un `raise` o solo un `log`? Codificado además en `docs/PLAN_MAESTRO_DESARROLLO.md` §4 (sin doble conteo).

### 2026-06-16 — Excel del BCRD apila BLOQUES que repiten las mismas etiquetas: parsear solo el primero

- **Síntoma**: en el conector de valor agregado por sector (T-E3-1), el `sector_growth` daba cifras falsas (2025 negativo en casi todos los sectores, total economía −1.7% cuando RD creció ~2%). Se descubrió al armar una matriz para el dueño y notar que el crecimiento no cuadraba con la realidad. El `sector_size` SÍ estaba bien.
- **Causa raíz**: cada hoja del `pib_origen_2018.xlsx` **apila varios bloques que repiten los mismos sectores**: la nominal (`PIB$_Trim`) trae bloque de niveles RD$ **y** bloque de participación %; la real (`PIBK_Trim`) trae bloque de índice de volumen **+** bloque de crecimiento% **+** bloque de incidencia. El parser sumaba TODAS las filas con la misma etiqueta → mezclaba índice+crecimiento+incidencia. El **tamaño** sobrevivió porque el nivel domina y el agregado se cancela en el cociente share=sector/total (Σ=100% se mantenía exacto, engañoso); el **crecimiento** (cociente YoY del índice) quedó corrompido. Una verificación de "Σ=100%" valida proporciones, NO niveles ni cocientes inter-anuales.
- **Regla**: en libros del BCRD con bloques apilados (niveles / participación / crecimiento / incidencia bajo las mismas etiquetas), **parsear solo el PRIMER bloque** — primera ocurrencia de cada etiqueta, cortar al llegar a la segunda fila de total ("Valor Agregado"). Verificar el dato derivado (crecimiento) contra una **realidad externa conocida** (RD creció ~5% 2024, ~2% 2025), no solo contra un invariante de proporción. Un Σ=100% correcto NO prueba que los niveles/cocientes lo sean.
- **Disparador**: ingerir cualquier hoja del BCRD de cuentas nacionales (PIB origen/gasto, IMAE) o cualquier Excel donde el mismo rótulo de fila aparezca más de una vez (nivel vs %, original vs desestacionalizado vs tendencia). Antes de confiar en un cociente/variación derivado: ¿lo verificaste contra una magnitud conocida del mundo real?

### 2026-06-17 — Nada de dato sembrado/fixture en la DB: cada fuente con su backfill real (patrón SIB)

- **Síntoma**: al cablear el IAI sectorial a dato real, en prod aparecían valores viejos (Turismo IAI 82.1, SGPS 70) que no eran del dato real — eran `SectorScore` stale bajo `"2025-Q4"`, restos de cuando el frontend posteaba un fixture `SAMPLE_SECTORS` de 3 sectores. Un fix de ordenamiento de período los enmascaraba, pero el dueño lo corrigió: **no deben QUEDAR datos sembrados/fixture; cada fuente debe tener su backfill real como hicimos con SIB.**
- **Causa raíz**: un índice computado se persistió solo para el período actual y arrastró cruft de flujos viejos (fixture-POST). Enmascarar (ordenar para que el dato bueno gane) no es limpiar; el dato fixture sigue en la DB.
- **Regla**: toda operación que computa un índice persistido debe ser un **backfill que abarca TODOS los períodos con dato real de la fuente** (patrón SIB `score_all_periods`) y **purga** cualquier registro fuera de ese set (los remanentes de fixture/seed). Guard de seguridad: si no hay dato real, retornar sin borrar (nunca `NOT IN ()` que borra todo). Para datos históricos donde una entrada es solo-actual (p.ej. el contrato macro), el histórico usa el valor declarado-neutral, no se estampa el valor actual en el pasado. Principio del dueño: la DB refleja backfills reales por fuente, sin restos sembrados.
- **Disparador**: cualquier operación de "snapshot"/scoring que persista por período; cualquier eje recién cableado a dato real que antes corría sobre fixture. ¿La operación backfillea todos los períodos reales y purga lo demás, o solo escribe el último y deja cruft? ¿Queda algún dato `SAMPLE_*`/seed en la DB?

### 2026-06-19 — Inferencia sobre un panel: IC por cross-section, no bootstrap de pares apilados

- **Síntoma**: el titular del Gate E sectorial era un Spearman con IC bootstrap [-0.24, 0.32] sobre ~60 pares sector-año APILADOS. El CI estaba demasiado angosto: sobre-afirmaba precisión sobre un resultado que en realidad es inconcluso por potencia.
- **Causa raíz**: `spearman_bootstrap_ci` remuestrea pares individuales como si fueran independientes, pero en un panel sector×año las observaciones están CLUSTERIZADAS — por año (shock macro común a todos los sectores ese año) y por sector (efecto persistente). Tratar 60 obs clusterizadas como 60 independientes infla el n efectivo y angosta el CI artificialmente. Corregido (IC dentro de cada año, t sobre la serie de ~6 ICs anuales), el CI es más ancho [-0.37, 0.41] y el veredicto inconcluso queda honesto (no cambia de signo).
- **Regla**: para validar un score sobre un panel entidad×período, el estadístico es el **IC clásico**: correlación dentro de cada cross-section (período), promediada, con inferencia (t de Student, df=k-1) sobre la **serie de los k ICs por período** — NO un único estadístico sobre todos los pares apilados con bootstrap de pares. El bootstrap de pares solo es válido si las obs son intercambiables/independientes; un panel no lo es. Si se reporta el pooled, etiquetarlo como secundario y decir que sobrestima la precisión. Badge honesto: "inconcluso por potencia (n insuficiente)" cuando el IC cruza cero con n chico, no "no significativo" (que sugiere refutación).
- **Disparador**: cualquier backtest de un score sobre un panel (sector/entidad/país × período): banking_score, IRMP, trade_intel, sector_intel. Antes de reportar un IC/Gini con su CI, preguntar: ¿las observaciones están agrupadas por período o por unidad? Si sí, la inferencia va sobre la serie de cross-sections, no sobre los pares apilados.

### 2026-06-20 — Confirmar a qué proyecto pertenece el trabajo antes de escribir en un repo

- **Síntoma**: ante "revisar deal scoring", asumí que era NexusRD (REQ-004 scoring conductual de leads) y escribí un ADR completo en `NexusRD/docs/adrs/`. El usuario corrigió: "ESTO NO VA EN ESTE PROYECTO, SINO EN SDQMIP". Deal scoring es de SDQMIP (probabilidad de cierre de deals de inversión, spec DEAL-Agent-003), no lead scoring inmobiliario.
- **Causa raíz**: hay dos proyectos con "scoring" y los confundí. Aterricé el análisis sobre la primera spec que encontré (NexusRD) sin verificar que el entregable iba a ese repo; el usuario tiene varias carpetas montadas.
- **Regla**: cuando un término (deal scoring, rating, etc.) puede existir en >1 proyecto, identificar el proyecto destino ANTES de escribir cualquier archivo. Si el deliverable es para SDQMIP, leer su spec real (`docs/Modelos Propietarios/`), no asumir desde otro repo. Confirmar ubicación con el usuario si hay ambigüedad.
- **Disparador**: inicio de cualquier tarea cuyo nombre/feature pueda existir en más de uno de los repos montados (NexusRD, SDQMIP, financial-analysis-agent).

### 2026-06-23 — Una narrativa con cifras DEBE pasar `axis=` o se salta el numeric_guard

- **Síntoma** (P0 productización, reviewer): la narrativa del nivel **Pulse** de Banca llamaba `narrative_engine.generate(template="sector_outlook", mode="standard")` sin `axis`. El Pulse inyecta cifras (score promedio del sistema, distribución de bandas, n entidades) y las narraba **sin** el guard anti-alucinación, justo en el nivel ABIERTO/público (máximo riesgo reputacional). El spec exige G3 "guard 0 violaciones".
- **Causa raíz**: en `shared/narrative/claude_engine.py` el `numeric_guard` corre SOLO en la **ruta cerebro**, que se activa cuando se pasa `axis` Y el template está en `THIN_TEMPLATES` Y el axis está en `AXIS_DOCTRINE`. Sin `axis`, cae a la ruta legacy que **no verifica ninguna cifra**. Default silencioso: el código "funciona" (devuelve texto) pero sin gobernanza. `sector_outlook` SÍ es thin y `banking` SÍ tiene doctrina → el camino guardado existía y simplemente no se invocó.
- **Regla**: toda llamada a `narrative_engine.generate` cuyo contexto contenga cifras debe pasar `axis="<eje>"` (y `audience`) para enrutar por el guard. Si el template no está en `THIN_TEMPLATES` o el axis no está en `AXIS_DOCTRINE`, NO hay guard — o se agrega el thin, o no se afirma "narrativa gobernada". Defensa en profundidad para productos de sistema (Pulse): correr también `enforce_anonymized` sobre el TEXTO narrado, no solo el payload. No usar `AssertionError` para violaciones de doctrina (se desactiva con `python -O`): usar el error de dominio (`AnonymizationError`).
- **Disparador**: cablear cualquier narrativa nueva (nuevo sector/nivel/template), sobre todo niveles abiertos/Pulse. ¿La llamada pasa `axis`? ¿El template está en `THIN_TEMPLATES`?

### 2026-06-24 — Cobertura del contrato + guard: el test debe ejercer la ruta DB y el ruteo REAL del template

- **Síntoma** (P5 cierre, sensores): dos brechas que el "verde" escondía. (a) `modules/banking_score/products.py` tenía **69% de cobertura** (<80% del sensor) porque su test sólo ejercía la ruta Pulse-muestra (sin DB); las señales `data_signals`/`has_engine`/`validation_state` y el snapshot nombrado (que consulta `BankingData`) nunca se probaban — y el fixture ni siquiera creaba esa tabla. (b) `app/products_macro.py` enrutaba la sección `recommendation` con `template="recommendation"`, que **NO está en `THIN_TEMPLATES`** → narraba el IRMP (cifra) por la ruta legacy SIN `numeric_guard` (el bug latente `task_fcc7a6b3` destapado en P4-trade).
- **Causa raíz**: (a) cobertura medida sólo sobre el camino feliz sin DB; un contrato que lee la base necesita un fixture con TODAS las tablas que toca (incl. las transitivas como `BankingData` vía `compute_market_concentration`). (b) Elegir el template por el NOMBRE de la sección (`recommendation`→`"recommendation"`) en vez de por el thin del eje; el guard sólo corre si `template ∈ THIN_TEMPLATES` Y `axis ∈ AXIS_DOCTRINE`. Un test que no graba la `(template, axis)` REAL pasada a `narrative_engine.generate` no detecta esto.
- **Regla**: (a) la cobertura ≥80% del contrato de un sector debe ejercer las señales que leen DB con un fixture que cree las tablas transitivas, y las ramas de error del snapshot nombrado (sin scope, entidad inexistente, sin rating). (b) Secciones cuyo "foco" no es thin (`recommendation`/`scenario`/`comparative`/`executive_summary`) se enrutan por el thin del eje (`risk_assessment`/`*_outlook`) con `ctx["enfoque"]`, NUNCA por un template homónimo no-thin. (c) El test de guard debe ser **de comportamiento**: monkeypatchear `narrative_engine.generate` sobre el singleton, correr `narratives()` del tier que incluye la sección, y assertar que cada `(template, axis)` grabado está en THIN_TEMPLATES/AXIS_DOCTRINE — así falla si el bug vuelve (verificado por simulación del mapeo viejo). Codificado en `test_macro_narratives_are_guarded` y `test_banking_pulse_narrative_is_guarded`.
- **Disparador**: cerrar la cobertura de un contrato `SectorProduct`; cablear/auditar cualquier narrativa de sección cuyo foco no sea el outlook del eje. ¿El template está en THIN_TEMPLATES? ¿El test graba la llamada real o sólo el manifiesto?

### 2026-06-23 — Framework sector-agnóstico: el test que lo prueba usa un sector FALSO

- **Síntoma/decisión** (P0 productización): para evitar Frankenstein, el framework `shared/products` no debe importar ningún módulo de sector. La forma de **probarlo**, no solo afirmarlo, es que el test del ensamblador genérico use un `FakeSector` (no banking) que implemente el `Protocol` — si el framework dependiera de banking, el test no compilaría con un sector falso.
- **Regla**: al promover lógica a `shared/` para que sea transversal (como el Cerebro): (a) `grep -rn "from modules" shared/<paquete>/` debe dar vacío, y (b) los tests del núcleo deben ejercitarlo con un implementador FALSO del contrato, no con el sector real. El contrato (Protocol) debe bastar para producir el output sin que el framework conozca el sector; el render específico se delega al sector. Onboarding del sector #N = implementar Protocol + manifiesto + señales, sin tocar el framework (test que lo verifique).
- **Disparador**: cualquier promoción de lógica a `shared/` reusable por varios módulos; cualquier "framework" nuevo. ¿Hay un import de `modules/` colándose? ¿El test usa el sector real (acopla) o uno falso (prueba el desacople)?

### 2026-07-17 — Labels con fallback silencioso + doctrina de voz sin generalizar + rutas de IA huérfanas

- **Síntoma**: (1) tres bugs de template visibles en los 6 Deep Dive entregados a clientes potenciales — tier crudo `deep_dive` en la portada de banca, header corrido repitiendo el nombre del eje (Política Monetaria, Estructura Sectorial), "Std Methodology"/"Std Sources" en inglés en el índice; (2) ningún mecanismo de glosario y el llamado anti-jerga vivía SOLO en `AXIS_DOCTRINE["banking"]`; (3) la ruta legacy de `claude_engine.py` corría sin `EPISTEMIC_STANDARD` (sin regla anti-fabricación en el prompt de market_brief/cross_compare/deal_outlook); (4) una tercera ruta, `shared/publications/digest.py`, generaba narrativa reader-facing sin NINGÚN gobierno de voz (sin `system=` en absoluto).
- **Causa raíz**: fallbacks silenciosos a `key.title()` y a tier crudo sin mapeo de etiqueta; la doctrina de voz y la disciplina epistémica quedaron sin generalizar más allá de lo que cada eje/ruta pidió explícitamente en su momento; las superficies nuevas de generación de narrativa se construyeron ad-hoc con su propio `client.messages.create` en vez de pasar por el motor compartido.
- **Regla**: todo dict de labels con fallback debe fallar ruidoso o loguear en dev, no imprimir la clave cruda en un PDF de cliente. Toda ruta de generación de narrativa nueva hereda `EPISTEMIC_STANDARD` por defecto (opt-out consciente, nunca opt-in). Antes de dar por cerrado un mapeo de "todas las piezas que generan narrativa con IA", correr el grep sistemático de `messages.create|Anthropic(` + imports del motor sobre TODO `shared/` y `modules/`, no confiar en la lista de módulos de sector conocidos.
- **Disparador**: agregar un tier/report_type/sección estándar nueva sin actualizar el mapeo de labels; crear cualquier superficie nueva que llame a Anthropic sin heredar la disciplina epistémica del núcleo; auditorías de cobertura de doctrina.

### 2026-07-18 — Selector de períodos "flaco": snapshot-solo-del-último + read que ignora el período

- **Síntoma**: varios productos por-sector mostraban 1-2 opciones en el selector de períodos (o 0), pese a que sus fuentes traían años de historia. Reportado por el dueño desde el catálogo (Seguros: 2 opciones). Barrido de los 14 sectores: Seguros, Pensiones (0 útiles), Energía, Telecom, Política Monetaria afectados con dos mecanismos distintos.
- **Causa raíz**: DOS defectos que suelen ir juntos. (1) El sync/persistencia materializaba el score/snapshot SOLO del período más reciente de cada corrida → el selector (`distinct_periods(...)`) solo acumulaba los períodos que alguna vez fueron "el último". (2) El `read`/`snapshot` del producto IGNORABA el período pedido y servía siempre el dato actual con la etiqueta del período elegido. Política Monetaria además no implementaba `available_periods` (selector vacío).
- **Regla**: un producto con selector de períodos necesita las TRES piezas juntas: (a) `available_periods` real; (b) backfill que persista un punto POR período histórico donde la fuente lo permita; (c) el `snapshot(period)` debe servir la vista AS-OF (insumos truncados a esa fecha), no el dato actual reetiquetado. Doctrina de COMPARABILIDAD: solo persistir períodos con cobertura PLENA de dimensiones — mezclar años de N y N-1 dimensiones lee como salto falso del índice (patrón ya escrito en `construction_intel.service.backfill_scores`, replicado a energía/telecom). Doctrina de HONESTIDAD point-in-time: un modelo/pronóstico/track-record que refleja el estado ACTUAL NO se reconstruye para fechas históricas (sería fabricar un "pronóstico retroactivo") — se declara la ausencia en prosa llana (Política Monetaria). Tras el deploy, el backfill requiere DISPARAR el sync en prod (idempotente) para poblar la historia; el código solo no basta.
- **Disparador**: agregar/tocar un producto con selector de períodos; revisar `available_periods` + `snapshot(period)` + cómo persiste el sync. Excepción legítima: fuentes con un solo vintage disponible (ESG/IRC — rezago anual genuino) o cobertura plena que exige N años aún no acumulados (Construcción — MIVHED desde 2022); ahí 1 período ES honesto, no un bug.

### 2026-08-01 — Cuarta superficie de narrativa construida sin pasar por el cerebro (brand_intel)

- **Síntoma**: el Informe de Contexto de Mercado de brand_intel (piloto McDonald's, ya en manos de un cliente potencial) se leía mecánico: el patrón «{proveedor} concluye: X / Lectura SDQ: Y» repetido ~46 veces (8 explicadas + 38 competitivas, estas últimas con solo 4 frases-plantilla posibles), tablas con tecnicismos crudos (`Origen: solo_marca`, `Estado: Utilizable`), tres secciones tituladas cuyo único contenido era "aún no hay X", y un "resumen ejecutivo" que contaba hallazgos en vez de sintetizar el trimestre. Objeción directa del dueño.
- **Causa raíz**: la misma que `digest.py`/`market_brief` (2026-07-17): la superficie de reporte nueva se construyó con su propia maquinaria de texto (f-strings en `report_docs.py`, plantillas fijas en `engines/explain.py::_competitive_reading`) en vez de registrarse en `AXIS_DOCTRINE`/`AUDIENCE_FRAMES` y narrarse por la ruta cerebro. La parte determinista del diseño (explain.py decide causalidad sin LLM) es correcta y se conservó; lo que faltó fue separar CÁLCULO (determinista) de REDACCIÓN (cerebro sobre lo calculado). Cuarta superficie con este patrón, contando digest.py.
- **Regla**: todo módulo de `modules/` que genere narrativa reader-facing se registra en `AXIS_DOCTRINE`/`AUDIENCE_FRAMES` + `THIN_TEMPLATES` desde el PRIMER commit, no como refactor posterior. El motor determinista calcula y su output viaja en el `context`; el cerebro redacta con REGLA DURA de no recalcular ni contradecir lo servido (ver doctrina `brand_intel`: "REGLA DURA DE CAUSALIDAD"). Si la narrativa degrada a estático, el documento cae a una composición determinista NO mecánica (agrupar lo repetitivo — p.ej. competitivas por dirección — en vez de una línea por ítem). Secciones estructuralmente vacías declaran su estado en Límites, nunca como título propio con una frase de disculpa. Tecnicismo interno (`solo_marca`, códigos de estado) jamás llega crudo a una tabla de cliente: mapa de labels con fallback observable.
- **Disparador**: agregar un módulo/eje nuevo con reporte narrativo; revisar un PDF que "funciona" pero repite una plantilla; cualquier `f"...{x}..."` que componga prosa de cliente fuera de la ruta cerebro. ¿El eje está en AXIS_DOCTRINE? ¿El template en THIN_TEMPLATES? ¿La llamada pasa axis= y audience=?

### 2026-08-02 — Determinista vs LLM: la línea se traza por RIESGO de la salida, no por preferencia de arquitectura

- **Síntoma/decisión**: para la ingesta de planes del cliente y la sección «El plan bajo el instrumento», el dueño pidió explícitamente ir por LLM "en vez de determinista" — en un módulo cuya doctrina previa (explain.py) es determinista a propósito. No era contradicción: era una tarea DISTINTA. La causalidad macro con tono seguro impresa en un PDF es el riesgo que motivó el veto; leer un documento abierto (cualquier agencia, cualquier formato de plan) y clasificar/prescribir brechas de medibilidad es juicio sobre espacio abierto donde una taxonomía rígida se queda corta con el próximo cliente.
- **Causa raíz** (del casi-error): tratar "determinista" como identidad del módulo en vez de como salvaguarda dirigida a un riesgo concreto. La regla correcta separa por capa: (a) aritmética/veredictos que alimentan decisiones → mecánicos siempre (check_feasibility, umbrales detectables, reparto explicadas/competitivas); (b) lectura de documentos, clasificación de brechas, prescripciones y narrativa → LLM con recibo (claim literal + página), schema estructurado y guard numérico; (c) el cruce se protege en el CONTEXTO: el LLM recibe los veredictos ya computados con REGLA DURA de no recalcular.
- **Regla**: ante "¿determinista o LLM?" preguntar QUÉ SALE MAL EN CADA CASO. Si el fallo es una cifra/causalidad falsa con tono seguro en material de cliente → mecánico o LLM+guard sobre datos servidos. Si el fallo es una taxonomía que no generaliza al siguiente input → LLM con salida estructurada + portón humano cuando la salida alimenta compromisos (una meta adoptada fija umbral y responsable → portón; una conclusión citable con recibo → sin portón). El portón se calibra por lo que la fila ALIMENTA, no por cómo se produjo.
- **Disparador**: cualquier feature nuevo de brand_intel u otro módulo que lea documentos del cliente/proveedor o que produzca categorías; cualquier discusión "el módulo es determinista". ¿La salida alimenta aritmética o compromisos? ¿El espacio de entrada es cerrado o abierto?

### 2026-08-10 — Un tablero operativo trae jornadas FUTURAS con el comparativo cargado

- **Síntoma**: al cargar los cinco tableros de ventas de McDonald's al motor nuevo, el sistema arrojó **−19,5%** de variación interanual donde el cómputo ad-hoc previo había dado **+5,7%**. Ninguna validación estructural chistó: la suma de los canales seguía cuadrando exacto con el total, la consistencia daba `reconciles: True`, y el desglose por plaza y canal era internamente coherente.
- **Causa raíz**: el tablero se emite a mitad de mes y trae el MES COMPLETO. Las jornadas posteriores al corte (10 de agosto al 31, en el archivo del 9 de agosto) llegan con `Venta 2025` cargada —el comparativo del año anterior existe para esas fechas— y `Ventas 2026` en **cero**. Promediar 22 jornadas con venta cero contra 22 jornadas reales del año anterior hunde el agregado. Mi script ad-hoc las excluía por accidente (`if not r[12]: continue`), así que la cifra correcta salió de una decisión implícita que nunca declaré — y el motor, al ser explícito y completo, expuso el hueco.
- **Regla**: todo cruce interanual sobre un tablero operativo define primero su **ventana comparable**: una jornada entra solo si tiene magnitud CORRIENTE efectiva (venta o transacciones > 0), y las excluidas se cuentan y se declaran con su fecha de corte. Un cero de "aún no ocurrió" y un cero de "no vendió" son indistinguibles en la columna, y el primero miente en la dirección de la caída. Corolario de método: cuando un cómputo ad-hoc y el motor gobernado difieren, **el sospechoso es el ad-hoc** — suele llevar un filtro implícito que nadie escribió, y el motor obliga a nombrarlo.
- **Disparador**: cualquier ingesta de dato operativo (venta, tráfico, inventario, producción) con comparativo del ejercicio anterior en la misma fila; cualquier archivo cuyo nombre lleve una fecha de corte anterior al fin del período que contiene. ¿El período del archivo termina después de su fecha de emisión?

### 2026-08-10 — Cargar historia ANTERIOR a lo ya cargado rompe el orden de la serie

- **Síntoma**: tras cargar 9 olas históricas (2018-2024) en un expediente que ya tenía 4 olas recientes, el orden de la serie quedó `['2025-05','2025-08','2025-11','2026-03','2018-09',...]`. La secuencia gobierna tendencia, ola previa, pronóstico y backtest: toda lectura de trayectoria se habría construido sobre un orden falso sin que ningún test fallara.
- **Causa raíz**: la ingesta asignaba `sort_order` incrementando desde el máximo existente —correcto cuando la historia llega en orden, falso cuando llega hacia atrás—. Lo mismo aplica a cualquier campo de orden derivado del momento de carga en vez del atributo que lo define.
- **Regla**: el orden de una serie temporal lo gobierna la **cronología**, no el momento de la carga. Toda ingesta que pueda insertar períodos anteriores a los existentes debe **renumerar el orden completo por fecha** al terminar, y reportar cuántas filas cambiaron. Las filas sin fecha (la ola de proyección, que solo sostiene un pronóstico congelado) van al final conservando su orden relativo. Verificación mínima: `fechas == sorted(fechas)` sobre la serie resultante.
- **Disparador**: agregar historia retroactiva a cualquier serie con campo de orden explícito (olas de tracker, períodos de índice, cortes de un panel). ¿El nuevo período es anterior a alguno ya cargado?

### 2026-08-10 — Un guard que no reconoce la forma del contexto se DESACTIVA en silencio

- **Síntoma**: al servirle a la ruta cerebro un contexto nuevo (la doble comparación de brand_intel), el log soltó `Chequeo de dirección no pudo completarse: 'list' object has no attribute 'items'`. La generación siguió normal y el informe salió bien — pero el chequeo de DIRECCIÓN de las comparaciones (el guard que existe justamente porque «cifras correctas, sentido invertido» ya llegó a producción) no corrió sobre esa sección.
- **Causa raíz**: `_direction_refs` lee `context["indicadores"]` esperando un MAPA indicador→blob y hace `.items()`. Mi contexto usaba la misma clave para una LISTA de filas. El `except Exception` que envuelve el chequeo —correcto como red, «best-effort: jamás rompe la generación»— convirtió una incompatibilidad de forma en un guard ausente. Es la lección de «un guard sin su input no falla, DESAPARECE», ahora por una vía nueva: no por falta de input, sino por input de otra forma bajo el mismo nombre.
- **Regla**: un guard que dependa de la FORMA del contexto valida esa forma explícitamente (`isinstance`) y registra que se salta, en vez de dejar que la excepción lo apague dentro de un `except` genérico. Y al servir un contexto nuevo a una ruta compartida, revisar qué claves ya tienen significado allí: reusar un nombre con otra estructura es indistinguible de no pasarlo. Verificación mínima: leer el log de una generación real buscando `no pudo completarse` / `omitido` antes de dar por bueno que los guards corrieron.
- **Disparador**: agregar una sección o un eje que sirva un contexto nuevo a `narrative_engine.generate`; cualquier `except Exception` alrededor de una verificación. ¿El guard corrió, o solo no rompió?

### 2026-09-03 — Filtré por el nombre del archivo y declaré vacía una serie que tenía 511 observaciones

**Síntoma.** En la fase 0 de la ingesta canónica BCRD reporté «`ipc_general`: 0 series, 0
obs» y lo escribí como hallazgo, cuando la serie existía completa: 511 observaciones de
1984-01 a 2026-07, sin huecos. Casi entra a un informe con recomendación de negocio.

**Causa raíz.** Filtré los códigos producidos con
`c.startswith("bcrd.xls.ipc_base_2019-2020.")`, tomando el `source_file` del canónico como
si fuera el prefijo del `series_code`. No lo es: `default_prefix` **slugifica y pasa a
minúsculas**, así que `ipc_base_2019-2020.xls` produce `bcrd.xls.ipc_base_2019_2020`. Mi
filtro no encontró nada y **la ausencia se leyó como hallazgo en vez de como filtro roto**.
Afecta a 10 de los 26 archivos del canónico (todos los que llevan guion o mayúscula).

**Regla futura.** Un filtro que devuelve CERO es sospechoso antes que informativo: antes de
reportar una ausencia, comprobar que el filtro encuentra algo en el caso donde sabés que hay
dato. Y para componer un identificador derivado, **usar la función que lo compone**
(`default_prefix`), nunca reconstruirlo a mano a partir del insumo — la transformación que
aplica es justamente la que no ves. Es la misma familia que «una aserción de AUSENCIA pasa
sola» y que «un `@parametrize` vacío sale SKIPPED, no FAILED».

**Disparador.** Cada vez que un conteo, un filtro o un barrido dé 0, vacío o «no encontrado»,
y eso se vaya a reportar como conclusión. También al escribir el test de T-PS-4: tiene que
usar `default_prefix`, no `bcrd.xls.{stem}.{sufijo}`.

### 2026-09-03 — `git checkout .` para restaurar UN stash me borró cuatro archivos sin commitear

**Síntoma.** Para comprobar que unos tests nuevos tenían dientes, guardé mis 3 archivos de
código con `git stash push -- <esos 3>`, corrí los tests contra el código viejo (fallaron,
bien) y restauré con `git checkout . && git stash apply`. El `git checkout .` revirtió
**todos** los archivos rastreados modificados del árbol, no solo los tres del stash: perdí
las secciones nuevas de `tasks/todo.md`, la entrada de `tasks/lessons.md` y los siete tests
que acababa de escribir en `test_upsert_dedupe.py` y `test_canonical.py`. Nada de eso estaba
en el stash ni commiteado: irrecuperable desde git. Lo reescribí desde el contexto.

**Causa raíz.** Dos errores encadenados. (1) `git checkout .` no tiene alcance: opera sobre
todo el árbol, mientras que mi `stash push` sí lo tenía. Restaurar con una herramienta más
ancha que la que guardó es asimétrico, y la diferencia se la come el trabajo no guardado.
(2) Más de fondo: llevaba una sesión entera de trabajo valioso sin commitear. **El commit no
es el final del trabajo, es lo que lo vuelve recuperable.** La memoria ya tenía esta lección
por haber destruido trabajo de OTRA sesión (`sesiones-concurrentes-mismo-arbol`); la
repetí contra mí mismo, que es la versión barata de la misma factura.

**Regla futura.** Para volver atrás un stash parcial, revertir **exactamente los mismos
paths** que se guardaron: `git checkout -- <los mismos paths>`, nunca `.`. Y antes de
cualquier maniobra de stash/checkout, **commitear lo que ya está bien** — un commit WIP
cuesta diez segundos y es la única red. Para probar que un test tiene dientes hay
alternativas sin tocar el árbol: `git stash show -p | git apply -R` sobre paths concretos,
o —mejor— revertir a mano la línea del fix, correr, y volver a ponerla.

**Disparador.** Cualquier `git checkout`, `git restore` o `git stash pop/apply` cuando
`git status` muestre archivos modificados que NO son los que estoy manipulando. Mirar
`git status --short` ANTES y confirmar que la lista de paths de la restauración coincide con
la del guardado.

### 2026-09-03 — Puse un diagnóstico ANTES de lo que diagnostica, y sin protección: tumbaba los 26 archivos

**Síntoma.** Al agregar a `ingest_canonical` la verificación de cadencia —comparar lo que el
registro DECLARA contra lo que dicen los períodos— la puse antes del upsert y sin `try`. Un
registro con otra forma (`records=[object()]`, sin `.series`) levantaba `AttributeError`
dentro del `try` general del bucle, que lo cuenta como archivo fallido: los 26 pasaban a
`failed` y **no se persistía absolutamente nada**. La ingesta entera muerta por el
observador. Lo cazó un test que ya existía —
`test_ingest_canonical_continues_after_a_failing_file`— y que simula justo el escenario de
producción de un upsert envenenado.

**Causa raíz.** Confundí un diagnóstico con un gate. Un gate puede y debe frenar; un
diagnóstico solo mira. Al ponerlo en el camino crítico y sin aislar, le di poder de veto a
algo que solo tenía que reportar. Y el orden lo empeoraba: corría **antes** de la escritura,
así que ni siquiera fallaba después de haber hecho el trabajo útil.

**Regla futura.** Todo lo que solo OBSERVA va después del trabajo que observa y envuelto en
`try/except` con log — el idioma que este repo ya usa en la contabilidad de LLM («best-effort
de punta a punta: jamás lanza»). Antes de agregar una llamada dentro de un `try` grande que
convierte excepciones en «fallo del archivo», preguntarse: **si esto revienta, ¿qué deja de
pasar?** Si la respuesta incluye «no se persiste el dato», está en el lugar equivocado.

**Disparador.** Agregar cualquier verificación, métrica, log enriquecido o telemetría dentro
de un bucle que ya tiene un `except` que degrada el resultado. También: cuando un test viejo
empieza a fallar con un contador en cero (`ok + flagged == 0`), sospechar de lo que agregué
en el camino, no del test.

### 2026-09-03 — Al modelo se le mostraban 12 columnas de un cuadro de 34, y contestó lo que vio

**Síntoma.** La hoja `PIB$_Trim_Acum` del PIB por sector de origen terminaba en **2020-Q2**
mientras sus tres hojas hermanas del MISMO libro llegaban a 2025-Q4: 10 de 32 trimestres, sin
error, sin marca, sin hueco visible — la serie simplemente se acababa cinco años antes. Y las
otras tres perdían el trimestre más reciente (2026-Q1) por la misma causa, medio grado más
suave.

**Causa raíz.** Cuando la heurística no resuelve una hoja, el trabajo cae en el modelo, y la
vista previa que se le arma tiene `PREVIEW_COLS = 12`. El encabezado de la vista declaraba
`dims=78x34`, pero solo se mostraban 12 columnas y **nada decía que estuviera cortada**. El
modelo emitió `value_col_end=11`: la respuesta correcta para lo que veía. Re-inferir daba
exactamente lo mismo, así que no era un caché viejo — era reproducible.

Y no se arregla ensanchando la vista: de las 27 planillas canónicas, **21 pasan de 12
columnas** y una llega a 256.

**Regla futura.** Cuando se le recorta el insumo al modelo —columnas, filas, cantidad de
ítems por pedido—, **el recorte tiene que estar declarado en el propio insumo** y el pedido
debe ofrecer una salida que no dependa de ver todo (acá: dejar el fin del rango abierto, que
el extractor ya interpretaba como «hasta el final»). Un modelo que contesta bien sobre un
insumo incompleto produce un resultado incompleto que parece completo. Es la misma familia
que el nombrado que devolvía «0 de 64» por truncamiento de la respuesta: en los dos casos el
tamaño del recorte decidía en silencio la calidad del resultado.

**Disparador.** Cualquier constante que limite lo que el modelo VE o lo que puede DEVOLVER
(`PREVIEW_*`, `max_tokens`, tamaño de lote, `[:N]` sobre una lista que va al prompt).
Preguntarse: si el insumo real supera este límite, ¿el resultado sale mal o sale corto? Y si
sale corto, ¿alguien se entera? Corolario de verificación: cuando una serie termina antes que
sus hermanas del mismo libro, sospechar del spec antes que de la fuente.

### 2026-09-03 — Mi primer detector daba un falso positivo por medir lo que era fácil, no lo que importaba

**Síntoma.** Al barrer los specs cacheados buscando lecturas truncadas, marqué `pib_gasto.xls`
con «22 columnas con dato sin leer» y estuve a un paso de «arreglar» un spec que estaba bien.
De la columna 24 en adelante ese cuadro tiene OTRO bloque —«Tasas de Crecimiento», con
encabezados `92/91`, `93/92`—, y no leerlo es lo correcto.

**Causa raíz.** Medí la propiedad cómoda («hay números fuera del rango») en vez de la que
define el defecto («el encabezado declara un PERÍODO fuera del rango, y esa columna trae
dato»). La primera es fácil de calcular y tiene falsos positivos estructurales en cualquier
planilla de dos bloques, que en este corpus son mayoría.

**Regla futura.** Antes de barrer, escribir en una frase qué distingue el caso malo del caso
bueno, y comprobar que la medición contiene esa distinción. Si el detector no puede explicar
por qué un caso bueno NO se marca, todavía no es un detector. Y ante el primer positivo:
abrir el archivo y mirarlo antes de escribir el arreglo — mirar los datos de `pib_gasto` costó
dos minutos y evitó romper un spec correcto.

**Disparador.** Cualquier barrido, auditoría o guard nuevo sobre un corpus. Correrlo primero
sobre un caso que se sabe BUENO y verificar que sale limpio, antes de confiar en los positivos.

### 2026-09-04 — Mi regla nueva rompió un caso legítimo que un test viejo ya cubría

**Síntoma.** Al enseñarle al motor que un eje de años REINICIADO es otro cuadro, la primera
versión trataba cualquier año repetido como reinicio. En una matriz trimestral el año se
escribe encima de **cada uno de sus cuatro trimestres** (`2010 2010 2010 2010 2011…`), así que
la regla partía cada año en cuatro «bloques» y el cuadro entero salía mal. Lo cazó
`test_matrix_quarterly_synthetic`, un test de calibración que existía desde antes.

**Causa raíz.** Generalicé desde UN archivo. Miré `lleg_total`, vi «un año que vuelve» y lo
convertí en regla sin preguntarme en qué OTRA forma legítima aparece un año repetido en este
corpus — y aparece en la más común de todas, la matriz trimestral. La condición correcta no
era «vuelve un año visto» sino «vuelve un año visto **que no es el de la columna anterior**, o
vuelve después de una columna separadora».

**Regla futura.** Antes de convertir una observación en regla del motor, buscar el
CONTRAEJEMPLO en el propio corpus: ¿dónde más aparece esta señal, y ahí qué significa? Un
patrón visto en un archivo es una hipótesis, no una regla. Y correr la suite del motor
—no solo los tests nuevos— antes de dar por buena una generalización: los tests de calibración
existen para eso y me avisaron gratis.

**Disparador.** Cualquier heurística nueva en `inference.py` o `extract.py` que dispare sobre
una señal estructural (un valor que se repite, una fila que aparece, una columna vacía).
Preguntarse qué caso NORMAL exhibe esa misma señal.

---

## Un criterio que no falla nunca puede estar mirando el lugar equivocado

**Síntoma.** Habilité `taap_pasivad.xlsx` con los seis criterios en verde —0 duplicados con
valores en conflicto, 0 períodos mezclados, 0 códigos por coordenada, 0 avisos de
truncamiento, 0 discrepancias de cadencia— y el archivo emitía **29.325 filas para 1.610
observaciones reales**. Las 27.715 de más eran nulas, bajo el código de la tasa
interbancaria, porque las 241 columnas de relleno de la hoja heredaban ese rótulo.

**Causa raíz.** Mis seis criterios eran todos criterios de CONFLICTO: preguntan si dos
valores se pelean por la misma clave. Un cuadro mal leído que produce nulos no pelea con
nadie. Construí el juego de criterios a partir del defecto del bloque anterior («último
gana») y me quedé con esa forma de mirar.

**Regla futura.** Junto a los criterios de conflicto va uno de VOLUMEN: filas contra claves
distintas, y claves contra el rectángulo serie×período. Una densidad de ×18 —o una cobertura
del 15% donde se esperaba 100%— no dice qué está mal, pero dice que hay algo, y es lo único
que se ve cuando el defecto produce vacío en vez de contradicción.

**Disparador.** Cualquier tabla de triaje que declare «pasa». Antes de firmarla, mirar los
conteos brutos al lado de los ceros: si un archivo tiene 14 series y 29.325 filas para 115
períodos, la aritmética no cierra aunque todos los criterios estén en verde.

---

## Un puente que no resuelve puede estar acusando al extractor

**Síntoma.** En la fase 0 encontré que el registro canónico declaraba para el IMAE el sufijo
`serie_original_variacion_porcentual_interanual` y que **ninguna serie del archivo terminaba
así**. Lo tomé como un error del registro, computé cuál de las cuatro candidatas era la buena
—coincidencia exacta, 0,00000 pp, contra la variación interanual del índice— y corregí el
registro a `variacion_porcentual_interanual`. La verificación numérica estaba bien hecha y la
conclusión era falsa.

**Causa raíz.** El sufijo declarado era el correcto desde el principio. Lo que estaba roto era
el extractor: el IMAE tiene un encabezado de TRES niveles y el nombrado solo sabía calificar
con el vecino de la izquierda, así que nueve de sus catorce columnas perdían el nombre de su
cuadro y dos se desempataban por coordenada (y no se persistían). Al arreglar el encabezado,
la declaración original volvió a resolver, y a resolver a una sola serie. Corregí el mapa
porque no coincidía con el territorio, sin comprobar que el territorio estuviera bien medido.

**Regla futura.** Cuando una declaración curada por un analista no coincide con lo que produce
el motor, las dos hipótesis valen lo mismo hasta que una se descarte. Antes de tocar la
declaración: mirar si lo que el motor produce tiene sentido POR SÍ MISMO. Nueve de catorce
columnas sin decir de qué cuadro son, y dos llamadas `_c13` y `_c15`, no es una lectura sana —
y eso se veía sin saber nada del IMAE.

**Disparador.** Todo cambio a `excel_series_suffix`, `api_series` o cualquier otro puente del
registro canónico. Primero listar TODAS las series que el archivo produce y preguntarse si esa
lista es plausible.

---

## Cachear un resultado parcial como si fuera total lo congela para siempre

**Síntoma.** Cambié qué filas se consideran ambiguas —al desempatar también la primera
aparición de un rótulo repetido, 140 filas más— y ninguna se nombró. Salieron con su
coordenada (`_rNN`) y el veto de la frontera de escritura las descartó: **129 series de un
archivo ya encendido habrían dejado de persistirse**, sin error y sin aviso.

**Causa raíz.** La caché de nombres se leía todo-o-nada: «si hay entrada para este hash, ya
está resuelto». Es cierto el día que se escribe y deja de serlo en cuanto cambia el conjunto
de filas que necesitan nombre. La caché guardaba una RESPUESTA cuando lo que tenía que guardar
era un MAPA parcial.

**Regla futura.** Una caché indexada por un hash de la ENTRADA (la estructura de la hoja) no
puede usarse como si estuviera indexada por la PREGUNTA (qué filas hay que nombrar). Al leerla,
comparar lo pedido contra lo guardado y pedir la diferencia.

**Disparador.** Toda caché cuya clave describe el insumo y cuyo valor responde una consulta
sobre él. Preguntarse: si mañana cambia la consulta, ¿esta caché devuelve una respuesta vieja
o admite que le falta?

---

## Lo que produce un motor NO se puede leer desde otro entorno cuando lo nombra un modelo

**Síntoma.** Después de sincronizar producción con el código corregido, mi herramienta de poda
listó **418** series huérfanas. Las reales eran 365. Las 53 de diferencia eran series **recién
escritas y correctas**: `lleg_total…via_aerea.volumen.no_residentes` en producción contra
`…via_aerea.total.no_residentes` en mi corrida local — la misma fila, con el rótulo que el
modelo eligió en cada entorno. De haberlas borrado, habría destruido datos buenos sin un solo
error a la vista: son códigos plausibles y el `DELETE` funciona igual de bien.

**Causa raíz.** Construí la herramienta sobre un supuesto que nunca comprobé: que «lo que
produce el motor» es lo mismo acá que allá. Vale mientras la extracción sea determinista, y
deja de valer en el punto exacto donde el motor le pide un nombre a un modelo — que es
justamente donde están las filas difíciles. Comparé un lado observado (producción) contra un
lado **reconstruido** (mi corrida) y traté a los dos como si fueran mediciones.

**Regla futura.** Antes de borrar en un destino remoto, la lista de lo que sobra tiene que
salir de algo OBSERVADO en ese destino, no reconstruido acá. Cuando no se puede observar
directamente, sirve un invariante temporal: *lo que no estaba antes de la operación, lo
escribió la operación*. Y si queda residuo, convertirlo en experimento: borrar, volver a
sincronizar y mirar qué reaparece — lo que vuelve demuestra que el destino sí lo produce, y
la pérdida dura lo que tarda la reposición.

**Disparador.** Cualquier borrado masivo cuya lista se calcule ejecutando código local contra
una fuente compartida. Preguntarse: ¿esta lista la MEDÍ en el destino, o la deduje? Y en
particular, ¿hay un modelo en algún punto de la cadena que la produce?


---

## Un identificador que produce un modelo no es estable, y un `series_code` es un contrato

**Síntoma.** Después de desplegar la poda automática, la primera sincronización en producción
podó **40 series de 2.103** cuando yo había anunciado que no podaría ninguna. Ningún dato se
perdió —los valores se reescribieron bajo nombres nuevos y la poda se llevó los viejos, que es
lo que debe hacer— pero cuarenta `series_code` publicados cambiaron solos:
`pibk_trim.indice_de_volumen_por_actividad_economica.*` pasó a
`pibk_trim.indices_de_volumen_encadenados.*`, dos redacciones del mismo encabezado.

**Causa raíz.** Las filas que la heurística no puede jerarquizar las nombra el MODELO, y ese
resultado se cacheaba en `data/bcrd_excel/specs.json` — un directorio gitignored que en
Railway es el filesystem del contenedor, o sea que **cada deploy lo borra**. Sin caché se
vuelve a preguntar, y la respuesta no es la misma dos veces. Traté una salida de modelo como
si fuera determinista solo porque estaba cacheada; la caché escondía la inestabilidad, y el
deploy la destapaba. Es la misma causa que unas horas antes había hecho que la poda manual
quisiera borrar 53 series recién escritas: el mismo no-determinismo, visto entre entornos en
vez de entre corridas.

**Regla futura.** Si la salida de un modelo se convierte en un IDENTIFICADOR —una clave
primaria, un código que se persiste, una ruta que alguien va a citar— no alcanza con
cachearla: hay que **congelarla en el repositorio** y hacer que lo congelado le gane a
cualquier respuesta nueva. La caché es una optimización; el contrato es un artefacto que se
revisa como código. Y el momento de descubrirlo no puede ser el deploy: la prueba es borrar
la caché, correr sin acceso al modelo y comprobar que los identificadores salen idénticos.

**Disparador.** Cualquier lugar donde el texto que devuelve un modelo termine formando una
clave: `series_code`, slugs, nombres de archivo, rutas de API. Preguntarse qué pasa si mañana
contesta distinto — y si la respuesta es «cambia una clave publicada», congelarla.

---

## Dos capas que dicen «el crecimiento del PIB» y miden cosas distintas

**Síntoma.** El informe de proyecciones del 2026-09-05 publicó una tabla sectorial con **8 de
18 actividades contrayéndose**, y declaró honestamente un ajuste de reconciliación de
−3,536 pp. Deshaciendo el ajuste, el modelo crudo proyectaba **las 18 positivas** (+1,24 % a
+7,24 %). Las ocho contracciones no eran una lectura: eran el residuo de la resta.

**Causa raíz.** No era el reparto de la brecha, que estaba bien argumentado y bien
implementado. Eran las UNIDADES. El panel sectorial mide interanual (`trimestres[i-4]`); el
bloque del BVAR medía trimestral (`DLOG` entre trimestres consecutivos); `reconciliar`
restaba el punto trimestral de una suma ponderada de interanuales. Sobre la serie real (77
trimestres) el QoQ promedia +1,13 % y el YoY +4,54 %: 3,41 pp de diferencia sistemática
contra una brecha publicada de −3,536 pp. **La «brecha contra el agregado» era la conversión
de unidades**, con nombre de hallazgo.

Encima, el QoQ se hacía sobre la serie ORIGINAL del BCRD, sin desestacionalizar: su QoQ medio
va de −1,13 % (Q3) a +4,67 % (Q4), 5,80 pp de amplitud puramente de calendario. El titular del
informe dependía de en qué trimestre caía el horizonte.

**Lo que hizo que durara.** Tres cosas, y ninguna es un test que faltara por descuido:

1. **Nada en el repositorio AFIRMABA que las dos series fueran comparables.** Cada capa tenía
   su propia función de crecimiento, cada una correcta por separado, y el punto donde se
   restaban no sabía nada de ninguna de las dos. Un guard sobre cada capa por su cuenta habría
   pasado en verde.
2. **La entrada canónica ya declaraba la regla.** `canonical.py`, `key="pib_real"`: «el
   crecimiento (YoY del volumen) es invariante a la base». El panel sectorial obedecía el
   registro; el bloque no, y nada cruzaba lo que el registro DECLARA contra lo que el motor
   HACE.
3. **La muestra curada estaba en la unidad correcta.** Publicaba `pib_real` = 3,41 % con una
   brecha de −0,42 pp: coherente en anual, mientras producción emitía +0,74 % con −3,54 pp.
   Escrita a mano, enseñaba el producto que uno querría, no el que la máquina produce. Es el
   mismo defecto que ya habíamos pagado en el eje de valuación, donde la cura fue GENERAR la
   muestra desde las mismas funciones que el informe real.

**Regla futura.** **Una magnitud que se va a RESTAR de otra viaja con su medida.** Es el
corolario de «el SUJETO viaja con el número» para las unidades: no alcanza con que cada capa
calcule bien: el punto de la resta tiene que poder preguntar *«¿esto mide lo mismo que
aquello?»* y negarse. Acá el parámetro `medida_del_agregado` es **obligatorio y sin default**,
a propósito — un default habría dejado pasar exactamente el caso que existe para impedir.

Y el test que lo cierra no vigila el mecanismo sino la PROPIEDAD: se siembra el mismo índice
en las dos capas y se exige que produzcan el mismo número. Da igual por qué dejen de
coincidir.

**Disparador.** Dos módulos que nombran igual una magnitud («crecimiento», «variación»,
«cuota», «margen») y la calculan cada uno por su lado, sobre todo si en algún punto se suman,
se restan o se comparan. Preguntar de qué a qué mide cada uno, y sembrar el mismo dato en las
dos para ver si sale el mismo número.

---

## Una frase computada afirmaba «dato real medido» en un informe de PRONÓSTICO

**Síntoma.** §8 del informe de proyecciones del 2026-09-05, con cuatro líneas entre las dos y
las dos COMPUTADAS:

> **Cobertura:** 100% del índice se construye sobre dato real medido en la fuente.
> **Procedencia por variable:** 0% del peso de este índice se sostiene en dato real…

**Causa raíz: dos defectos, y el segundo es el interesante.**

1. **El producto contestaba otra pregunta.** `coverage=1.0 if vig else 0.0` responde «¿hay
   alguna proyección vigente?»; `DataHealth.coverage` declara responder «¿qué fracción del
   peso de mi índice está anclada a dato real?». La única proyección vigente ni siquiera
   pasaba el gate —el propio informe la rotula «¿ancla una afirmación? **no**»— y aun así el
   eje puntuaba `cobertura=1.00`.

2. **La superficie que se quedó atrás.** El mecanismo para esto YA EXISTÍA:
   `provenance.coverage_sentence()` rutea por `coverage_kind`, y su comentario dice que la
   frase de índice en el eje de leyes es «sencillamente falsa» y que «salía en la Metodología
   del informe». El arreglo se hizo en `provenance.py` y **no** en
   `report_sections._methodology_md`, que siguió con el literal cableado. Resultado: el eje de
   leyes publicaba hoy, en su metodología, exactamente la frase que el repositorio ya había
   declarado falsa para él. Nadie se enteró porque **arreglar una superficie hace desaparecer
   el síntoma que uno estaba mirando**.

**Y un tercero, que apareció al arreglar.** Cambiar solo la redacción dejaba el mismo defecto
más chico: metodología 50% y procedencia 0%, dos números bajo la misma palabra en la misma
página. La causa era que `coverage_real` es 0 por construcción en un eje de proyección. Hizo
falta una cobertura con nombre propio (`coverage_anclada`) y que la cifra determinada del
nowcast VIAJARA al registro.

**Regla futura.** Cuando una prosa generada dependa de un discriminador (`coverage_kind`,
`scope`, `nature`), **el discriminador se rutea con un MAPA, nunca con un `if` ni con un
literal**, y hay un test que cruza el mapa contra el vocabulario entero. Un `.get()` con
default sobre un vocabulario que crece convierte «me falta una frase» en «publico una frase
falsa», en silencio. Y al arreglar una prosa que aparece en dos superficies, **buscar la otra
antes de dar por cerrado**: `grep` de la frase, no del nombre de la función.

**Lo que la prueba de rotura encontró y yo no.** Mi primer guard sobre la cobertura de
procedencia **no falló** al romper el código: el caso que usaba tenía `coverage_real` y
`coverage_anclada` iguales. Un test que no separa las dos ramas no prueba la rama. Faltaba el
caso de una proyección ADMISIBLE, donde valen 0 y 1.

**Disparador.** Cualquier frase de producto que se arme con un número más una plantilla. Dos
preguntas: ¿el número contesta la pregunta que la plantilla hace?, y ¿esta plantilla vive en
más de un lugar?

---

## Arreglar una repetición puede borrar el dato: la regla no es «nunca», es «acá no»

**Síntoma.** El informe listaba las fuentes dos veces: inline en «Metodología y fuentes» y en
viñetas en «Fuentes y referencias», cuatro líneas después, las dos desde `sig.sources`. No era
de un producto: alcanzaba a **todo producto de deep dive que declare fuentes**, por
construcción del framework.

**La trampa.** La cura obvia —borrar la lista inline— rompía otra cosa. La sección de fuentes
es solo de **deep dive** (`_TIERS_WITH_SOURCES`) mientras la metodología se sirve también en
**insight**: borrarla dejaba a insight sin fuentes en ninguna parte. Eso no es arreglar una
repetición, es borrar el dato, y no habría fallado ningún test porque nadie afirmaba que
insight tuviera fuentes. El test que lo impide se escribió ANTES del arreglo, mirando el otro
nivel — el que no exhibía el síntoma.

**La segunda trampa, encima.** Con la lista fuera, la sección seguía titulada «Metodología y
fuentes» y ya no traía ninguna: se cambiaba una repetición por una promesa incumplida. Y
renombrar el título tampoco era la salida: vive en **siete** superficies —el framework, el
motor de research, tres archivos i18n y dos pantallas— **sin ningún guard de paridad**.
Renombrar habría dejado alguna atrás, que es el modo de falla ya documentado. La salida fue un
PUNTERO de una línea, con la cuenta concordada («La fuente que respalda…» / «Las 2 fuentes
que respaldan…»), que cumple el título sin repetir un solo nombre.

**Regla futura.** Antes de borrar algo que sale dos veces, preguntar **en qué configuración
sale UNA sola vez** — casi siempre existe, y ahí el borrado es una pérdida silenciosa. La
condición no va sobre el contenido («¿está repetido?») sino sobre el CONTEXTO («¿va a salir la
otra superficie?»), así que la función que decide necesita saber su contexto: acá, que
`_methodology_md` recibiera su nivel, que hasta entonces no recibía.

**Corolario sobre los títulos.** Un título que promete contenido es un contrato. Si el arreglo
lo deja sin cumplir hay dos salidas —cambiar el título o cumplirlo— y la elección la decide
**en cuántas superficies vive el título**. Con siete y sin paridad, cumplirlo sale más barato
que renombrarlo.

---

## El número y su unidad son UNA cosa, y el mecanismo lo dicta el FORMATO

**Síntoma.** «una variación de 0.38 \n% contra…»: el número en una línea y su unidad en la
siguiente, en el PDF que se vende. Misma familia que los glifos de subíndice que salían como
cajas — se ve en el entregable y en ningún test.

**Lo que casi hago mal.** Iba a meter el carácter U+00A0 sin verificar que el renderer lo
dibujara. Es exactamente cómo llegaron los glifos que salen como cajas: un carácter que el
código acepta y la fuente no tiene. **El repositorio ya tenía la respuesta**: las viñetas y la
numeración de secciones se arman con la ENTIDAD `&nbsp;` de ReportLab, que funciona hace rato.

**Y el mecanismo no es el mismo en los dos formatos.** En el Word la entidad se dibujaría
literal; ahí va el carácter. La REGLA (qué unidades, qué patrón) vive en una sola constante
que los dos importan; lo que cambia por formato es cómo se escribe el espacio. Dos copias de
la lista de unidades habrían divergido en la primera que alguien ampliara.

**El detalle de orden, que tiene su test.** `_inline` escapa `&` → `&amp;`. Insertar la
entidad ANTES de ese escape la vuelve `&amp;nbsp;` y el cliente lee «0.38&nbsp;%» literal —
peor que el defecto original. Un arreglo de forma puede empeorar la forma.

**Regla futura.** Antes de meter un carácter no-ASCII en un entregable, **buscar cómo lo
resuelve el repo hoy** y verificarlo EN EL PDF, no en la cadena de Python. La verificación que
sirve es negativa y sobre el artefacto: «ninguna línea empieza con `%`» y «la cadena `nbsp` no
aparece ni una vez».

---

## Una aserción de RELOJ no distingue «lento» de «roto»

**Síntoma.** CI puso en rojo un PR que no tocaba el módulo del fallo:
`test_las_tres_secciones_corren_A_LA_VEZ`, de `banking_score`, con
`assert tardanza < motor.demora * 2` → 0,60 s contra un tope de 0,30 s. En local pasaba 10 de
10 en 0,18 s.

**Lo que el propio fallo probaba.** La aserción que reventó era la TERCERA. La segunda —
`motor.max_en_vuelo == 3`— **había pasado en esa misma corrida**: las tres secciones sí se
generaron solapadas. Lo lento era el runner, no el código.

**Y no se arregla subiendo el umbral.** Una corrida secuencial de tres tramos de 0,15 s daría
>= 0,45 s, y lo observado fue 0,60 s: **no existe un umbral que separe «runner cargado» de
«se volvió secuencial»**. La aserción no tenía poder discriminante en el entorno donde corre.

**Regla futura.** Para una propiedad de CONCURRENCIA, el instrumento es un **contador de
solapamiento**, no el reloj: tres corrutinas simultáneamente dentro de la función solo pueden
estar ahí si se agendaron a la vez, y en serie el máximo sería 1. Es una prueba directa; el
tiempo total es un indicio, y encima uno que mide la máquina.

Antes de borrar la aserción hay que comprobar que la que queda tiene dientes: se rompió el
`asyncio.gather` a un bucle secuencial y el test falló con «solo 1 sección(es) a la vez». Sin
esa comprobación, «saqué la aserción flaky» y «dejé el test ciego» se ven igual.

**Disparador.** Cualquier `assert` sobre `time.monotonic()`, `elapsed`, `duration` o un
`timeout` en un test. Preguntar: si esto falla, ¿puedo distinguir un bug de una máquina
ocupada? Si la respuesta es no, el instrumento está mal elegido.
### 2026-09-05 — Un identificador que un modelo se pone a sí mismo no es un identificador del sistema

- **Síntoma**: toda proyección del BVAR quedaba `pending` para siempre y la sección de desempeño publicaba «ninguna de las proyecciones emitidas alcanzó su período de cierre», que se lee como «los trimestres no cerraron». La verdad era que **no podían** cerrar: `emision.OBJETIVO = "pib_real"` es el nombre de la variable DENTRO del bloque del BVAR, y viajaba al ledger como `target_series`. En producción, `GET /api/v1/macro-monitor/series/pib_real` devuelve `observations: []`.
- **Causa raíz**: el nombre con que un modelo llama a su variable y el `series_code` con que el sistema la observa son dos cosas distintas, y el código las trataba como una. Nada falló al escribir la fila: el defecto solo se manifiesta tres meses después, como silencio. Al lado había un segundo defecto de la misma familia —el `point` es un Δlog en % (~0,4) y se comparaba contra el índice de volumen (~133), o sea `abs_error ≈ 132,75` publicado como RMSE— que no explotó **solo porque el primero mantenía la sección vacía**. Arreglar uno sin el otro publicaba el número absurdo en la primera corrida.
- **Regla**: cuando un modelo emite algo que otro proceso va a **puntuar, comparar o buscar**, lo que viaja tiene que ser el identificador del SISTEMA, no el del modelo — y el número tiene que viajar con su MEDIDA, no solo con su valor. Es la misma cura que `shared/data/series_nature.py` ya aplicó un nivel más arriba: la magnitud se declara junto al dato en vez de adivinarse al leerlo. Al escribirlo, comprobar en el momento de la ESCRITURA que el destino existe (`emision._serie_observable`), porque es el único momento en que todavía se puede decir por qué.
- **Disparador**: cualquier campo que sea a la vez el nombre interno de algo y la clave con que otro proceso lo va a buscar. Preguntarse: si escribo esto y nadie lo lee nunca, ¿algo falla? Si la respuesta es «no, se queda pendiente», hay que hacer que falle al escribir.

### 2026-09-05 — Un veto que no deja marca se lee como paciencia

- **Síntoma**: el mensaje de sección vacía decía que los trimestres no habían cerrado, con filas que estaban rotas. Un lector no tenía forma de distinguir «el producto es nuevo» de «el producto está roto», y las dos son el mismo texto.
- **Causa raíz**: `puntuar_pendientes` hacía `continue` sobre lo que no podía puntuar. Saltear en silencio convierte una rotura en espera, y la espera no se investiga.
- **Regla**: cuando un lazo saltea filas, la pregunta no es «¿las saltea bien?» sino **«¿alguien se entera de que las salteó, y puede distinguir "todavía no" de "nunca"?»**. Lo salteado se LISTA con su causa nombrada (`ledger.no_puntuables`), y el test que importa es el CONTRAEJEMPLO: que un pendiente que solo espera el dato NO aparezca en esa lista — sin él, un `no_puntuables` que devuelva todo pasa igual.
- **Disparador**: todo `continue`/`if not …: return` dentro de un proceso automático cuyo resultado se publica como un conteo.

### 2026-09-05 — La misma sección se publicaba por DOS caminos, y arreglé uno

- **Síntoma**: corregí el texto engañoso en `desempeno.seccion()` y los tests quedaron verdes. El producto «SDQ Proyecciones Macro» seguía publicando la frase vieja: `products_forecast._md_desempeno` la tenía duplicada **palabra por palabra**, porque renderiza desde el snapshot congelado y no ve la base.
- **Causa raíz**: dos superficies, dos copias del literal. Es el mismo patrón que ya costó cuatro registros de a uno en el anuario, y que la doctrina describe como «la superficie no re-juzga: se ENTERA». Lo encontré revisando los llamadores, no porque algo fallara — no había nada que pudiera fallar.
- **Regla**: la prosa compartida vive en CONSTANTES exportadas y el renderizador es UNO, sin `Session` en la firma, para que la superficie sin base no tenga excusa para escribir la suya. Lo que la segunda superficie necesita saber viaja en el payload ya resuelto (`no_puntuables`), no se recomputa. Y se vigila con un test de PARIDAD que compara los dos textos, más uno estructural que prohíbe el literal duplicado.
- **Disparador**: antes de dar por cerrado un arreglo de texto o de lógica de presentación, `grep` de una frase distintiva del texto viejo en todo el árbol. Si aparece dos veces, son dos superficies.

### 2026-09-05 — «El período anterior» no es «la observación anterior que haya»

- **Síntoma**: al unificar la transformación Δlog en un solo lugar, las tres copias existentes tomaban la observación previa DISPONIBLE. Con un hueco en la serie eso computa una variación de dos trimestres y la rotula de uno, sin que nada avise.
- **Causa raíz**: `zip(serie, serie[1:])` sobre las claves ordenadas es la forma natural de escribirlo y esconde el supuesto de que no hay huecos.
- **Regla**: una variación exige el período anterior **DE CALENDARIO** (`shared.data.periodos.periodo_anterior`); si falta, no hay valor y se declara el motivo. Y el test que lo protege usa una serie CON un hueco, no una completa — con una completa las dos implementaciones dan lo mismo y el test no distingue nada.
- **Disparador**: cualquier cálculo de variación, delta o tasa de cambio sobre una serie temporal.


---

### 2026-09-05 — Un readiness RANCIO me hizo leer «no cambió nada» donde había cambiado todo

- **Síntoma**: tras verificar que producción servía el commit del merge, `GET /api/v1/products/readiness` devolvió para `macro_forecast` **exactamente el mismo texto de `g1` que la línea base**. Iba a reportar «desplegado, sin cambio observable».
- **Causa raíz**: el readiness está PERSISTIDO con su `computed_at`, y el endpoint lo sirve tal cual. El `computed_at` decía `20:40` y el deploy había sido a las `21:49`. Peor: el texto que veía ni siquiera correspondía al código anterior de mi rama, sino a uno más viejo todavía — otra rama ya había cambiado la forma de esa frase y el readiness tampoco la reflejaba. Recomputar lo movió de 0,85 a 0,70 y de una frase a otra completamente distinta.
- **Regla**: cuando se verifica un cambio en prod contra un valor **almacenado**, comprobar el commit servido NO alcanza: hay que mirar el `computed_at` del valor y forzar el recómputo (`POST /api/v1/products/readiness/recompute`) ANTES de comparar. Y el chequeo que lo delata sin saber nada más: si el texto es idéntico byte a byte a la línea base cuando el código de por medio lo cambió, lo que estoy leyendo es caché.
- **Disparador**: cualquier verificación post-deploy contra un endpoint que sirve un resultado computado y guardado — readiness, snapshots de producto, narrativas cacheadas.

### 2026-09-05 — Lo que la fila no registra, la migración no lo puede afirmar

- **Síntoma**: escribí un backfill que ponía `measure='dlog_pct'` a las filas de los dos motores, con el argumento de que eran de una sola versión del código. Al mergear `main` apareció que otra rama había cambiado ESE MISMO DÍA la transformación del PIB de trimestral a interanual, y que hubo diecinueve despliegues en el día.
- **Causa raíz**: `as_of` es una fecha SIN HORA. La fila no registra con qué versión del código se produjo, y las dos medidas difieren en puntos porcentuales enteros (QoQ +1,13 % vs YoY +4,54 %) — o sea que el error resultante no habría sido absurdo, solo mal, que es peor porque nadie lo mira dos veces.
- **Regla**: un backfill solo puede afirmar lo que la FILA registra o lo que es invariante a toda versión del código. Lo demás queda NULL y se LISTA. Acá: el nowcast sí (su medida nunca cambió), el BVAR no; y el `target_series` sí en las dos, porque que `"pib_real"` no sea un `series_code` no depende de ninguna versión. El argumento «es de una sola versión del código» hay que verificarlo contra el `git log` del día, no contra la fecha del primer commit.
- **Disparador**: toda migración de datos que deduzca un valor a partir del `model_id`, del productor o de la fecha. Preguntarse: ¿cuántas veces se desplegó entre la primera fila y hoy, y el registro tiene la resolución para distinguirlas?

### 2026-09-05 — Dos arreglos correctos se cruzan y el resultado DESAPARECE

- **Síntoma**: al mergear `main`, todos los tests en verde. La sección sectorial del informe, en cambio, se había vuelto imposible: `_payload` llamaba a `bloque.medida_de(primera["serie"])`, que espera el NOMBRE DE LA VARIABLE, y mi rama había hecho que `serie` fuera el `series_code`. `KeyError`, tragado por un `except Exception` que solo escribe un warning.
- **Causa raíz**: las dos ramas arreglaron bien lo suyo el mismo día. Una hizo que el identificador dejara de ser el nombre del modelo; la otra empezó a usar ese nombre como clave de un diccionario. Ninguna de las dos suites lo ve, porque cada una prueba su lado. Y el `except` genérico convierte el cruce en silencio: el informe promete diecisiete secciones y entrega dieciséis.
- **Regla**: después de mergear `main`, no alcanza con que los tests pasen — hay que buscar a mano quién CONSUME lo que mi rama cambió de forma, y con qué llave. Y un `except Exception` alrededor de una sección entera necesita, al lado, un campo de MOTIVO que viaje en el payload: sin él, «no se pudo» y «no aplica» se leen igual y ninguno de los dos se investiga.
- **Disparador**: mergear una rama que cambia el VALOR de un identificador (un código, una clave, un slug) contra un `main` que avanzó. Buscar el identificador viejo en todo el árbol, no solo en los archivos que toqué.

### 2026-09-05 — El literal volvió mientras yo lo estaba sacando

- **Síntoma**: saqué el `%` hardcodeado de tres superficies y escribí un guard estructural sobre esas tres. El siguiente merge trajo `_md_resumen_ejecutivo`, de otra rama, con `f"{d['punto']:.2f} %"` — el mismo literal, escrito de nuevo en las mismas horas.
- **Causa raíz**: un guard con una lista explícita de funciones protege lo que había cuando se escribió. No es un defecto del guard: es su naturaleza, y por eso la lección escrita no alcanza.
- **Regla**: cuando el guard es una lista de sujetos, la lista se AMPLÍA en cada merge y eso se dice en su docstring, con el caso que lo demuestra. Y el guard se escribe con `ast` sobre un hecho sintáctico preciso —una interpolación del punto seguida de un texto que arranca en «%»— y no con una regex por línea, que en este archivo marcaría «banda 80 %» y los pesos. Al lado van SUS DOS contra-pruebas: que ve el defecto en el código como estaba, y que no marca el porcentaje legítimo.
- **Disparador**: todo guard parametrizado con una lista de funciones, archivos o módulos. Preguntarse qué queda afuera — y volver a preguntárselo después de cada merge.


---

### 2026-09-06 — Antes de rellenar un hueco, preguntar qué se vuelve POSIBLE al rellenarlo

- **Síntoma**: había una fila del ledger sin medida, listada como impuntuable. La tarea era estamparla. Determiné la medida correcta con dos líneas de evidencia y estuve a punto de escribir la migración y terminar.
- **Causa raíz**: el hueco estaba tapando otro defecto. El `backtest_id` no incluía la medida, así que en cuanto la fila se volviera puntuable iba a caer en el mismo conjunto que los pronósticos del mismo modelo en OTRA unidad —el bloque había cambiado de trimestral a interanual— y su RMSE se promediaría. Medido con errores de 0,50 y 4,00: **2,850**, que no es el error de ninguno de los dos. Estampar y nada más habría cambiado una brecha VISIBLE por una corrupción INVISIBLE.
- **Regla**: cuando un dato faltante está bloqueando un camino, la pregunta no es solo «¿cuál es el valor correcto?» sino **«¿qué va a hacer el sistema en cuanto se lo dé, y está listo para hacerlo bien?»**. Recorrer el camino aguas abajo ANTES de escribir el valor: quién lo va a leer, con qué lo va a agrupar, contra qué lo va a comparar. Un hueco declarado es incómodo pero honesto; un hueco rellenado hacia un camino roto es un número malo que nadie va a volver a mirar.
- **Disparador**: cualquier backfill, default o valor por defecto que habilite una rama de código que hasta ahora no corría.

### 2026-09-06 — Cuando el dato no registra el hecho, lo registra el RELOJ

- **Síntoma**: una fila no decía con qué versión del código se produjo, y las dos candidatas daban resultados que difieren en puntos porcentuales enteros. `as_of` era una fecha sin hora. Parecía indecidible, y por eso la había dejado en NULL.
- **Causa raíz**: estaba buscando la respuesta solo DENTRO del registro. Pero el momento de escritura sí queda grabado en otros lados: el `last_run` de la operación que la escribió, el `%cd` del commit que introdujo el cambio, el `merged_at` del PR y la lista de despliegues. Cruzarlos dio una respuesta con margen de **cuatro horas y media** — la fila es anterior a que el commit existiera.
- **Regla**: antes de declarar un dato indeterminable, cruzar los relojes que sí hay: `last_run` de la operación, fecha del commit (`git log --format='%cd'`), `merged_at` del PR, `railway deployment list`. Y corroborar con una segunda línea independiente —acá, reproducir el modelo con el dato real y ver que la trayectoria de la otra hipótesis ni se acerca—. Una sola línea es una inferencia; dos que no comparten supuesto son una determinación.
- **Disparador**: «no se puede saber con qué versión se produjo esta fila». Casi siempre sí se puede: el hecho no está en la fila, está en el reloj.

---

## Probé la función y no la RUTA, y el informe real lo destapó en veinte minutos

**Síntoma.** Un informe generado en producción publicó, en el mismo `std_methodology`:

> **Cobertura:** 50% de lo que este eje publica está sostenido por un pronóstico admisible…
> **Procedencia por variable:** 50% **del peso de este índice se sostiene en dato real**…

La primera frase es la del eje de pronóstico —la que acababa de escribir— y la segunda es la
de ÍNDICE, o sea exactamente la afirmación falsa que ese trabajo existía para eliminar. Las
dos, en la misma página, sobre el mismo eje.

**Causa raíz.** `report_sections._provenance_md` arma un `AxisRegistry` efímero desde
`variable_signals()` y **no le pasaba el `coverage_kind` que ese mismo diccionario trae**.
Caía al default de índice. Afectaba también al eje de leyes, que declara
`COVERAGE_INSTRUMENT` y lo perdía igual.

**Por qué mis tests no lo vieron, que es lo que importa.** Todos construían el `AxisRegistry`
**a mano**, con la semántica ya puesta:

```python
eje = AxisRegistry(..., coverage_kind=raw.get("coverage_kind") or COVERAGE_INDEX)
assert "50%" in coverage_sentence(eje)
```

Eso verifica `coverage_sentence`. **No verifica que alguien le pase la semántica**, que era el
defecto. El test hacía a mano justamente el paso que el código de producción se salteaba —
así que el arreglo de una superficie quedó probado mientras la otra publicaba lo falso.

Es la regla que ya estaba escrita en el CLAUDE.md —«un test del motor NO es un test de la
ruta», con cinco defectos previos de la misma forma— y la repetí en el mismo trabajo en el que
estaba arreglando otra instancia de «un guard existe en un motor y falta en el otro».

**Regla futura.** Cuando el arreglo consiste en que un dato VIAJE de un lado a otro, el test
tiene que entrar por **el llamador más externo que exista** —acá `standard_sections`, que es
por donde pasa el informe— y nunca construir el objeto intermedio. Construirlo a mano es
declarar como cumplida la precondición que se está probando.

**Y el hallazgo sobre el método.** Esto no lo encontró ningún test: lo encontró **generar el
informe real en producción y leerlo**. Cuando el entregable es un documento, leer el
documento no es una verificación de más — a veces es la única que mira lo que el cliente ve.

---

## Tres cosas que creía saber del entregable y las tres eran distintas al medirlas

La pasada de forma del informe de proyecciones. Venía arrastrando tres descripciones de sus
defectos, escritas de sesiones anteriores, y **ninguna sobrevivió a medirla**.

**1. «Los glifos `BV₀`, `λ₁`, `λ₂` salen como cajas».** Falso a medias. Renderizando cada
familia y leyendo el PDF: la `λ` sale perfecta, igual que el resto del griego, la matemática,
las flechas y la tipografía. Lo que falla son los SUBÍNDICES —todos— y los superíndices salvo
¹²³, que son Latin-1. `BV₀` fallaba por el subíndice y nunca por la letra griega.

Y yo había planteado la decisión como «transliterar o cambiar la fuente», dos opciones malas,
y se la había pasado al dueño. **Había una tercera**: ReportLab entiende `<sub>`/`<super>` y
con la fuente que ya está dibuja un subíndice de verdad. Ni pierde la forma ni toca el aspecto
de los demás informes. Presentar un dilema de dos opciones antes de buscar la tercera le pasa
al dueño una decisión que no le correspondía.

**2. «La portada dice Período sobre una fecha».** Cierto para UN eje, no en general.
Consultados los 18 del catálogo en producción: cuatro pasan una fecha, pero tres son CIERRES
de período (30-jun, 31-dic, 31-jul) que bajo ese rótulo se leen bien. Generalizar de un caso
habría cambiado el rótulo a los otros tres sin motivo.

**3. «La tabla publica el código interno `pib_real`».** Ya no: el arreglo del ledger lo
resolvió al código real y ahora publica la ruta de Excel COMPLETA, que es peor. Un defecto de
forma descrito hace días puede haber cambiado de forma.

**Regla futura.** Una lista de defectos de forma **envejece**, y envejece distinto de una de
lógica: el documento se sigue generando y cada cambio aguas arriba lo mueve. Antes de
arreglarlos, **regenerar el entregable y volver a mirarlo**, uno por uno. Y cuando un defecto
parezca exigir una decisión cara del dueño —cambiar una fuente, mover un umbral—, buscar la
tercera opción antes de preguntar: en este repo casi siempre existe y suele estar en una
capacidad que la herramienta ya tiene.

**Y el guard: mi primer barrido miraba DOS funciones de prosa** y el defecto vivía en una
tercera —la sección de Desempeño—. Lo encontró el PDF, no el test. Se reemplazó por un barrido
de todas las `_md_*` del módulo, con su testigo de que encontró algo. Una lista escrita a mano
protege lo que uno se acordó de poner.

**Apéndice de la misma pasada — un test que depende de un binario de MI máquina.**
Los dos tests de portada leían el PDF con `pdftotext`. Está en mi Mac por homebrew y **no en
el runner**: pasaron en local y rompieron el build con `FileNotFoundError`. Es la segunda vez
en la sesión —antes fue `pypdf`— y la forma es idéntica: instalé una herramienta para
inspeccionar algo a mano y después la dejé dentro de un test.

La distinción que faltaba: **inspeccionar a mano y verificar en CI son cosas distintas.** Leer
el PDF con `pdftotext` y mirar la página con `pdftoppm` fue lo que encontró los tres defectos
y hay que seguir haciéndolo. Lo que no puede es quedar comiteado. El test equivalente espía
`_cover` desde `render_product_pdf` —la ruta real, que es donde estaba el defecto— y no
necesita nada instalado. Regla: antes de comitear un test, preguntarse **qué instalé yo para
que esto ande**.

---

### 2026-09-06 — `n_oos` contaba EMISIONES, no evidencia

- **Síntoma**: un compañero me pasó su proyección de plazos —«el eje vuelve a publicar con 12 pronósticos puntuados, o sea 3 años a emisión trimestral»— y al ir a confirmarla medí otra cosa: **cuatro trimestres de evidencia real dan `n_oos = 12` y el gate admite**. La emisión se dispara en cascada tras cada ingesta y `as_of` está en la clave de cinco campos, así que cada corrida en otra fecha escribe una fila nueva del mismo trimestre objetivo.
- **Causa raíz**: el conjunto se definió sobre el supuesto de que «un trimestre se pronostica una sola vez a cada distancia» —lo dice el docstring del `backtest_id`— y nadie comprobó que la cadencia de emisión lo respetara. El contador no estaba mal: estaba contando otra cosa que la que el gate creía. Y no era solo el conteo: con tres filas del mismo trimestre, su error pesaba el triple en el RMSE, así que el promedio quedaba inclinado por cuántas veces corrió una operación.
- **Regla**: un umbral sobre un contador («hacen falta 12 observaciones») exige verificar **qué incrementa ese contador en la operación real**, no en el diseño. Preguntarse: ¿cuántas filas escribe un ciclo completo del sistema, y son todas evidencia independiente? Si el proceso puede re-escribir el mismo hecho con otra clave, el umbral se alcanza sin evidencia.
- **Disparador**: cualquier gate de la forma `if n >= N`. Simular el ciclo real de la operación que produce `n` —no un caso de test— y contar.

### 2026-09-06 — Deduplicar apagó un aviso que sí se daba

- **Síntoma**: al deduplicar por horizonte, la única regla implementada de `_se_solapan` («dos filas comparten horizonte») se volvió inalcanzable. La función habría devuelto `False` siempre y el informe habría dejado de declarar un solapamiento que hoy declara — sin que ningún test fallara, porque el test que lo cubría estaba escrito sobre el caso que la deduplicación elimina.
- **Causa raíz**: el arreglo eliminaba la CAUSA que el aviso detectaba, y el aviso quedaba mudo aunque el fenómeno que nombra siga existiendo por otra vía. Su propio docstring declaraba la regla real —«cuando el paso entre cortes es menor que el salto entre horizontes»— y nunca se había escrito.
- **Regla**: cuando un arreglo hace inalcanzable la condición de un guard, no basta con dejarlo: hay que preguntarse si el FENÓMENO que declara sigue ocurriendo. Si sigue, se codifica la regla que de verdad lo detecta; si no, el guard se borra y se dice por qué. Un guard que no puede dispararse nunca es peor que ninguno: se lee como que el fenómeno no ocurre.
- **Disparador**: todo arreglo que elimine, filtre o deduplique lo que un guard existente inspecciona. Y la señal barata: un test de guard que hay que reescribir porque su caso ya no se puede construir.
