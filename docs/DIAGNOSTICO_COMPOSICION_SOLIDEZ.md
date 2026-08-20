# Por qué `solidez` ordena al revés — y por qué arreglar la curva habría sido el error

**Corrida:** 2026-08-19, contra producción (commit servido `37c9759`), panel real de 1.693
observaciones.
**Reproducible con:** `python scripts/ops_trigger.py banca-diagnostico-composicion --timeout 1800`
**Código:** [`modules/banking_score/validation/composicion.py`](../modules/banking_score/validation/composicion.py)

Cierra el punto 1 de la §5 de [`DIAGNOSTICO_DISCRIMINACION_BANCA.md`](DIAGNOSTICO_DISCRIMINACION_BANCA.md),
que declaraba: *«No afirma causalidad sobre por qué `solidez` está invertida […]. Probarla es
trabajo aparte: partir el panel por tipo de entidad y volver a medir.»* Se partió, se volvió a
medir, y la respuesta cambia dónde hay que tocar el score.

---

## 0. Las cuatro conclusiones

1. **La inversión agregada de `solidez` es COMPOSICIONAL, y el estrato que la explica es el
   TAMAÑO.** Comparando solo entidades del mismo tramo de tamaño, el Gini pasa de **−0,1944**
   [−0,260 · −0,122] a **−0,0055** [−0,080 · **+0,071**]: el intervalo cruza cero. No queda
   inversión que explicar.
2. **Casi la mitad del panel del Banking Score son entidades que no prestan.** 794 de 1.693
   observaciones (**47 %**) son agentes de cambio: 1.390 veces más chicos que un banco
   múltiple, con `solidez` mediana **92,7/100** por diseño del negocio, y aportan el **63 %**
   de todos los eventos del desenlace.
3. **Contra deterioro de CRÉDITO pasa lo contrario: la composición TAPABA el hallazgo.** El
   agregado no dice nada (−0,0436, IC cruza cero); al comparar solo lo comparable aparece una
   inversión sólida, **−0,31** [−0,443 · −0,160]. Y sobrevive a todas las estratificaciones.
4. **Las dos reglas del desenlace predicen su propio evento desde el nivel de partida, mejor
   que cualquier dimensión del score.** El ROA de base ordena el evento de pérdidas con
   **+0,6674**; la mora de base ordena el evento de crédito con **+0,4689**, y lo hace *a
   favor de la entidad sana*: la regla dispara sobre quien partía mejor.

---

## 1. Método: solo se ordena lo comparable

El Gini es una cuenta de pares (evento contra no-evento). El diagnóstico repite la cuenta
contando **solo los pares que comparten estrato** —mismo tipo de entidad, mismo tramo de
tamaño, ambos— y compara ese número con el agregado. Un par formado por un agente de cambio y
un banco múltiple no informa sobre el ordenamiento: son poblaciones distintas en la misma
bolsa, y es justo el par que el AUC agrupado cuenta. Es el mismo principio que la doctrina ya
aplica a los rankings.

El veredicto se **computa** de los dos intervalos, no se narra: si la inversión desaparece al
estratificar es *composicional*; si sobrevive es *intrínseca*; si se achica sin cruzar cero es
*parcial*.

**Comprobación de fidelidad primero:** sobre las 1.693 observaciones el instrumento reproduce
exactamente el **−0,1944** publicado, con **cero** descartes (`n_sin_dimension = 0`). Dos
corridas independientes contra producción devolvieron cifra por cifra lo mismo.

---

## 2. Quién está en el panel

| Tipo de entidad | Obs | Eventos | Tasa | `solidez` mediana | Activos medianos (RD$) |
|---|---|---|---|---|---|
| **cambiaria** | **794** (47 %) | **189** (63 %) | **23,8 %** | **92,7** | 22.224.237 |
| banca múltiple | 323 | 55 | 17,0 % | 67,8 | **30.889.946.934** |
| banco de ahorro y crédito | 291 | 42 | 14,4 % | 73,3 | 2.239.896.863 |
| aap | 200 | 8 | 4,0 % | 81,6 | 8.248.243.162 |
| corporación de crédito | 65 | 6 | 9,2 % | 82,1 | 379.908.055 |
| fiduciaria | 20 | 1 | 5,0 % | 58,9 | 281.132.922 |

Y por tramo de tamaño (terciles del activo total al corte de cada observación):

| Tramo | Obs | Eventos | Tasa | `solidez` mediana |
|---|---|---|---|---|
| chico | 565 | 177 | **31,3 %** | **97,2** |
| mediano | 564 | 75 | 13,3 % | 74,8 |
| grande | 564 | 49 | **8,7 %** | 73,0 |

La entidad más capitalizada del panel es la más chica y la que más falla. Correlación de rangos
`solidez` ↔ activo total: **−0,4631** (n = 1.693). No es una hipótesis: es el mecanismo, medido.

**Y el tamaño, puesto a competir como score**, ordena mejor que casi todo el rating: **+0,413**
[+0,345 · +0,472] contra el desenlace agregado y **+0,556** [+0,496 · +0,617] contra pérdidas
sostenidas — por encima de `eficiencia` (+0,5985), la mejor dimensión del score.

> **Esto no es un control nuevo: ya existía en otro motor.** `sector_intel` lo tiene desde la
> Fase 3 como `control_solo_tamano`
> ([`validation/report.py`](../modules/sector_intel/validation/report.py)), con el razonamiento
> escrito —«sin medir qué hace el tamaño SOLO contra el mismo desenlace, *el índice ordena al
> revés* y *el deflactor produce el signo* son indistinguibles, y son conclusiones opuestas»— y
> con un test que exige que el control viaje con la cifra. Ahí el veredicto fue que el IAI **no
> agrega poder sobre el tamaño del sector**: contra intensidad de IED daba −0,321 y el tamaño
> solo −0,323; contra nivel, +0,287 contra **+0,377** del tamaño solo.
>
> **Banca es la segunda vez que el control por tamaño cambia el veredicto de un motor.** Que se
> repita entre motores es, por doctrina, la condición para dejar de escribirlo como lección y
> exigirlo con un test estructural: hoy nada obliga a que un motor de validación que publica un
> Gini traiga su control. `sector_intel` lo trae porque alguien se acordó.

---

## 3. El veredicto, por familia de desenlace

| Universo comparado | Agregado (301 ev.) | Resultados (250 ev.) | Crédito (66 ev.) |
|---|---|---|---|
| Agrupado (la cifra publicada) | **−0,1944** [−0,260 · −0,122] | **−0,2419** [−0,321 · −0,161] | −0,0436 [−0,162 · **+0,083**] |
| Solo mismo **tipo de entidad** | −0,1421 [−0,215 · −0,063] | −0,1408 [−0,221 · −0,057] | **−0,3100** [−0,443 · −0,160] |
| Solo mismo **tramo de tamaño** | **−0,0055** [−0,080 · +0,071] | **+0,0248** [−0,051 · +0,110] | −0,2538 [−0,396 · −0,102] |
| Solo mismo tipo **y** tamaño | **+0,0104** [−0,065 · +0,097] | +0,0239 [−0,054 · +0,114] | −0,2450 [−0,389 · −0,085] |
| Solo entidades **con libro de crédito** | −0,0986 [−0,227 · +0,045] | −0,0813 [−0,284 · +0,135] | −0,2556 [−0,409 · −0,098] |
| **Veredicto computado** (tipo y tamaño) | **composicional** | **composicional** | *sin inversión agregada que explicar* |

Las dos primeras columnas dicen lo mismo: **la inversión no sobrevive a comparar entidades de
tamaño parecido**. La tercera dice lo contrario, y por eso importa leerla al revés: contra
crédito **no hay** inversión agregada, pero al comparar solo lo comparable **aparece** una, con
el intervalo entero bajo cero. Agrupar no la producía: la escondía.

---

## 4. Lo que NO es composicional

`solidez` sí ordena mal dentro de dos poblaciones reales, que **sí** prestan:

| Población | Obs | `solidez` vs agregado | vs pérdidas | vs crédito |
|---|---|---|---|---|
| banco de ahorro y crédito | 291 | **−0,4936** [−0,634 · −0,346] | **−0,6694** [−0,772 · −0,548] | −0,4215 [−0,596 · −0,243] |
| aap | 200 | −0,5599 [−0,863 · −0,202] | *sin eventos* | −0,5599 [−0,863 · −0,202] |
| **banca múltiple** | 323 | **+0,1062** [−0,086 · +0,303] | +0,0684 [−0,208 · +0,336] | −0,1299 [−0,364 · +0,109] |

**Este es el argumento para no tocar la curva.** Dentro de banca múltiple —la población que el
producto vende— `solidez` no está invertida. Recalibrar el indicador para todo el panel
arreglaría un problema que banca múltiple no tiene, y lo haría con la evidencia de entidades
que no se le parecen.

Y por indicador (solo las entidades del set estándar, n ≈ 870 — **no** es la población de la
dimensión):

| Indicador | vs pérdidas | vs crédito |
|---|---|---|
| solvencia | −0,3839 [−0,577 · −0,189] | −0,0870 [−0,253 · +0,076] |
| tier1_ratio | −0,3498 [−0,511 · −0,179] | −0,1138 [−0,273 · +0,035] |
| leverage | −0,3476 [−0,522 · −0,158] | −0,0751 [−0,254 · +0,094] |
| patrimonio_activos | −0,2125 [−0,413 · +0,001] | −0,1480 [−0,318 · +0,024] |
| **cobertura_provisiones** | **+0,5579** [+0,418 · +0,695] | **−0,4480** [−0,565 · −0,327] |

Un indicador que se da vuelta según la regla no está midiendo mal. Son las reglas las que
miden cosas distintas — y eso es lo que abre la sección siguiente.

---

## 5. Las reglas del desenlace miden el nivel de partida

`outcomes_derivation` descartó en su momento un desenlace por estar «mecánicamente sesgado por
el piso del rating» (daba Gini −0,66 **por construcción**). Nadie le había aplicado esa misma
prueba a las reglas que sí quedaron. Aplicada:

| Regla | Su nivel de base como score | IC 95 % | N | Eventos |
|---|---|---|---|---|
| ROA<0 sostenido | **+0,6674** | [+0,601 · +0,734] | 1.693 | 250 |
| morosidad ×2 | **+0,4689** | [+0,312 · +0,610] | 857 | 66 |

**Las dos son concluyentes, y las dos superan a la mejor dimensión del score** (`eficiencia`,
+0,5985). Qué significa cada una:

- **La regla de pérdidas mide persistencia.** El ROA de hoy predice «ROA negativo en ≥2 de los
  próximos 4 trimestres» con 0,667. Quien ya perdía sigue perdiendo. Que el 83 % del desenlace
  sea esta regla explica por qué `eficiencia` —que tiene el ROA como insumo— es la única
  dimensión fuerte: está midiendo la misma serie contra sí misma.
- **La regla de crédito penaliza a la entidad sana.** Duplicar una mora de 0,5 % es fácil;
  duplicar una de 8 % es casi imposible. Medido: partir con mora BAJA predice el evento con
  0,469. Y `cobertura_provisiones` lleva la cartera vencida en el **denominador**, así que mora
  baja ⇒ cobertura alta por construcción. Ahí está el −0,448 de la tabla anterior: no es que
  provisionar bien anticipe deterioro, es que las dos cifras son las dos puntas del mismo
  hecho.

---

## 6. Qué cambia para la decisión

La tabla de opciones del informe anterior (§4) queda revisada por esta evidencia:

| # | Opción | Estado a la luz de lo medido |
|---|---|---|
| A | Revisar la dirección de `solidez` | **Desaconsejada como estaba planteada.** La inversión agregada es composicional; dentro de banca múltiple no existe. Tocar la curva movería un indicador sano por evidencia de otra población |
| B | Re-especificar el desenlace | **Ya hecho** (señales por familia, en producción). Lo que este diagnóstico agrega es que además hay que **auditar el sesgo de cada regla**: las dos evaluables predicen su evento desde el nivel de partida |
| C | Re-pesar las dimensiones | **Prematuro y probablemente mal dirigido.** El tamaño solo ordena mejor (+0,413) que el score entero. Re-pesar contra un desenlace que mide persistencia ajustaría el score a la autocorrelación |
| **E** | **Definir el universo del backtest** | **La que sale de acá.** 47 % del panel son entidades sin libro de crédito que aportan 63 % de los eventos. Medir la credencial sobre el universo que el producto vende es un cambio de UNIVERSO, no de score |
| **F** | **Exigir el control por tamaño con un test estructural** | El mismo control ya dio vuelta el veredicto en `sector_intel` (IAI) y ahora en banca. Dos motores es la condición doctrinal para un guard que lea el código con `ast`, en vez de confiar en que cada autor se acuerde |

**Recomendación:** E primero — declarar y separar el universo—, y con la credencial medida
sobre entidades comparables, revisar `solidez` **solo dentro de las poblaciones donde sigue
invertida** (banco de ahorro y crédito, aap). Antes de eso, auditar `morosidad_x2`: una regla
que dispara a favor de quien partía mejor no puede sostener la afirmación «el score no
discrimina deterioro de crédito».

**Lo que no cambia:** la credencial fuerte de banca sigue siendo la cohorte de quiebras reales
—Bancrédito 11 meses de anticipación, Baninter 7, señal tardía en Mercantil— sobre **tres**
casos evaluables. No depende de nada de lo anterior.

---

## 7. Lo que este diagnóstico NO afirma

1. **No prueba por qué `solidez` está invertida dentro de banco de ahorro y crédito.** Que ahí
   la inversión sea intrínseca es un hecho medido; su causa, no. Es el trabajo siguiente.
2. **No corrige el supuesto de independencia.** Las observaciones son trimestres repetidos de
   la misma entidad y el bootstrap las trata como independientes, así que **todos** los IC de
   este informe —y los del backtest publicado, que usa el mismo método— son más angostos de lo
   que corresponde. Un bootstrap por conglomerados de entidad es un cambio de metodología del
   backtest, no de este diagnóstico.
3. **Los tramos de tamaño son terciles del activo total al corte**, no una clasificación
   regulatoria. El `peer_group` del catálogo no se usó: es estático.
4. **El desglose por indicador vive en otra población** (n ≈ 870, solo el set estándar):
   cambiarias y fiduciarias arman sus dimensiones con otros indicadores y quedan contadas
   aparte, nunca mezcladas.
5. **No mide la familia de capital.** `solvencia_breach` no disparó ni una vez en toda la
   ventana: eso es ausencia de evidencia, no evidencia de solidez.
