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
