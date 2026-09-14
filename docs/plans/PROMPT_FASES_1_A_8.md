# Prompt de implementación — Fases 1 a 8 del plan de entregables mensuales

Escrito 2026-09-12. Plan de referencia: [`PLAN_ENTREGABLES_MENSUALES.md`](PLAN_ENTREGABLES_MENSUALES.md) (v3).
Prompt anterior: [`PROMPT_IMPLEMENTACION_FASE_0.md`](PROMPT_IMPLEMENTACION_FASE_0.md).

**Por qué ahora sí hay un solo prompt.** El de la Fase 0 explicaba que las Fases 1+ no se podían
lanzar porque el §5 del plan tenía decisiones abiertas y un agente las habría tomado por su cuenta.
Ya no: las cinco decisiones del §5 están tomadas con evidencia (ver §A). Lo que queda es trabajo
con criterio conocido, y la forma de que no se derrame es la de siempre: **un PR por fase, cada uno
mergeado y verificado en producción antes de abrir el siguiente.**

---

> Copiar desde aquí.

Trabajás en `sdq-market-intelligence`. Vas a ejecutar **las Fases 1 a 8** del plan de entregables
mensuales, **en orden, una por PR, sin parar entre fases y sin preguntar** salvo en los casos de
§H. Leé primero, en este orden:

1. `CLAUDE.md` del repo (la doctrina de datos y narrativa NO es estilo; cada regla salió de un
   defecto que se vendió).
2. `docs/plans/PLAN_ENTREGABLES_MENSUALES.md` (v3) — el plan. Si no lo ves en tu worktree, está
   sin versionar en el checkout principal:
   `/Users/ricardomercado/Developer/SDQMIP/sdq-market-intelligence/docs/plans/`. Leelo por ruta
   absoluta. **Tu primer PR lo mete a git** (§C, paso 0).
3. La memoria del proyecto (`MEMORY.md` y sus ficheros, en particular
   `rebanada-construccion-mensual.md`, `entregables-mensuales-fase-0-hecha.md`,
   `un-tipo-nuevo-se-registra-en-todas-sus-superficies.md`, `acceso-produccion-via-api.md`,
   `producto-anual-a-hecha-b-pendiente.md`). Lo que dice de código, verificalo antes de usarlo.

## A. Estado real al 2026-09-12 — qué ya existe y qué NO

El plan se escribió el 09-09. Desde entonces entraron a producción #1158 (Fase 0), #1159/#1160/
#1163/#1164 (rebanada vertical de construcción) y #1167 (títulos). Eso cambió el mapa:

| Pieza del plan | Estado | Dónde |
|---|---|---|
| Fase 0 completa | ✅ en prod | `shared/operations/fuentes_congeladas.py`, `uso_de_herramientas.py`, ledger cerrado |
| §2.1 tabla transversal de observaciones, con `provincia`/`tipologia` y `nature` | ✅ existe | `shared/observations/{models,service,delta}.py`, tabla `sector_observations` |
| §5.2 línea base | ✅ decidido y escrito | `shared/observations/delta.py`: la elige `nature` (flow → mismo período del año anterior + ventana móvil 12 m; stock → último nivel; rate/index → puntos; unknown → no se computa) |
| §5.1 frescura dual | ✅ decidido | el feed es otra FUENTE, no otra cadencia. Medido: `cadence="monthly"` en `DataHealth` cuesta 0,300 de readiness y despublica el eje. **No se toca `DataHealth.cadence`.** El sensor da un veredicto por `(eje, fuente)` vía `senales_de_fuentes()` |
| §5.3 mes suelto vs acumulado | ✅ no era decisión | el CSV del MIVHED trae una fila por permiso con su mes; la acumulación anual era nuestra |
| §5.4 publicar el piloto | ✅ decidido: SE PUBLICA | sin clientes no expone nada y es la única forma de verlo. Publicar ≠ desplegar: hay que recomputar readiness y activar (§F) |
| §5.5 techo en herramientas | ✅ decidido: NO todavía | solo contador; se reabre con meses de uso real |
| §3.1 MIVHED microdato provincial/tipológico | ✅ persistido y en contexto | `ingest_observaciones_mensuales` escribe m² por provincia y tipología; `ai_context.construction_delta_context` los pasa (top 5) |
| Sección de delta narrada | ✅ solo en construcción, **dentro del módulo** | `construction_intel/products.py`: `_delta_mensual()` va al payload, `_narrar_delta` narra, `completar_en_vivo` agrega la frase de atraso después de la caché |
| §1/§2.2 hook transversal narrado con caché propia | ❌ **NO existe** | el delta de construcción vive en `ProductReportCache` con todo el informe: cada mes nuevo del feed regenera el Deep Dive ENTERO (6 llamadas, no 1) |
| Fuente atrasada | ✅ decidido | se publica con el mes nombrado y la frase «no figuraba en la fuente en nuestra última descarga, del <fecha>»; `indeterminada` sigue vetando |
| Sonda diaria de la fuente | ✅ | `mivhed-vigilancia` (24 h), no ingiere; con novedad dispara el sync |

Consecuencia: **la Fase 1 que queda es la generalización**, no el andamiaje desde cero. Y la
Fase 2 queda reducida a §3.5 (ONE).

## B. Reglas que gobiernan toda la corrida

1. **Un PR por fase**, base `main`, rama `claude/fase-N-<tema>`. La fase termina cuando el PR está
   mergeado, prod sirve ese commit y la verificación de §F está hecha. **No abrís la fase N+1 con
   la N sin mergear.** Si una fase se parte en dos PRs por tamaño (>40 ficheros), está bien; se
   dice explícitamente.
2. **Plan de ejecución antes de código, por fase**: ficheros a tocar y por qué, escrito en el
   cuerpo del PR. Si al implementar te desviás, pará y replanteá el plan de esa fase en el mismo
   PR — no lo fuerces.
3. **Los TRES gates, y el frontend cuando lo tocás**:
   ```bash
   pytest modules/ shared/ -q
   ruff check modules/ shared/ app/
   mypy shared/ modules/ app/ 2>&1 | mypy-baseline filter   # juzgá el EXIT CODE, no el texto
   cd frontend && npx tsc --noEmit && npx vitest run
   ```
   `mypy-baseline` sale con código no cero también cuando RESOLVISTE deuda. Si resolviste,
   `mypy shared/ modules/ app/ | mypy-baseline sync` y comitealo. Corré mypy sobre los tres
   directorios completos; sobre uno solo el veredicto miente. Y no midas `$?` de una tubería con
   `| tail`: es el de `tail`.
4. **Tus tests nacen ciegos**: cada guard nuevo se corre contra el código VIEJO (o con una
   mutación deliberada) y tiene que fallar. Un test que pasa de entrada no probó nada. Pegá la
   salida de la mutación en el PR.
5. **La ruta se prueba por HTTP**, no solo el motor. Cuando el entregable sale por
   `/api/v1/products/...`, se pide por ahí, en test y en prod.
6. **Doctrina que aplica a cada fase** (de `CLAUDE.md`):
   - Declarar la brecha, nunca rellenarla: ausente es `None`, jamás `0.0` ni un promedio.
   - Las relaciones se COMPUTAN (dirección, deltas, rankings) y el modelo las copia.
   - El sujeto viaja con el número: `metros_cuadrados_licenciados_por_provincia_del_mes`, no
     `por_provincia`.
   - La frescura veta y `stale=null` también veta; lo vetado se LISTA, no desaparece.
   - Módulos no importan de otros módulos. Lo transversal va a `shared/`.
   - Un tipo/sección/producto nuevo se registra en TODAS sus superficies (título en la app en
     los 3 idiomas, PDF, Word, catálogo). Lo vigila
     `shared/products/tests/test_toda_seccion_tiene_titulo_en_la_app.py`.
   - **La sección de delta lee el movimiento y su magnitud. NO explica causas** (§0.3 del plan).
     El gate no puede respaldar una afirmación causal. Va en la plantilla y en un test que
     busque «debido a», «responde a», «por efecto de», «explicado por» en la salida de muestra.
   - **El feed de deltas NO entra al `context` de ninguna sección narrada preexistente** (§2.3).
     El precedente del error sigue vivo: `modules/energy_intel/products.py:374-391` inyecta
     `trayectoria` al contexto de `positioning` sin que esté en el payload. No lo repitas; en
     la Fase 5 lo corregís.
7. **Un dato que cambia más seguido que el contenido NO va al payload**: va por
   `completar_en_vivo` (gancho post-caché del ensamblador, `shared/products/assembler.py:558`,
   contrato en `shared/products/contract.py:350`). Con la fecha de descarga en el payload la
   huella cambiaba a diario y el informe entero se regeneraba cada día.
8. **En prod, el tiempo de respuesta es el dato**: < 2 s es un HIT de caché y no verificaste la
   generación; una generación real toma 15–90 s (Deep Dive de banca: ~2 min). Cuando quieras
   probar generación, cambiá algo que rote la huella o usá un período no pedido antes.
9. **Escribí en memoria** lo que no está en el código: decisiones, umbrales elegidos por el dueño,
   trampas encontradas. Un fichero por hecho, con `**Why:**` y `**How to apply:**`, y su línea en
   `MEMORY.md`. Antes de crear, buscá si ya existe.

## C. Fases — alcance, trampas y criterio de terminado

### Paso 0 (dentro del PR de la Fase 1) — el plan entra a git

Copiá `docs/plans/PLAN_ENTREGABLES_MENSUALES.md`, `PROMPT_IMPLEMENTACION_FASE_0.md` y este
prompt desde el checkout principal a tu rama y comitealos. Agregá al plan un encabezado
«Estado al 2026-09-12» con la tabla de §A. Un plan que solo vive en un checkout no existe para
nadie más.

### Fase 1 — Hook transversal narrado con caché propia, y construcción migrado a él

**Por qué existe.** Hoy el delta de construcción se narra dentro de su módulo y su bloque va al
payload del informe. Funciona, pero cada mes nuevo del feed regenera el informe ENTERO (6
llamadas en vez de 1) y el segundo eje (seguros, Fase 3) copiaría 300 líneas. El plan pide un
solo mecanismo en `shared/` que los 17 ejes puedan usar sin tocar su `render()`.

**Alcance.**
1. En `shared/products/` (no en ningún módulo): una sección estándar «delta del feed» que el
   ensamblador narra por su cuenta cuando el producto declara un feed. Propuesta de contrato:
   el producto expone `feeds_mensuales() -> list[FeedDeclarado]` (clave de serie(s), etiqueta,
   `nature`, fuente, cadencia); el ensamblador lee `leer_delta` para el último período con
   observaciones, narra con la plantilla `construction_delta` generalizada (renombrala a
   `feed_delta` y mantené el mismo contrato de contexto), y anexa la sección al `section_order`
   como hoy hace `standard_sections`. Elegí los nombres que mejor encajen con lo que ya existe;
   lo que no se negocia son las propiedades de abajo.
2. **Caché propia por sección**, con clave `(sector_key, clave_del_feed, período_del_feed, tier,
   lang, huella de la receta)`, separada de `ProductReportCache`. El delta se regenera solo
   cuando cambia SU período o SU receta; el informe del índice no se entera. Reusá la huella de
   receta que ya calcula el ensamblador (`assembler.py:216`, `NARRATIVE_CACHE_VERSION`) para la
   parte de plantilla y sanitizador.
3. **Migrar construcción** al mecanismo nuevo y borrar `_delta_mensual`/`_narrar_delta` del
   módulo. `senales_de_fuentes()` y `completar_en_vivo` (la frase de atraso) se quedan, pero
   evaluá si `completar_en_vivo` también se generaliza: la frase «no figuraba en la fuente en
   nuestra última descarga» aplica a cualquier feed. Si la generalizás, la fecha de última
   descarga se lee del registro que cada módulo guarda (`ultima_descarga_del_feed`).
4. Sacar `delta_mensual` del payload de construcción (si no, la huella del informe sigue rotando
   con el feed y el punto 2 no sirve de nada).

**Trampas verificadas.**
- `ProductReportCache` es único por `(sector_key, tier, scope, period, lang)` y guarda TODAS las
  secciones en un JSON. No hay caché por sección en esa capa: hay que crearla.
- Cambiar `products.py` de un módulo NO rota la huella; cambiar una plantilla de
  `claude_engine.py` rota la de los 17 ejes. Si tocás la plantilla, todos los informes cacheados
  de prod se regeneran al primer pedido. Es aceptable una vez; decilo en el PR.
- El título de la sección en la app va por eje si el nombre difiere («Movimiento mensual de
  licencias (MIVHED)» no sirve para seguros). Usá `sectionBySector` en los 3 idiomas; el guard
  lo exige.
- La degradación (sin clave de API) hoy devuelve 503 para el informe entero. La sección de delta
  no puede empeorar eso: si el motor está degradado, la sección se omite y se lista como
  omitida, sin tumbar el informe.

**Criterio de terminado.**
- Control negativo: con la tabla vacía para un eje, los 17 ejes renderizan **igual que hoy** en
  JSON, PDF y Word, y la sección no aparece (no aparece vacía). Guard estructural que lo exija.
- Control positivo: construcción en prod sigue sirviendo `delta_mensual` con las mismas cifras y
  la misma frase de atraso que antes de la migración (pedilo por HTTP antes y después y pegá los
  dos).
- Prueba del ahorro: rotá el período del feed en un entorno local con observaciones (o insertá
  el mes siguiente como prueba y borralo después) y mostrá con el ledger
  (`GET /api/v1/operations/llm-spend`) que se hizo **1** llamada, no 6, y que el informe del
  índice fue HIT.
- El eje `law` sigue `indeterminada` (no `congelada`) en `GET /api/v1/operations/fuentes`.

### Fase 2 — Lo que queda del MIVHED: ONE mensual y cuadro 4.8

**Por qué existe.** §3.1 ya está. Queda §3.5: `shared/data/one_construction.py:142` en
orientación filas=mes lee solo la fila «Total», descartando los meses; y el cuadro 4.8
(«construcciones», ya parseado en `_METRICS`) distingue licencias de construcciones y el
producto no lo publica.

**Alcance.** (1) `_parse_sheet` conserva las filas mensuales y `ingest` las escribe como
observaciones (`sector_key="construction"`, series `one.licencias.*` con `nature="flow"`,
`frequency="monthly"`). (2) `construcciones` entra como serie propia con su sujeto en la clave
(`one.construcciones.conteo`, no `conteo`). (3) Si la ONE y el MIVHED cuentan cosas distintas
para el mismo mes, **las dos se publican con su emisor**; no se promedian ni se elige una.

**Trampa.** Un backfill que corre verde puede no persistir nada: el gate `coverage < 0.999`
descarta el período en silencio. Verificá por fila (`obs.contar`) no por el acuse.

**Terminado.** Filas mensuales de la ONE en prod (`contar` antes/después), el delta de
construcción muestra ambos emisores cuando ambos tienen el mes, y el fixture de
`test_one_construction.py` cubre la orientación filas=mes con más de un mes.

### Fase 3 — Piloto técnico: SEGUROS

**Por qué existe.** Es el eje con la plomería hecha: SISALRIL y ARS ya se ingieren cada 720 h
(`insurance_intel/operations.py:163-174`), `InsuranceSeries` guarda períodos `"2025-12"`, y
`service.py:38-41` ya tiene vista as-of. Es el primer eje con entrega mensual real sin construir
un conector, y la prueba de que el mecanismo de la Fase 1 sirve para un segundo eje.

**Alcance.**
1. En el sync mensual de SISALRIL/ARS, **escribir además** las series mensuales en
   `sector_observations` (`sector_key="insurance"`, códigos `sfs.afiliacion.total`,
   `sfs.afiliacion.contributivo`, y las de ARS que sean flujo o stock claro), con `nature`
   tomada de `shared/data/series_nature.py` — si una serie no está clasificada ahí, se
   clasifica ahí, no en el módulo. `insurance_series` NO se migra (plan §2.1): conviven, y un
   guard cuenta que por período hay las mismas filas en las dos tablas.
2. El producto declara `feeds_mensuales()` y `senales_de_fuentes()` para SISALRIL y ARS.
3. Título de sección por eje en los 3 idiomas.
4. `DataHealth.cadence` de seguros sigue `"quarterly"`.

**Trampa.** Afiliación es un STOCK (personas cubiertas), no un flujo: su base es el último nivel,
no el mismo mes del año anterior. Si `nature` sale `unknown`, la sección no se computa y se
declara; no la fuerces.

**Terminado.** Informe Insight/Deep Dive de una aseguradora y el Pulse del sistema en prod con la
sección de delta, pedidos por HTTP con tiempo de generación real; el sensor de fuentes muestra
`sisalril` y `ars` con su veredicto; readiness recomputado sin caída (G1 sin cambio).

### Fase 4 — `limitations` dinámica + labels de Deal Scoring

Dos deudas independientes, baratas, en un PR (o dos si preferís).

**4a. `limitations` dinámica.** Hoy es texto fijo: `construction_intel/products.py:567-568`,
`energy_intel/products.py:382-383`, `insurance_intel/products.py:526` (y cualquier otro que
encuentre `grep -rn '"limitations"' modules/*/products.py app/products_*.py`). Alcance: la
sección se COMPUTA a partir de lo que el informe ya sabe de sí mismo —fuentes con veredicto
`congelada`/`indeterminada`, secciones omitidas por degradación o veto, período del feed vs
período del índice, dimensiones sin dato (`None`) en el payload— y se redacta en código, no con
el modelo. El texto fijo actual se conserva como párrafo de cierre (son limitaciones de diseño,
que no cambian). Un eje sin nada que declarar dice eso, explícitamente.

**4b. Labels de Deal Scoring.** `HistoricalDeal` (`deal_scoring/models/models.py:84`) solo se
puebla con `POST /deals` («Guardar al registro», `api/router.py:134`) o con el seed. La
`learning_curve` (`validation/learning_curve.py:93`) depende de esa acción manual. Alcance:
**cada corrida de scoring persiste sus entradas y su score** como fila con
`closed_successfully=None` y `outcome_date=None` (la brecha se declara, no se rellena), con un
origen (`manual`/`automatico`) para que el registro curado no se mezcle con el automático; el
label se agrega después por `PATCH`; la curva de aprendizaje solo consume filas con label.
**No cambies la rúbrica ni los pesos.** `docs/CLAIMS_COMERCIALES.md` sigue prohibiendo «modelo
predictivo» hasta que la curva lo respalde; no lo toques.

**Terminado.** 4a: informe de construcción en prod cuya sección de limitaciones nombra el atraso
del MIVHED con fecha; control negativo con un eje al día que no lo nombra. 4b: una corrida de
scoring por HTTP crea la fila sin label; `GET /deals` la lista separada del registro curado; la
curva la ignora hasta que se etiqueta.

### Fase 5 — Energía (OC-SENI) + zonas francas

**5a. Energía.** No existe conector del OC-SENI (`shared/data/` solo tiene `sie_client.py`).
Alcance: conector `shared/data/oc_seni_client.py` (API JSON pública sin login; IMTE mensual),
observaciones mensuales con `nature`, `feeds_mensuales()` + `senales_de_fuentes()` en el
producto, y **corregir el precedente de §2.3**: `energy_intel/products.py:374-391` deja de
inyectar `trayectoria` en `positioning` sin pasar por el payload — o entra al payload (y a la
huella) o no entra al contexto. `default_interval_hours` del sync de energía: 2160 → 720
(`operations.py:31`), **y** `PUT /api/v1/operations/{op}/schedule` en prod, porque la agenda
guardada manda sobre el default del código.
**Trampa:** el listado del OC devuelve **200 con `[]`** para un área inexistente. Lista blanca de
áreas (van con guiones, no espacios) o un typo se lee como «no hubo publicaciones».

**5b. Zonas francas.** `cnzfe_client.py:32-35` parsea `wage_operator_rd`, `wage_technician_rd`,
`local_spend_musd`, `occupied_area_sqft`; `free_zones_intel/scoring/` solo consume exports,
investment, jobs, companies. Alcance: los cuatro campos se publican en el payload y en el
contexto con su sujeto en la clave, y en una sección o tabla del informe. **NO entran al
índice**: cambiar pesos de un score sin backtest está prohibido por la doctrina de validación.
El CNZFE es anual y solo anual: no hay feed mensual de zonas francas en esta fase, y el plan lo
dice; no inventes uno con exportaciones de la DGA sin resolver antes qué mide.

**Terminado.** 5a: sensor de fuentes muestra `oc_seni` al día; informe de energía con delta
mensual en prod; test de que un área fuera de la lista blanca falla ruidosamente. 5b: los cuatro
campos aparecen en el informe de zonas francas y el score no cambió (mismo valor antes/después
para el último período, pegado).

### Fase 6 — Turismo

Hoy corre con **una fuente anual** (`tourism_intel/operations.py:27`, 2160 h). Existe
`shared/data/tourism_arrivals_client.py` (llegadas de no residentes): **antes de escribir un
conector nuevo, verificá si ya trae filas mensuales** y si el módulo las descarta al agregar.
Alcance: llegadas mensuales del BCRD como observaciones (`nature="flow"`, base = mismo mes del
año anterior + ventana móvil 12 m: es el flujo estacional puro del plan), conector JAC (XLSX
mensual) si el existente no lo cubre, sync a 720 h + schedule en prod. Revalidá el disclaimer de
`tourism_intel/ai_context.py` sobre ocupación hotelera contra lo que publica MITUR/SITUR hoy; si
sigue siendo cierto, se queda; si no, se corrige, y en cualquiera de los dos casos se deja
anotado con fecha.

**Terminado.** Informe de turismo con delta mensual en prod, con la base del año anterior visible
en el contexto; sensor con la fuente mensual al día.

### Fase 7 — Piloto comercial: OCDS de la DGCP

**Comprobación #1, antes de escribir una línea:** que la DGCP puebla
`tender/mainProcurementCategory = "works"`. Bajá una muestra del mirror de OCP (la API propia de
la DGCP daba 502 el 07-09) y contá. **Si no lo puebla, la fase termina ahí**: se documenta en
`docs/` con la muestra y el conteo, y se pasa a la Fase 8. Filtrar por modalidad está
prohibido: sería un número inventado con cara de medición.

Si lo puebla: conector con licencia ODbL declarada (`license` es `Text`; medí el largo igual),
observaciones de obra pública adjudicada por mes (`nature="flow"`), alimenta construcción y
energía **por evento**, no por import cruzado. Es un feed de EVENTOS: la sección no explica por
qué se adjudicó; cuenta y compara.

### Fase 8 — Leyes, vía JurisAI

Del lado de MIP ya existe `shared/data/jurisai_client.py` con `buscar(desde, hasta)` y
`vacio_es_concluyente`. Del lado de JurisAI (`/Users/ricardomercado/Developer/JurisAi/jurisai-backend/`)
existen `app/services/normative_digest_service.py` (`_find_recent_changes`),
`app/services/credenciales_de_servicio.py`, `app/api/router_normas.py` y `app/services/normas_api.py`.
**Antes de construir, verificá qué expone ya `/normas` con credencial de servicio `normas:read`**:
puede que la dependencia esté cubierta. Si falta exponer el digest por credencial de servicio,
ese cambio va en **un PR del repo JurisAI**, con sus propios gates, y MIP no se mergea hasta que
ese esté en prod.

Alcance en MIP: sección mensual del eje `law` que lista lo promulgado en el mes que afecta el
marco vigilado, o publica la **negativa concluyente** («no se promulgó nada que afecte este marco,
y esto es concluyente») **solo si** `vacio_es_concluyente` lo respalda; si no, dice que no se
puede afirmar. Filtra por fecha de INGESTA, no de promulgación. `esg` y `social_dev` quedan fuera
(no hay corpus).

**Terminado.** Un mes con novedades listado y un mes vacío concluyente, ambos por HTTP en prod;
el sensor muestra `jurisai` como fuente con su veredicto.

## D. Lo que NO hay que hacer en ninguna fase

- No tocar `scoring/` de ningún eje ni cambiar pesos de un índice.
- No cambiar `DataHealth.cadence` de ningún eje a `"monthly"`.
- No meter el feed en el `context` de una sección narrada preexistente.
- No dejar que la sección de delta explique causas.
- No poner gate, cuota ni cobro en las herramientas.
- No traer de vuelta el pre-calentado (lo impiden `test_regla_sin_precalentado.py` y
  `test_events_sin_prewarm.py`, y hay tres caminos por los que revivía).
- No migrar `mm_series`, `insurance_series` ni `pension_series` a la tabla transversal.
- No filtrar obra pública por modalidad.
- No cerrar una fase con la tabla vacía y el render igual: eso prueba que no rompiste nada, no
  que el delta funcione.
- No escribir cifras de validación a mano en ningún documento ni memoria.

## E. Trampas de entorno ya pagadas

- **La agenda guardada manda sobre `default_interval_hours`.** Cambiar la cadencia en código es
  inerte en prod sin `PUT /api/v1/operations/{op}/schedule`.
- **Un deploy mata las operaciones en vuelo.** Antes de mergear, `GET /api/v1/operations` y
  confirmá 0 corriendo; si hay una, esperá.
- **La protección de rama bloquea con `mergeStateStatus=BEHIND`** aunque diga MERGEABLE. Traé
  `main` a la rama; nunca `--admin`.
- **CI no se dispara al retargetear la base de un PR**: mergeá `main` y pusheá.
- **SQLite no aplica el largo de VARCHAR; Postgres sí.** Todo string nuevo de conector se mide
  contra su columna en `shared/tests/test_lo_que_sqlite_no_vigila.py`.
- **SQLite necesita WAL** para que una segunda conexión escriba con un lector abierto; ya está
  en `shared/database/session.py`. No lo toques.
- **CI corre en UTC**: nada de `date.today()` local en aserciones.
- **zsh no parte `$VAR`**: en scripts de gates usá rutas explícitas y un resumen que grite si
  no hay línea de resultado.
- **La fecha de publicación del CKAN de datos.gob.do está en `metadata_modified`**, no en
  `last_modified` (viene `None`).
- **FastAPI 0.139 no aplana routers**: `app.routes` tiene `_IncludedRouter` anidados.
- **Los tests de alembic exigen el import del modelo a nivel de módulo** en el módulo que lo
  usa, si no la tabla queda «invisible».
- **Acceso a prod: por la API con la cuenta E2E** (`scripts/seed_e2e_user.py`), nunca por la
  base. `railway logs -s <servicio> --lines N` solo, sin `cd`, tubería ni redirección, o lo
  bloquea el clasificador.

## F. Verificación en producción, por fase

1. `gh pr checks` en verde, `gh pr merge --merge`; luego comprobar que prod sirve el commit
   (endpoint de versión o `railway logs`). Un deploy fallido sirve la versión vieja sin avisar.
2. `POST /api/v1/products/readiness/recompute` y leer `GET /api/v1/products/readiness`; si un
   nivel cayó por debajo del umbral, esa fase no está terminada. Para un eje nuevo en el feed,
   `POST /api/v1/products/{sector}/{tier}/activate` si estaba inactivo.
3. Pedir el informe por HTTP con período y scope reales, con tiempo medido. Pegá el JSON de la
   sección de delta y el tiempo.
4. `GET /api/v1/operations/fuentes`: la fuente nueva aparece con veredicto; `law` sigue
   `indeterminada`.
5. `GET /api/v1/operations/llm-spend`: el costo de la generación del delta es 1 llamada, tarifada
   (`llamadas_sin_tarifa = 0`).
6. Abrir el informe en la app (login con la cuenta E2E en el navegador; los tokens van en cookie
   httpOnly, no en localStorage) y confirmar el título de la sección en pantalla. El Pulse trae UNA
   sección: usá Insight o Deep Dive para ver títulos.
7. Memoria actualizada (§B.9) y el estado de §A del plan actualizado en el repo.

## G. Cierre de cada fase — qué va en el PR

Diff, salida de los cuatro comandos de gates, la mutación que hizo fallar a cada guard nuevo,
el control positivo y el negativo, la evidencia de prod (§F), y la lista de lo que **no**
verificaste. Preguntate: ¿un staff engineer aprobaría esto? Si un gate falla, no cierres: iterá,
o documentá por qué se acepta.

## H. Únicos motivos válidos para parar

1. Un defecto en producción que no podés corregir en el mismo PR (readiness que despublica un
   eje, 5xx en un informe que antes servía).
2. La comprobación #1 de la Fase 7 da negativo → se documenta y se SALTA la fase, no se para.
3. El PR del repo JurisAI (Fase 8) no se puede mergear → se reporta y se para en la Fase 8.
4. Una fuente externa caída más de 24 h → se documenta, la fase queda abierta, se sigue con la
   siguiente y se vuelve al final.
5. Un cambio que exigiría violar §D.

En cualquiera de los cinco: escribí en el PR y en memoria exactamente dónde quedó, qué se
verificó y qué no, y qué decisión hace falta. Nada de «hecho» sin evidencia.

> Copiar hasta aquí.
