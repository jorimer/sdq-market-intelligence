# SPEC — API de datos propietarios (SDQ Data API)

**Estado:** **F1 EN PRODUCCIÓN + F2 IMPLEMENTADA** (2026-07-22).
F1 (PRs #559/#561): manifiesto auto-extensible + cuarentena calculada + llaves con cuota y
bitácora + `/catalog` y `/series`; migración corrida en prod; **llave de SDQ-PMS emitida**
(`usage=internal`) y verificada E2E — 315 series expuestas, 0 en cuarentena.
F2: `/scores/{sector}` (desglose dimensional numérico, jamás narrativa), `/signals/{sector}`
(motor determinista) y `/quality/{sector}` (el registro de honestidad servido al cliente,
con la prosa de procedencia GENERADA). Productores iniciales: `macro`→IRMP + señales de
alerta temprana; `esg`→IRC. Auto-extensión también en scores: un sector que declare
`canonical_scores()` aparece sin tocar la capa API. Guía de consumo para clientes:
[`GUIA_CONSUMO_DATA_API.md`](GUIA_CONSUMO_DATA_API.md). Las decisiones abiertas de §9 se
toman cuando se necesiten, por decisión del dueño.
**Fecha:** 2026-07-22
**Origen:** "capa de distribución del Anexo B" diferida a Fase 2/3 en
[`SPEC_PLATFORM_PRODUCTIZATION.md`](SPEC_PLATFORM_PRODUCTIZATION.md) §6 y
[`SPEC_TIER_PRODUCTIZATION_BANKING.md`](SPEC_TIER_PRODUCTIZATION_BANKING.md) §4.
**Decisiones del dueño que fijan el alcance (2026-07-22):**
1. Se expone **lo propietario**, no el dato crudo.
2. **Lo más amplia posible**: entran las series canónicas normalizadas *y* todos los datos derivados.
3. **Auto-extensible**: cada serie normalizada o activo derivado nuevo queda expuesto **por defecto**
   a medida que Market Intelligence lo produce, sin que nadie tenga que cablear un endpoint.
4. **Primer cliente = SDQ-PMS™**, consumiendo **vía la API** (no DB compartida). Ver §8.

---

## 1. Qué es y qué no es

**Es:** un canal máquina-a-máquina para que un cliente incorpore a sus propios sistemas
(modelos de riesgo, tableros, ALM, comités) los **activos que SDQ produce**: scores, índices,
series normalizadas con linaje, veredictos y track record.

**No es:** un espejo del dato público. El BCRD, la SIB, SIPEN, la DGA y el Banco Mundial ya
publican sus cifras; re-servirlas no es un producto y compite con fuentes gratuitas.

### 1.1 Frontera de exposición (la regla que decide cada endpoint)

La decisión es **máxima amplitud**: todo lo que la plataforma normaliza o deriva se expone. La
lista corta de exclusiones no es de amplitud, es de protección del negocio y de la IP.

| Se expone — todo lo normalizado y derivado | No se expone (4 exclusiones, y solo estas) |
|---|---|
| Scores compuestos y sus dimensiones: ISA (banca), ISA/ISF (pensiones, seguros), IRMP (riesgo macro-político), IRC (ESG), IAI (atractivo de inversión) | **1. El payload crudo del conector** tal como llega de SIB / BCRD / SIPEN / DGA / WB, y los PDF/Excel originales del emisor. No aporta valor y compite con la fuente gratuita. |
| **Todas** las series canónicas normalizadas (`mm_series` y equivalentes por módulo), con período canónico, unidad, frecuencia y linaje | **2. La narrativa IA completa** del Insight / Deep Dive. Ese *es* el producto de reporte; servirlo por API lo canibaliza. |
| Bandas cualitativas, percentiles, posición en panel comparado, trayectoria multi-período | **3. El núcleo de IP**: prompts, doctrina, `cerebro.py`, rúbricas internas, pesos del XGBoost entrenado, rúbrica del Deal Scoring. |
| Veredictos y señales deterministas (alerta temprana, precursores), y el registro de señales por variable (`AxisRegistry` / `VariableSignal`) | **4. Lo que la licencia del emisor no permite redistribuir**, y lo que está bajo cuarentena automática (§3.1). |
| Track record de pronósticos (`tpm_forecast_log`) con acierto verificable | |
| Metadatos de calidad: cobertura real ponderada, frescura, gates G1–G5, caveats, estado REAL/RUBRIC/GAP por variable | |

Nótese que la exclusión 2 protege el margen y la 3 la IP: **ninguna de las dos limita el dato**.
Un cliente puede reconstruir su propio análisis con lo que la API le da; lo que no obtiene es el
dictamen redactado de SDQ.

**Caveat comercial, sin adornos:** cuanto más se acerca la API al dato normalizado bruto, más
grande el universo de compradores y más frágil el precio — la serie normalizada es replicable por
un equipo con tiempo, el score no. Máxima amplitud es la decisión correcta para adopción y para
volverse infraestructura del mercado; solo conviene saber que el poder de fijar precio vive en
los scores y en el track record, no en las series.

---

### 1.2 Calculamos, no revendemos (decisión del dueño, 2026-07-22)

El negocio es el cálculo, no el traslado del dato ajeno. Eso se implementó como **dos ejes
independientes**, porque la pregunta "¿esto es reventa?" no se contesta mirando la fuente:

**Eje 1 — qué se sirve** (`derivation`, declarado por el producto en cada activo):
- `verbatim`: el valor del emisor, normalizado (período canónico, unidad, linaje). Servirlo
  **es** redistribuir → lo alcanza la licencia de la fuente.
- `derived`: cálculo de casa (índice, score, tasa deflactada, brecha). Es obra propia: una
  restricción no-comercial del insumo no impide servir el **resultado**.

**Eje 2 — para qué lo usa quien lo recibe** (`usage`, declarado en la llave):
- `internal`: insumo de análisis propio; el dato no sale hacia terceros. Es el caso de
  SDQ-PMS, que interpreta el mercado con esto.
- `external` (default): el consumidor podría reexponerlo → solo recibe lo que la licencia
  de origen permite redistribuir.

Ambos defaults son los restrictivos: lo permisivo se declara, nunca se asume. La detección
de licencias restrictivas es una heurística por patrón (NC · share-alike · ODbL) que
**marca para revisión, no dictamina** — no sustituye leer los términos.

**Dónde muerde hoy:** ITU (espina del sector telecom desde que murió INDOTEL) declara
`CC BY-NC-SA 3.0 IGO` — no-comercial y share-alike. SIS/SISALRIL (seguros) declaran ODbL.
Los scores construidos sobre esos insumos salen sin problema; las series tal cual, solo a
una llave `internal`. El resto del corpus (BCRD, Banco Mundial CC-BY, Datos Abiertos RD,
NOAA dominio público) no toca este filtro.

---

## 2. Doctrina que la API hereda (no negociable)

La plataforma ya tiene reglas de honestidad de dato. La API las hereda **en el payload**, no
en una nota al pie:

1. **Point-in-time.** Todo recurso acepta y devuelve `as_of`. Un score consultado hoy para un
   período pasado devuelve lo que se sabía entonces, no la revisión posterior.
2. **Linaje obligatorio.** Cada valor viaje con `source`, `source_period`, `retrieved_at`,
   `method`. Sin fuente citable, no se sirve.
3. **Nulo honesto.** Un indicador sin dato devuelve `null` + `reason`, nunca un valor imputado
   ni un cero. Prohibido inventar para completar un payload.
4. **Caveats condicionales.** Los mismos que ya emiten los reportes viajan como arreglo
   `caveats[]` estructurado.
5. **Gates de publicación.** No se sirve por API un (sector, recurso) cuya readiness esté por
   debajo del umbral que ya gobierna la publicación del producto equivalente.

---

## 3. Auto-extensión: la API se genera del registro, no se cablea a mano

Esta es la exigencia que define la arquitectura. Si cada serie nueva requiriera un endpoint
nuevo, la API quedaría desactualizada respecto de la plataforma en el primer trimestre y el
costo de onboarding de un sector subiría. La regla es:

> **Ningún endpoint conoce una serie ni un indicador concreto.** La superficie se deriva del
> registro; agregar una serie normalizada o un derivado nuevo la publica automáticamente.

### 3.1 Cómo funciona

La plataforma ya tiene la mitad del andamiaje: [`shared/registry/signals.py`](../shared/registry/signals.py)
enumera cada eje con sus variables, estado (REAL / RUBRIC / GAP), fuente, cadencia y cobertura
ponderada; [`MacroSeries`](../modules/macro_monitor/models/models.py) ya guarda `series_code`,
`period`, `unit`, `frequency`, `source`, `published_at` y **`license`** por observación. Lo que
falta es un **manifiesto de exposición** que se resuelva en tiempo de consulta:

1. **Descubrimiento**: la API enumera los activos publicables recorriendo el registro de ejes +
   el catálogo de series, no una lista escrita a mano.
2. **Default expuesto**: un activo nuevo aparece en `/catalog` y es consultable **sin cambio de
   código**. El onboarding de un sector (ver [`RECETA_ONBOARDING_SECTOR.md`](RECETA_ONBOARDING_SECTOR.md))
   no gana un paso "publicar en la API": ya está publicado.
3. **Cuarentena automática** — un activo se retiene, sin intervención humana, si:
   - su readiness está por debajo del umbral que ya gobierna la publicación del producto;
   - su `license` de origen no permite redistribución (campo ya existente, hoy poco poblado);
   - el sector aún no está activado (`ProductActivation`), o el backfill está en curso.
   La cuarentena es **estado calculado, no lista curada**: se levanta sola cuando la condición
   deja de aplicar. Así "lo más amplia posible" no depende de que alguien se acuerde de aprobar.
4. **Contrato estable sobre inventario cambiante**: los endpoints son genéricos
   (`/series?code=…`, `/scores/{sector}`), así que el inventario crece sin romper a nadie. Lo
   que cambia es el contenido de `/catalog`, que el cliente consulta para descubrir novedades.
5. **Changelog máquina-legible**: `/catalog/changes?since=…` lista altas, bajas y cambios de
   método. Un cliente que automatiza no debería enterarse de una serie nueva por email.

### 3.2 El costo real de esta decisión

Auto-exponer traslada el riesgo aguas arriba: **cualquier serie que se cablee mal queda
publicada a terceros el mismo día**. Hoy un error de ingesta se ve en un reporte interno antes
de llegar al cliente; con auto-extensión, no. Contrapesos, todos automáticos:

- La cuarentena por readiness es el filtro principal — una serie recién cableada no pasa el gate
  hasta tener cobertura y frescura.
- Un activo entra a `/catalog` marcado `stability: "new"` durante su primer ciclo, y el cliente
  puede filtrarlo. No se oculta; se etiqueta.
- Poblar `license` deja de ser opcional: un conector nuevo sin licencia declarada queda en
  cuarentena por omisión (conservador, igual que `normalize_state` asume GAP).

Esto último es trabajo real que hoy no está hecho: `license` existe como columna pero no está
poblada de forma consistente en los ~40 conectores. Es prerrequisito de F1, no de F3.

---

## 4. Superficie propuesta

Namespace **separado** del interno: `/api/data/v1/…`. Motivo: `/api/v1/*` es el contrato de la
SPA, cambia con el frontend y no puede quedar congelado por terceros. Versionado explícito,
con política de deprecación anunciada (mínimo 6 meses).

```
GET /api/data/v1/catalog                         # inventario completo visible para ESTA llave
GET /api/data/v1/catalog/changes?since=…         # altas/bajas/cambios de método (auto-extensión)
GET /api/data/v1/series?code=…&from=…&to=…       # cualquier serie canónica normalizada + linaje
GET /api/data/v1/scores/{sector}                 # scores del sector, filtrable por entidad/período
GET /api/data/v1/scores/{sector}/{entity_id}     # ficha de score + dimensiones + trayectoria
GET /api/data/v1/indices/{index_key}             # IRMP · IRC · IAI (país / panel comparado)
GET /api/data/v1/signals/{sector}                # alertas tempranas y veredictos deterministas
GET /api/data/v1/forecasts/{model_key}           # pronósticos + track record verificable
GET /api/data/v1/quality/{sector}                # readiness, frescura, cobertura, caveats
```

Ninguna ruta nombra una serie ni un indicador: todas toman la clave como parámetro y la resuelven
contra el registro (§3). Por eso el inventario crece sin tocar el enrutador.

Convenciones: paginación por cursor, `Retry-After` en 429, respuestas en JSON con `meta`
(as_of, quota restante, `method_version`, `stability`) + `data` + `caveats`. **Excepción a la
convención del repo:** los mensajes de error de esta API van en español **e** inglés
(`message` / `message_en`), porque el consumidor es un sistema de terceros que puede no ser
dominicano.

---

## 5. Autenticación, cuotas y acceso

Hoy el auth es JWT de usuario + RBAC ([`shared/auth`](../shared/auth)) — sirve para una SPA, no
para máquina-a-máquina. Hace falta construir:

- **Llaves de API**: `sdq_live_<prefix>_<secret>`; se guarda solo el hash (bcrypt/argon2) + el
  prefijo visible para identificarla en la UI. Se muestra el secreto **una sola vez**. Rotación
  y revocación por el dueño de la cuenta; caducidad opcional.
- **Scopes derivados del SKU**, no declarados a mano: la llave hereda los entitlements del
  usuario/organización vía el resolvedor que ya existe ([`shared/products/access.py`](../shared/products/access.py)),
  más un scope nuevo `api:read`. Un cliente sin SKU de API tiene entitlements de lectura web
  pero **no** de API — son ejes independientes.
- **Cuotas y rate limit** por llave: llamadas/minuto y llamadas/mes según el plan. Excederse
  devuelve 429, nunca datos degradados ni silenciosamente truncados.
- **Bitácora de uso** por llamada (llave, recurso, `as_of`, filas servidas, latencia) — insumo de
  facturación, de soporte y de detección de scraping masivo.
- **Marca de agua lógica**: cada respuesta lleva `license` y `client_ref`; permite rastrear
  redistribución no autorizada de un payload filtrado.

### 5.1 Modelo comercial

Familia de SKU nueva, coherente con [`shared/billing/skus.py`](../shared/billing/skus.py):

- `api:{sector}` — acceso de API a los activos de un sector (mensual/anual).
- `api_all_access` — todos los sectores, **incluidos los que se agreguen durante la vigencia**.
  Con auto-extensión esto es una promesa real de valor creciente, no una frase de marketing: el
  cliente que compra hoy recibe los sectores nuevos sin renegociar. Es el argumento de venta más
  fuerte que habilita la decisión de amplitud.
- El plan `enterprise` **no** incluye API por defecto: es un SKU aparte. Regalarlo con el
  enterprise canibaliza el Deep Dive recurrente.

Consecuencia de precio a tener presente: si el bundle crece solo, el precio fijado con 14 sectores
queda barato con 20. Conviene revisión anual de tarifa, o cobrar por cuota de consumo además del
acceso.

Términos de licencia obligatorios antes del primer cliente: uso interno, prohibición de
redistribución y de reventa, atribución requerida al citar, y la cláusula de que SDQ no
garantiza continuidad de una serie cuyo emisor primario la discontinúe (ya pasó: turismo BCRD,
INDOTEL, Doing Business).

---

## 6. Fases

Con la decisión de amplitud + auto-extensión, el orden cambia respecto de un roadmap por
recursos: **primero el manifiesto y la cuarentena, después los recursos** — porque una vez que
existe el manifiesto, los recursos entran solos.

| Fase | Alcance | Sensor de cierre |
|---|---|---|
| **F0 · Decisión** | ~~El dueño resuelve §9~~ → **decidido**: se implementa ya; las abiertas se resuelven cuando la necesidad llegue. | ✅ |
| **F1 · Manifiesto + cimiento** | Manifiesto de exposición sobre el catálogo de productos; cuarentena calculada (readiness · licencia · activación); llaves + hash + scopes + cuotas + bitácora; `/catalog` y `/series` genéricos. | ✅ **Hecho**: 65 tests; el manifiesto de dev expone 4 series y retiene 3 por `no_license`. Pendiente: migración en prod + llave de PMS. |
| **F2 · Cobertura derivada** | `scores`, `indices`, `signals`, `quality` — todos resueltos por registro, no por sector cableado. | Un sector publicado nuevo expone sus scores sin PR en la capa API. |
| **F3 · Profundidad** | ✅ **Hecho**: `forecasts` + track record (TPM), `catalog/changes` sobre ledger de activos, webhooks firmados (HMAC) de "nuevo snapshot", SDK Python vendoreable. Pendiente: portal de documentación público. | ✅ Verificado en dev: aviso entregado a un receptor real con firma válida, sin el dato en el payload; `/catalog/changes` reporta las 10 altas del inventario. |

### 6.1 Cómo quedó implementada F1

| Pieza | Dónde |
|---|---|
| Contrato opcional `canonical_series()` / `series_observations()` | `shared/products/contract.py` |
| Manifiesto + cuarentena calculada | `shared/data_api/manifest.py` |
| Llaves (SHA-256 sobre secreto de 256 bits, no bcrypt — ver el docstring) | `shared/data_api/keys.py` |
| Cuota mensual + rate limit, contados en DB (no en memoria: hay varios workers) | `shared/data_api/quota.py` |
| Autenticación y alcance por entitlements del dueño | `shared/data_api/dependencies.py` |
| Rutas públicas `/api/data/v1/{catalog,series}` | `shared/data_api/router.py` |
| Consola del dueño (emitir/revocar/uso + manifiesto interno con cuarentena) | `shared/data_api/admin_router.py` |
| Primer productor real: series canónicas del monitor macro | `modules/macro_monitor/service.py` |
| Migración | `infrastructure/alembic/versions/a4d7e2f9b115_…` |

**Hallazgo del smoke contra dev:** de 7 series macro, 3 quedaron retenidas por `no_license` —
entre ellas una de **491 observaciones** (inflación interanual, 1985→hoy). El código de los
conectores SÍ declara licencia hoy; esas filas son **anteriores** a que se agregara, y como el
upsert reescribe la licencia en cada corrida, **una re-sincronización las libera sola**. Es la
cuarentena funcionando como se diseñó, no un bug — pero implica que una serie de un conector
que ya no corre (INDOTEL, fuentes discontinuadas) queda retenida para siempre. Decidir si eso
se acepta (postura conservadora) o si se declara la licencia históricamente es del dueño; el
manifiesto interno de admin muestra exactamente qué está retenido y por qué.

**Segundo hallazgo:** `MacroSeries.frequency` no la puebla ningún ingestor, así que toda serie
se reportaba como cadencia "unknown". Se deriva del formato del período canónico (`2025` → anual,
`2025-Q1` → trimestral, `2025-01` → mensual), que sí es dato real fijado por el parser.

F1 fue la fase cara. De acá en adelante es incremental: el manifiesto ya existe, así que una
serie nueva se publica sola.

---

## 7. Riesgos

1. **Canibalización.** Si la API sirve todo lo que trae el Deep Dive, el cliente deja de
   comprar el reporte. Mitigación: la narrativa, el encuadre y el dictamen NO van por API —
   ese es el producto de reporte.
2. **Soporte de contrato.** Una API pública congela decisiones internas: renombrar un
   `sector_key` o cambiar el método de un índice pasa a ser breaking change. Por eso namespace
   separado, versión y campo `method_version` por valor.
3. **Redistribución.** El activo se copia una vez y se revende. Mitigación: licencia + marca de
   agua lógica + detección de patrón de descarga masiva en la bitácora.
4. **Derechos sobre el derivado.** Un score construido sobre dato público es propio; una serie
   normalizada sobre un emisor con términos restrictivos, no siempre. Con auto-extensión esto
   deja de ser revisable caso por caso: por eso `license` sin poblar ⇒ cuarentena (§3.1), que es
   el único control que escala.
5. **Publicar un error el mismo día.** Consecuencia directa de la auto-extensión; ver §3.2.
6. ~~**Sobre-construir.**~~ Mitigado: hay cliente concreto (§8). Queda el riesgo inverso —
   construir para un cliente interno y descubrir que un externo necesita otra cosa. Mitigación:
   contrato genérico resuelto por registro, no moldeado a PMS.

---

## 8. Primer cliente: SDQ-PMS™ (decisión del dueño, 2026-07-22)

El primer consumidor es **SDQ-PMS** (`~/Developer/SDQ-PMS`, app SaaS multi-tenant del grupo),
**vía la API** — no por DB compartida ni por volcado de archivos. Es la decisión correcta: obliga
a que el contrato sea real antes de venderlo afuera, y evita acoplar dos esquemas de base de datos
que evolucionan por separado.

### 8.1 Qué gana PMS desde el día 1 (hallazgo concreto)

PMS tiene hoy un conector llamado `bcrd` que **no consume el BCRD**: baja la tasa USD/DOP de
`open.er-api.com`, un agregador gratuito sin autenticación. Su propio docstring reconoce que la
fuente oficial del BCRD queda "post-MVP regulatorio… hasta que un cliente regulado pida fuente
oficial".

MIP ya tiene esa fuente oficial resuelta: conector live del BCRD con token e IPs de Railway en
allowlist, más el ETL histórico (268 series). Para una app que apunta a asesoría bajo licencia
**SIMV**, la diferencia entre "agregador gratuito" y "serie oficial citable con linaje y
point-in-time" no es cosmética: es la diferencia entre poder sustentar una recomendación ante el
regulador y no poder.

Casos de uso inmediatos para PMS, por orden de valor:
1. **FX y macro oficial citable** — reemplaza el agregador por serie BCRD con `source`,
   `published_at` y `as_of`.
2. **Bloque macro RD del "SDQ Outlook"** — la Fase 4 del programa ya ensambla secciones firmadas;
   el editorial macro puede alimentarse de series e índices de MIP en vez de investigarse a mano.
3. **Contexto país para el cerebro de tres capas** — IRMP, IRC e indicadores sectoriales como
   features del motor cuanti.

### 8.2 Qué implica que el primer cliente sea interno

- **Es dogfooding, no una excepción.** PMS consume con llave de API, cuota y bitácora como
  cualquier cliente externo. Si se le da un atajo (acceso directo a la DB, endpoint sin llave),
  la API no queda probada y el primer cliente externo estrena bugs.
- **Sin facturación en F1.** El SKU `api_all_access` se otorga como entitlement interno; el motor
  de cobro no bloquea el arranque. Lo que sí se ejerce desde el día 1 es scope + cuota + log.
- **Multi-tenancy de PMS ≠ multi-tenancy de MIP.** PMS es multi-workspace; MIP es mono-tenant. La
  llave pertenece a **PMS como organización**, no a cada workspace de PMS. PMS reexpone el dato a
  sus workspaces bajo su propio control de acceso — y eso lo convierte en un caso de
  **redistribución interna** que los términos de licencia deben contemplar explícitamente antes
  del primer cliente externo, o se sienta un precedente incómodo.
- **El contrato lo fija el uso real.** La lista de endpoints de §4 se valida contra lo que PMS
  necesita de verdad; lo que PMS no use en 3 meses probablemente tampoco lo use un cliente externo.

### 8.3 Ajuste al plan por tener cliente

F1 se justifica ahora (había recomendado no arrancar sin cliente). Orden sugerido dentro de F1:
manifiesto + cuarentena + llaves + `/catalog` + `/series`, y como sensor de cierre, **PMS
consumiendo FX y macro oficial en su entorno de staging con llave real** — no un cliente de prueba
sintético.

---

## 9. Decisiones abiertas (del dueño, no de código)

1. ~~¿Hay cliente?~~ **Resuelto:** SDQ-PMS, vía API. Ver §8.
2. ~~¿Series o solo scores?~~ **Resuelto:** lo más amplio posible, con auto-extensión. Ver §3.
3. **¿PMS retira su conector propio o corre en paralelo un tiempo?** Recomiendo paralelo un
   trimestre con comparación de valores — si MIP y el agregador difieren, quiero saberlo antes de
   que lo note un comité de inversión.
4. **Licencia de redistribución interna del grupo:** ¿PMS puede mostrar el dato de MIP a sus
   clientes finales, o solo usarlo como insumo de cálculo? Afecta el texto de los términos y el
   precio del futuro cliente externo que pida lo mismo.
5. **¿Tier académico gratuito?** Estaba en el Anexo B original. Sirve de vitrina y de citación
   externa; cuesta soporte y cuota.
6. **Precio y unidad de cobro para terceros:** ¿por sector, por llamada, por asiento, o cuota
   mensual plana? Con bundle auto-creciente, revisar tarifa cada año.
7. **Alcance del contrato:** ¿SDQ garantiza SLA de disponibilidad y frescura? Un SLA es una
   obligación operativa real sobre syncs que hoy dependen de emisores que rompen sin aviso. Para
   PMS bajo SIMV esto pesa más que para un cliente cualquiera.
