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
