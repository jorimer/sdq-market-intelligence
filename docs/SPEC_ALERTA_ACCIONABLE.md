# SPEC — Alerta accionable suscribible

> v1 · 2026-08-20 · Documento accionable por desarrollo.
> Origen: revisión competitiva contra Dapper (`dapperglobal.com`, inteligencia regulatoria
> LATAM). El hallazgo no fue una feature que copiar sino una **categoría que a SDQ·MIP le
> falta**: el producto de FLUJO. La plataforma mide muy bien y avisa muy mal.

---

## 1. Qué es, y qué NO es

**Es**: un aviso que sale de la plataforma hacia el cliente cuando **una cifra que él eligió
vigilar cambió de manera que importa** — cruzó un umbral declarado, cambió de banda, se movió
en el ranking de su universo comparable, o perdió el dato que la sostenía.

**No es** un monitor de documentos. Dapper alerta «se publicó el PL 042/2026». Esa alerta la
puede mandar cualquiera con 327 scrapers, y su valor caduca cuando el LLM genérico resume el
PDF igual de bien. La alerta que **solo SDQ puede mandar** es la que necesita el panel:

> «La cobertura de provisiones de <entidad> cayó a 91% al 2026-Q2, tercer trimestre
> consecutivo por debajo del 100%. Es la única de las 17 entidades de su tramo en esa
> situación. Señal a monitorear anclada a la crisis RD 2003 (provisiones insuficientes).»

Ese texto no se puede producir sin la serie, sin el panel de pares y sin el universo
comparable. Ese es el foso, y la alerta es su superficie de mayor frecuencia.

**Tampoco es una predicción.** Una regla de umbral es una **señal a monitorear**, jamás una
probabilidad de quiebra ni un pronóstico — `docs/CLAIMS_COMERCIALES.md` lo prohíbe para todo
lo que no tenga backtest contra un desenlace externo, y hay una instrucción vigente del dueño
de no vender un contador de umbrales como detección temprana. El motor de propensión, cuando
exista, será un **productor más** de este canal; no cambia el gate ni el vocabulario.

---

## 2. Dónde vive

Módulo transversal nuevo: **`shared/alerts/`**. No es de sector (recorre los 16 ejes) y no es
de operaciones (no es una tarea de consola: es un producto que el cliente compra).

```
shared/alerts/
├── models.py      # AlertSubscription · AlertEvent · AlertDelivery
├── reglas.py      # catálogo de disparadores — funciones PURAS
├── motor.py       # barrido: sujetos suscriptos → reglas → gate → eventos
├── gate.py        # los seis vetos (§5) — la pieza que hace que esto sea SDQ
├── entrega.py     # canales + dedup + digest
├── router.py      # /api/v1/alerts
└── tests/
```

**Colisión de nombre a evitar**: `shared/products/subscriptions.py` ya existe y significa
**cobro** (`Subscription` concede un `AccessTier`). Lo de acá es **contenido**. Por eso el
modelo se llama `AlertSubscription` y nunca `Subscription`, y vive en otro módulo. Dos cosas
distintas con el mismo nombre en el mismo repo es cómo se escribe el bug de acceso.

---

## 3. Pieza 1 — La watchlist

Hoy SDQ no tiene el primitivo «esto me interesa». Sin él, cualquier alerta es spam o es
broadcast a admins (que es lo único que hay: `shared/operations/freshness.py` notifica a
`_admin_ids`, no a clientes).

```python
class AlertSubscription(UUIDMixin, Base):
    __tablename__ = "alert_subscriptions"

    user_id     = Column(String, nullable=False, index=True)
    sector_key  = Column(String(40), nullable=False)   # clave de PRODUCT_CATALOG
    subject     = Column(String(120), nullable=True)   # None = todo el eje
    rule_codes  = Column(JSON, nullable=True)          # None = todas las reglas del eje
    min_severity= Column(String(10), nullable=False, default="media")
    channels    = Column(JSON, nullable=False)         # ["inapp"] | ["inapp","email"]
    digest      = Column(String(10), nullable=False, default="inmediato")  # | diario | semanal
    active      = Column(Boolean, nullable=False, default=True)
```

**`subject` es texto libre a propósito.** Los 16 ejes no comparten tipo de sujeto: banca tiene
`entity_key`, macro/IRMP tienen ISO3, `social_dev` tiene provincia, `law` tiene expediente. El
contrato canónico ya lo resolvió así — `ScoreObservation.subject` es `str` y su naturaleza la
declara `CanonicalScore.subject_kind` (`shared/products/contract.py`). La watchlist **copia esa
convención en vez de inventar una segunda**; validar el sujeto es resolverlo contra
`canonical_scores()`/`canonical_series()` del producto, no contra una tabla nueva.

`subject = None` (todo el eje) es el caso real de un gremio o un supervisor: no vigila una
entidad, vigila el sistema.

---

## 4. Pieza 2 — Las reglas

### Contrato de regla

Toda regla es una **función pura** — sin sesión de base — que recibe valores ya resueltos y
devuelve `Optional[AlertEvent]`. Es el patrón que `modules/banking_score/early_warning.py` ya
usa en sus nueve `rule_*` y que hace el motor testeable sin DB; se copia, no se reinventa.

```python
def rule_<codigo>(...) -> Optional[AlertEvent]: ...
```

**`None` de entrada ⇒ `None` de salida, siempre.** Un dato ausente no dispara ni deja de
disparar: no se evalúa. Es la doctrina de la brecha aplicada al canal de mayor frecuencia — y
es donde más barato se viola, porque un `if valor > umbral` con `valor = None` en Python
levanta, pero un `if (valor or 0) > umbral` no, y publica un umbral que nadie cruzó.

### Catálogo de disparadores (v1)

| Código | Dispara cuando | Requiere |
|---|---|---|
| `umbral` | una métrica cruza un umbral **declarado y fechado** | serie + umbral en doctrina |
| `banda` | el sujeto cambia de banda/tier entre períodos | `ScoreObservation.band` |
| `posicion` | el sujeto se mueve ≥N puestos en su ranking | **universo comparable** |
| `brecha` | una dimensión que tenía dato dejó de tenerlo (o al revés) | `sources` del snapshot |
| `frescura` | el insumo de una credencial de validación quedó huérfano | `shared.validation.frescura` |
| `publicacion` | entró una edición nueva de una fuente recurrente | `shared/publications` |

Tres notas que no son de estilo:

- **`posicion` obliga a `shared.narrative.derived.universo_comparable`.** Un score armado
  sobre 3 de 5 dimensiones no rankea contra uno de 5, y una alerta de ranking es exactamente
  la superficie donde ese defecto se vuelve una afirmación falsa enviada por email. Ya pasó en
  seguros y pensiones con «7 de 35».
- **`brecha` es una alerta de pleno derecho, no la ausencia de una.** Que un eje haya perdido
  su dato es noticia para quien lo vigila; declararlo es la doctrina, y callarlo se lee como
  «no pasó nada».
- **`publicacion` ya existe a medias**: `_audit_publications` en `shared/operations/freshness.py`
  detecta la edición nueva pero solo notifica a admins. La v1 **no reescribe ese detector**: lo
  conecta como productor de este canal.

### El evento

```python
@dataclass(frozen=True)
class AlertEvent:
    codigo: str          # "umbral" | "banda" | ...
    sector_key: str
    subject: str
    periodo: str
    severidad: str       # "alta" | "media" | "baja"
    titulo: str          # computado, no redactado
    cuerpo: str          # computado, no redactado
    relaciones: Dict     # dirección, delta, posición, referencia — COMPUTADAS
    basis: str           # por qué esta regla existe (lección/doctrina que la ancla)
    procedencia: Dict    # {var: "live"|"rubric"} de lo que se afirma
    frescura: Optional[bool]   # None = indeterminado. Ver §5.
```

`relaciones` no es decorado: es el cumplimiento de «las relaciones se COMPUTAN, no se derivan».
Si en v2 el cuerpo lo redacta el modelo, **copia de este dict**; nunca lo infiere del número.

---

## 5. Pieza 3 — EL GATE (la parte que hace que esto sea SDQ)

Una alerta es una **afirmación publicada** hacia afuera, igual que un informe, y con menos
revisión humana que ningún otro artefacto de la plataforma. Por eso pasa por seis vetos antes
de entregarse. `gate.py` es el único camino a `entrega.py`.

| # | Veto | Regla |
|---|---|---|
| 1 | **Frescura** | `stale=False` publica · `stale=True` no · **`stale=None` tampoco** |
| 2 | **Brecha** | ninguna entrada `None` produce alerta; la ausencia usa `brecha` |
| 3 | **Comparabilidad** | rankings y superlativos, solo dentro del universo comparable |
| 4 | **Sujeto** | toda cuota/participación/concentración nombra su población en el texto |
| 5 | **Relación** | dirección/delta/posición vienen de `relaciones`, no de la prosa |
| 6 | **Vocabulario** | nada de «predice», «probabilidad de», «riesgo de quiebra» |

**El veto 1 es el que ya costó caro.** La asimetría de tres estados es la misma de
`shared/products/credenciales.py`: producción sirvió 19 días un Gini de 0,44 calculado con un
score que ya no existía porque nadie distinguió «no sé de cuándo es» de «está al día». Una
alerta hereda ese riesgo amplificado: el informe hay que ir a buscarlo, la alerta llega sola.

**Lo vetado se LISTA, no desaparece.** El barrido devuelve `vetadas` con motivo, y el usuario
ve en su bandeja «3 señales retenidas por frescura del dato» con enlace al detalle. Un veto
silencioso se lee como que no pasó nada, que es la lectura opuesta a la verdadera.

**El veto 6 es de vocabulario, y va con test.** El texto sale de constantes y plantillas, no de
literales incrustados — un literal se parte por ancho de línea y la frase deja de existir en el
fuente aunque el valor sea correcto.

---

## 6. Pieza 4 — El motor y su cadencia

El barrido se registra como operación del framework existente
(`shared/operations/service.py::register_operation`):

```python
register_operation(Operation(
    name="alerts-sweep", label="Barrido de alertas",
    runner=run_alerts_sweep, default_interval_hours=24, ...))
```

**Pero el reloj es el respaldo, no el disparador.** El disparador es la **cascada**: cada
operación que produce dato declara `alerts-sweep` en sus `Operation.triggers`, igual que hoy
dispara el re-score y la re-validación. Una alerta que llega un día después de que el dato
entró no es una alerta.

Es la misma cura de dos mitades de `shared/validation/frescura.py` — cascada para que corra a
tiempo, huella para que sepamos si corrió. Acá la huella es el `periodo` del evento: dos
barridos sobre el mismo período no producen dos avisos.

**Alcance por barrido**: solo sujetos con al menos una `AlertSubscription` activa. Con 16 ejes
y cientos de sujetos, evaluar todo en cada barrido es gasto sin destinatario.

---

## 7. Pieza 5 — Entrega

### Canales

| Canal | Estado | Nota |
|---|---|---|
| **In-app** | existe | `shared/notifications/service.py` + `NotificationsBell.tsx`. Ya persiste y navega por `action_url`. Se reusa entero. |
| **Email** | **a construir** | No hay emisor en `shared/`. Es la brecha real: hoy nadie se entera si no abre la plataforma. |
| **Webhook** | reusar | `shared/data_api/webhooks.py` ya firma HMAC-SHA256, entrega en hilo aparte y se autodesactiva a los 10 fallos. |
| **WhatsApp** | **fuera de v1** | Exige proveedor (BSP), plantillas aprobadas por Meta y costo por mensaje. Es apuesta de Dapper; decidir con número en mano, no por paridad. |

**Una divergencia deliberada que hay que declarar.** El webhook de la Data API decide que *«el
aviso no lleva el dato»*: solo dice qué cambió y el cliente vuelve con su llave. Una **alerta
sí lleva su contenido** — un aviso que no dice qué pasó no es una alerta. No es una
inconsistencia: son dos canales con propósito distinto, y por eso el webhook de alertas usa un
tipo de evento propio (`alert.raised`) y **no entra a `PUBLIC_EVENTS`**, que es la lista de
«hay dato nuevo».

### Dedup

Se reusa el buzón de `shared/operations/freshness.py` (`_recently_notified` / `_mark_notified`
/ `_clear_notified`): re-notifica solo si pasó otra cadencia, o si la condición se resolvió y
volvió a romperse. Esa semántica es exactamente la que hace falta y ya está probada — antes de
escribir un guard, buscar si otro módulo lo resolvió.

Hoy vive en `freshness.py` y ahora tendría dos consumidores: **promoverlo a
`shared/notifications/dedup.py`** en la misma PR, sin cambiar comportamiento.

### Ritmo

`severidad="alta"` entrega inmediata; el resto respeta el `digest` de la suscripción. Y un tope
por usuario y barrido, con el excedente resumido en una línea — nunca truncado en silencio.

---

## 8. Acceso: una alerta es una lectura

Una alerta de un eje que el usuario no tiene contratado **filtra el dato que se le está
cobrando a otro**. Dos reglas:

1. Crear una `AlertSubscription` exige `can_access` (`shared/products/access.py`) sobre ese eje.
2. **Se re-verifica en la entrega, no solo al suscribir.** Una suscripción sobrevive al fin del
   contrato; si el gate no re-chequea, el cliente que se dio de baja sigue recibiendo producto.

Cuando el acceso cae, la suscripción se **suspende** (no se borra): si renueva, vuelve a lo que
ya había elegido.

---

## 9. Superficies

**API** — `/api/v1/alerts`:

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/subscriptions` | mis vigilancias |
| `POST` | `/subscriptions` | crear (valida acceso + sujeto contra el canónico) |
| `PATCH`/`DELETE` | `/subscriptions/{id}` | editar / dar de baja |
| `GET` | `/events` | historial, con `vetadas` y su motivo |
| `GET` | `/rules` | catálogo de disparadores por eje, con su `basis` |

**UI** — dos pantallas y un botón:
- **«Vigilar»** en la ficha de cada sujeto (banco, país, provincia, ley). Es el punto de
  entrada real: nadie configura alertas desde una pantalla de configuración.
- **Bandeja** — extiende `NotificationsBell.tsx`, con filtro por eje y las retenidas visibles.
- **Mis vigilancias** — administración, en `/mi-plan` o adyacente.

---

## 10. Tests

Además de los unitarios por regla (puras, sin DB):

- **`test_gate_frescura.py`** — que `stale=None` **no** publica. Es el defecto de los 19 días,
  y sin test se reintroduce.
- **`test_regla_ninguna_entrada_none_dispara.py`** — barre el catálogo y confirma que toda
  regla con una entrada `None` devuelve `None`.
- **`test_estructural_reglas.py`** — lee `reglas.py` con `ast` y exige que toda función
  `rule_*` declare retorno `Optional[AlertEvent]` y tenga rama explícita de `None`, o una
  excepción declarada. Es la cura que este repo ya sabe que hace falta: un guard que existe en
  un motor y falta en el otro pasó cinco veces en un solo módulo. **Al escribir el glob,
  preguntarse qué queda afuera** — los productores externos (`early_warning`,
  `_audit_publications`) también emiten a este canal y deben entrar al barrido del test.
- **`test_vocabulario.py`** — ninguna plantilla contiene «predice», «probabilidad de»,
  «riesgo de quiebra».
- **`test_acceso_en_entrega.py`** — revocado el acceso, la entrega se suspende.

---

## 11. Fases

| Fase | Alcance | Deja utilizable |
|---|---|---|
| **A** ✅ | modelos + watchlist + API + botón «Vigilar» | el cliente declara qué le importa |
| **B** | `reglas.py` (`umbral`, `banda`, `brecha`) sobre **banca** + gate + in-app | alerta real punta a punta en un eje |
| **C** | emisor de email + digest + dedup promovido | el cliente se entera sin abrir la app |
| **D** | `posicion` + `frescura` + `publicacion`; productores de los otros ejes | producto transversal |
| **E** | webhook `alert.raised` | integrable por el cliente institucional |

La fase B es la que prueba la tesis: si la alerta de banca no se lee como algo que ningún
monitor de documentos podría haber mandado, el producto no es lo que este spec dice que es.

### Lo que la fase A dejó cerrado (2026-08-20)

`shared/alerts/` (models · reglas · service · router) + migración `d3f7b0a56e12` +
`/api/v1/alerts` + `VigilarButton` en el cajón del catálogo. 22 tests de backend y 8 de
componente; los tres gates en verde.

Tres decisiones que se tomaron al implementar y no estaban en este spec:

- **El nivel exigido lo determina el SUJETO**, no una constante: sin sujeto es Pulse (el
  sistema, sin nombrar), con sujeto es Insight (entidad nombrada). Es la misma línea que ya
  separa los niveles del catálogo, y tenerla acá evita que la alerta se vuelva una puerta
  lateral al dato que se cobra aparte.
- **El sujeto se valida contra `scope_options()`**, la superficie que el contrato de producto
  ya expone y que el selector del catálogo ya consume. Un producto que no la implementa es de
  sujeto FIJO: ahí el único valor legítimo es «todo el eje». No hizo falta un segundo catálogo
  de sujetos que se desincronizara del primero.
- **`subject` es NOT NULL con sentinela `''`.** Con NULL, el UNIQUE `(user, sector, subject)`
  no muerde —dos NULL son distintos entre sí en SQLite y en Postgres— y el mismo usuario podía
  tener dos vigilancias «todo el eje» del mismo eje, cada una entregando su copia. Lo prueba
  `test_la_base_RECHAZA_dos_vigilancias_iguales`, verificado contra el diseño con NULL: ahí
  falla.

Y una honestidad que la UI declara en vez de callar: la vigilancia se guarda pero **todavía no
suena** —ningún disparador tiene motor hasta la fase B— y tanto `GET /alerts/rules`
(`implementado: false`) como el botón lo dicen.

---

## 12. Fuera de v1 (declarado, no olvidado)

- **WhatsApp** — decisión de costo, no de ingeniería.
- **Cuerpo redactado por el modelo** — v1 es determinista. La narrativa IA entra cuando el
  `relaciones` computado esté estable, y **copiando** de él.
- **Reglas cruzadas entre ejes** («cae el turismo *y* sube la morosidad hotelera») — necesita
  un modelo de correlación que hoy no existe y que no se improvisa en una plantilla.
- **Alertas sobre datos privados de cliente** (`brand_intel`) — el aislamiento por cliente
  merece su propio análisis antes de sumarle un canal de salida.

---

## 13. Riesgos declarados

1. **Que la alerta sea ruido.** Es el modo de falla dominante y mata el producto en una semana.
   Mitigación: severidad, dedup con estado, digest y tope por barrido — pero la prueba real es
   la fase B con lectores reales antes de abrir los 16 ejes.
2. **Que un umbral mal calibrado publique una afirmación falsa.** Un informe se revisa; una
   alerta ya salió. Por eso todo umbral es **declarado y fechado en doctrina**, no una constante
   suelta en el motor.
3. **Que el email se lea como marketing.** Se mitiga con la métrica y su procedencia en el
   cuerpo, no con diseño.
4. **Que la suscripción de contenido se confunda con la de cobro.** Ver §2: nombres y módulos
   distintos, y test de acceso en la entrega.

---

## Anexo — Por qué esta forma y no la de Dapper

| | Dapper | Este spec |
|---|---|---|
| Disparador | apareció un documento | cambió una cifra vigilada |
| Insumo | 327 scrapers, 36K min/mes de ASR | el panel que ya existe |
| Costo marginal | flota de scrapers a mantener | un barrido sobre dato ya ingerido |
| Verificable | «modelos entrenados», sin cifra publicada | procedencia por variable + veto de frescura |
| Copiable | sí, por cualquiera con presupuesto | no sin el panel |

No se copia la máquina de Dapper. Se copia **la cadencia** — que es lo que a SDQ le falta — y
se la conecta a lo que Dapper no tiene.
