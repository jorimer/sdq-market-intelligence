# La lectura de una comparación se COMPUTA — y qué hacer cuando aun así sale mal

**Estado:** CERRADA. Causa raíz, reparación y freno de último recurso, los tres implementados.
**Bloqueante:** sí — acordado resolverlo ANTES de la próxima generación de informes.
**Origen:** §7 de un Deep Dive de banca REAL, corte 2026-03-31.

> **Nota de versión.** La primera versión de este documento proponía que una relación
> invertida VETARA la entrega, por analogía con la cifra inventada. El dueño objetó que no
> son lo mismo, y tenía razón: eso llevó a encontrar la causa real, que es otra. Se deja
> constancia porque el razonamiento descartado explica por qué el remedio es éste y no aquél.

---

## 1. El caso

En un informe entregado, tres secciones hablaron del mismo indicador —patrimonio sobre
activos, 7,41% contra una mediana de grupo de 11,11%, segundo desde abajo entre 16 bancos
múltiples, percentil 5— y una lo dijo al revés:

| sección | qué dijo | |
|---|---|---|
| §2 Solidez | «…**por debajo** del promedio de bancos múltiples en 3.70 puntos porcentuales» | ✓ |
| §10 Riesgos | «7.41% de sus activos —frente al **11.11%** del promedio del grupo—» | ✓ |
| **§7 Comparativo** | «La capitalización contable **supera** en 3.70 puntos porcentuales al promedio de su grupo» | ✗ |

No hay lectura de negocio que salve a §7: §2 usa la misma base y da la misma brecha, y el
mismo párrafo de §7 continúa diciendo que el margen de absorción es «estructuralmente **más
delgado** que el del par típico» — la lectura correcta, dos líneas después de la incorrecta.

## 2. La causa

Esto es TODO lo que el modelo recibía sobre ese indicador, en dos lugares distintos del
contexto:

```
en un lado →  "un valor MÁS ALTO del indicador es MEJOR"
en otro    →  "por debajo del promedio de bancos múltiples en 3.70 puntos porcentuales"

el veredicto (¿fortaleza o debilidad?) →  no se servía en ninguna parte
```

Los dos hechos, por separado, y la UNIÓN a cargo del modelo. Esa unión es una **derivación**,
que es exactamente la operación que la doctrina de este repo dice que el modelo erra y que en
todos los demás casos —direcciones, aportes, deltas, rangos— ya se sirve resuelta.

Y explica la huella: §7 escribió «supera» y dos líneas después «más delgado». No es un desliz
de una palabra — son **dos uniones distintas del mismo par de hechos**, una bien y otra al
revés. Un error de tipeo no se comporta así.

Es la misma familia que el defecto del LTD de BPD (2026-08-13) que documenta
`_semantica_indicadores`: allí se agregó «en qué sentido corre la escala» y «de qué lado del
óptimo cayó el valor», y se paró justo antes del veredicto.

## 3. La cura (implementada en este PR)

Cada comparación viaja con su veredicto **computado**:

```
lectura    "por debajo del promedio de bancos múltiples en 3.70 puntos porcentuales"
veredicto  "desfavorable"
por_qué    "en este indicador un valor más alto es mejor"
```

**El veredicto es INTERNO** (decisión del dueño). Orienta al modelo para que no invierta la
lectura; él redacta con su criterio de analista. Por eso NO va dentro de `lectura` —que el
prompt manda a copiar literal— o la palabra «desfavorable» terminaría impresa en el informe.
Hay un test que lo fija, y la directiva del prompt prohíbe transcribirlo.

**Excepción declarada:** en los indicadores de ÓPTIMO INTERMEDIO (`ltd`, `exposicion_re`,
`migracion`) el veredicto es `no_aplica`, y no por no saber: ahí la vara **no es el promedio
sino el óptimo**, así que estar por encima o por debajo del grupo no tiene lectura de bueno o
malo. Esa la da `posicion_vs_optimo`.

## 4. Por qué el remedio NO es vetar

La analogía con la cifra inventada no se sostiene:

| | cifra inventada | relación invertida |
|---|---|---|
| ¿tenemos el dato? | **no** | **sí**, los dos números |
| ¿sabemos qué habría que decir? | no | **sí — está computado** |
| ¿es reparable? | **no** sin inventar | **sí** |

Una cifra inventada es irreparable: no hay número que poner, y frenar es la única salida
honesta. Una relación invertida es reparable, porque la respuesta correcta ya la calculamos.
Frenar quince secciones buenas para castigar una frase reparable no protege al cliente: le
niega un análisis correcto en el 94% de su extensión.

**Gravedad y remedio no son lo mismo.** El prompt dice que una comparación invertida es «tan
grave como una cifra inventada» —y lo es, como error— pero de ahí no se sigue que merezca la
misma consecuencia.

## 5. Reparar mejor (implementado)

El aviso de corrección le pedía al modelo «restá y mirá el signo» — **volver a derivar** la
relación que acababa de errar, teniendo el sistema la frase correcta ya computada y sin
entregársela. Reparar así es pedirle que repita la operación que falla.

Ahora el hallazgo lleva la cláusula adosada:

```
patrimonio_activos: se afirma una brecha de 3.70 puntos porcentuales 'por encima' de
'al promedio de su grupo', pero la dirección servida es 'por debajo'
  → escribí exactamente: "por debajo del promedio de bancos múltiples en 3.70 puntos porcentuales"
```

Y el aviso dice explícitamente: **copiala, no la deduzcas de nuevo.**

Los reintentos pasan de **uno a dos** (`_MAX_REINTENTOS_GUARD`), con corte apenas el texto
queda limpio — hay un test de que no se gastan por deporte, porque con trece secciones eso
sería pagar el doble de modelo sin necesidad. En el último intento se avisa que es el último.

No se sube más: en el caso real que motivó esto, la única corrección que NO convergió fue la
vez que **el guard estaba equivocado** (el falso positivo del 69%). Insistir ahí solo quema
dinero.

## 6. Frenar como último recurso (implementado)

Se llega al veto solo si el modelo contradice **dos veces** una lectura que se le entregó
redactada. En ese punto ya no es «se equivocó»: es señal de que algo más está roto —quizá el
propio guard— y publicar sería apostar a que el equivocado es el detector.

| nivel | cifra sin respaldo | relación invertida |
|---|---|---|
| Deep Dive / Insight (premium) | veta | **veta, tras dos reparaciones fallidas** |
| Pulse (abierto) | registra | registra |

**El canal:** un acumulador por generación (`shared/narrative/relaciones_pendientes`). El
motor **deposita**; el ensamblador **drena** y decide. El motor no puede decidir solo: es
transversal y no sabe si sirve un premium o un Pulse — vetar desde ahí rompería el Pulse.

Mismo mecanismo que `lang_context` y `llm_ledger.attributed_to`. El riesgo —estado implícito—
se acota con un `contextmanager` y un test de que **dos generaciones concurrentes no se
mezclan**: sin eso, un informe podría vetarse por el defecto de otro.

Fuera del `contextmanager`, `registrar()` es no-op: un job de fondo no acumula basura global.

El veto **LISTA** las secciones, como sus hermanos, y la superficie ya lo muestra (503 con
detalle). El manejador del router no hubo que recordarlo: el test estructural de #915 lo
exigió solo.

## 7. Lo que NO se hizo, y por qué

No se tocó `GUARD_VERSION`. La lógica de detección no cambió —cambió el aviso de corrección,
que viaja en el mensaje de usuario, no en el system— y una narrativa cacheada es limpia por
construcción: el motor nunca propaga a la caché compartida un texto marcado.
