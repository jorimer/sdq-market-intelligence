# Prompts de implementación — plan de entregables mensuales

Escrito 2026-09-09. Plan de referencia:
[`docs/plans/PLAN_ENTREGABLES_MENSUALES.md`](PLAN_ENTREGABLES_MENSUALES.md) (v3).

**Por qué no hay un solo prompt para las 8 fases.** Un prompt que diga "implementá el plan" con
ocho fases es exactamente cómo se producen los refactors que empiezan estimados en 2 ficheros,
terminan en 14 y acaban en rollback. Además, **las Fases 1 en adelante están bloqueadas** por las
decisiones abiertas de §5 del plan — sobre todo la de frescura dual. Un agente que las encuentre
sin resolver va a decidir por su cuenta, y esa decisión va a quedar enterrada en el código.

La Fase 0 es la única que puede arrancar hoy: no depende de ninguna decisión abierta.

---

## PROMPT — Fase 0 · Instrumentación

> Copiar desde aquí.

Trabajás en `sdq-market-intelligence`. Leé primero `CLAUDE.md` del repo y
`docs/plans/PLAN_ENTREGABLES_MENSUALES.md` (v3). Vas a implementar **solo la Fase 0**. No
empieces ninguna otra fase, aunque el plan las describa.

**Contexto de por qué esta fase existe.** Vamos a publicar entregables mensuales por eje. Hoy los
ejes publican anual y hay tres defectos de instrumentación que harían que ese trabajo falle en
silencio: no hay detección de fuente congelada por eje, el ledger de costo LLM tiene tres call
sites que no escriben en él, y las tres herramientas comerciales no tienen contador de uso. Sin
esto no se puede saber si un eje mensual dejó de recibir dato, ni cuánto cuesta operarlo.

**Antes de escribir código: escribí el plan de ejecución** con los ficheros que vas a tocar y por
qué, y confirmámelo. Si al implementar te desviás de ese plan, pará y replanteálo — no lo fuerces.

### Alcance — cuatro entregables

**1. Sensor de fuente congelada por eje.**
Hoy `shared/operations/freshness.py` audita publicaciones BCRD y ratings soberanos, pero
**ningún eje sectorial registra `register_freshness_audit`** (el hook existe en las líneas 64-71 y
los extras se invocan en 277-282).

El patrón correcto ya está escrito: `_audit_publications` (L161-214) mide la antigüedad del
**último dato nuevo ingerido** (`Publication.created_at`), no del último sync exitoso. Su docstring
(L48-55) nombra el caso: *"el sync corre 'ok' sin traer nada nuevo"*.

Replicá ese patrón para los ejes sectoriales. La medida es antigüedad del dato, nunca éxito del
job. Un job verde sobre una fuente muerta es el fallo que estamos cazando.

**2. Superficie del sensor — en este mismo PR.**
Decidí y construí dónde ve el operador el resultado **sin abrir Sentry ni la CLI**. Detección sin
superficie no es monitoreo: un sensor que corre, detecta y muere su hallazgo en un canal que nadie
mira es trabajo perdido. Si no hay un sitio natural, proponelo antes de construirlo.

**3. Cerrar el ledger de costo LLM.**
Tres call sites llaman `record_usage` (contador diario de presupuesto en Redis) en vez de
`record_call`/`account`, así que su costo **no entra al ledger consultable**:
- `shared/research/domain_router.py:240`
- `shared/research/relevance.py:137`
- `shared/research/entity_check.py:87`

Además `shared/research/pilot.py:39,119` fija `ai_cost_usd = 0.0` con la nota *"núcleo
determinista: sin costo de IA todavía"*, que hoy es falsa — el motor narra con LLM. Corregilo o
declaralo explícitamente como no medido; lo que no se puede dejar es un cero que se lee como gasto
real de cero.

Referencias: el ledger es `llm_calls` (`shared/observability/models.py`), la atribución por
endpoint está en `app/main.py:49-67`, y la consulta admin es
`GET /api/v1/operations/llm-spend` (`shared/operations/router.py:112`).

⚠️ Cuidado con el patrón `total += c or 0`: `coste_usd` devuelve `None` cuando el modelo no está
tarifado, y esa forma lo absorbe en silencio. Un total tiene que devolver el importe **y** lo no
convertido, o fallar. No sumes `None` como cero.

**4. Contador de usos en las tres herramientas.**
`Research a Medida` (`shared/research/router.py`), `Deal Scoring` (`app/deal_scoring_api.py` y
`modules/deal_scoring/api/router.py`) y `Contexto de Marca` (`modules/brand_intel/api/router.py`)
no tienen contador de ejecuciones, ni cuota, ni gate de tier.

**En esta fase: solo el contador y su superficie. NO agregues gate, cuota ni cobro** — esa es una
decisión comercial que no está tomada. El objetivo es medir, no restringir.

Contexto de por qué importa: es el único lugar del sistema con costo variable real por corrida, y
el modelo comercial estima que de esa capa sale el 80% del ARPU.

### Lo que NO hay que hacer en esta fase

- No tocar ningún `scoring/`, ni `service.py`, ni ningún índice.
- No crear la tabla transversal de observaciones (es Fase 1).
- No tocar `DataHealth.cadence` de ningún eje.
- No agregar secciones al producto.
- No poner gate ni cuota en las herramientas.

### Doctrina del repo que aplica

De `CLAUDE.md`, y no son estilo — cada una salió de un defecto que llegó a producción:

- **Declarar la brecha, nunca rellenarla.** Un dato ausente es `None`, jamás `0.0` ni un promedio.
  Aplica directo al punto 3.
- **El sujeto viaja con el número.** Toda clave de cuota o conteo nombra su población.
- **La frescura veta, y `stale=null` también veta.** "No sé de cuándo es" y "está al día" son cosas
  distintas. Confundirlas puso un Gini de 0,44 en producción durante 19 días. Lo vetado se **lista**,
  no desaparece.
- **Módulos independientes**: nunca importar de otro módulo; la comunicación es por
  `shared.events.event_bus`.

### Verificación — los TRES gates, no solo pytest

```bash
pytest modules/ shared/ -q
ruff check modules/ shared/ app/
mypy shared/ modules/ app/ 2>&1 | mypy-baseline filter
```

⚠️ `mypy-baseline` **sale con código no cero también cuando resolviste deuda** ("Great work!").
Mirá el *exit code*, no el texto. Si resolviste, corré
`mypy shared/ modules/ app/ | mypy-baseline sync` y comiteá el baseline. Y corré mypy sobre
`shared/ modules/ app/` completo: sobre un subdirectorio el resto del baseline aparece como
"resuelto" y el veredicto miente.

### Criterio de terminado

No marques nada completo sin evidencia. Para cerrar hace falta:

1. Diff de los ficheros tocados.
2. Los tres gates en verde, con su salida pegada.
3. **El caso positivo del sensor**: apuntá deliberadamente un eje a una fuente congelada conocida
   —la sección "Estadísticas" de la SIE está muerta desde 2019-2023 y aparenta estar viva— y mostrá
   que el sensor la marca. Un sensor no probado contra un caso positivo no está probado, y un
   verde sobre datos frescos no prueba que detecte lo congelado.
4. **El control negativo**: un eje con fuente al día no debe marcarse. Los dos controles usan la
   misma función de medición; dos implementaciones del mismo criterio es cómo se cuela un falso.
5. Una captura o descripción de dónde ve el operador el resultado del sensor.

Preguntate antes de cerrar: *¿un staff engineer aprobaría esto?*

Si un sensor falla, no cierres la tarea: iterá hasta resolverlo, o documentá explícitamente por qué
se acepta el fallo.

> Copiar hasta aquí.

---

## Plantilla para las fases siguientes

Las Fases 1+ **no se pueden lanzar** hasta resolver §5 del plan. Cuando estén resueltas, el prompt
se arma con esta estructura, que es la que hace que la fase termine con evidencia y no con "hecho":

1. **Ancla**: leé `CLAUDE.md` y el plan; implementás **solo la Fase N**.
2. **Por qué existe la fase** — el defecto o la oportunidad concreta, no el objetivo abstracto.
3. **Plan de ejecución antes de código**, confirmado. Si te desviás, parás y replanteás.
4. **Alcance enumerado** con rutas y líneas.
5. **Lo que NO hay que hacer** — explícito. Es lo que evita que la fase se derrame.
6. **Trampas verificadas de esa fase** (ver abajo).
7. **Los tres gates**, con la advertencia de `mypy-baseline`.
8. **Criterio de terminado con control positivo y negativo.**

### Trampas por fase, ya verificadas — copiarlas al prompt correspondiente

**Fase 1 (andamiaje):** el feed de deltas **no entra al `context` de ninguna sección narrada
preexistente**. Precedente del error: `modules/energy_intel/products.py:349-350` inyecta la serie
de tendencia al contexto de `positioning` sin que esté en el payload, así que el fingerprint no la
ve y la narrativa cacheada describe la tendencia vieja. Replicarlo alcanzaría a 17 ejes.

**Fase 1:** la sección del delta necesita **caché propia** con clave por eje y período del feed.
`ProductReportCache` es único por `(sector_key, tier, scope, period, lang)` y guarda **todas** las
secciones en un solo JSON: no hay caché por sección en esa capa.

**Fase 2 (MIVHED):** resolver primero si los flujos van como mes suelto o acumulado móvil de 12
meses. Un mes suelto en una serie de acumulado anual es un dato falso, no un dato parcial.

**Fase 5 (OC-SENI):** el listado devuelve **200 con `[]`** para un área inexistente, no un error.
Validar el nombre de área contra lista blanca o un typo se lee como "no hubo publicaciones". Las
áreas van con guiones, no espacios.

**Fase 7 (OCDS):** verificar **antes de construir** que la DGCP puebla
`tender/mainProcurementCategory = "works"`. Filtrar por modalidad en su lugar subestima gravemente
la obra pública y sería un número inventado con cara de medición.

**Todas:** un backfill que corre verde puede no persistir nada — el gate `coverage < 0.999`
descarta el período en silencio. Verificá por fichero y por fila, no por el acuse de la
herramienta.
