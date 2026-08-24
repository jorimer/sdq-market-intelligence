# La lectura de una comparación se COMPUTA — y qué hacer cuando aun así sale mal

**Estado:** la causa raíz está implementada en este PR. Quedan dos decisiones (§5).
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

## 5. Lo que queda por decidir

### 5.1 Reparar mejor

Cuando el guard detecta una inversión, el sistema pide una reescritura. Pero el aviso dice:

> «Reescribí esas afirmaciones con la dirección correcta (**restá y mirá el signo** antes de
> escribir 'por encima' / 'por debajo')»

Le pide **volver a derivar** — la operación que acaba de fallar. Teniendo la cláusula correcta
computada, no se la entrega.

**Propuesta:** entregarle la frase hecha para que la copie, y reintentar más de una vez (hoy
es un solo intento).

*Evidencia de que reparar funciona*, de los registros de una corrida real: de tres
reparaciones, dos salieron limpias; la única que falló fue el caso en que **el guard estaba
equivocado** y el modelo tenía razón en insistir. Muestra chica.

### 5.2 ¿Frenar como último recurso?

Si tras entregarle la respuesta correcta el modelo la sigue contradiciendo, ya no es «se
equivocó»: es señal de que algo más está roto —quizás el propio guard, como en el caso del
`69%`—. Las opciones son frenar, o entregar marcando la sección para revisión humana.

**Medición disponible:** los tres chequeos de relación corridos sobre el informe COMPLETO
(16 secciones narrativas) marcan **1 sección, y era el defecto real**. Cero falsos positivos
en las otras quince, que incluyen nueve comparaciones correctas con las mismas
construcciones. Límite: es un informe, y las referencias se reconstruyeron de su prosa.

**Obstáculo técnico si se decide frenar:** la pieza que detecta y la que decide publicar son
distintas y hoy no se comunican — la marca del guard no sobrevive al borde del producto
(`SectorProduct.narratives()` devuelve `Dict[str, str]`). La vía recomendada es un acumulador
por generación (`ContextVar`): el motor deposita, el ensamblador drena y decide la política
(premium veta, Pulse registra). El motor no puede decidir solo: es transversal y no sabe si el
producto es premium. Hay dos precedentes del mecanismo en el repo (`lang_context`,
`llm_ledger.attributed_to`).
