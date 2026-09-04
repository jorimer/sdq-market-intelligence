# T-MP-4 · Sectorial — plan

## Lo que la medición cambió (antes de escribir una línea de modelo)

El spec fija la **restricción de agregación** contra el PIB agregado. Medí primero, y el
cuadro que parecía el natural para imponerla —`incidencia_por_actividad_economica`— **no
cierra en el archivo del BCRD**. Verificado celda por celda contra `pib_origen_2018.xlsx`,
hoja `PIBK_Trim`, filas 84-115: nuestra extracción es fiel, el que no cierra es el origen.

| identidad en el cuadro de INCIDENCIA (29 trimestres) | resultado |
|---|---|
| Σ(agropecuario+industrias+servicios) − valor_agregado | **exacto 0,0000** en 28; **−1,9451** en 2021-Q4 |
| valor_agregado + impuestos − PIB | **nunca 0**; \|d\| medio 0,22 pp, máximo **1,29** (2021-Q3) |
| Σ(sub-actividades) − servicios | ~0,01-0,05, salvo **−1,18** en 2021-Q1 |
| Σ(sub-actividades) − manufactura local | hasta **0,39** |

O sea: el cuadro de incidencias del BCRD tiene residuos propios y dos trimestres con
defectos francos. **No puede ser el sustrato de una restricción exacta.**

El cuadro **nominal** sí lo es:

| `PIB$_Trim` · `valor_agregado_por_actividad_economica` | resultado |
|---|---|
| todos los grupos y subgrupos, 33 trimestres (2018-Q1 → 2026-Q1) | error **0,00000** |
| **17 actividades + impuestos − PIB** | error máximo **0,000000000** millones RD$ |

Y las 17 actividades del spec existen, exactamente: agropecuario · minas · manufactura
local · zonas francas · construcción · energía y agua · comercio · hoteles · transporte ·
comunicaciones · intermediación financiera · inmobiliarias · enseñanza · salud ·
administración pública · servicios profesionales · otras actividades de servicios.

## El límite que hay que declarar, no esconder

Con índices encadenados **la agregación exacta contra el PIB publicado es imposible**, y no
por nuestro método: es la no-aditividad del encadenamiento. Reconstruí el crecimiento del
PIB agregando las 17 actividades con pesos nominales:

| ponderación | error medio | máximo |
|---|---:|---:|
| participación nominal en t−4 | **0,149 pp** | 0,625 |
| participación nominal del año previo | 0,176 pp | 1,029 |

**Nuestro agregador es más ajustado que el propio cuadro de incidencias del BCRD**
(0,149 / 0,63 contra 0,22 / 1,29). El sensor del plan dice «reconciliación exacta»: lo es
**contra el agregado que publicamos**, y la distancia contra el PIB publicado del BCRD se
mide y se declara en la metodología. No se finge que sea cero.

## Pasos

- [ ] **1.** `forecasting/sectoral.py`: las 17 actividades + impuestos, con la partición
      verificada; ponderación nominal en t−4 (elegida por medición, no por defecto).
- [ ] **2.** Método elegido **con la data en mano**: comparar contra la línea base ingenua
      («cada sector crece como el PIB», que es la proporción sin corrección). Si el método
      no le gana fuera de muestra, se publica la línea base y se dice.
- [ ] **3.** Reconciliación contra el PIB del BVAR, con el ajuste **reportado por sector**;
      si la brecha excede lo que el error histórico de agregación explica, se declara en vez
      de prorratearse en silencio.
- [ ] **4.** Sector con huecos o cambio de base: **no se proyecta**, se declara brecha.
- [ ] **5.** Profundidad **33 trimestres** declarada (decisión del dueño), y el backtest
      sectorial declara su n, que es corto.

## Sensor
- [ ] Reconciliación exacta contra el agregado publicado (test).
- [ ] Sectores no proyectables declarados (test).
- [ ] La partición 17+impuestos=PIB se verifica en el dato, no se supone (test).
