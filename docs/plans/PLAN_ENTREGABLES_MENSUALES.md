# Plan — entregables mensuales por eje

## Estado al 2026-09-12

El plan se escribió el 09-09. Desde entonces entraron a producción #1158 (Fase 0),
#1159/#1160/#1163/#1164 (rebanada vertical de construcción) y #1167 (títulos de sección). Eso
cambió el mapa; lo que sigue es lo que YA existe y lo que NO. El prompt de ejecución de las
Fases 1 a 8 es [`PROMPT_FASES_1_A_8.md`](PROMPT_FASES_1_A_8.md).

| Pieza del plan | Estado | Dónde |
|---|---|---|
| Fase 0 completa | ✅ en prod | `shared/operations/fuentes_congeladas.py`, `uso_de_herramientas.py`, ledger cerrado |
| §2.1 tabla transversal de observaciones, con provincia/tipologia y `nature` | ✅ existe | `shared/observations/{models,service,delta}.py`, tabla `sector_observations` |
| §5.2 línea base | ✅ decidido y escrito | `shared/observations/delta.py`: la elige `nature` (flow → mismo período del año anterior + ventana móvil 12 m; stock → último nivel; rate/index → puntos; unknown → no se computa) |
| §5.1 frescura dual | ✅ decidido | el feed es otra FUENTE, no otra cadencia. Medido: `cadence="monthly"` en `DataHealth` cuesta 0,300 de readiness y despublica el eje. No se toca `DataHealth.cadence`. El sensor da un veredicto por (eje, fuente) vía `senales_de_fuentes()` |
| §5.3 mes suelto vs acumulado | ✅ no era decisión | el CSV del MIVHED trae una fila por permiso con su mes; la acumulación anual era nuestra |
| §5.4 publicar el piloto | ✅ decidido: SE PUBLICA | sin clientes no expone nada y es la única forma de verlo. Publicar ≠ desplegar: hay que recomputar readiness y activar |
| §5.5 techo en herramientas | ✅ decidido: NO todavía | solo contador; se reabre con meses de uso real |
| §3.1 MIVHED microdato provincial/tipológico | ✅ persistido y en contexto | `ingest_observaciones_mensuales` escribe m² por provincia y tipología; el contexto del delta los pasa (top 5) |
| Sección de delta narrada | ✅ (Fase 1 la generaliza) | hasta #1164 vivía en `construction_intel/products.py`; la Fase 1 la mueve a `shared/products/feed_delta.py` con caché propia |
| §1/§2.2 hook transversal narrado con caché propia | ✅ **Fase 1 en prod** (#1168, 2026-09-14) | `shared/products/feed_delta.py`: el producto declara `feeds_mensuales()`, el ensamblador narra con caché propia `feed_delta_cache`. Medido: un mes nuevo cuesta 1 redacción; la generación fría del Deep Dive de construcción son 4 |
| Fuente atrasada | ✅ decidido | se publica con el mes nombrado y la frase «no figuraba en la fuente en nuestra última descarga, del <fecha>»; indeterminada sigue vetando |
| Sonda diaria de la fuente | ✅ | `mivhed-vigilancia` (24 h), no ingiere; con novedad dispara el sync |

Consecuencia: la Fase 1 que queda es la generalización, no el andamiaje desde cero. Y la
Fase 2 queda reducida a §3.5 (ONE).

### Avance de la corrida de las Fases 1 a 8 (actualizado 2026-09-14)

| fase | estado | evidencia |
|---|---|---|
| 1 · hook transversal | ✅ en prod | #1168: Deep Dive de construcción 89,1 s frío y 0,9 s en HIT, delta fuera del payload, mismas cifras y encabezado |
| 2 · ONE mensual y cuadro 4.8 | ⏸ **abierta por §H** | `one.gob.do` responde 403 con desafío de Cloudflare a clientes automáticos en todo el sitio. La capa ONE ya había desaparecido de prod en el sync del 2026-09-10. No se elude el desafío. Decisión que falta, del dueño: pedir acceso a la ONE o cargar los XLSX a mano. |
| 3 · seguros | ✅ en prod | #1169 + arreglos #1172 (período sin valores, «del», aviso duplicado) y #1174 (ausencias narradas y aviso por código al pie). Verificado por HTTP sobre `53cbbc0b` |
| 4 · §Limitaciones computada y labels de Deal Scoring | ✅ en prod | #1170, sobre `f79636e6`: §Limitaciones de construcción nombra el atraso del MIVHED con sus dos fechas; cada corrida de Deal Scoring deja su fila automática sin label y la curva no la cuenta. La migración se colgó de la de #1171 (dos cabezas) |
| 5 · energía (IMTE OC-SENI) y zonas francas | ✅ en prod, ⏸ dos fuentes caídas (§H) | #1175 + arreglo #1177, sobre `a2d7b8d7`: IMTE sincronizado (edición de julio de 2026), `energy:oc_seni_imte` al día, delta en el Deep Dive, trayectoria del IRSE en el payload. **La SIE retiró sus CSV (404) y los recursos del CNZFE en datos.gob.do dan HTTP 500**: el IRSE no se recalcula y los cuatro campos complementarios siguen vacíos. Score IZF sin cambio (49,2) |
| 6 · turismo | ✅ en prod | #1176, sobre `985cc6d8`: llegadas mensuales del BCRD (`lleg_total.xls`, columnas verificadas contra la tasa que publica el BCRD), `tourism:bcrd_llegadas` al día, delta en el Deep Dive; texto de ocupación corregido (MITUR la publica en SITUR, verificado 2026-09-14) |
| 7 · obra pública DGCP | ✅ en prod | comprobación #1 positiva: la DGCP puebla `mainProcurementCategory` en todos sus releases. #1180, sobre `0c459a91`: `dgcp-obras-sync` escribe en construcción y en energía (por unidad de compra), sensores al día, deltas con la DGCP |
| 8 · leyes vía JurisAI | ✅ en prod | jorimer/JurisAi#1311 (`/normas/novedades`, por fecha de ingesta, alcance por corridas) y #1181, sobre `523871cd`: la sección lista lo ingresado en agosto de 2026 que cita la Ley 1-12; `law:jurisai` en el sensor (indeterminada: agosto no concluyente) |

**Queda abierto:** la Fase 2 (decisión del dueño sobre la ONE) y, por §H, la SIE y el CNZFE. Pendiente de revisión: el
delta narra «faltan N de los doce meses» de la ventana móvil anterior cuando no hay base, que declara un hueco; se corrige
en el contexto del delta, sin tocar plantillas.

---

**Estado: PROPUESTA v3. No implementar hasta confirmar §5.**
Escrito 2026-09-07 · revisado 2026-09-09.
Fuentes: [`docs/GUIA_FUENTES_SUBANUALES_4_EJES.md`](../GUIA_FUENTES_SUBANUALES_4_EJES.md).
Modelo comercial: `Modelo_Empaque_Mensual_SDQMIP_2026-09-07.xlsx` (raíz del repo).

**Cambios de v2 a v3:** el delta pasa a ser narrado, no estático (§0.2). Se incorpora el
inventario de decisiones de ahorro que limitan valor (§3) y las correcciones al modelo comercial
(§4). Las fases se reordenan por valor desbloqueado, no por riesgo técnico (§6).

---

## 0. Decisiones tomadas

### 0.1 El entregable mensual es un DELTA contra línea base, no el índice recalculado

Razón: *no es posible hacer un cálculo sobre un período que no se captura*. Un índice que promedia
CAGR de 3 años sobre datos anuales no tiene nada que decir sobre marzo.

Consecuencia mayor: **el scoring no se toca.** Si nunca se escribe un período mensual en
`en_scores`/`const_scores`, el `latest - 3` de `momentum.py:78`, `resilience.py:63`,
`traction.py:56` y `attractiveness.py:54` nunca ve un período infra-anual. También resuelve:
la columna (tabla nueva, no `en_scores`), y la convivencia (el delta no pasa por `get_latest`).

### 0.2 El delta se NARRA. El dato es determinista; la lectura es LLM

Corrección de la v2, que proponía una sección estática por ser el hook transversal barato. Eso
optimizaba costo, no valor: un delta crudo es una tabla, y una tabla la produce cualquiera. Lo que
nadie más produce es la lectura del movimiento contra la línea base.

**Pero la separación de capas se mantiene, y no por costo:** la cifra, la línea base, la variación
y el emisor se calculan y se citan; el LLM lee ese bloque ya cerrado. Es la única forma en que el
guardrail numérico (`shared/narrative/numeric_guard.py`) puede trabajar — exige que toda cifra del
texto se trace al contexto. Si el modelo produce el número, no hay contra qué trazarlo.

### 0.3 🔴 Límite de lo que la sección puede afirmar

El gate valida cifras, pero **no existe citación por afirmación narrativa**: la atribución es por
sección y fuente, no por oración (`shared/narrative/atribucion.py`). Un delta narrado mensual en 17
ejes es prosa densa en afirmaciones causales, y *"la caída responde a X"* es exactamente lo que el
gate no puede respaldar.

**Regla de alcance, no negociable:** la sección lee el movimiento contra la línea base y su
magnitud. **No explica su causa.** La causa exige evidencia que el feed no tiene.

---

## 1. Qué no hay que construir, y qué sí

Verificado en código:

- **El esquema de `period` ya sirve** (`String(10)`, unicidad por período). Con 0.1 ni se usa.
- **El assembler, la descarga y `shared/products/periods.py`** no requieren cambios.
- **Existe un hook transversal** que anexa secciones a los 17 ejes desde un solo archivo:
  `shared/products/report_sections.py`, anexado en `assembler.py:373-389` al `section_order` que
  consumen las tres superficies (JSON in-app, PDF, Word). Precedente probado: metodología, fuentes
  y glosario, con cero cambios en los 12+ módulos.

⚠️ **Pero ese hook solo admite contenido estático.** El ensamblador nunca invoca al motor por su
cuenta: la única llamada es `await product.narratives(...)` (`assembler.py:207`). Con la decisión
0.2, **hay que extenderlo** para que una sección estándar pueda narrarse.

Esa extensión es la pieza nueva de infraestructura del plan, y es un cambio en un lugar
—`assembler.py` + `report_sections.py`— no en diecisiete módulos.

---

## 2. Arquitectura propuesta

### 2.1 Tabla transversal de observaciones

**No existe nada reutilizable.** Barrido de `__tablename__` en `shared/`: ninguna tabla almacena
observaciones (eje + período + indicador + valor + fuente). `shared/registry/signals.py` es
in-memory; `shared/data/lineage.py` es un dataclass sin persistencia; `CanonicalSeries` /
`SeriesObservation` (`contract.py:118-172`) son DTOs de transporte de la Data API.

Lo que sí existe es **el mismo esquema copiado tres veces**: `mm_series`
(`macro_monitor/models/models.py:22-50`), `insurance_series` (`insurance_intel/models/models.py:46-71`)
y `pension_series`. Los demás ejes ni siquiera tienen tabla de series.

Propuesta: tabla transversal con la forma ya probada (`series_code`, `period`, `value`, `unit`,
`frequency`, `nature`, `source`, `published_at`, `license`) más `sector_key` y las dimensiones que
exige §3.1 (`provincia`, `tipologia` o su equivalente genérico).

Migrar las tres existentes queda **fuera de alcance**. Conviven.

### 2.2 Sección narrada transversal, con caché propia

- Se declara en `report_sections.py` y se gatea por tier ahí mismo (las actuales, líneas 32-33).
- El assembler la narra a través del hook extendido (§1).
- **Caché propia, con clave por eje y período del feed**, separada de `ProductReportCache`. Sin
  esto, el delta invalidaría el reporte del índice y se perdería todo el ahorro.

### 2.3 🔴 La trampa a evitar

Existe el precedente contrario y no hay que repetirlo. En `modules/energy_intel/products.py:386-388`
la línea de tendencia del IRSE se lee dentro de `render()` —bien, no toca el fingerprint— pero en
las líneas 349-350 **esa misma serie se inyecta al contexto narrativo de `positioning`** sin estar
en el payload. La trayectoria puede cambiar y el fingerprint no se entera: la narrativa cacheada
sigue describiendo la tendencia vieja.

**El feed de deltas no entra al `context` de ninguna sección narrada preexistente.** Solo al de su
propia sección, con su propia caché. Si entra a las otras, replicamos ese agujero en 17 ejes.

---

## 3. Valor dejado sobre la mesa — decisiones de ahorro a revertir

Inventario verificado en código, ordenado por valor desbloqueado contra trabajo requerido. Cada
una está asignada a una fase en §6.

### 3.1 🥇 MIVHED: microdato transaccional reducido a un conteo

`shared/data/mivhed_client.py:73,151` — el CSV trae **una fila por permiso**, con provincia,
municipio, tipología, m² e inversión en RD$. `parse_licenses` conserva `months = len(set(meses))`,
un conteo para descartar años parciales.

Se descarta granularidad **geográfica y tipológica** de un microdato que ya se descarga en cada
corrida. No es solo frescura mensual: es la diferencia entre *"el sector creció 4%"* y *"Punta Cana
concentra el 31% de los m² licenciados de uso turístico"*. Lo segundo es otro producto.

**Es la de mayor valor por unidad de trabajo de todo este plan.** El dato ya está en disco.

### 3.2 `limitations` es texto fijo hardcodeado

`modules/energy_intel/products.py:341-342` y `modules/insurance_intel/products.py:527`:
`if section == "limitations": out["limitations"] = _LIMITATIONS; continue`.

En un producto cuyo diferenciador declarado es la honestidad sobre lo que no puede afirmar, la
sección de limitaciones no dice qué le falta a *este* período de *este* eje. Es la sección que más
debería ser dinámica y es la única que nunca lo es — y con feed mensual el problema se agrava,
porque las limitaciones de un mes con fuente atrasada no son las del mes anterior.

Nota de implementación: `STATIC_SECTIONS` (`narrative_depth.py:33`) **no gobierna esto**. Su único
uso funcional (L65) es excluir la sección al elegir cuál lleva `mode="deep"`. Lo que hace estática
a `limitations` es el `if` hardcodeado en cada módulo.

### 3.3 Deal Scoring pierde sus labels por defecto

`HistoricalDeal` (`modules/deal_scoring/models/models.py`) **solo se puebla si el usuario aprieta
"Guardar al registro"**. La `learning_curve` (`modules/deal_scoring/validation/learning_curve.py`)
que decidiría si la rúbrica gradúa de declarada a modelo entrenado depende de una acción manual
opcional.

Los labels son el activo que convierte una rúbrica en IP defendible, y se están perdiendo por
defecto. `docs/CLAIMS_COMERCIALES.md:35-41` prohíbe hoy decir "modelo predictivo" — con razón, y
sin labels esa prohibición es permanente.

### 3.4 CNZFE: cuatro campos ingeridos que el índice ignora

`shared/data/cnzfe_client.py:26` parsea `wage_operator_rd`, `wage_technician_rd`,
`local_spend_musd` y `occupied_area_sqft`. `scoring/attractiveness.py` solo consume exports,
investment, jobs y companies.

**Salarios por zona franca es dato caro de conseguir y está persistido sin usar.** Gasto local y
área ocupada también.

### 3.5 ONE construcción: dato mensual descartado en el parser

`shared/data/one_construction.py:111` (`_parse_sheet`) lee únicamente la columna "Total" de hojas
cuyas columnas **son los meses** (confirmado por el fixture `test_one_construction.py:19`).

Además, `docs/SPEC_INTELIGENCIA_FUENTES_ONE_JUL2026.md` §2.3 documenta que la ONE distingue
"licencias" (149) de "construcciones" (113) para comercial y oficinas 2025 — un conteo que MIVHED
no reproduce. El conector ya trae el cuadro 4.8; el producto no publica esa métrica.

### 3.6 Sin pre-calentado, la primera descarga de cada período paga la generación

El pre-calentado se eliminó el 2026-08-20 por una razón buena —la cascada por evento ignoraba el
toggle de la consola— y hay dos tests que impiden que vuelva
(`test_regla_sin_precalentado.py`, `test_events_sin_prewarm.py`).

Efecto colateral: la primera descarga de cualquier período paga **15 a 90 segundos**. Con feed
mensual eso pasa de excepción a norma. No propongo revertirlo: propongo decidir explícitamente si
el delta del mes se genera al publicarse o al primer pedido, porque es una decisión de experiencia
que hoy se toma por omisión.

---

## 4. Correcciones al modelo comercial

Errores míos en el modelo, no del repo. Los registro para que la corrección quede trazable.

### 4.1 Precios bajados sin fundamento de valor

Puse Deep Dive en US$300 contra los **450** del tarifario, y el informe custom en US$2,500 contra
el ancla de **3,500** — la única cifra decidida en el repo
(`scripts/build_tarifario_docx.py:30`), y decidida contra consultoría de US$7,000–25,000 por
encargo (`docs/SPEC_MOTOR_RESEARCH_CUSTOM.md:33`).

Lo justifiqué como "escenario de adopción". Adopción es razón para bajar la **barrera de entrada**,
no para descontar el entregable que más se parece a lo que reemplaza. La palanca correcta es la
tarifa base y los créditos incluidos.

▶ **Corregido en el modelo: ambos vuelven al ancla documentada.**

### 4.2 El OCDS de la DGCP estaba mal clasificado

En la guía de fuentes lo agrupé con "prensa: costo alto, emisor débil" y lo puse en el puesto 6 del
orden de construcción. Es incorrecto: tiene **emisor oficial, licencia ODbL, actualización diaria y
574.694 adjudicaciones**. No es prensa — es registro público estructurado, y es el feed de eventos
con mejor procedencia de todo el inventario.

Lo penalicé por peso técnico (438 MB, `mainProcurementCategory` sin verificar), no por valor. Sube
de prioridad en §6.

### 4.3 El piloto se eligió por riesgo de implementación, no por aprendizaje

Seguros es el eje más fácil porque la plomería ya existe. También es el que menos enseña sobre
disposición a pagar, porque no es el que se está vendiendo. Sigue siendo el piloto **técnico**
correcto; §6 agrega un segundo piloto elegido por valor comercial.

---

## 5. Qué falta confirmar antes de implementar

1. 🔴 **Frescura dual.** Con índice anual y feed mensual conviviendo, una sola `DataHealth.cadence`
   no alcanza. Gobierna lógica real: `_CADENCE_THRESHOLDS` (`readiness.py:38-42`, anual = 730/2190
   días) y G1 pesa 0.30 del readiness. Si declara `"annual"`, el feed puede estar muerto tres meses
   y el gate lo da por fresco — el caso de la SIE. Si declara `"monthly"`, castiga al índice, que
   legítimamente es anual. **¿Indicador propio y visible que no toca G1, o entra al readiness con
   peso separado?** Bloquea la Fase 1.
   Agravante: `freshness_days` se deriva hoy del período del score
   (`energy_intel/products.py:234`, `construction_intel/products.py:231`:
   `date.today() - date(int(period[:4]), 12, 31)`). Para el feed esa cuenta no significa nada.
2. **Línea base por indicador.** (a) último anual publicado, (b) mismo mes del año anterior,
   (c) promedio histórico. Para estacionales —licencias, llegadas, reclamaciones— **(b) es la única
   que no confunde estación con tendencia**; para stocks (capacidad instalada), (a). Confirmar el
   criterio, no cada caso.
3. **Flujos: mes suelto o acumulado móvil de 12 meses.** `permits`, `sqm`, `investment_dop`
   (`construction_intel/models/models.py:24-26`) son acumulados anuales. Bloquea Fases 5 y 6.
4. **¿El piloto de seguros se publica o queda interno** hasta validar 12 entregas?
5. **¿La Fase 0 punto 4 (contadores en herramientas) va aquí o como plan aparte?** El modelo dice
   que el 62% del ARPU sale de esa capa, lo que argumenta separarlo y priorizarlo sobre este plan.

---

## 6. Fases

Reordenadas por valor desbloqueado. Cada fase termina con evidencia, no con "hecho".

### Fase 0 — Instrumentación

Sin esto, todo lo demás falla en silencio.

1. **Sensor de fuente congelada por eje.** `register_freshness_audit`
   (`shared/operations/freshness.py:64-71`), midiendo antigüedad del **último dato nuevo ingerido**,
   no del último sync exitoso. El patrón existe y funciona (`_audit_publications`, L161-214, escrito
   para el caso "el sync corre ok sin traer nada nuevo"). Hoy **ningún eje sectorial lo usa**.
2. **Superficie del sensor, en el mismo PR.** Dónde lo ve el operador sin abrir Sentry ni la CLI.
3. **Cerrar el ledger de costo LLM.** `shared/research/domain_router.py:240`, `relevance.py:137` y
   `entity_check.py:87` llaman `record_usage` (contador Redis) en vez de `record_call`. Y
   `shared/research/pilot.py:39,119` fija `ai_cost_usd = 0.0` con una nota hoy falsa.
4. **Contador de usos en las tres herramientas** (§5.5).

**Verificación:** apuntar deliberadamente un eje a una fuente congelada conocida y comprobar que el
sensor la marca. Un sensor no probado contra un caso positivo no está probado.

### Fase 1 — Andamiaje del delta

1. Tabla transversal de observaciones (§2.1), con las dimensiones que exige §3.1.
2. Extender el hook transversal para secciones narradas (§1), con caché propia (§2.2).
3. Resolver §5.1 y §5.2.

**Verificación:** con la tabla vacía, los 17 ejes renderizan **exactamente igual que hoy** en las
tres superficies, y la sección no aparece para un eje sin observaciones (en vez de aparecer vacía).
⚠️ Eso prueba que no se rompió nada, **no** que el delta funcione: hace falta también el caso
positivo con observaciones reales.

### Fase 2 — MIVHED: microdato completo (§3.1)

Sube al segundo puesto: el dato ya está descargado y desbloquea granularidad provincial y
tipológica, no solo cadencia. Independiente del resto de construcción.

Junto con esto, §3.5 (ONE columna "Total" y el cuadro 4.8 de construcciones).

⚠️ Requiere §5.3 resuelto antes de escribir observaciones de flujo: un mes suelto en una serie de
acumulado anual es un dato falso, no un dato parcial.

### Fase 3 — Piloto técnico: SEGUROS

El eje con toda la plomería construida: `InsuranceSeries` ya tiene `frequency` por fila
(`models.py:65`) y períodos `"2025-Q4"`/`"2025-12"` (L62); ya declara `cadence="quarterly"`
(`products.py:365`); único con vista as-of real (`service.py:98-99`, `period <= as_of`); SISALRIL y
ARS ya se ingieren mensualmente (`operations.py:141-197`); su CAGR ya interpola huecos
(`service.py:115`).

Primer eje con entrega mensual real, vendible, sin construir un conector.

### Fase 4 — `limitations` dinámica (§3.2) + labels de Deal Scoring (§3.3)

Dos deudas de honestidad y de activo, independientes entre sí y del resto. Se agrupan porque ambas
son baratas y ninguna bloquea nada.

### Fase 5 — Energía + zonas francas

Conector OC-SENI (API JSON pública sin login; IMTE mensual, 50 archivos consecutivos hasta
ago-2026). `default_interval_hours` 2160 → 720 (`operations.py:31`).

⚠️ El listado del OC devuelve **200 con `[]` para un área inexistente**, no un error. Validar contra
lista blanca, o un typo se lee como "no hubo publicaciones".

Zonas francas: exportaciones DGA/BCRD (el CNZFE es anual y solo anual, rezago ~6 meses) más los
cuatro campos ya ingeridos y sin usar (§3.4).

### Fase 6 — Turismo

Hoy corre con **una sola fuente anual** mientras `registry.py:37` declara tres inexistentes en
código. Conector JAC (XLSX 2005→jul-2026) + BCRD llegadas mensuales. Requiere §5.2(b): las llegadas
son flujo estacional puro.

Revalidar el disclaimer de `tourism_intel/ai_context.py` ("no hay serie de ocupación hotelera"):
SITUR/MITUR publica industria hotelera en XLSX mensual.

### Fase 7 — Piloto comercial: OCDS de la DGCP (§4.2)

Feed de eventos de obra pública con emisor oficial y actualización diaria. Alimenta construcción y
energía a la vez, y es el candidato con mejor procedencia del inventario.

⚠️ **Comprobación #1 antes de construir encima:** que la DGCP puebla
`tender/mainProcurementCategory = "works"`. Nadie lo verificó. Filtrar por modalidad en su lugar
subestima gravemente la obra pública — el diccionario de la DGCP dice que *Comparación de Precios*
cubre "obras menores" y *Licitación Restringida* aplica a "obras a ejecutarse"; la obra grande va
por Licitación Pública. Un corte por modalidad sería un número inventado con cara de medición.

⚠️ La API propia de la DGCP daba **502** el 2026-09-07. La vía fiable es el mirror de OCP.

### Fase 8 — Law, vía JurisAI

Depende del otro repo: exponer `NormativeDigestService._find_recent_changes` por credencial de
servicio `normas:read`. La lógica correcta ya existe —filtra por fecha de ingesta, no de
promulgación— pero solo tras JWT de usuario con perfil (`app/api/normative/profile_digest.py`).

Habilita **la negativa concluyente**: `alcance.vacio_es_concluyente` permite publicar "no se
promulgó nada que afecte este marco, y esto es concluyente", con 99,5% de reconciliación para leyes
2010-2025. Es la única afirmación del catálogo que un sustituto genérico no puede emitir.

**Fuera de alcance:** esg y social_dev. No existen resoluciones de organismos sectoriales en ningún
corpus —tampoco en JurisAI— ni hay taxonomía por sector económico. Es proyecto propio.

---

## 7. Costo

| | v1 (índice mensual) | v2 (delta estático) | **v3 (delta narrado)** |
|---|---|---|---|
| Llamadas LLM por eje-período | 6 × idioma × scope | 0 | **1** |
| Al año, 17 ejes, un idioma | ~1.224 | 102 (sin cambio) | **~204** |
| Invalidación de caché del índice | Total | Ninguna | **Ninguna**, con caché propia (§2.2) |
| Scoring a reescribir | 4 índices | 0 | **0** |

Duplica el gasto actual; no lo multiplica por doce. Y es bajo demanda: el pre-calentado no existe
(§3.6), así que solo se paga si alguien pide ese período.

Sube también la ingesta: 2160h → 720h por eje mensual, 3× las corridas de sync. Red y cómputo, no
LLM.

**Sigue sin medirse el costo por eje-mes.** La Fase 0 es lo que lo hace medible.

---

## 8. Lo que no se debe hacer

- **No meter el feed de deltas en el `context` de una sección narrada preexistente** (§2.3). Es el
  agujero que ya existe en energía y se replicaría en 17 ejes.
- **No dejar que la sección explique causas** (§0.3). El gate no puede respaldar una afirmación
  causal, y no hay citación por oración.
- **No cambiar `DataHealth.cadence` a `"monthly"`** antes de resolver §5.1.
- **No escribir observaciones de flujo antes de resolver §5.3.**
- **No filtrar obra pública por modalidad** en el OCDS (§ Fase 7).
- **No declarar la Fase 1 terminada con la tabla vacía y el render igual.** Eso prueba que no
  rompiste nada, no que el delta funcione.
