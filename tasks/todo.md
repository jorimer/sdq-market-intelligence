# `n_oos` cuenta EMISIONES, no trimestres — plan

## El defecto, medido

Simulé cuatro trimestres objetivo con tres emisiones cada uno —la cadencia real: el sync
dispara la emisión en cascada y cada corrida en otra fecha escribe una fila nueva, porque
`as_of` está en la clave de cinco campos—:

```
trimestres OBJETIVO distintos: 4
n_oos que reporta el ledger:   12
¿declara solapamiento?         True
mínimo que exige el gate:      12
¿el gate la deja anclar?       True
```

**Cuatro trimestres de evidencia real abren el gate que exige doce.** Y no es hipotético:
hoy ya hay DOS filas para 2026-Q3 a h=2, con `as_of` 2026-09-05 y 2026-09-06. Están en
conjuntos distintos solo porque entre medias cambió la medida; con la medida estable, la
próxima emisión suma una fila al mismo conjunto.

Es exactamente lo que este ledger existe para impedir. El `backtest_id` fue diseñado para que
«un trimestre se pronostica una sola vez a cada distancia» —lo dice su propio docstring— y la
re-emisión rompe ese supuesto sin que nada avise.

**El error también se distorsiona, no solo el conteo.** Con tres filas del mismo trimestre, el
error de ESE trimestre pesa el triple en el RMSE. El promedio queda sesgado hacia los
trimestres que más veces se re-emitieron, que es un criterio sin ningún sentido.

## Por qué la re-emisión no es evidencia nueva

Una fila re-emitida desde el MISMO bloque es el mismo pronóstico re-sellado con otra fecha: el
conjunto de información no cambió, el punto es idéntico. Y si el bloque SÍ avanzó, el
horizonte relativo cambia —2026-Q3 pasa de h=2 a h=1— y la fila cae en otro conjunto sola.
O sea: **dentro de un conjunto, varias `as_of` para el mismo horizonte implican el mismo
bloque, y por tanto el mismo pronóstico.**

## El arreglo

### 1 · Un horizonte cuenta UNA vez

`_del_conjunto` se queda, por horizonte, con la emisión de `as_of` más TEMPRANO — el
pronóstico como se publicó por primera vez. Es la misma doctrina que ya rige para las
revisiones: «el track record mide el pronóstico como se PUBLICÓ, no como se corrigió después».

### 2 · Y entonces hay que codificar el solapamiento que el docstring ya declaraba

La única regla implementada en `_se_solapan` es «dos filas comparten horizonte». Con la
deduplicación eso no puede pasar nunca, así que la función pasaría a devolver `False`
siempre y el informe **dejaría de declarar un caveat que hoy declara**. Apagar un aviso en
silencio es peor que el defecto que estoy arreglando.

Su docstring ya nombra la regla real y nunca se escribió: «cuando el paso entre cortes es
menor que el salto entre horizontes». Es el resultado estándar: pronósticos a `h` pasos
emitidos cada `paso` períodos comparten información cuando `paso < h`, y sus errores quedan
autocorrelacionados. Se computa: `min(gap entre horizontes consecutivos) < h`.

- `h = 1` con emisión trimestral → `1 < 1` es falso → no solapan. (Conserva lo que el test
  vigente ya afirma.)
- `h = 2` con emisión trimestral → `1 < 2` → **solapan**, y hoy eso no se declaraba.
- un conjunto de una sola fila no solapa con nada → `False`.
- si algún horizonte no resuelve a un trimestre, **`None`**: «no sé» no es «no solapan», y el
  gate ya rechaza el `None` con su motivo.

### 3 · El test que hoy afirma lo contrario

`test_re_emitir_el_mismo_trimestre_si_solapa` afirma que re-emitir el mismo trimestre marca
solapamiento. Con la deduplicación esa fila ya no entra al conjunto, así que la afirmación
cambia — y por una MÁS fuerte: re-emitir no infla `n_oos` ni cambia el error. Se reescribe
para exigir eso, que es la garantía que de verdad protege el track record.

## Tests, contra el código viejo primero

- N emisiones del mismo trimestre objetivo dan `n_oos = 1`, no N. **Falla hoy con 12 vs 4.**
- El RMSE no se sesga hacia el trimestre más re-emitido.
- `h = 2` con emisión trimestral DECLARA solapamiento; `h = 1` no. Falla hoy: h=2 no lo
  declaraba.
- Un horizonte que no resuelve a trimestre da `None`, no `False`.
- El contraejemplo: trimestres objetivo DISTINTOS sí suman a `n_oos` — sin él, un
  `_del_conjunto` que devuelva una sola fila siempre pasaría todo lo de arriba.

## Los tres gates

`pytest modules/ shared/ -q` · `ruff check modules/ shared/ app/` ·
`mypy shared/ modules/ app/ --no-incremental | mypy-baseline filter` (exit code del FILTRO).
