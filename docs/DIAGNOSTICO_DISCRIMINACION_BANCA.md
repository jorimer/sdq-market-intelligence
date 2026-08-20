# Diagnóstico — la caída 0,44 → 0,16 y qué mide realmente el backtest de banca

**Corrida:** 2026-08-19, contra producción (`3c03b0a`), panel real de 1.693 observaciones.
**Reproducible con:** `python scripts/ops_trigger.py banca-diagnostico-recalibracion`
**Código:** [`modules/banking_score/validation/recalibracion.py`](../modules/banking_score/validation/recalibracion.py)

Cierra la pregunta 1 de la Fase 2 del [plan](PLAN_CIERRE_BRECHAS_VALIDACION.md). La respuesta
es más grande que la pregunta: la recalibración **sí** degradó la discriminación, y al medir
por qué apareció algo que ninguna de las dos cifras (ni 0,44 ni 0,16) dejaba ver.

---

## 0. Las tres conclusiones

1. **La recalibración del 7-ago degradó la discriminación, y no marginalmente.** Sobre el
   mismo panel, con las curvas anteriores el Gini es **0,3444** [0,275 · 0,409]; con las
   vigentes, **0,1615** [0,092 · 0,233]. Los intervalos **no se solapan**.
2. **La causa es que la dimensión de mayor peso discrimina AL REVÉS.** `solidez` pesa 40 % y
   tiene Gini **−0,1944**, con el IC entero por debajo de cero. Antes saturaba (96 % del
   sistema en 100/100) y por eso casi no ordenaba nada; la recalibración le dio varianza real
   y con ella le dio voz a una señal invertida.
3. **El desenlace que el backtest llama «distress financiero» es, en un 83 %, pérdidas
   sostenidas.** De los 301 eventos, **250** los aporta la regla de ROA<0 sostenido, 66 la de
   mora que se duplica y **0** la de solvencia bajo el mínimo — esa regla nunca disparó en
   toda la ventana. Y contra la regla de CRÉDITO, la que un banquero llamaría deterioro, el
   score discrimina **invertido**: Gini −0,1437 [−0,235 · −0,050].

---

## 1. Método: se cambia UNA sola cosa

El diagnóstico rehace el backtest con el mismo panel y los mismos desenlaces —los produce
`derive_observations`, que no se toca— y reconstruye el score previo aplicando las curvas de
`02fcdd2^` a los mismos valores crudos, reagregando con los sub-componentes persistidos de las
otras cuatro dimensiones.

**Comprobación de fidelidad primero:** el instrumento reproduce exactamente la cifra publicada
(0,1615) y reconstruye **1.693 de 1.693** observaciones, cero descartes. Sin eso, la
comparación no se puede sostener.

**Límite declarado:** la reconstrucción revierte solo las curvas de los cinco indicadores de
solidez. La recalibración también cambió el trato del dato ausente en `morosidad` (denominador
en cero pasó de puntuar 0 a declarar el indicador no disponible), y ese efecto queda dentro del
score persistido de `calidad`: no se le atribuye a la curva. Por eso el 0,3444 reconstruido no
tiene por qué coincidir con el 0,4436 que producción sirvió el 27-jul — la diferencia restante
es de esa segunda mitad del cambio, no de las curvas.

---

## 2. Qué discrimina cada dimensión

| Dimensión | Peso | Gini | IC 95 % | Lectura |
|---|---|---|---|---|
| `solidez` | **40 %** | **−0,1944** | [−0,260 · −0,121] | **invertida**, concluyente |
| `calidad` | 30 % | −0,0182 | [−0,098 · +0,062] | nula |
| `eficiencia` | 15 % | **+0,5985** | [+0,537 · +0,656] | la única fuerte |
| `liquidez` | 10 % | −0,1026 | [−0,186 · −0,024] | invertida, concluyente |
| `diversificacion` | 5 % | +0,1280 | [+0,061 · +0,197] | débil, positiva |

El 70 % del peso (solidez + calidad) no aporta discriminación positiva; el 15 % que sí la
aporta con fuerza es `eficiencia`. El score agregado promedia una señal fuerte con dos
invertidas, y el resultado es la cifra que se publica.

---

## 3. Qué es un «evento» en este backtest

| Regla | Eventos | Cuota | Gini del score contra ESA regla |
|---|---|---|---|
| `roa_negativo_sostenido` | **250** | 83 % | **+0,2287** [+0,147 · +0,311] |
| `morosidad_x2` | 66 | 22 % | **−0,1437** [−0,235 · −0,050] |
| `solvencia_breach` | **0** | 0 % | — (nunca disparó) |

*(Las cuotas suman más de 100 % porque una observación puede disparar dos reglas.)*

Y por dimensión, contra cada regla:

| Dimensión | vs ROA<0 sostenido | vs mora ×2 |
|---|---|---|
| `solidez` | −0,2419 | −0,0436 |
| `calidad` | +0,0107 | −0,0424 |
| `eficiencia` | **+0,7112** | +0,0626 |
| `liquidez` | −0,0828 | **−0,1803** |
| `diversificacion` | +0,1728 | −0,0778 |

**Dos cosas que esto obliga a decir en voz alta:**

- **El Gini de banca mide sobre todo persistencia de resultados.** Y hay que mirarlo con
  cuidado: el ROA es un insumo de `eficiencia`, así que «eficiencia predice ROA<0 futuro»
  (+0,711) es en parte autocorrelación de una serie consigo misma, no anticipación. No es
  circularidad plena —el desenlace es futuro y la ventana es de cuatro trimestres— pero está
  más cerca de la persistencia que de la discriminación.
- **Contra el deterioro de crédito, el score ordena al revés.** Es el resultado que un Chief
  Economist va a buscar primero, y hoy la plataforma no lo publica.

---

## 4. Qué se corrigió ya, y qué es una decisión

**Corregido en este ciclo** (no requiere decidir nada: es declarar lo que ya pasaba):

- El reporte publica `composicion_del_desenlace` — cuántos eventos aporta cada regla y cuáles
  no dispararon nunca — y agrega dos caveats computados: que una regla domina el desenlace y
  que `solvencia_breach` no aportó evidencia. Seguir listando las tres reglas como si pesaran
  parecido infla lo que el desenlace abarca.
- El caveat de monotonía nombra la banda real y su N (Fase 2, punto 3), y la superficie que
  dibuja la curva ya no la presenta como ordenamiento de riesgo.

**Abierto, y es decisión del dueño** — cada opción tiene consecuencia comercial:

| # | Opción | Qué implica |
|---|---|---|
| A | **Revisar la dirección de `solidez`** dentro del score | ⚠️ **Desaconsejada como estaba planteada**, por lo medido en [`DIAGNOSTICO_COMPOSICION_SOLIDEZ.md`](DIAGNOSTICO_COMPOSICION_SOLIDEZ.md): la inversión agregada es composicional y dentro de banca múltiple no existe. Sigue en pie, pero acotada a las poblaciones donde la inversión es intrínseca (banco de ahorro y crédito, aap) |
| B | **Re-especificar el desenlace** | **HECHO** (`2d84956`): el reporte publica `signals` por familia —`resultados`, `credito`, `capital`— con su N y su IC, más `headline_signal`. El agregado se conserva marcado como `desenlace_agregado` |
| C | **Re-pesar las dimensiones con evidencia** | El peso actual es doctrinal. La evidencia dice que la discriminación vive en `eficiencia`; re-pesar contra el desenlace sería ajustar a la muestra, así que exige método (validación fuera de muestra), no un tirón de perillas |
| D | **No tocar el score y acotar la afirmación comercial** | Publicar el Gini declarando que el desenlace es mayoritariamente de resultados, y no presentarlo como discriminación de riesgo de crédito |

**Recomendación (revisada el 2026-08-19):** B está hecho. Lo que sigue es **definir el
universo del backtest** —47 % del panel son entidades sin libro de crédito que aportan 63 % de
los eventos— y recién después revisar `solidez`, solo donde su inversión sobrevive a comparar
lo comparable. Re-pesar (C) quedó prematuro: el **tamaño solo** ordena mejor (+0,413) que el
score entero. Detalle y evidencia en
[`DIAGNOSTICO_COMPOSICION_SOLIDEZ.md`](DIAGNOSTICO_COMPOSICION_SOLIDEZ.md).

**Lo que NO cambia:** la credencial fuerte de banca sigue siendo la cohorte de quiebras reales
—Bancrédito con 11 meses de anticipación, Baninter con 7, señal tardía en Mercantil— sobre
**tres** casos evaluables. Ese resultado no depende de nada de lo anterior.

---

## 5. Lo que este diagnóstico NO afirma

1. ~~**No afirma causalidad sobre por qué `solidez` está invertida.**~~ **CERRADO el
   2026-08-19** → [`DIAGNOSTICO_COMPOSICION_SOLIDEZ.md`](DIAGNOSTICO_COMPOSICION_SOLIDEZ.md).
   Se partió el panel y se volvió a medir: la hipótesis composicional **se confirma**, y el
   estrato que la explica es el **tamaño**. Comparando solo entidades del mismo tramo, el Gini
   de `solidez` pasa de −0,1944 a **−0,0055** [−0,080 · +0,071] — el intervalo cruza cero.
   Dentro de banca múltiple no hay inversión (+0,1062). La causa: **47 % del panel son agentes
   de cambio**, 1.390 veces más chicos, con `solidez` mediana 92,7/100 por diseño del negocio,
   que aportan el **63 %** de los eventos.
2. **No dice que la recalibración haya estado mal.** Corrigió una saturación real y medida
   (96 % del sistema en 100/100 en tres indicadores). Lo que muestra es que, al darle varianza
   al sub-componente de mayor peso, quedó a la vista que ese sub-componente no ordena el
   desenlace — un problema que la saturación tapaba.
3. **No mide el efecto del cambio de dato ausente**, declarado en §1.
