# Propuesta: que una RELACIÓN invertida vete la entrega, como ya la veta una cifra inventada

**Estado:** propuesta · pendiente de decisión del dueño
**Bloqueante:** sí — acordado hacerlo ANTES de la próxima generación de informes
**Origen:** §7 de un Deep Dive de banca REAL entregado el 2026-03-31

---

## 1. El hecho

El informe afirmó, en su §7 «Análisis Comparativo»:

> «La capitalización contable (7.41% de activos) **supera** en 3.70 puntos porcentuales al
> promedio de su grupo.»

El contexto servía «**por debajo** … en 3.70 puntos porcentuales». La §2 y la §10 del **mismo
documento** lo decían bien. Verificado contra el panel de producción: la mediana de los 17
bancos múltiples es 11,11% y el sujeto 7,41% — está por debajo.

El guard de dirección no lo vio (arreglado en #922). Pero al ir a verificar que el arreglo
impidiera la reincidencia, apareció lo que esta propuesta viene a cerrar:

> **Aunque el guard lo hubiera visto, el informe habría salido igual.**

## 2. Por qué sale igual

El gate de entrega del ensamblador (`_content_from_snapshot`) corre **solo** los chequeos de
CIFRA SIN RESPALDO:

```python
sin_respaldo = secciones_con_cifra_sin_respaldo(narratives, level.sections, snapshot.payload)
if sin_respaldo and blocked:
    raise NarrativeSinRespaldoError(sin_respaldo)
```

Los chequeos de RELACIÓN —dirección, brecha y razón— viven en el motor y solo disparan **una
regeneración**. Si la inversión sobrevive a esa regeneración, la marca se guarda en
`result.guard_unsupported`, se escribe una línea de log… y el texto se entrega.

Y esa marca **no sobrevive al borde del producto**: los productos devuelven `Dict[str, str]`
(solo textos), así que para cuando el ensamblador decide, la información ya se perdió.

Esto contradice al propio sistema. `DIRECTION_DISCIPLINE`, en el prompt, dice:

> «Una comparación con el sentido invertido es un error de hecho **tan grave como una cifra
> inventada**, y es peor cuando el propio informe muestra la tabla que la desmiente.»

Si eso es cierto —y el caso de §7 lo confirma: el documento se contradice a sí mismo—, la
consecuencia debería ser la misma. Hoy una cifra inventada veta y una relación invertida no.

## 3. Cuánto vetaría de más (medido, no estimado)

Corrí los tres chequeos de relación sobre el **informe completo** — las 16 secciones
narrativas, texto extraído del PDF entregado:

| | |
|---|---|
| Secciones analizadas | 16 |
| Secciones marcadas | **1** |
| Hallazgos totales | **1** |
| ¿Era un defecto real? | **Sí** — §7, confirmada contra el panel |

Cero falsos positivos en las otras quince, incluidas nueve frases de comparación correctas
que usan las mismas construcciones (§1, §2, §3, §5, §11).

**Límite declarado de esta medición:** es UN informe, y los valores de referencia los
reconstruí de la prosa del propio documento (solo `patrimonio_activos` está verificado contra
el panel). Es indicativo, no una tasa medida de falsos positivos.

## 4. Las opciones

### A · El motor levanta la excepción
El motor tiene el contexto por sección, así que no hay que plumbear nada.
**No sirve:** el motor es transversal y **no sabe si el producto es premium o abierto**. Esa
decisión vive en el ensamblador (`level.granularity`), y el Pulse por doctrina solo registra.
Vetar desde el motor rompería el Pulse.

### B · Cambiar el contrato `SectorProduct.narratives()`
Devolver `(textos, marcas)` en vez de `Dict[str, str]`.
**No sirve:** rompe los diez módulos de sector para resolver un problema de dos.

### C · El producto expone sus contextos (`narrative_contexts()`)
Método opt-in; el ensamblador, si existe, re-corre los chequeos por sección.
**Viable**, sigue el patrón de `supports_sample` / `AI_CONTEXT_FILES`. **Costo:** el contexto
se arma dos veces (CPU, no modelo), y quien no lo implemente no gana el gate — hay que
LISTAR a los que quedan fuera, o el hueco desaparece en silencio.

### D · Acumulador por generación (RECOMENDADA)
El motor **deposita** las marcas de relación persistentes en un `ContextVar`; el ensamblador
las **drena** y decide la política (premium veta, Pulse registra).

- El motor solo **reporta**; la política sigue donde corresponde.
- No cambia ninguna firma pública ni el contrato de los productos.
- No duplica trabajo: la marca ya se calcula hoy y se tira.
- **Dos precedentes en el repo:** `shared/narrative/lang_context.py` usa un `ContextVar`
  exactamente para no tocar ~13 firmas de endpoint, y `shared/observability/llm_ledger.py`
  usa `attributed_to` con el mismo mecanismo.

**Riesgo a manejar:** estado implícito. Se acota con un `contextmanager` que abre y cierra el
acumulador alrededor del ensamblado, y un test de que **dos generaciones concurrentes no se
mezclan** — `lang_context` ya documenta la copia de contexto de anyio para endpoints sync.

## 5. La política que propongo

| nivel | cifra sin respaldo | relación invertida |
|---|---|---|
| Deep Dive / Insight (premium, nombrado) | veta (hoy) | **veta** (propuesto) |
| Pulse (abierto, sistema) | registra (hoy) | registra |

El veto **LISTA** qué sección y qué relación, igual que el de cifra sin respaldo: un veto mudo
se lee como que el informe no existía. La superficie ya sabe mostrarlo (503 con detalle, #915).

## 6. Cómo se verifica

1. **Dientes:** el texto REAL de §7 vetado por el gate, y las otras 15 secciones entregadas.
2. **Prueba negativa:** que el barrido encontró secciones (un gate que no mira nada pasa en
   verde).
3. **Concurrencia:** dos ensamblados en paralelo no se contaminan las marcas.
4. **El Pulse no se rompe:** una relación invertida en un Pulse registra y entrega.
5. **Test estructural:** que la nueva excepción tenga manejador en el router — lo cubre
   automáticamente `test_veto_tiene_manejador` (#915), que lee los `raise` del ensamblador.
6. **En prod:** regenerar el mismo Deep Dive y ver que ahora entrega §7 corregida — o que
   veta declarando el motivo.

## 7. Qué hace falta decidir

1. **¿Se aprueba que las relaciones veten en premium?** (el cambio de política)
2. **¿Opción D?** (acumulador por generación) o preferís C, que es más explícito y más caro.
3. **¿Alcance:** las tres relaciones (dirección, brecha, razón) o solo la dirección para
   empezar?
