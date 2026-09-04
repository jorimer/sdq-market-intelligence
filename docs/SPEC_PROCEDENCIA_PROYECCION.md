# SPEC — Procedencia de proyección: la cuarta categoría

> Versión v0.1 · 2026-09-03 · Documento de construcción.
> Etiquetas de confianza: **[Certain]** verificable contra código/doc citado ·
> **[Likely]** inferencia fuerte, no probada · **[Guessing]** supuesto a validar ·
> **[Lock]** decisión ya tomada por el dueño.

> **Disciplina de notación.** La escala de letras SDQ-AAA…D está RETIRADA
> (`CLAUDE.md`). El guard `shared/narrative/tests/test_sin_notacion_heredada.py` lee
> `ast` sobre `modules/` y `shared/` — **no cubre los `.md`**. En este documento y en
> todo lo que derive de él, la disciplina es manual. Perfil SDQ de dos ejes:
> Resiliencia (absoluta, cortes 75/60/45) y Ejecución (relativa, cuartiles por panel).

> **Documento bloqueante.** `SPEC_MOTOR_PROYECCION_MACRO`, `SPEC_VALUADOR_ENTIDADES` y
> cualquier producto forward-looking futuro dependen de que esto exista primero. No es
> una capa opcional: es el permiso para que la plataforma diga algo sobre el futuro sin
> romper la disciplina que la distingue.

---

## 0. Qué se construye (BLUF)

Una **cuarta categoría de procedencia** —`PROJECTED`, "proyección declarada"— en
`shared/registry`, con su gate de admisión, sus frases de prosa y su tratamiento
separado en cobertura.

SDQMIP hoy tiene tres estados y son todos retrospectivos: `real` (dato observado con
lineage), `rubric` (supuesto de la casa declarado), `gap` (brecha declarada). El
`REPORT_STANDARD` exige que toda afirmación material ancle a uno de los tres.

**Una proyección no es ninguno de los tres.** No es dato real —no ocurrió—; no es
rúbrica —no es un supuesto de ponderación sino una inferencia de un modelo con error
medible—; y declararla brecha, que es lo que el código hace hoy
(`shared/research/orchestrator.py:114-127`, `_forward_gaps`), significa no poder
venderla.

La decisión de diseño central: **`PROJECTED` ancla una afirmación, pero NO suma a
cobertura real.** Si sumara, cualquier producto podría inflar su cobertura proyectando
lo que no midió. Esa asimetría es todo el spec.

---

## 1. Principio rector

> Una proyección es admisible cuando el lector puede saber **de qué modelo salió, con
> cuánta incertidumbre, y qué tan mal le fue a ese modelo antes**. Sin las tres, es una
> opinión con decimales y se declara brecha.

Esto no es prudencia decorativa. Es la extensión natural de la regla que ya rige la
plataforma: lo que no hay se declara, no se rellena. La novedad es que ahora hay una
forma legítima de hablar del futuro — y tiene precio de entrada.

---

## 2. Estado real (verificado contra código, 2026-09-03)

### 2.1 Los tres estados actuales

`shared/registry/signals.py:24-26` — constantes string, **no Enum**:

```python
REAL = "real"       # dato real con lineage
RUBRIC = "rubric"   # rúbrica declarada
GAP = "gap"         # brecha declarada
```

`_STATE_ALIASES` (`:48-52`) normaliza entradas sucias; `normalize_state(raw) -> str`
(`:55`) devuelve `GAP` ante lo desconocido. **[Certain]**

### 2.2 Dónde vive el juicio de cobertura

| Punto | Ruta | Comportamiento actual |
|---|---|---|
| Crédito de cobertura | `signals.py:155-159` `_real_credit(s)` | Da crédito **solo** si `state == REAL`, y por `real_fraction` (parcial cuenta parcial) |
| Cobertura ponderada | `signals.py:133` `AxisRegistry.coverage_real` | Suma `weight × _real_credit` |
| Conteo por estado | `signals.py:147` `state_counts` | Inicializa `{REAL:0, RUBRIC:0, GAP:0}` pero acumula con `counts.get(s.state, 0)` |
| Resumen global | `signals.py:173` `DataRegistry.summary.by_state` | Mismo patrón: 3 claves iniciales, acumulación con `.get` |

**[Certain] Matiz importante:** `state_counts` y `by_state` **no explotan** con una clave
nueva — ambos acumulan con `.get(k, 0)`. Lo que hacen es no inicializarla en cero, así que
un eje sin señales proyectadas omitiría la clave en vez de reportar `projected: 0`. El
cambio es de consistencia de reporte, no de corrección. `_real_credit` y `coverage_real`
sí requieren cambio explícito.

### 2.3 El punto de anclaje del gate

`shared/research/models.py:77-80`:

```python
@property
def anchored(self) -> bool:
    return self.state in (REAL, RUBRIC)
```

**[Certain]** Esta línea es el interruptor. `evaluate_gate` (`shared/research/gate.py:20`)
calcula `gap_fraction = 1 - anchored_fraction` y manda a `GATE_SCOPING` si supera
`DEFAULT_GAP_THRESHOLD = 0.40` (`:17`).

### 2.4 Lo prospectivo ya está detectado — y bloqueado

- `shared/research/decompose.py:179-189` — `is_forward_looking(question)` con `_FORWARD_RE`.
- `shared/research/orchestrator.py:114-127` — `_forward_gaps(...)` emite `DeclaredGap`
  con nota del tipo "no se estima".

**[Certain]** La plomería de detección existe. Lo que falta es la vía legítima al otro
lado del `if`.

### 2.5 Estructura de la señal

`VariableSignal` — `@dataclass(frozen=True)`, `signals.py:65-113`. Campos actuales:
`key, label, state, dimension, weight, source, cadence, value, period, history,
real_fraction, note, scope`. **[Certain]**

### 2.6 Lo que NO existe

- **[Certain]** No hay ORM de registry ni de lineage. `build_data_registry(db)`
  (`shared/registry/service.py:119`) computa en lectura recorriendo `PRODUCT_CATALOG` y
  llamando el método opcional `variable_signals()` de cada producto.
- **[Certain]** No hay `shared/products/packaging.py`. El precio vive en
  `shared/billing/` (`skus.py:45-53`, `tariffs.py:81`).
- **[Certain]** No existe ninguna noción de horizonte, intervalo de confianza ni error
  fuera de muestra en el vocabulario de procedencia.

---

## 3. Diseño

### 3.1 La constante y su normalización

`shared/registry/signals.py`:

```python
REAL = "real"
RUBRIC = "rubric"
GAP = "gap"
PROJECTED = "projected"   # proyección declarada — ver SPEC_PROCEDENCIA_PROYECCION

STATES = (REAL, RUBRIC, PROJECTED, GAP)
```

`_STATE_ALIASES` suma: `"projected" | "proyeccion" | "proyección" | "forecast" |
"nowcast" → PROJECTED`.

**[Lock]** `normalize_state` mantiene `GAP` como destino de lo desconocido. Una cadena
que no reconocemos nunca escala a proyección.

### 3.2 Metadato obligatorio de proyección

Campo nuevo en `VariableSignal`, opcional en el tipo y **obligatorio en el gate**:

```python
@dataclass(frozen=True)
class ProjectionMeta:
    model_id: str          # modelo Y su versión, en un solo identificador.
                           # Ej: "bridge_imae_pib.m2.v1" — la variante es parte del id
    target_series: str     # series_code proyectado
    horizon: str           # "2026-Q4" | "+1T" | "+4T"
    as_of: str             # fecha de corte de la información usada (point-in-time)
    revision: int          # 0 = como se publicó; 1+ = corrección posterior
                           # los cinco campos de arriba son la clave del ledger
    point: float           # la estimación central
    intervals: Tuple[Tuple[float, float, float], ...]
                           # ((level, lo, hi), ...) — p.ej. ((0.80, 3.1, 4.7), (0.90, 2.6, 5.2))
    backtest_id: str       # clave del conjunto de backtest (§3.2.1)
    oos_error: float       # RMSE/MAE fuera de muestra del backtest citado
    error_metric: str      # "rmse" | "mae" — nombrada, no inferida
    n_oos: int             # observaciones fuera de muestra que sostienen el error
    n_oos_overlapping: bool  # True si las ventanas se solapan (ver §3.2.2)
    interval_coverage: Tuple[Tuple[float, float, int], ...]
                           # ((level, cobertura_observada, n), ...) — calibración empírica
```

**[Lock] Un solo campo de versión.** `model_id` incluye modelo, variante y versión. Un
`model_version` separado versionaría lo mismo dos veces y admitiría que se contradigan. La
variante del nowcast (`m1`/`m2`/`m3`, `SPEC_MOTOR_PROYECCION_MACRO` §3.2) es parte del
`model_id` porque **es un modelo distinto**, con su propio backtest.

**[Lock] `interval_coverage` no es opcional.** Un modelo cuyo intervalo del 80% acierta el
45% de las veces está mal calibrado aunque su RMSE sea bajo. Sin este campo la calibración
no tiene dónde viajar hasta el reporte, y el `[Lock]` que exige publicarla queda sin
portador.

#### 3.2.1 `backtest_id` — qué resuelve

**[Lock]** `backtest_id` es la tupla `(model_id, target_series, horizon)` serializada como
`"{model_id}|{target_series}|{horizon}"`. Identifica el **conjunto** de pronósticos ya
puntuados de ese modelo para ese objetivo y horizonte — no una fila individual. El ledger
que lo materializa se define en `SPEC_MOTOR_PROYECCION_MACRO` §3.6; el gate solo exige que
resuelva a un conjunto con `n_oos ≥ MIN_OOS` filas en estado `scored`.

Un `backtest_id` que no resuelve es rechazo, no advertencia.

#### 3.2.2 Solapamiento

**[Lock]** Doce pronósticos a horizonte de 8 trimestres tomados trimestre a trimestre
comparten información: no son doce observaciones independientes. `n_oos_overlapping`
declara esa condición y la prosa de §3.5 la nombra. No se corrige el conteo hacia abajo con
una fórmula inventada; se declara, que es lo que la casa hace con toda limitación.

`MIN_OOS` aplica sobre `n_oos` tal cual, pero el gate **exige** que
`n_oos_overlapping` esté explícitamente seteado — no admite `None`.

Y en `VariableSignal`: `projection: Optional[ProjectionMeta] = None`.

**[Lock]** `as_of` es obligatorio y no decorativo: sin corte point-in-time no se puede
distinguir un pronóstico de un ajuste con información posterior. Esa distinción es la
diferencia entre track record y autoengaño.

### 3.3 Cobertura: la asimetría

```python
def _real_credit(s: VariableSignal) -> float:
    return s.real_fraction if s.state == REAL else 0.0          # SIN CAMBIO

def _projected_credit(s: VariableSignal) -> float:
    return s.real_fraction if s.state == PROJECTED else 0.0     # NUEVO
```

**[Lock]** `_projected_credit` usa `real_fraction`, **no `1.0` plano**, por simetría con
`_real_credit`. En un panel donde solo algunos sujetos se proyectan, una señal proyectada
parcialmente cubierta debe contar parcialmente. Un `1.0` plano sobreestimaría la cobertura
proyectada — el mismo error que el spec previene del lado real.

`AxisRegistry` gana una propiedad hermana, no un reemplazo:

```python
@property
def coverage_projected(self) -> float:
    """Fracción ponderada del índice sostenida por proyección declarada.
    NO se suma a coverage_real. Se reporta al lado."""
```

`state_counts` inicializa ahora `{REAL:0, RUBRIC:0, PROJECTED:0, GAP:0}`; igual
`DataRegistry.summary.by_state`, que suma `coverage_projected_mean`.

**[Lock]** `coverage_real` no cambia de definición ni de valor para ningún producto
existente. Un producto que hoy reporta 62% de cobertura real sigue reportando 62%
después de este cambio. Si algún número se mueve, es un bug — hay test para eso (§5.1).

### 3.4 Anclaje condicionado

**Prerrequisito [Certain]:** `SubQuestion` (`shared/research/models.py:63`) y
`VariableSignal` (`shared/registry/signals.py:65`) son clases distintas en paquetes
distintos. `ProjectionMeta` se agrega a **ambas**, más a `Evidence`, y el cableado tiene
tres puntos — ninguno de ellos es `_evidence_state`:

| Punto | Ruta | Qué hace |
|---|---|---|
| 1 | `shared/knowledge/ingest.py:36-85` `registry_passages` | Propaga la meta de la señal al `meta` del pasaje, junto al `state` que ya propaga |
| 2 | Construcción de `Evidence` | Campo `projection: Optional[ProjectionMeta]` poblado desde `meta` |
| 3 | `shared/research/orchestrator.py:110` | Donde hoy hace `sq.state = REAL` tras un match, asigna también `sq.state = PROJECTED` y `sq.projection` cuando la evidencia es proyectada |

**[Certain] Por qué no `_evidence_state`:** esa función
(`shared/research/models.py:47-60`) recibe un `Dict` y devuelve un `str`. No tiene acceso
a la `SubQuestion` ni puede escribir en ella — solo clasifica. El estado se **asigna** en
el orquestador (`orchestrator.py:110`), y ahí es donde va el cableado. Un primer borrador
de este spec ubicaba la propagación en `_evidence_state`; era incorrecto y habría mandado
a implementar algo imposible en ese punto.

Sin los tres puntos, `self.projection` no existe en `SubQuestion` y el código de abajo
lanza `AttributeError`.

`shared/research/models.py`:

```python
@property
def anchored(self) -> bool:
    if self.state == PROJECTED:
        ok, _motivo = projection_is_admissible(self.projection)
        return ok
    return self.state in (REAL, RUBRIC)
```

**[Lock]** El desempaquetado de la tupla es obligatorio y no es un detalle de estilo:
`projection_is_admissible` devuelve `Tuple[bool, str]`, y una tupla no vacía es siempre
truthy. Retornarla directo haría que **toda** señal proyectada quedara anclada, con o sin
backtest — exactamente lo que este documento existe para impedir. Hay test para eso (§5.2).

Con el gate de admisión en `shared/registry/projection.py` (archivo nuevo):

```python
def projection_is_admissible(meta: Optional[ProjectionMeta]) -> Tuple[bool, str]:
    """Devuelve (admisible, motivo). Motivo vacío si admisible.

    Rechaza si:
      · meta es None
      · falta model_id, target_series o backtest_id
      · intervals está vacío
      · algún level fuera de (0, 1), o niveles duplicados
      · algún intervalo no contiene al punto (lo <= point <= hi)
      · los intervalos no están anidados: un nivel mayor debe contener al menor
        (el de 90% contiene al de 80%)
      · n_oos < MIN_OOS
      · n_oos_overlapping es None (debe estar explícitamente seteado)
      · oos_error no finito
      · as_of posterior al fin del período de horizon
      · interval_coverage declara niveles que no están en intervals
    """
```

El `motivo` no se descarta: alimenta la nota del `DeclaredGap` cuando la proyección se
degrada, para que el reporte diga *por qué* no se estimó.

`MIN_OOS = 12` **[Guessing]** — doce observaciones fuera de muestra es el mínimo con el
que un RMSE dice algo. Recalibrable por PR a esta constante; se fija aquí para que la
discusión sea sobre un número y no sobre una intuición.

**Una proyección que no pasa el gate no es una proyección mala: es un `GAP`.** Se degrada,
se declara, y su nota dice por qué. Nunca se publica a medias.

Precedente de diseño: es el mismo movimiento de `verify_rubric_relevance`
(`shared/research/relevance.py`), que ya degrada RUBRIC→GAP cuando la rúbrica no aplica.

### 3.5 Prosa

`shared/registry/provenance.py` suma `projection_sentence(axis)` y la integra en
`provenance_paragraph`. Las frases declaran modelo, horizonte, intervalo y error, en
prosa natural y sin corchetes — consistente con el estándar epistémico del Cerebro
(`shared/narrative/cerebro.py`, `EPISTEMIC_STANDARD`).

Forma canónica:

> «La proyección de PIB real para 2026-Q4 sale del modelo `bridge_imae_pib.m2.v1`, con
> intervalo de 80% entre 3.1% y 4.7%. Ese modelo erró en promedio 0.6 puntos porcentuales
> (RMSE) en 34 trimestres fuera de muestra, y su intervalo de 80% contuvo al dato
> observado en 76% de esos casos. Las ventanas de evaluación se solapan, así que esos 34
> trimestres no son 34 observaciones independientes. La estimación usa información
> disponible al 2026-09-30 y no incorpora nada posterior.»

**[Lock]** Los cuatro elementos van en la frase: error, **calibración empírica del
intervalo**, **solapamiento cuando existe**, y corte de información. La calibración
importa porque un intervalo del 80% que acierta el 45% de las veces engaña a quien
dimensiona riesgo con él, aunque el RMSE se vea bien. El solapamiento importa porque `n`
grande sugiere una precisión que ventanas correlacionadas no sostienen.

Cuando `n_oos_overlapping` es `False`, esa cláusula se omite — no se escribe «no se
solapan», que sería ruido.

**[Lock]** El error de backtest va **en la misma frase** que la proyección, no en una
sección de limitaciones al final. Enterrar el error en el apéndice es exactamente la
práctica que la plataforma existe para no repetir.

### 3.6 El Cerebro

`AXIS_DOCTRINE` no cambia. Se añade al `EPISTEMIC_STANDARD` (núcleo, aplica a todos los
ejes) un cuarto párrafo:

```
PROYECCIÓN: cuando el contexto marca una cifra como "proyección declarada", trátala
como lo que es — la salida de un modelo con error conocido, no un hecho. Nómbrala
siempre como proyección, cita su intervalo cuando la conclusión dependa de ella, y
NUNCA la compares con un dato observado sin decir que una es proyectada. Si tu lectura
principal descansa sobre una proyección, dilo en la primera línea.
```

**[Lock]** Va en el núcleo, no por eje. La regla es de la casa, no de macro.

---

## 4. Contrato para productos

Un producto que emite proyecciones:

1. Devuelve señales con `state=PROJECTED` y `projection` completo desde su
   `variable_signals()` (contrato en `shared/products/contract.py:362-367`).
2. Declara su `coverage_kind` sin cambios — la proyección no altera el denominador.
3. Persiste su backtest en un ledger consultable por `backtest_id` (definido en
   `SPEC_MOTOR_PROYECCION_MACRO` §3.6; el patrón existente es `tpm_forecast_log`).
4. Expone `ESTADO_BACKTEST = EstadoBacktest(...)` de clase, ya exigido por
   `shared/products/tests/test_estado_de_validacion.py`.

`shared/data_api/router.py:485-536` (bloque `quality`) suma `coverage_projected` y
`state_counts.projected` a lo que ya expone. Es aditivo: ningún consumidor existente se
rompe.

---

## 5. Fases de build

| Fase | Alcance | Cierre |
|---|---|---|
| 1 | Constante `PROJECTED`, alias, `STATES`, `ProjectionMeta`, campo en `VariableSignal` | Tipos importables; tests de normalización verdes |
| 2 | `_projected_credit`, `coverage_projected`, `state_counts`, `summary` | **Test de invariancia (§5.1)** verde |
| 3 | `projection_is_admissible` + degradación a GAP | Tabla de casos límite cubierta |
| 4 | `anchored` condicionado en `research/models.py`; `_forward_gaps` consulta el gate antes de declarar brecha | Round-trip: pregunta prospectiva con proyección admisible → `GATE_REPORT`; sin backtest → `GATE_SCOPING` |
| 5 | `projection_sentence` + integración en `provenance_paragraph` | Golden test de prosa |
| 6 | Párrafo en `EPISTEMIC_STANDARD`; `quality` del data_api | Barra de insight sin regresión; contrato de API aditivo |

### 5.1 El test que no puede faltar

`shared/registry/tests/test_cobertura_no_se_infla_con_proyeccion.py`:

Construye un `AxisRegistry` con señales mixtas, calcula `coverage_real`, convierte una
señal `GAP` en `PROJECTED` admisible, recalcula. **`coverage_real` debe ser idéntico.**
`coverage_projected` debe subir.

Ese test es el spec entero comprimido en una aserción. Si se pone en rojo alguna vez, el
producto perdió su razón de ser.

### 5.2 El test del falso positivo

`shared/research/tests/test_proyeccion_sin_backtest_no_ancla.py`:

Construye una `SubQuestion` con `state=PROJECTED` y `projection=None`; después con
`ProjectionMeta` sin `backtest_id`; después con `n_oos = MIN_OOS - 1`. **Las tres deben
dar `anchored is False`.**

Existe porque el modo de falla más probable de este diseño no es que rechace de más: es
que acepte todo por un desempaquetado olvidado (§3.4). Un `assert anchored is False` —con
`is False`, no `not anchored`— es lo que separa el gate real del gate decorativo.

---

## 6. Riesgos

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Un producto marca `PROJECTED` lo que en verdad es rúbrica, para sonar más riguroso | Alta | El gate exige `backtest_id` resoluble. Sin ledger, no hay estado. |
| El umbral `MIN_OOS=12` es arbitrario y bloquea un producto legítimo | Media | Constante en un archivo, cambiable por PR con justificación en el propio PR. No hardcodeada en la lógica. |
| Los 17 productos existentes cambian de cobertura sin que nadie lo note | Alta | Test de invariancia §5.1 + correr `scripts/build_estado.py` antes y después y diferenciar. |
| `state_counts` con clave nueva rompe un consumidor de frontend | Media | Es aditivo, pero hay que grepear `by_state` en `frontend/` antes de mergear. |
| El Cerebro empieza a hedgear todo porque el párrafo nuevo lo vuelve tímido | Media | La barra de insight (regla POSTURA) sigue vigente y tiene test. Declarar incertidumbre no es lo mismo que no concluir. |

---

## 7. Fuera de alcance v1 (explícito)

- **No** se construye ningún modelo de proyección aquí. Este spec es el vocabulario; los
  modelos viven en `SPEC_MOTOR_PROYECCION_MACRO` y `SPEC_VALUADOR_ENTIDADES`.
- **No** se migra ningún producto existente a `PROJECTED`. Los 17 ejes siguen siendo
  retrospectivos hasta que alguien decida lo contrario, producto por producto.
- **No** se toca el tarifario. Que una proyección valga más o menos es decisión comercial
  posterior.
- **No** se implementa versionado de modelos ni registro de artefactos. `model_id` es un
  string con convención; el registro formal, si hace falta, es otro spec.

---

## 8. Próximos pasos

1. Revisión del dueño sobre dos decisiones fijadas: la asimetría de cobertura (§3.3) y
   `MIN_OOS = 12` (§3.4).
2. Fase 1-2 en una PR; correr `scripts/build_estado.py` antes/después y adjuntar el diff
   al PR como evidencia de invariancia.
3. Fases 3-6 en una segunda PR.
4. Solo entonces arranca `SPEC_MOTOR_PROYECCION_MACRO`.

---

## 9. Referencias

- `CLAUDE.md` — arquitectura, tres gates de CI, notación retirada
- `docs/REPORT_STANDARD.md` — anatomía canónica y regla de procedencia
- `docs/SPEC_MOTOR_RESEARCH_CUSTOM.md` §4 — la regla de honestidad para pregunta libre
- `docs/SPEC_PERFIL_SDQ_TAXONOMIA.md` — precedente de reemplazo de vocabulario
- `shared/registry/signals.py`, `shared/research/gate.py`, `shared/research/models.py`
